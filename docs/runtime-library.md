# Runtime Library (`stdlib/`) — How It Works

This is the durable reference for pyc's C runtime: the hand-written 16-bit NASM
that implements the C standard library and platform glue. Read this before adding
or changing any runtime function so the conventions below don't have to be
rediscovered.

## Build / link model

- Every `stdlib/<name>.obj` is linked into **every** program, unconditionally.
  The list and link order live in `src/pyc/builder.py:get_stdlib_objects()`
  (`stdlib_order`). `_get_stdlib_object()` assembles `stdlib/<name>.asm` with
  NASM on demand and caches the `.obj` (rebuilding when the `.asm` is newer).
- To add a runtime function: (1) define + `global`-export the symbol in an `.asm`
  that is listed in `stdlib_order`; (2) declare its prototype in a built-in header
  (see "Headers" below). No codegen change is needed — the compiler emits an
  `extern` for any call target it can't resolve locally
  (`src/pyc/codegen.py` `_gen_call`, ~line 3021: unknown identifier ⇒ implicit
  external function), and the linker binds it to the stdlib object.
- The linker is `alink`; `build()` in `builder.py` produces a DOS `.EXE`.

## Symbol naming convention

- **C-visible** functions are exported `global <cname>` with **no leading
  underscore** — e.g. `global malloc`, `global printf`, `global open`,
  `global memcpy`. The C source calls `foo()` and codegen emits `call foo`.
- **Internal helpers** use a leading underscore: `_putchar`, `_print_int`,
  `_emit_char`, `__mul64`, `__fp_result`. These are not meant to be called from C
  directly (though some, like `__f322d64`, are emitted by codegen for conversions).
- Data symbols follow the same rule: `errno` (C-visible) vs. `__fp_result`
  (internal scratch).

## Calling convention (cdecl, 16-bit)

- Arguments are pushed **right-to-left**; the **caller** cleans the stack
  (`add sp, N`).
- After the standard prologue `push bp; mov bp, sp`, arguments start at `[bp+4]`
  (`[bp+0]`=saved BP, `[bp+2]`=return address). Each successive word arg is at
  `[bp+6]`, `[bp+8]`, …
- A 32-bit (`long`) argument occupies two words pushed high-then-low, so it reads
  back little-endian: low word at the lower address. Example for
  `long lseek(int fd, long offset, int whence)`:
  `[bp+4]`=fd, `[bp+6]`=offset-low, `[bp+8]`=offset-high, `[bp+10]`=whence.
- Return values: 16-bit in `AX`; 32-bit (`long`/pointer-pair) in `DX:AX`
  (DX=high). 64-bit returns use `AX`/`DX` plus the `__ret64_hi` helper slot.
- `BX`, `SI`, `DI`, `BP` are callee-saved; `AX`, `CX`, `DX` are caller-saved
  (DX is intentionally not preserved across calls — see codegen note ~line 418).

## Memory model (why near pointers "just work")

The bootstrap (`builder.py`, single- and multi-file paths) sets
`SS = DS = ES = DGROUP` (small model). Consequences relied on throughout the
runtime:

- A near pointer passed from C is a plain offset that is valid against `DS`,
  including pointers to **stack locals** (because `SS == DS`). That is why DOS
  calls needing `DS:DX → buffer` (read/write/open) can take the C pointer
  directly in `DX` with no segment juggling.
- See `docs/real-mode.md` for the full real-mode constraints (addressing modes,
  segment roles, pointer types).

## DOS / BIOS interrupts

Use Ralf Brown's list via the curated index `interrupts/dos_int_ref.md` (each row
cites `INTERRUP.X:line`). Interrupts already used by the runtime:

| Area | Interrupt(s) |
|------|--------------|
| console char I/O | INT 21h AH=01h/02h (`dos_io.asm`) |
| process exit | INT 21h AH=4Ch (`dos_io.asm`) |
| file I/O | INT 21h AH=3Ch/3Dh/3Eh/3Fh/40h/42h (`posix_io.asm`) |
| serial (BIOS) | INT 14h AH=00h/01h/02h/03h (`serial.asm`) |
| heap (malloc) | INT 21h AH=48h/49h (planned/partial — see stdlib.asm) |

## Module map

| File | Provides |
|------|----------|
| `dos_io.asm` | `_putchar`, `_getchar`, `_exit` (low-level console) |
| `stdio.asm` | `printf`, `sprintf`, `puts`, `putchar`, `getchar`, the `%`-format engine, and `_print_*` integer/hex/double helpers |
| `long_io.asm` | 32/64-bit print + `__mul32/64`, `__udiv32`, `__sdiv32`, … |
| `fp.asm` | soft-float: conversions, add/sub/mul/div (`__dadd64`/`__dmul64`/`__ddiv64`), and `__print_d64`/`__print_f32` (fraction printing + rounding) |
| `string.asm` | `strlen`, `strcpy`, `strcmp`, `memcpy`, `memset` |
| `stdlib.asm` | `malloc`, `calloc`, `realloc`, `free`, `atoi`, `atol`, `atof`, `exit`, `_heap` |
| `posix_io.asm` | `open`, `close`, `read`, `write`, `lseek`, `errno` |
| `dos_dir.asm` | `mkdir`, `set_dta`, `find_first`, `find_next` (INT 21h 39h/1Ah/4Eh/4Fh); header `<dos.h>` with `FA_*`/`DTA_*` macros. `find_*` fill the DTA: `[21]`=attr, `[26..29]`=size, `[30..]`=name. |
| `serial.asm` | `serial_init`, `serial_putc`, `serial_getc`, `serial_status` (INT 14h); plus direct-UART `uart_init`/`uart_rx_ready`/`uart_getc`/`uart_putc` (polled 8250/16550 by I/O base) |

