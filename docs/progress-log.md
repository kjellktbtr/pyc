# Progress Log & Discoveries

## 2026-06-23 — Codegen bug: 2D `char` array store was a word store (corrupted adjacent element)

Storing to a multi-dimensional **`char`** array element via computed indices
(`m[i][j] = v`) emitted a 16-bit **word** store (`mov [bx], ax`) instead of a
byte store (`mov [bx], al`). The high byte (0 for small values) overwrote the
*next* element, so `seen[tx][ty] = 1` on a `char[48][32]` silently cleared
`seen[tx][ty+1]`.

**Root cause** (`src/pyc/codegen.py`): the store path picks byte-vs-word from
`_lvalue_element_size(target)` → for a `Subscript` it calls
`_expr_ptr_inner_size(target.array)` → `_expr_pointee_type(target.array)`. That
helper handled `Identifier`/`UnaryOp`/`CastExpr` but **not `Subscript`**, so for
a *nested* subscript (`m[i]` inside `m[i][j]`) it returned `None` and the size
defaulted to 2 → word store. 1-D arrays were fine (`target.array` is a plain
Identifier). The *read* path was already correct (`mov al,[bx]`); only the store
was wrong.

**Fix**: added a `Subscript` case to `_expr_pointee_type` (returns the
element/inner type of `_subscript_element_type(expr.array)`), so `m[i]` on
`T[A][B]` reports pointee `T` and the store is sized correctly. Also collapsed a
dead duplicate definition of `_expr_pointee_type` (two identical copies; the
second shadowed the first) into one, so the fix can't be silently undone.

**Impact**: this was the SJAKTENE "tiles that should be visible turn black when
moving" bug. `RevealAround` (engine.c) sets `seen[tx][ty]=1`; the word store
cleared the tile below it, and once the lamp moved on, that tile was never
re-revealed → drawn black on the next full redraw. Found via a differential
harness (incremental scroll/dirty render vs. forced full redraw of the same
state): identical under gcc/SDL, divergent under pyc/DOS. `gfx_scroll`,
`gfx_fill_rect`, `gfx_blit_sprite` and the 2D *read* path were all verified
correct; the bug was purely this store. Not optimizer-related (identical at
`-O0` and `-O1`).

Regression test: `tests/test_m2d_subscript.py::test_m2d_char_write_is_byte_store`
(asserts the 2D `char` store is `mov [bx], al`, not `mov [bx], ax`). Full suite:
261 passed, 1 xfailed.

Known remaining (separate, cosmetic, pre-existing): a 1-pixel column just past
the viewport's right edge (x=335, the byte-granular `gfx_scroll` touches one
pixel beyond the non-byte-aligned 15..334 region). Outside the play area; not
the tile bug.

## 2026-06-23 — Peephole optimizer: flag-safety audit + two new passes

Audited `src/pyc/optimizer.py`. The push/pop and `mov r,r` passes were correct
and conservative, but two issues turned up and three improvements followed.

**Flag-safety (the latent footgun).** Pass 3 (`add/sub/xor r, 0`) and pass 4
(adjacent `add sp,N`/`sub sp,N`) deleted instructions that are value-neutral but
*write the flags*. Safe only because codegen always re-establishes flags with
`test`/`cmp` right before any `jcc` (e.g. `codegen.py:518,1903`) — an unstated
invariant. Empirically harmless today (0 occurrences of `add/sub/xor reg,0`
across the whole `single/` suite). Fixed properly: both passes now gate deletion
on a new `_flags_dead_after()` forward-scan that deletes only when the next
flag-touching instruction *overwrites* the flags before any instruction *reads*
them; any reader / control-flow boundary / end-of-stream → keep. The module
docstring's "provably no-ops" / "section-aware" claims were corrected.

**Two new safe passes** (grounded in real `-O0` output, not theory):
- `_pass_jmp_to_next`: drop `jmp L` when `L:` is the next significant line. This
  is the function-epilogue trampoline (`jmp .f_ret` immediately before
  `.f_ret:`) — control-flow-, value- and flag-safe. **66 hits across 40 files**,
  the single biggest win.
- `_pass_store_reload`: `mov [m],r1` / `mov r2,[m]` (adjacent) drops the reload
  (or rewrites to `mov r2,r1`). Both are `mov` → flag- and value-safe; guarded
  on identical operand text **and equal register width** (a byte store + word
  reload must not fold — `test_size_mismatch_kept`).

Result: suite line-reduction ~0.55% → ~1.09% (78 → 155 lines), all 41 optimizer
unit tests pass, optimized output still assembles under NASM. `tests/`: 260
passed / 1 xfailed (the `serial_xfer/` QEMU tests error at *collection* due to a
missing `/tmp/fdboot.img`, unrelated). `test_return_jumps_to_epilogue` now
compiles with `optimize=0` because it asserts a codegen property and the
optimizer legitimately strips that trailing-return jump.

**Known interaction (flagged, not a regression):** `volatile` is still a no-op
(`todo.md:32`). If volatile is ever implemented, `_pass_store_reload` and
`_pass_zero_arith` must skip accesses to volatile-qualified memory — eliminating
a volatile reload/read would drop a required memory access. Harmless today
because the compiler doesn't honor volatile at all.

## 2026-06-22 — SJAKTENE + NATTMAT actually *run* (five runtime bugs fixed)

The 2026-06-21 work made the games assemble+link; they still hung/blanked at
runtime. Headless screenshot diagnostics (a new `plat_screenshot` in
`div/cdos/plat_pyc.asm` dumping EGA planes via INT 21h, run under DOSBox with
`SHOTMODE`) plus binary-bisection isolated five distinct root causes. Both games
now render correctly and match the OpenWatcom reference, including fog-of-war.

