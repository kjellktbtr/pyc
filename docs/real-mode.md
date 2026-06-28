# x86 16-bit Real Mode — Compiler Reference

Distilled from `docs/raw/real-mode.txt` and `docs/raw/x86-16-bit-register-model.txt`.
This file focuses on constraints that directly affect code generation for a C compiler targeting MS-DOS 16-bit real mode.

---

## Data Model

- Default operand size is **16 bits** (`int`, pointers = 2 bytes). [real-mode.txt §Common Misconception]
- 32-bit registers (EAX, EBX, …) are accessible via the **Operand Size Override Prefix** (`0x66`); NASM emits this automatically when 32-bit registers are referenced. [real-mode.txt §Common Misconception]
- 32-bit addressing modes require the **Address Size Override Prefix** (`0x67`); NASM handles this automatically. [real-mode.txt §Addressing Modes]
- Using 32-bit operands costs one extra byte per instruction — prefer 16-bit where possible in size-critical output. [real-mode.txt §Addressing Modes]

---

## Memory Model & Segmentation

- Physical address = `Segment × 16 + Offset` (20-bit address space, max ~1 MB usable). [real-mode.txt §Memory Addressing; x86-16-bit-register-model.txt §Real mode]
- Each **segment is at most 64 KB**. No segment can span more than 64 KB. [x86-16-bit-register-model.txt §Real mode]
- Segments start on 16-byte **paragraph** boundaries. [x86-16-bit-register-model.txt §Real mode]
- A single physical address maps to up to 4096 distinct segment:offset pairs. [x86-16-bit-register-model.txt §Real mode]
- No memory protection: any code can access any address by changing segment registers. [x86-16-bit-register-model.txt §Real mode]

### Segment Registers and Their Implicit Roles

| Register | Role | Default for |
|----------|------|-------------|
| CS | Code segment | All instruction fetches |
| DS | Data segment | Most data reads/writes |
| SS | Stack segment | SP/BP-based stack accesses |
| ES | Extra segment | String instruction **destinations** (STOS, MOVS, CMPS) |
| FS, GS | General purpose (80386+) | No hardware-defined default |

[x86-16-bit-register-model.txt §Real mode; §Practices]

- DS is the default for general data access; override with a segment prefix if needed.
- SS is used implicitly for `PUSH`, `POP`, `CALL`, `RET`, `INT`, and any `[BP+…]` access. [real-mode.txt §The Stack; x86-16-bit-register-model.txt §Practices]
- ES **cannot be overridden** as the destination for string operations (MOVS, STOS, etc.). [x86-16-bit-register-model.txt §Practices]

### Common Memory Models

| Model | Constraint | Notes |
|-------|-----------|-------|
| **tiny** | CS = DS = ES = SS | All code+data+stack in one 64 KB segment (`.COM` style) |
| **small** | DS = SS, CS separate | Code and data each up to 64 KB |

[x86-16-bit-register-model.txt §Real mode — memory model paragraph]

For MS-DOS `.EXE` targets the **small** model is typical: DS=SS for data+stack, CS for code.

---

## Stack

- SS:SP points to the current top of stack; stack **grows downward**. [real-mode.txt §The Stack]
- Stack stores **16-bit words**; must be aligned on a 16-bit (word) boundary. [real-mode.txt §The Stack]
- Instructions that implicitly use the stack: `PUSH`, `POP`, `CALL`, `RET`, `INT`, `IRET`, and hardware interrupts. [real-mode.txt §The Stack]
- Function frame pointer convention: `BP` indexes into SS (implicit SS override for `[BP+…]`). [x86-16-bit-register-model.txt §Practices]

---

## 16-bit Addressing Modes

Only the following registers may be used as base/index pointers in 16-bit mode. This restricts which registers the compiler can use for memory indirection. [real-mode.txt §Addressing Modes]

| Mode | Example |
|------|---------|
| Base only | `[BX]`, `[BP]`, `[SI]`, `[DI]` |
| Base + displacement | `[BX + val]`, `[BP + val]`, `[SI + val]`, `[DI + val]` |
| Base + index | `[BX + SI]`, `[BX + DI]`, `[BP + SI]`, `[BP + DI]` |
| Base + index + displacement | `[BX + SI + val]`, etc. |
| Direct address | `[address]` |

**AX, CX, DX are not valid base/index registers in 16-bit addressing mode.**

---

## Calling Convention Implications

- Function arguments pushed on stack as 16-bit words (or 32-bit dwords with prefix).
- `BP` used as frame pointer; access locals via `[BP - n]` (SS-relative, no prefix needed).
- `SP` must remain word-aligned at all call sites.
- Return values: 16-bit in AX; 32-bit in DX:AX (high word in DX). This is the standard DOS/Turbo C convention.
- Caller or callee cleanup depends on calling convention (`cdecl` = caller cleans, `pascal`/`stdcall` = callee cleans).

---

## Pointer Types

- **Near pointer** (16-bit offset): references within the current segment (DS or SS). Default in small/tiny model.
- **Far pointer** (32-bit segment:offset): crosses segment boundaries; requires explicit segment manipulation and is significantly more expensive.

Compiler should use near pointers by default and only emit far-pointer sequences when explicitly requested or when an address exceeds the current segment.

---

## Key Constraints Summary for Code Generation

1. Default int/pointer = 16 bits; use `short`=16, `long`=32 (needs `0x66` prefix).
2. Max addressable data without segment change = 64 KB.
3. Only BX, BP, SI, DI are valid 16-bit base/index registers.
4. BP-relative addressing implicitly uses SS — correct for stack frames.
5. ES must be set correctly before any string instruction destination write.
6. Stack words are 16-bit; keep SP word-aligned.
7. No memory protection — out-of-bounds writes silently corrupt memory.
8. 32-bit operands cost one extra byte each; minimize use in tight loops.