## POSIX file I/O (`posix_io.asm` + `<fcntl.h>`/`<unistd.h>`/`<errno.h>`)

- `int open(char *path, int flags, int mode)` — `O_CREAT` ⇒ INT 21h AH=3Ch
  (create/truncate, normal attrs), else AH=3Dh with `AL = flags & 3` (access
  mode). `O_APPEND` is **emulated**: after a successful open the code seeks to end
  (AH=42h, whence=2). On `CF`, stores `AX` into `errno` and returns `-1`.
- `int close(int fd)` — AH=3Eh; returns 0 / sets errno + returns -1.
- `int read/write(int fd, void *buf, unsigned count)` — AH=3Fh / AH=40h; returns
  the byte count, or -1 on error.
- `long lseek(int fd, long offset, int whence)` — AH=42h; returns the new
  position in `DX:AX`, or `0xFFFFFFFF` (-1) on error.
- `int errno` lives in `posix_io.asm`'s `.data`.
- **Flag values** (`<fcntl.h>`) are pyc's own encoding decoded in the runtime;
  only the low two access-mode bits map directly to the DOS `AL` byte:
  `O_RDONLY 0`, `O_WRONLY 1`, `O_RDWR 2`, `O_CREAT 0x100`, `O_TRUNC 0x200`,
  `O_APPEND 0x400`.
- **Serial via the same API:** DOS exposes `COM1`/`AUX`/`CON` as character
  devices, so `open("COM1", …)` returns a handle that `read`/`write` drive
  through the same INT 21h calls. No baud control this way — use the raw layer.

## Raw serial (`serial.asm` + `<serial.h>`)

BIOS `INT 14h`, `port` is 0-based (0 = COM1):
- `serial_init(port, params)` — AH=00h; `params` is the INT 14h line-control byte
  (baud bits 7-5, parity 4-3, stop bit 2, word length 1-0). `<serial.h>` defines
  `SER_9600`, `SER_8N1`, etc. Returns the status word.
- `serial_putc(port, ch)` — AH=01h; returns the line-status byte.
- `serial_getc(port)` — AH=02h; returns the byte (0-255), or -1 if AH bit7
  (error/timeout) is set.
- `serial_status(port)` — AH=03h; returns the 16-bit status word.

> Headless DOSBox has no real UART, so serial data round-trips can't be asserted
> automatically. The smoke test (`single/serial_smoke.c`) only checks the calls
> link and run without hanging (run DOSBox with `-c "config -set serial1 null"`).

## Headers

Built-in headers are embedded as strings in `src/pyc/preprocessor.py`,
registered in `_register_builtin_headers()` and emitted by `_<name>_h()`
staticmethods. They are stubs: just enough prototypes/macros/typedefs for the
parser. To add a header: add the `self._headers["x.h"] = self._x_h()` line and a
matching staticmethod (mirror `_stdio_h()`).

Currently provided: `stdio.h`, `stdlib.h`, `string.h`, `ctype.h`, `math.h`,
`stdarg.h`, `stdbool.h`, `stdint.h`, `stddef.h`, `inttypes.h`, `alloca.h`,
`fenv.h`, `float.h`, `fcntl.h`, `unistd.h`, `errno.h`, `serial.h`, `dos.h`.

## Known limitations (do not rediscover — see also `docs/progress-log.md`)

- **(FIXED 2026-06-02) Data-size-dependent memory corruption / looping** — a
  ~40-byte band of `.data` sizes put a stdlib BSS write onto a live
  return-address slot near `_stack_top`, making programs loop/re-execute
  (e.g. two distinct `double`s via `printf`). Fixed with a 1 KB guard gap after
  `_stack_top` in `codegen.py`. (Kept here as a pointer; see progress log.)
- **`%f`/`%lf` fraction printing works (fixed 2026-06-02):** `__print_d64`
  emits real fractional digits with round-to-nearest (buffered in `__fp_dig`),
  and `__d642f32` (double→float) rounds half-up. Direct `double` values print
  correctly (`2.1`→`2.100000`, `0.5`→`0.500000`, `12.1f`→`12.100000`). The
  earlier "prints `.000000`" stub and the `.small`-path AX-clobber bug are gone.
- **Soft-float: add/sub/mul/div on `double` work** (`__dadd64`/`__dsub64`/
  `__dmul64`/`__ddiv64`, fixed 2026-06-02; mul/div were previously skeletons).
  Remaining gaps elsewhere: `bigstack`/`test_indvars` fail for non-arithmetic
  reasons (struct-array codegen, 40 KB stack vs 16 KB) and huge-value printing.
- Octal (`0644`) and binary (`0b1010`) integer literals work (fixed 2026-06-02).
- See `docs/progress-log.md` for the running status of fixes.