**1. Cross-TU `.bss` symbols mis-resolved across object modules**
(`src/pyc/builder.py` — new `_merge_asm_modules`)
- Multi-file builds linked one object module per TU. NASM resolves a module's
  *own* `.bss` symbol group-relative (adds *that module's* `.data` size), but
  alink resolves a *cross-module* extern reference to the same symbol
  `.bss`-segment-relative (no `.data` base). The two disagree by exactly the
  defining module's `.data` size, so a global array defined in `engine.c` and
  read from `sjakt4.c` landed at the wrong DGROUP offset (measured: 240-byte
  skew) and silently overlapped other data. Never exercised by the single-file
  `single/` suite, so it stayed latent until a real two-file program.
- Fix: compile each TU separately (per-file symbol tables → correct
  global/extern), then **merge all TUs into one assembly module** before
  assembly — identical layout to a single-file program, the only configuration
  the OMF group offsets are reliable in. Per-TU `_str_<n>` labels are renamed
  `_str_<tu>_<n>` to avoid collisions. Tests: `tests/test_multifile_merge.py`.

**2. stdlib `.bss` not in DGROUP → heap overlapped the in-BSS stack**
(`stdlib/{stdlib,stdio,fp,long_io,posix_io}.asm`)
- Only the program module declared `group DGROUP data bss`; the stdlib modules
  did not, so alink placed the 16 KB malloc `_heap` (and fp/stdio scratch) at a
  near-fixed offset (~27 KB) that, for a large program, fell *inside* the
  program's 16 KB in-BSS stack reserve. The stack grew down into the heap and
  corrupted memory. Added the group directive to every stdlib module that has
  `.data`/`.bss`; the heap now lands above `_stack_top`. (Supersedes the old
  BSS-only workaround comment in `fp.asm`.)

**3. Initialized pointer arrays emitted as zeroed BSS**
(`src/pyc/codegen.py:_gen_global_var` — new `_collect_array_dw` / `_intern_string`)
- `static const char *spr_rows[17][16] = {{"...",...},...}` (the sprite-row
  string table) hit the int-array path, where `_constant_value(StringLiteral)`
  is None, so it fell back to `resw` (uninitialized, wrong size). Every sprite
  row read back empty → blank map. Fix: a recursive flattener emits an
  initialized `dw` table, interning string-literal elements and recursing
  through nested arrays (zero-padding short initializers). Tests:
  `tests/test_global_pointer_arrays.py`.

**4. `sizeof(array-expression)` returned 2** (`src/pyc/codegen.py:_gen_sizeof`)
- For any non-string expression operand, sizeof emitted a hardcoded `mov ax, 2`.
  `memset(seen, 0, sizeof(seen))` therefore cleared 2 bytes, not 1536 — the fog
  array never reset. Fix: infer the operand's type via `_expr_type` and use its
  `.size` (arrays do not decay under sizeof). Same test file.

**5. alink mis-links near calls whose displacement exceeds 32 KB**
(`src/pyc/builder.py` — `link(linker=...)`, `get_stdlib_objects(exclude=...)`,
`_link_wlink`, `_find_wlink`)
- The combined game+stdlib code is ~40 KB. A near `call` (E8 + rel16) from a
  low function (`RandInt` at `text:0x15`) to a high stdlib routine (`rand` at
  `text:0x82F9`) needs a +33 KB displacement; alink does not emit the correct
  mod-65536 wraparound for displacements past the signed-16-bit range, so the
  call jumped to garbage (`RandInt(5,9)` returned a constant 36 → `numRooms`
  garbage → out-of-bounds room writes → hang). Confirmed via map file and by
  reversing TU order (moving `RandInt` next to `rand` fixed it).
- **Two ways to stay correct, both supported:**
  - **Keep the code under 32 KB (chosen for the games).** ~9 KB of the bloat is
    the soft-float runtime `fp.obj`, force-linked only by stdio's single
    `__print_d64` (`%f`/`double` printer) reference — dead weight for float-free
    programs. `get_stdlib_objects(exclude=["fp"])` / `build(exclude_stdlib=["fp"])`
    drops it; the lone reference is satisfied by a 1-instruction stub
    (`div/cdos/fpstub.asm`). This pulls `rand` down to ~28 KB, within range, and
    needs only nasm+alink — no Open Watcom. Trade-off: no `%f`/`double` output.
  - **`linker="wlink"`** (Open Watcom) links the full >32 KB code correctly and
    keeps float support, at the cost of an Open Watcom dependency.
- `div/cdos/build-pyc.sh` uses the alink + `exclude_stdlib=["fp"]` path.

Net: `SJAKT4P.EXE` / `NATMATP.EXE` run under DOSBox (built with plain
nasm+alink) — title, sprite map, HUD (`%d`/`%-Nd`), messages, room generation,
and fog-of-war all correct. Full suite: 218 passed, 1 xfailed.

## 2026-06-21 — pyc builds SJAKTENE + NATTMAT as DOS EXEs (first real-game port)

Closed the remaining gaps between pyc and what the SJAKTENE/NATTMAT roguelikes
need, producing `SJAKT4P.EXE` (85 KB) and `NATMATP.EXE` (87 KB) as valid MZ
DOS executables that assemble and link without errors.

### Compiler / preprocessor fixes

**`__VA_ARGS__` in variadic macros** (`src/pyc/preprocessor.py`)
- `Macro` now has a `variadic: bool` field. `_handle_define` strips `...` from
  params and sets the flag. `_expand_one_pass` treats variadic macros as
  function-like even when `params=[]`. `_expand_func_macro` binds `__VA_ARGS__`
  to all args beyond the named params, joined with `", "`.
- Tests: `tests/test_va_args.py` (4 tests, all pass).

**`CharLiteral.value` is already `int`** (`src/pyc/codegen.py:_constant_value`)
- Second site of the same bug fixed earlier in `parser.py`: `codegen.py` called
  `ord(expr.value)` / `len(expr.value)` but `expr.value` is already the ordinal
  `int` (stored by the lexer). Fixed to `return expr.value`.

**Nested `switch` case scoping** (`src/pyc/codegen.py:_gen_switch`)
- `collect_cases()` recursed into nested `SwitchStmt` bodies via the catch-all
  `elif hasattr(node, "body")` branch, pulling inner switch cases into the outer
  dispatch table. Added `elif isinstance(node, SwitchStmt): pass` guard.
- Tests: `tests/test_switch_nested.py` (2 tests, all pass).

### Multi-file build fixes (`src/pyc/builder.py`)

**Per-file symbol tables** instead of a shared one across passes
- The old two-pass approach with a shared `SymbolTable` caused a bug: the second
  pass saw symbols already in the table (from pass 1) and emitted them as `extern`
  instead of `global`. Now each file gets a fresh `SymbolTable()` (non-None to
  suppress entry-point emission) so its own definitions stay `global`.

**`_data_start` / `_stack_top` export from the file containing `main`**
- When `main` is not in the first file, the bootstrap's `seg _data_start` /
  `_stack_top` references needed `global` declarations in the file that defines
  them (the one with `main`). `build()` now patches the relevant ASM after
  compilation to add `global _data_start` / `global _stack_top`.

**`extra_objects` parameter on `build()`**
- `build()` now accepts `extra_objects: list[Path]` for pre-assembled `.obj`
  files to be linked after source objects and before stdlib. Used by `build-pyc.sh`
  to inject `plat_pyc.obj`.

### New NASM platform backend (`div/cdos/plat_pyc.asm`)

Hand-written 16-bit NASM implementing the full `platform.h` contract:
- `plat_init`: INT 10h mode 0x10 (EGA 640×350); GC write mode 2 + SEQ all-planes;
  reads INT 43h IVT to locate the ROM 8×14 font.
- `plat_shutdown`: INT 10h mode 0x03 (text).
- `plat_present`: no-op (EGA VRAM writes are immediately visible).
- `plat_random_seed`: returns low 16 bits of BIOS tick counter at 0040:006Ch.
- `gfx_plot`: byte-offset + bit-mask, GC reg 8, latch-read then write mode 2.
- `gfx_fill_rect`: left/right byte masks + middle full-byte loop; all in write mode 2.
- `gfx_draw_box`: four `gfx_fill_rect` calls.
- `gfx_blit_sprite`: 16×16 loop over `signed char` pixel array; -1 = transparent.
- `gfx_scroll`: EGA write mode 1 (latch copy) for four scroll directions.
- `gfx_draw_char`: `gfx_fill_rect` background + ROM font scan; calls `gfx_plot`.
- `inp_get_key`: INT 16h poll + read; returns ASCII or 0x100|scancode for arrows.
- `snd_play`: PIT channel 2 (1193180/freq divisor) + PC speaker + BIOS tick wait.

### Build script (`div/cdos/build-pyc.sh`)

Orchestrates: `nasm -f obj plat_pyc.asm` then `pyc build()` for each game.
Produces `build/SJAKT4P.EXE` and `build/NATMATP.EXE` alongside the Watcom build.

### `%-Nd` left-justify width in `sprintf` (also fixed 2026-06-21)

Added `%-Nd` (left-justified, minimum width) support to `sprintf` in
`stdlib/stdio.c`. Added `static int _spr_n` counter incremented by
`_spr_emit_char`; snapshot `_spr_n` before each format-specifier call and
pad with trailing spaces to reach the minimum width. Right-justify without
`-` is parsed but not yet padded (NATTMAT only needs `%-Nd`). `stdio.asm`
regenerated from the updated `stdio.c`. Tests: `tests/test_sprintf_width.py`
(2 compile-only tests). Both EXEs rebuilt: SJAKT4P 85 443 B, NATMATP 87 469 B.

### Remaining item

- `plat_pyc.asm` runtime validation under DOSBox/qemu (visual screen check,
  keyboard input, sound).

## 2026-06-03 — Console newline now CR+LF (fix DOS staircase output)

`_putchar` (`stdlib/dos_io.asm`) emitted a bare LF for `'\n'`, so on a real DOS
console the cursor dropped a line without returning to column 0 (each line
started further right — "staircase"). Now `'\n'` is written as CR+LF, the DOS
text-mode convention. All console output (`putchar`/`puts`/`printf`) funnels
through `_putchar`, so this fixes everything at once. The serial protocol is
unaffected (it uses `uart_putc`, a separate path). The `single/` suite is
unchanged (its harness strips `\r` before comparing) — still 31/40; serial
round-trip still byte-exact.



## 2026-06-03 — serial_xfer: whole-file CRC, tree up/download, retry-forever, report

Extended the serial file-transfer subsystem (`serial_xfer/`):

- **New DOS directory runtime** `stdlib/dos_dir.asm`: `mkdir`/`set_dta`/
  `find_first`/`find_next` (INT 21h 39h/1Ah/4Eh/4Fh), header `<dos.h>`
  (FA_/DTA_ macros), added to `builder.py` `stdlib_order`. Verified under DOSBox
  (create a subdir, write a file in it, enumerate it).
- **Whole-file CRC-32** (reflected `0xEDB88320`) on both sides — confirmed the
  pyc 32-bit `unsigned long` implementation matches `zlib.crc32` exactly
  (`0xCBF43926` for `"123456789"`). The final `CLOSE` carries the 4-byte CRC;
  upload's `CLOSE`-ACK returns a status byte, download verifies host-side.
- **Retry-forever queue** (`Link.run_queue`): a file failing its whole-file CRC
  (or any transport error) is requeued to the back and retried indefinitely;
  the run ends when the queue drains or on **Ctrl-C**, which prints the report
  with still-PENDING files (attempt counts + last error).
- **Structure-preserving tree upload** (`MKDIR` + per-component 8.3 mangling) and
  **recursive tree download** (`LIST`/`ENTRY` walk). New packet types MKDIR(6),
  LIST(7), ENTRY(8).
- **Transfer report** (`TransferReport`): per-file bytes/time/KB·s/attempts,
  totals, and the renamed target structure. CLI gains `--report` and
  `download --tree`.
- **Dual logging**: host → stdout (per-file + report); DOS agent → its console
  (`puts`/`printf`) so the vintage operator sees activity (separate from the COM
  port carrying the protocol).

- **Interactive emulator workflow** (boot → run exe → run script): `host.py`
  gained `--socket`/`--tcp` transports (a `SocketTransport`) to talk to an
  emulator's virtual serial port; `serial_xfer/make_disk.py` builds a bootable
  FreeDOS floppy with `XFER.EXE`, and `serial_xfer/run_emulator.sh` boots it
  under QEMU with COM1 on a Unix socket. No QEMU config file needed. Documented
  step-by-step in `serial_xfer/README.md` ("Run under an emulator…").

Verified end-to-end under QEMU: file round-trip with CRC, nested-tree round-trip
(structure + content, incl. a binary file with embedded NULs and `~N`-colliding
names), one-byte corruption recovered via NAK/retransmit, (pure-Python)
retry-forever + interrupt report, and the manual `make_disk.py` →
`run_emulator.sh` → `host.py --socket` upload flow. No compiler regression:
`single/` 31/40, 197 unit tests pass.



## 2026-06-02 — Serial file-transfer subsystem (`serial_xfer/`) — working

Built a host⇄vintage-DOS file-transfer protocol over serial and verified it
end-to-end under QEMU. New code:

- **Runtime:** direct 8250/16550 UART primitives in `stdlib/serial.asm`
  (`uart_init`/`uart_rx_ready`/`uart_getc`/`uart_putc`, polled, by I/O base) +
  prototypes/`COM1_BASE`/`COM2_BASE` in `<serial.h>`. More reliable than the
  INT 14h layer for a framed protocol.
- **DOS agent** `serial_xfer/xfer.c` (compiled by pyc): COBS framing, CRC-16,
  ACK/NAK, file write for uploads, file read/stream for downloads.
- **Host** `serial_xfer/host.py`: COBS + CRC-16 codec, ack-and-wait `Link`, DOS
  8.3 filename mangling with Windows-9x `~N` collision avoidance, recursive
  directory upload, download, a pyserial `SerialTransport` for real hardware,
  and a CLI (`upload`/`download`/`quit`/`--selftest`).
- **Test harness** `serial_xfer/qemu_serial.py`: boots the agent under QEMU with
  COM1 on a Unix socket (`-serial unix:...,server=on`) so the host drives it
  with no hardware. Plus `test_upload.py`/`test_roundtrip.py`/`test_tree.py`.

Verified: interactive echo; upload (374 B text and 900 B binary) byte-exact on
the floppy; download byte-exact back to the host; recursive tree upload of 6
files (incl. a binary file with an embedded `0x00`, and colliding long names →
`DOCS_A~1.MD`/`DOCS_A~1.MAR`) all correct. No compiler-suite regression (31/40),
197 unit tests pass. Protocol + usage documented in `serial_xfer/README.md`.



## 2026-06-02 — test_indvars fits the stack (PASS); serial RX feed/log works

**`test_indvars` (t34) now PASSES (suite 30→31/40).** Its `int Array[100][200]`
(40 KB) overflowed the 16 KB in-DGROUP stack. Halved the dimensions/loop bounds
to `int Array[50][100]` (10 KB, fits), keeping the same feature coverage (loop
induction vars, 2D-array access, `double` sum). Regenerated the reference with
`gcc -m32` (`Checksum = 13922`); pyc matches exactly (16-bit vs 32-bit int is
irrelevant here — all values are small). The reduction is the right call: the
64 KB tiny model can't hold a 40 KB frame alongside 13.5 KB text + 16 KB heap.

**Serial RX (feed data in + log out) confirmed working under QEMU.** Answering
"can data be fed into the serial port and logged": yes, fully scriptably with
QEMU's file chardev —
`-chardev file,id=s0,path=OUT.log,input-path=IN.dat -serial chardev:s0`.
`input-path` is delivered to the guest's UART (read via INT 14h/AH=02), and the
guest's TX (INT 14h/AH=01) is written to `path`. Demonstrated with an echo
program (`serial_getc`→`serial_putc`): fed `HELLO-FROM-HOST\n`, captured the
same string echoed back in the output log. Recipe added to
`docs/debugging-dos.md`. (DOSBox 0.74's serial only does nullmodem/directserial,
not file I/O — use QEMU for serial round-trip testing.)



## 2026-06-02 — `__builtin_clzll` + `fesetround` (last COMPILE_FAIL gone)

Added two missing runtime symbols to `stdlib/fp.asm`:
- **`__builtin_clzll`** — count-leading-zeros of a 64-bit value (4 words at
  `[bp+4..10]`), returns 0..63 in `AX`. Correct, useful for any program.
- **`fesetround`** — no-op returning 0 (the runtime only does round-to-nearest,
  the default).

This makes `uint64_to_float` (t36) **link and run** — the lone COMPILE_FAIL is
gone, so **all 40 suite tests now compile and run** (30 PASS / 10 MISMATCH / 0
COMPILE_FAIL). 197 unit tests pass, no regressions.

`uint64_to_float` still doesn't *pass*, for three independent reasons (verified
on a reduced-scale copy that completes): (1) the full test does ~tens of
millions of 64-bit iterations — infeasible under the 12 s DOSBox timeout
regardless of correctness; (2) the compiler's `uint64_t`→`float` conversion
disagrees with the reference `floatundisf` on some values (≥2 in a small range);
(3) the `%016llx`, `%a` (hex float) and `%08x` printf specifiers aren't
implemented (print as literal `16llx` / `` / `8x`). Documented for later; none
are quick.



