"""Peephole optimizer: post-pass over generated NASM assembly.

Runs one or more optimization passes on the raw assembly text produced by the
codegen phase.  Passes:

  1. push/pop cancellation    — drop LIFO-adjacent `push r` / `pop r` pairs.
  2. redundant mov            — drop `mov r, r`.
  3. store/reload elimination — `mov [m], r1` / `mov r2, [m]` (adjacent, same
     operand size) drops the reload, or rewrites it to a register move when
     `r2 != r1` (a register copy is cheaper than a memory load).
  4. zero arithmetic          — drop `add/sub/xor r, 0`, but *only* when the
     flags the instruction writes are provably dead (see `_flags_dead_after`).
  5. stack-balance            — drop adjacent `add sp, N` / `sub sp, N` pairs,
     again only when their flags are dead.
  6. jump-to-next             — drop `jmp L` when `L:` is the next significant
     line (the jump falls straight through to its own target).

Design principles:
- Conservative: an instruction is removed only when it is provably both
  value-neutral and flag-neutral in context.  push/pop and `mov r, r` never
  touch the flags; store/reload uses only `mov` (flag-neutral); the zero-arith
  and stack-balance passes additionally verify that the flags they write are
  dead before deleting.  A mismatched pop or an intervening call resets push/pop
  tracking.
- Label-safe: never removes a label line (`foo:`) — jump targets are preserved.
- Pass 1 only inspects `section .text`; passes 2-6 scan all lines but match only
  instruction mnemonics, which never appear in data/BSS directives.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Instruction classification
# ---------------------------------------------------------------------------

_REG16 = r"(?:ax|bx|cx|dx|si|di|bp|sp)"

_PUSH_RE = re.compile(r"^push\s+(" + _REG16 + r")\s*$", re.I)
_POP_RE = re.compile(r"^pop\s+(" + _REG16 + r")\s*$", re.I)
_LABEL_RE = re.compile(r"^[a-zA-Z_\.][a-zA-Z0-9_\.]*\s*:$")
_MOV_REG_REG = re.compile(r"^mov\s+(" + _REG16 + r"),\s*(" + _REG16 + r")\s*$", re.I)
_ADD_ZERO = re.compile(r"^add\s+" + _REG16 + r",\s*0\s*$", re.I)
_SUB_ZERO = re.compile(r"^sub\s+" + _REG16 + r",\s*0\s*$", re.I)
_XOR_ZERO = re.compile(r"^xor\s+" + _REG16 + r",\s*0\s*$", re.I)
_ADD_SP = re.compile(r"^add\s+sp,\s*(\d+)\s*$", re.I)
_SUB_SP = re.compile(r"^sub\s+sp,\s*(\d+)\s*$", re.I)

# Any 8- or 16-bit general register (for store/reload matching).
_ANYREG = r"(?:ax|bx|cx|dx|si|di|bp|sp|al|ah|bl|bh|cl|ch|dl|dh)"
_REG8 = {"al", "ah", "bl", "bh", "cl", "ch", "dl", "dh"}
_MOV_STORE = re.compile(r"^mov\s+(\[[^]]+\]),\s*(" + _ANYREG + r")\s*$", re.I)
_MOV_LOAD = re.compile(r"^mov\s+(" + _ANYREG + r"),\s*(\[[^]]+\])\s*$", re.I)

# `jmp <label>` (direct only — indirect `jmp word [bx]` has a space and won't match).
_JMP_RE = re.compile(r"^jmp\s+(\.?[A-Za-z_][A-Za-z0-9_.]*)\s*$", re.I)

# Flag classification for proving a flag-setting instruction is dead.
#   readers  — consume the arithmetic flags (deleting a setter before one of
#              these would change behaviour).  `jmp` is excluded (unconditional).
#   writers  — fully overwrite the consumable flags (CF/OF/SF/ZF/PF), so any
#              earlier flag value is dead from here on.
#   barriers — control-flow boundaries across which flags may be live; treated
#              conservatively (assume not dead).
_FLAG_READERS = re.compile(
    r"^(?:j(?!mp\b)[a-z]+|set[a-z]+|cmov[a-z]+|adc|sbb|rcl|rcr|"
    r"lahf|pushf|loope|loopz|loopne|loopnz|into|daa|das|aaa|aas)\b",
    re.I,
)
_FLAG_WRITERS = re.compile(
    r"^(?:cmp|test|add|sub|and|or|xor|neg|shl|shr|sal|sar)\b",
    re.I,
)
_FLAG_BARRIER = re.compile(r"^(?:call|ret|retn|retf|jmp|int|iret)\b", re.I)


def _reg_size(reg: str) -> int:
    """Byte width of a general register name (1 for 8-bit, else 2)."""
    return 1 if reg.lower() in _REG8 else 2


def _flags_dead_after(lines: list[str], i: int) -> bool:
    """True if the arithmetic flags written by ``lines[i]`` are provably dead.

    Scans forward (skipping blank/comment lines) for the first instruction that
    touches the flags.  Returns True only if that instruction fully overwrites
    the flags before any instruction reads them.  Conservatively returns False
    at any control-flow boundary, label, section change, or end of stream.
    """
    for j in range(i + 1, len(lines)):
        s = lines[j].strip()
        if not s or s.startswith(";"):
            continue
        if _FLAG_READERS.match(s):
            return False
        if _FLAG_WRITERS.match(s):
            return True
        if (_FLAG_BARRIER.match(s)
                or _LABEL_RE.match(s)
                or s.startswith("section ")):
            return False
        # Neutral instruction (mov/push/pop/lea/inc/dec/...) — keep scanning.
    return False


@dataclass
class OptStats:
    """Counts of eliminated instructions per pass."""
    push_pop_cancel: int = 0
    redundant_mov: int = 0
    zero_add_sub: int = 0
    stack_balance: int = 0
    store_reload: int = 0
    jmp_to_next: int = 0

    @property
    def total(self) -> int:
        return (
            self.push_pop_cancel
            + self.redundant_mov
            + self.zero_add_sub
            + self.stack_balance
            + self.store_reload
            + self.jmp_to_next
        )


# ---------------------------------------------------------------------------
# Pass 1: Push/Pop cancellation (adjacent pairs only)
# ---------------------------------------------------------------------------
#
# Tracks a window of push/pop instructions.  Maintains a "push stack" of
# register names.  When a pop matches the top of the push stack AND there
# were no intervening instructions, both the push and pop are marked for
# elimination.  When the push stack becomes empty, the entire window is
# provably a no-op and gets removed.
#
# Tracking resets (keep everything) on:
#   - mismatched pop (pop reg where top-of-stack pushed a different reg)
#   - pop matching a push that had intervening instructions
#   - any call/jmp (callee may clobber stack in unknown ways)
#   - labels, directives, blanks, comments (structural boundaries)
#
# Labels are never removed (they're jump targets).


def _pass_push_pop_cancel(lines: list[str], stats: OptStats) -> list[str]:
    result: list[str] = []
    # Pending pushes: list of (reg, line_text)
    pending: list[tuple[str, str]] = []

    def flush_keep() -> None:
        """Flush all pending pushes to result (keep everything)."""
        result.extend(text for _, text in pending)
        pending.clear()

    for line in lines:
        stripped = line.strip()

        # Empty / comment / directive → structural boundary
        if (not stripped
                or stripped.startswith(";")
                or stripped.startswith("section ")
                or stripped.startswith("global ")
                or stripped.startswith("extern ")
                or stripped.startswith("group ")):
            if pending:
                flush_keep()
            if not pending:
                result.append(line)
            continue

        # Label → always keep, breaks tracking
        if _LABEL_RE.match(stripped):
            if pending:
                flush_keep()
            result.append(line)
            continue

        push_m = _PUSH_RE.match(stripped)
        pop_m = _POP_RE.match(stripped)

        if push_m:
            reg = push_m.group(1).lower()
            pending.append((reg, stripped))
            continue

        if pop_m:
            reg = pop_m.group(1).lower()

            if pending and pending[-1][0] == reg:
                # Adjacent push/pop (no intervening instructions) — eliminate both
                pending.pop()
                stats.push_pop_cancel += 2
            else:
                # Mismatch or empty stack — keep all
                flush_keep()
                result.append(line)
            continue

        # Any other instruction — flush pending pushes first, then add instruction
        if pending:
            flush_keep()
        result.append(line)

    # End — flush remaining pushes
    result.extend(text for _, text in pending)
    pending.clear()

    return result


# ---------------------------------------------------------------------------
# Pass 2: Redundant move elimination
# ---------------------------------------------------------------------------
# mov ax, ax  →  (delete)

def _pass_redundant_mov(lines: list[str], stats: OptStats) -> list[str]:
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        m = _MOV_REG_REG.match(stripped)
        if m and m.group(1).lower() == m.group(2).lower():
            stats.redundant_mov += 1
            continue
        result.append(line)
    return result


# ---------------------------------------------------------------------------
# Pass 3: Zero add/sub/xor elimination
# ---------------------------------------------------------------------------
# add ax, 0  →  (delete)
# sub bx, 0  →  (delete)
# xor cx, 0  →  (delete)

def _pass_zero_arith(lines: list[str], stats: OptStats) -> list[str]:
    result: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        is_zero_op = (
            _ADD_ZERO.match(stripped)
            or _SUB_ZERO.match(stripped)
            or _XOR_ZERO.match(stripped)
        )
        # `add/sub/xor r, 0` leaves the register unchanged but *writes* flags;
        # only safe to drop when those flags are provably dead.
        if is_zero_op and _flags_dead_after(lines, i):
            stats.zero_add_sub += 1
            continue
        result.append(line)
    return result


# ---------------------------------------------------------------------------
# Pass 4: Stack balance cancellation
# ---------------------------------------------------------------------------
# add sp, 4  /  sub sp, 4  (adjacent) → (delete both)

def _pass_stack_balance(lines: list[str], stats: OptStats) -> list[str]:
    result: list[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        add_m = _ADD_SP.match(stripped)
        sub_m = _SUB_SP.match(stripped)

        # Cancelling the pair reverts the flags to their pre-`add` state, so
        # only do it when the flags written by the second instruction are dead.
        cancelled = False
        if add_m and i + 1 < len(lines):
            sub_next = _SUB_SP.match(lines[i + 1].strip())
            if (sub_next and add_m.group(1) == sub_next.group(1)
                    and _flags_dead_after(lines, i + 1)):
                stats.stack_balance += 2
                i += 2
                cancelled = True
        if not cancelled and sub_m and i + 1 < len(lines):
            add_next = _ADD_SP.match(lines[i + 1].strip())
            if (add_next and sub_m.group(1) == add_next.group(1)
                    and _flags_dead_after(lines, i + 1)):
                stats.stack_balance += 2
                i += 2
                cancelled = True

        if not cancelled:
            result.append(lines[i])
            i += 1
    return result


# ---------------------------------------------------------------------------
# Pass 5: Store/reload elimination
# ---------------------------------------------------------------------------
# mov [m], r1  /  mov r1, [m]   (adjacent) → drop the reload (r1 already holds it)
# mov [m], r1  /  mov r2, [m]   (adjacent) → rewrite reload as `mov r2, r1`
#
# Both instructions are `mov`, so no flags are involved.  Only fires when the
# memory operand text matches exactly and the two registers have the same width.

def _pass_store_reload(lines: list[str], stats: OptStats) -> list[str]:
    result: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        store = _MOV_STORE.match(lines[i].strip())
        if store and i + 1 < n:
            load = _MOV_LOAD.match(lines[i + 1].strip())
            mem, src = store.group(1), store.group(2)
            if (load
                    and load.group(2).lower() == mem.lower()
                    and _reg_size(load.group(1)) == _reg_size(src)):
                dst = load.group(1)
                result.append(lines[i])  # keep the store
                if dst.lower() != src.lower():
                    # Replace the memory reload with a cheaper register copy.
                    result.append(f"mov {dst}, {src}")
                # else: reload into the same register is fully redundant — drop it.
                stats.store_reload += 1
                i += 2
                continue
        result.append(lines[i])
        i += 1
    return result


# ---------------------------------------------------------------------------
# Pass 6: Jump-to-next-line elimination
# ---------------------------------------------------------------------------
# jmp L  /  (blanks/comments)  /  L:   → drop the jmp (falls through to L anyway)
#
# The label itself is kept (other code may jump to it).  Only blank and comment
# lines may sit between the jmp and its target; any real instruction or a
# different label blocks the rewrite.

def _pass_jmp_to_next(lines: list[str], stats: OptStats) -> list[str]:
    result: list[str] = []
    n = len(lines)
    for i, line in enumerate(lines):
        m = _JMP_RE.match(line.strip())
        if m:
            target = m.group(1) + ":"
            j = i + 1
            while j < n:
                s = lines[j].strip()
                if not s or s.startswith(";"):
                    j += 1
                    continue
                break
            if j < n and lines[j].strip() == target:
                stats.jmp_to_next += 1
                continue  # drop the jmp; label stays in place
        result.append(line)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def optimize(asm: str, passes: int = 3) -> tuple[str, OptStats]:
    """Run peephole optimization passes on generated NASM assembly.

    Args:
        asm: Raw NASM assembly text from the codegen phase.
        passes: Number of times to repeat the full pass sequence.  Most
            patterns resolve in one pass; cascading chains may need 2-3.

    Returns:
        Tuple of (optimized_asm, stats) where stats records how many
        instructions were eliminated per category.
    """
    lines = asm.split("\n")
    stats = OptStats()

    for _ in range(passes):
        before = len(lines)
        lines = _pass_jmp_to_next(lines, stats)
        lines = _pass_push_pop_cancel(lines, stats)
        lines = _pass_redundant_mov(lines, stats)
        lines = _pass_store_reload(lines, stats)
        lines = _pass_zero_arith(lines, stats)
        lines = _pass_stack_balance(lines, stats)
        after = len(lines)

        # Early exit if nothing changed
        if before == after:
            break

    return "\n".join(lines), stats