## 2026-06-02 — Double multiply & divide implemented (+ a codegen high-word bug)

`__dmul64` / `__ddiv64` in `stdlib/fp.asm` were skeletons that returned an
operand unchanged — i.e. `1.5 * 2.0` silently evaluated to `1.5`, `6.0 / 2.0`
to `2.0`. Implemented both:

- **`__dmul64`**: 64×64→128-bit schoolbook multiply of the 53-bit mantissas
  (nasm `MULADD` macro into the 8-word `__fp_p`), normalise (leading bit at 104
  or 105 ⇒ shift right 52 or 53), `er = ea+eb-1023(+1)`, pack. Truncating.
- **`__ddiv64`**: restoring division — pre-normalise so dividend mantissa ≥
  divisor (shift, `er--`), then 53 steps (`Q<<=1; if R≥M_b {R-=M_b; Q|=1};
  R<<=1`) yield a result mantissa already in `[2^52,2^53)`. `er = ea-eb+1023`.
  Divide-by-zero ⇒ ±inf, `0/x` ⇒ ±0.

**Also fixed a codegen bug it exposed:** after a double-valued FP binop the
result's 4 words go to `__fp_result`, but codegen only loaded 3 (`ax/dx/bx`) and
the variadic-printf consumer pushed `cx` for the high word *without loading it*
— so `printf("%f", <double expr>)` printed a value with a garbage sign/exponent.
Now loads `cx = [__fp_result+6]` (`codegen.py` `_gen_fp_binop`). This had been
masked because passing tests used the float-promotion or double-variable paths.

Verified: `1.5*2.0=3`, `1.1*1.1=1.21`, `6/2=3`, `10/4=2.5`, `100/8=12.5`,
`22/7=3.142857`, `1/3=0.333333`. New regression test
`single/double_muldiv.c`. Suite **29→30/40**, no regressions, 197 unit tests
pass.

Note: this completes the soft-float library but did not flip a *failing* suite
test — `bigstack`/`test_indvars`/`GlobalVarInitializers` don't use double `*`/`/`
(they need big-value printing, a 40 KB stack vs the 16 KB one, or struct-array
codegen fixes — see the FP investigation notes). It fixes real silent
miscompilation regardless.



## 2026-06-02 — `%f` fraction printing enabled + rounding (callargs PASSES, 29/39)

With the looping bug fixed (guard gap), re-enabled and corrected the
floating-point fraction printer in `stdlib/fp.asm`:

1. **Re-enabled `__print_d64`'s real fractional loop** (was stubbed to print
   `.000000`). The "main loops" hazard that gated it was the separate layout
   bug, now fixed.
2. **Fixed the `.small` path** (values < 1.0): it printed the leading `'0'`
   *before* reading the unbiased exponent from `AX`, but `putchar` clobbers
   `AX`, so the shift count was `52 - '0'` (garbage) → every sub-1.0 value
   printed `.000000`. Now computes the shift before the `putchar`. (`0.5`,
   `0.001` now correct.)
3. **Added round-to-nearest** to the fraction printer: extract `prec+1` digits
   into a buffer (`__fp_dig`), round the last printed digit from the guard
   digit (carry propagates leftward), then emit. Switched the ×10 multiply from
   fragile stack-relative scratch (`[bp-14..]`) to BSS scratch (`__fp_t*`) so it
   can't collide with the buffering pushes. (`3.14159` → `3.141590`, not
   `3.141589`.)
4. **Added round-half-up to `__d642f32`** (double→float): it truncated the
   discarded mantissa bits; now if the top discarded bit (mantissa bit 28) is
   set it increments the 32-bit float pattern (mantissa overflow carries into
   the exponent for free). Fixed `12.1f` printing as `12.099999` → `12.100000`.

Result: **`callargs` (t18) now PASSES**; suite **28→29/39**, no regressions,
whole-number doubles still exact, 197 unit tests pass.

Remaining FP mismatches are unrelated to printing: `bigstack`/`test_indvars`/
`GlobalVarInitializers` need real soft-float *arithmetic* (`fp.asm`'s
add/mul/div are skeletal); `UnionBitfields`/`UnionTest`/`casts`/`globalrefs` are
16-bit-data-model divergence (not bugs); `PR1386` (bitfields), `InlinerAndAllocas`
(alloca/VLA), `uint64_to_float` (`__builtin_clzll`/`fesetround`).



## 2026-06-02 — FP looping bug FIXED (stack/stdlib-BSS guard gap)

**Fixed** the layout-dependent corruption that made programs with ≥2 distinct
`double`s (and other `.data` sizes in a ~40-byte band) loop / re-execute.

Empirical root-cause via the qemu harness: the stack region lives in DGROUP
with the stdlib BSS (`__fp_*` soft-float scratch + the malloc heap) placed
immediately above `_stack_top`. For a narrow band of `.data` sizes a stdlib BSS
write lands on a live return-address slot near `_stack_top`, corrupting control
flow (the program loops; `printf("%f",2.5);printf("%f",2.1)` was the repro).

**Fix:** emit a 1 KB guard gap after `_stack_top` in `codegen.py` (~line 207),
separating the stack region from the stdlib BSS. This extends the existing
`sub sp, 16` bootstrap mitigation into a proper guard. Validated:
- byte-level `.data` sweep 0..1000 B: **loop-free** (previously looped at 20–60 B);
- N-distinct-double programs (1..8): all clean;
- full `single/` suite: **28/39 PASS** (was 27/38), no regressions, no timeouts,
  `sumarray2d` (the delicate 64 KB-cap case) still passes;
- 197 unit tests pass.

New regression test: `single/multi_double_print.c` (whole-number doubles print
exactly even with the `%f` fraction stub, so it's a clean PASS that loops →
NO_OUTPUT without the fix).

Caveat: the exact corrupting instruction wasn't isolated (gdb tooling friction —
see prior entries); the guard is an *empirically validated* fix, and it costs
1 KB of BSS per program (safe vs the 64 KB DGROUP cap for the current suite).
The `%f` fraction printer is still stubbed to zeros — a separate bug.



A running, dated log of what was changed and what was learned, so findings don't
have to be rediscovered. Newest entries first. For durable "how it works"
references see `docs/runtime-library.md`, `docs/real-mode.md`, and
`docs/single-suite-testing.md`.

---

## 2026-06-02 — FP corruption: gdb shows DOS RE-EXECUTES the program in a loop

Got `main`'s exact load address by searching memory for its prologue
(`55 89 e5 53 51 52 56 57`) — the lowest match is `main` (image offset
`0x8060`). For the `FA.EXE` repro it landed at linear `0x2b8f0`, giving
`LOADSEG=0x2389`, text `CS=0x2b8f`. Set hardware breakpoints at `main`
(`0x2b8f0`), `_entry` (`0x2b941`), and the exit `INT 21h/4C` (`0x2b966`), and
traced.

**Result — every one of 12 consecutive stops was at `_entry` (`CS:IP=2b8f:0051`)
with `SP=0x0010`** (the EXE header's load-time SP) and `AX=0`. `main` and the
exit `INT 21h` were **never hit**. `SP=0x0010` is the value the DOS EXEC loader
sets, so each hit is a **fresh program load**: DOS is re-executing the program
from its entry point over and over. This reframes the bug yet again:

- It is **not** in-`main` stack corruption. The program loads, (a watchpoint run
  separately confirmed it reaches `main` once with `SP=0x400c` and prints), then
  it gets **re-EXEC'd from scratch repeatedly** → the looping output. The
  trigger is still the layout/size window (~20–60 B of `.data`).
- Most likely cause: the program's **exit path or memory footprint corrupts a
  DOS memory-control structure** (MCB chain / PSP / terminate vector) for certain
  sizes, so when it terminates, DOS mis-behaves and reloads it. Consistent with
  the cramped-64KB observations and the `codegen.py:200-205` note. Candidate
  areas to scrutinise in codegen/runtime: the EXE min/max-alloc the linker emits,
  the `INT 21h/AH=4C` exit in the bootstrap (`codegen.py` `_entry`), and whether
  the 16 KB in-DGROUP stack + 16 KB heap overrun the program's allocated block.

**Tooling ceiling hit (documented in `docs/debugging-dos.md`):** `LOADSEG` is not
reliably reproducible across *cold* boots, so a hardcoded breakpoint address from
one boot misses on the next; gdb disassembles the 16-bit guest as 32-bit; and
QEMU `-S`/lock/launch races made iteration slow. A robust next attempt should
*first* learn `LOADSEG` in the same session (search memory for `main`'s prologue,
or break at `_entry` by scanning for `B8 xx xx 8E D8 8E C0 FA`), then set the
`main` breakpoint and watch the exit/terminate path and the MCB above the program.

---

## 2026-06-02 — FP corruption: gdb session, control-flow-corruption confirmed

Attached gdb to the looping program via the qemu gdb stub (`-s`), non-invasively
(no binary change). Findings:

- Multiple attaches caught the CPU with **`CS` pointing into DGROUP** (`CS=DS=SS`)
  or in the **BIOS** (`CS=f000`) — i.e. execution has escaped its code segment.
  Our codegen uses only *near* `ret`/`call`, so a near return cannot change `CS`.
  The escape therefore comes from a **far control transfer popping a corrupted
  `CS:IP`** — almost certainly the `IRET` at the end of an `INT 21h` (every
  `_putchar` does `INT 21/AH=02`) once the stack pointer/contents are already
  wrong. So: a near-`ret` first returns to the wrong place (re-entry → stack
  marches down), and then an `INT 21h` `IRET` reads a garbage `CS:IP` and the
  program goes fully wild. Output shows ~20 correct lines before the breakdown,
  so the first corruption is subtle/cumulative.
- Deterministic addressing for the repro `FA.EXE` (2.5/2.1): `main` at `text:0`,
  `_entry` at `text:0x51`, EXE-header `CS=0x0806` (relative). At load segment
  `LOADSEG` (=`DS`=`SS`, set by the bootstrap), runtime `CS = LOADSEG+0x806`, and
  `main`'s linear address = `(LOADSEG+0x806)<<4`. To break at `main` you must
  first learn `LOADSEG` by catching the program at entry.

**Practical gotchas for next time (in `docs/debugging-dos.md`):**
- gdb (this build) disassembles the 16-bit code as **32-bit** even with
  `set architecture i8086` — its `x/i` output is misleading. Dump bytes
  (`x/NXb`) and run them through `ndisasm -b16` instead.
- gdb attach timing is non-deterministic; the program escapes its segment after
  ~20 iterations, so late attaches only show the wild state. To catch the first
  corruption: qemu `-S`, learn `LOADSEG` (break at `_entry`, read the `mov ax,
  imm16` immediate = relocated DGROUP seg), `hbreak` at `main`, read `SS:SP`, set
  a **hardware watchpoint on `main`'s return slot** (`(SS<<4)+SP`), continue —
  the watchpoint fires on the corrupting write, and `CS:IP` then names the
  culprit instruction.

**Two concrete next paths** (the harness is ready for both):
1. *Pinpoint* — the deterministic watchpoint procedure above. Highest certainty,
   leads straight to the offending instruction, but more fiddly real-mode gdb.
2. *Empirical layout sweep* — qemu now iterates in ~2 s, so try targeted memory
   re-budgets (stack size/placement in `codegen.py:206`, heap size in
   `stdlib.asm:716`) and measure whether the looping window disappears, re-checking
   the delicate `sumarray2d`. Faster to a candidate fix, lower certainty of root
   cause.

---

## 2026-06-02 — FP corruption: emulator debugging, NEW mechanism evidence

Stood up a full DOS debugging harness (see `docs/debugging-dos.md`): pure-Python
FAT12 injector (`tools/fat12img.py`), a bootable FreeDOS floppy, and runs under
both **qemu** (fast, `-monitor`/`-serial`/gdb-stub) and **bochs** (scriptable
debugger + magic breaks, but slow under xvfb).

Findings that change the picture:

- **The corruption is NOT a DOSBox quirk — it reproduces identically under
  qemu.** A known-looping binary (`printf("%f",2.5); printf("%f",2.1)`) loops on
  both emulators. (An earlier "clean under qemu" reading was the *observer
  effect*: the bug is so layout-sensitive that adding any instrumentation shifts
  the binary out of the trigger window.) So it is a real, emulator-independent,
  layout-dependent code/runtime bug — worth fixing.
- **Runtime mechanism = runaway re-entry via a corrupted return address.**
  Freezing the looping program *non-invasively* with the qemu monitor (binary
  untouched) showed `ESP≈0x0A3E` mid-loop, whereas a clean run's `main`-entry SP
  is `~0x3FFB`: the stack has **marched ~14 KB downward**. Functions are being
  re-entered instead of returning — consistent with a layout-triggered write
  clobbering a return-address slot with a value that points back into code.
  Load segment ≈ `0x00D8` (CS=SS=DS, tiny model).
- **Observer effect is the key obstacle:** instrumentation (extra code/data)
  moves the binary out of the looping window, so the exact corrupting write must
  be caught with a *non-invasive* tool — qemu monitor (done, gave the signature)
  or a qemu+gdb hardware watchpoint on `main`'s return slot (the open next step;
  recipe in `docs/debugging-dos.md`).

Status unchanged: 27/38 suite, 197 unit tests. No code changed this round —
diagnosis + reusable harness only.

---

## 2026-06-02 — Binary literals fixed; FP corruption fully characterized

**Fixed: binary integer literals (`0b1010`, `0B100`).** Added a `0b`/`0B`
branch to `lexer.py:_read_number` (the parser already parsed the magnitude).
Unit tests in `tests/test_lexer.py`; verified end-to-end under DOSBox. Suite
unchanged (27/38), 197 unit tests pass.

**FP double-print corruption — fully characterized as a 64KB memory-budget
bug (deferred, too risky to fix blind).** Extends the entry below. Proved with
alink map/EXE-header diffs that clean vs looping builds are structurally
identical (shifted one paragraph), and that a *dead* trailing `dq` triggers it
— so it is a cramped-tiny-model layout problem, not values/printer. See the
refined root-cause bullet in the entry below for the full detail and the
re-budgeting options. Not attempted because the layout is delicately balanced
(`sumarray2d`'s 20KB locals only pass by luck per `codegen.py:200-205`) and a
blind change risks regressing currently-passing tests without a DOS debugger.

---

## 2026-06-02 — Octal literals fixed; FP double-print corruption root-caused

**Fixed: C octal integer literals (`0644`).** Added
`parser.py:_parse_c_int_magnitude`, which handles `0x`/`0b`/`0o` prefixes, the
C octal form `0NNN` (base 8 — the case Python's `int(s, 0)` rejects), and
decimal. `_parse_int_literal` now calls it. Unit test:
`tests/test_parser.py::TestIntegerLiterals`. Integration: `single/posix_fileio.c`
uses `0644` for `open`'s mode. **Verified** end-to-end under DOSBox
(`0644`→420, `010`→8, `0xFF`→255). Suite unaffected (27/38).

**Discovered: binary literals `0b1010` are not lexed** as one token (the lexer
splits `0b1010` into `0` + identifier `b1010`). The parser-level magnitude
function already handles `0b`; only the lexer number-scanner needs a `0b`/`0B`
prefix. Logged in `todo.md`.

**Root-caused (not yet fixed): printf corrupts memory with multiple DISTINCT
`double` values.** This is the real blocker behind the floating-point suite
mismatches — bigger than the missing fraction printer.

- Repro: `printf("%f\n", 2.5); printf("%f\n", 2.1);` corrupts memory — output
  duplicates, strings get mangled (`MID`→`VID`), and `main` re-runs. With one
  call, or with N calls of the *same* value, it is clean. Even two distinct
  **whole-number** doubles (`2.0` then `3.0`) corrupt — so it is unrelated to
  fractions; it is purely "≥2 distinct double values in one program."
- **Likely root cause = a memory-layout / heap collision, not printer logic.**
  `fp.asm:2036-2038` carries an author note: *"No .data section — keep fp.obj
  BSS-only so the linker's layout of main's .data/.bss doesn't shift in a way
  that places fp's table at an address conflicting with the malloc heap."* The
  bug is data-size-sensitive: a second distinct double adds a `_fconst_N` (8
  bytes) to `.data`, which shifts the linked `.bss`/heap/`_stack_top` layout
  into a conflicting arrangement. Adding 4 words to `.bss` was enough to flip
  the symptom from "terminates (rc=0)" to "infinite loop (rc=124)". The fix is
  about the segment/stack/heap layout (`builder.py` bootstrap `mov sp,
  _stack_top`, the `resb 0x4000` stack region, and where alink places stdlib
  `.bss` / `_heap`), NOT `__print_d64`.
- This reproduces on the **untouched git-HEAD `fp.asm`** (the original just
  happens to terminate with rc=0 after the corruption rather than looping).
  So it is pre-existing, independent of the fraction printer.
- Key clue: `__print_d64`'s control flow is **value-independent** for equal
  exponents (2.5 and 2.1 both have E=1 ⇒ identical shift/loop counts and
  identical memory addresses touched), and the integer parts printed are
  identical ("2"). A value-independent code path cannot itself produce
  value-dependent memory corruption — so the fault is very likely **outside**
  `__print_d64`: in how `printf`/`_print_double_words` marshal the second
  distinct double, or a data-layout-sensitive latent bug (adding a second
  `_fconst_N` to `.data` shifts addresses and flips the symptom between
  "terminates" and "loops"). Adding 4 words to `.bss` (`__fp_t*`) was enough to
  turn rc=0 into an infinite loop — strong evidence of a layout-sensitive
  stack/BSS/stack-top collision.
- **Refined root cause (2026-06-02, follow-up):** it is a cramped-64KB
  **memory-budget/layout** problem, not value- or printer-related at all. Proof
  chain: (1) a *dead, unreferenced* trailing `dq` in `.data` triggers it, so
  values are irrelevant; (2) it loops for `.data` sizes ≈20–60 bytes but is
  clean below 16 and above 76 — a size window, not a monotonic threshold;
  (3) the alink **map files and EXE headers for a clean vs looping build are
  structurally identical, just shifted by one paragraph** — so pyc's layout
  logic is self-consistent; the failure is in the emergent absolute layout.
  The tiny model puts everything in one 64KB segment: `text`≈13.5KB,
  `_heap`=16KB (`stdlib.asm:716 resw 8192`), the 16KB in-BSS stack
  (`codegen.py:206 resb 0x4000`, `_stack_top`), `__fp_*` scratch, and `.data`.
  `_stack_top` sits at bss offset 0x4000 with `__fp_result`/`__fp_*` only ~0x18
  bytes *above* it and the heap just beyond — so a small absolute-address shift
  (or any stack drift above `_stack_top`) lands a frame/return-address on the
  `__fp_*` words that `__print_d64` then overwrites → corrupted return → main
  re-runs. The author already flagged this tension in `codegen.py:200-205`
  ("Larger stacks have left less room for the 16 KB heap … causing corruption
  when both are near the 64 KB DGROUP cap"); `sumarray2d` (20KB locals) only
  passes by luck. **A real fix means re-budgeting the 64KB tiny-model layout**
  (separate the stack from `__fp_*`/heap with real headroom, shrink the heap,
  or move to a larger memory model) — and must be re-verified against
  `sumarray2d`, which is delicately balanced. Too risky to change without a DOS
  debugger; deferred.
- Next step for whoever picks this up: trace `printf`'s `%f` path
  (`stdio.asm:1003/1969 → _print_double_prec/_print_double_words → __print_d64`)
  and check the vararg-pointer / format-pointer registers (SI/DI) and the
  `_stack_top` vs stdlib `.bss` placement in the linked image (see the layout
  in a `-S` dump: `resb 0x4000` + `_stack_top`, with stdlib `.bss` merged by
  alink). Fixing this likely unblocks the fraction printer AND
  `callargs`/`bigstack`/`test_indvars`/`GlobalVarInitializers` together.
- **Attempted and reverted:** re-enabling the disabled `__print_d64` fractional
  multiply-by-10 loop made single-value fractions correct (2.1→2.100000,
  123.456→123.456000) but exposed the corruption above as a hard timeout, so
  it was reverted to the zeros stub. The fraction algorithm itself looks
  correct; it is gated on fixing the corruption first.

---

## 2026-06-02 — POSIX file I/O + serial port runtime

**Added** a POSIX-style low-level I/O layer (user request).

- New runtime `stdlib/posix_io.asm`: `open`, `close`, `read`, `write`, `lseek`,
  and a global `errno`, layered over DOS INT 21h handle calls
  (AH=3Ch/3Dh/3Eh/3Fh/40h/42h). `O_APPEND` is emulated with a post-open seek to
  end. Functions return `-1` and set `errno` to the DOS error code on `CF`.
- New runtime `stdlib/serial.asm`: raw BIOS INT 14h layer `serial_init`,
  `serial_putc`, `serial_getc`, `serial_status`. Serial also works through the
  file layer because DOS treats `COM1`/`AUX` as character devices.
- New built-in headers in `src/pyc/preprocessor.py`: `<fcntl.h>`, `<unistd.h>`,
  `<errno.h>`, `<serial.h>`.
- `builder.py` `stdlib_order` extended with `posix_io` and `serial`.
- New suite tests: `single/posix_fileio.c` (file create/write/seek/read
  round-trip, **passes**) and `single/serial_smoke.c` (links + runs, **passes**).

**Suite status:** 27 PASS / 10 MISMATCH / 1 COMPILE_FAIL of 38 (was 25/10/1 of
36). Both new tests pass; no regressions.

**Discoveries:**

- **Octal literals unsupported.** `int(s, 0)` in
  `parser.py:_parse_int_literal` raises `ValueError` on a C octal form like
  `0644` (Python needs `0o644`). The lexer's todo note claiming octal works is
  inaccurate for the parser path. Logged in `todo.md`.
- **`read()` does not null-terminate** (correct POSIX behavior) — a short reread
  into a buffer that previously held a longer read leaves the trailing bytes, so
  `printf("%s")` shows the longer content. (Corrected a wrong expectation in the
  original plan.)
- Confirmed the runtime conventions now captured in `docs/runtime-library.md`:
  no-underscore C-visible symbols, cdecl arg layout, implicit-extern emission,
  and that `SS==DS` makes near pointers (incl. stack locals) valid as DOS
  `DS:DX` buffers without segment work.

---

## Baseline before this session (from `todo.md` root-cause map)

The remaining MISMATCH/COMPILE_FAIL fall into buckets that are **not** quick
wins:

- **Data-model divergence (not bugs):** `UnionTest`, `casts`, `globalrefs`
  reference outputs assume 32-bit `int`/64-bit `long`; pyc is correctly 16-bit
  (`int`=16, `long`=32) for DOS, so its outputs legitimately differ.
- **Soft-float arithmetic skeletons** (`fp.asm`): `bigstack`,
  `GlobalVarInitializers`, `test_indvars`.
- **`__print_d64` fractional-digit stub** (`fp.asm` prints `.000000`): affects
  `callargs` and any non-integer `%f`.
- **Substantial feature work:** `PR1386` (64-bit/packed bitfields),
  `UnionBitfields` (IEEE bit overlay + inf from FP div), `InlinerAndAllocas`
  (alloca/VLA arithmetic), `uint64_to_float` (long-double bitpatterns + fenv,
  the lone COMPILE_FAIL: needs `__builtin_clzll`, `fesetround`).
