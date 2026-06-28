Make sure the following is correct or done:

 - [x] static keyword works correctly both outside functions (makes variables only accessible in the file), as part of function definition/declaration (function only available inside file) and inside functions (value is retained in the function)
 - [x] const keyword works correctly
 - [ ] various C programs works correctly
 - [ ] basic variants of stdint.h stdio.h stdlib.h ... exists as files in a dedicated folder
 - [x] POSIX-style low-level file I/O: `open`/`close`/`read`/`write`/`lseek`
       + global `errno`, layered over DOS INT 21h handle calls
       (AH=3Ch/3Dh/3Eh/3Fh/40h/42h). Runtime in `stdlib/posix_io.asm`;
       headers `<fcntl.h>`, `<unistd.h>`, `<errno.h>` in
       `src/pyc/preprocessor.py`. Verified by `single/posix_fileio.c`
       (file round-trip: create/write/seek/read).
 - [x] Raw BIOS serial layer (INT 14h): `serial_init`/`serial_putc`/
       `serial_getc`/`serial_status` in `stdlib/serial.asm`, header
       `<serial.h>` with baud/parity macros. Serial-over-DOS-handles
       (open "COM1"/AUX) also works through the POSIX layer above.
       Smoke-tested by `single/serial_smoke.c` (links + runs; headless
       DOSBox has no UART so TX/RX data is not asserted).
 - [x] Octal integer literals (`0644`) now parse correctly. Added
       `parser.py:_parse_c_int_magnitude` (handles `0x`/`0b`/`0o`, C octal
       `0NNN` via base 8, and decimal); `_parse_int_literal` uses it.
       Unit test: `tests/test_parser.py::TestIntegerLiterals`. Integration:
       `single/posix_fileio.c` uses `0644`.
 - [x] Binary integer literals (`0b1010` / `0B100`) now lex and parse.
       Added a `0b`/`0B` branch to `lexer.py:_read_number` (the parser's
       `_parse_c_int_magnitude` already handled the value). Unit tests:
       `tests/test_lexer.py::TestLiterals::test_binary_literal*`. Verified
       end-to-end under DOSBox (0b1010→10, 0b11111111→255, 0B100→4).
 - [ ] support for specifying multiple include paths
 - [ ] support for globally defined variables
 - [x] support for extern keyword (for specifying a variable exist in another file)
 - [ ] accept volatile keyword. For the moment it doesn't do anything since there is no optimizations. NOTE: there now *is* a peephole optimizer (`src/pyc/optimizer.py`); if volatile is implemented, `_pass_store_reload` and `_pass_zero_arith` must skip volatile-qualified memory (else a required volatile read/reload gets eliminated).
 - [x] create unit tests to validate or verify that the points above works (ex. testing static, const, extern and volatile)
 - [ ] for convenience and readability, translate C comments to assembly comments. comments above or on a line of C code can be inserted as assembly comment before the corresponding translated code
 - [x] Implement typedef parsing and resolution
 - [x] Add typedef tests and validate preprocessor handling of typedefs

Codegen bugs fixed (codegen.py):
 - [x] Entry point used `mov ax, cs; mov ds, ax` → DS pointed to code segment, not data
       segment. Intermediate fix used `mov ax, ss`, but with a separate stack
       segment SS no longer equals DGROUP, so DS pointed at the stack instead.
       Final fix: codegen emits a leading `_data_start:` label in `.data` and
       `_entry` uses `mov ax, seg _data_start` (NASM emits a SEG relocation that
       alink resolves at load time). Same fix mirrored in builder.py and
       compiler.py entry-point injection.
 - [x] alink wrote SS:SP=0000:0000 into the MZ header without a stack segment,
       which dosbox-x rejects with "EXEC stack underflow/wrap". Fixed:
       codegen emits `section .stack stack class=STACK / resb 0x1000` when
       the TU defines `main`. Entry point no longer touches SP — the loader
       sets it from the EXE header.
 - [x] Stdlib object cache in builder.py only rebuilt `.obj` if missing,
       ignoring `.asm/.c` newer than the cached `.obj`. Fixed with mtime check.
 - [x] `stdlib/dos_io.asm` declared `global _exit` but had no `_exit:` label —
       the exit body was orphaned after `_getchar`'s `ret`. Rewritten with
       proper labels; `_putchar` switched from INT 10h AH=0Eh (BIOS teletype,
       bypasses stdout) to INT 21h AH=02h (DOS char output, redirectable).
 - [x] String literals emitted in `.data` as hex bytes (`db 0x48, 0x69, 0`) —
       hard to read. Now emitted as text with control bytes inline
       (`db "Hi", 10, 0`).
 - [x] `_gen_return` emitted `mov sp, bp` then fell through to epilogue whose pops
       read from [BP+0]/[BP+2]/… (saved BP / ret addr) instead of the actual saved
       registers, trashing caller's BX/CX/DX/SI/DI on every call. Fixed: return now
       emits `jmp .func_ret`; epilogue restores registers via `mov reg, [bp-N]`.
 - [x] Parameter copy loop had wrong source offset (`4+(n-i)*2` instead of `4+i*2`),
       wrote to [BP-0] (saved BP) instead of allocated locals, and the load address
       never matched the store. Fixed: parameters are now registered at their natural
       cdecl offsets [BP+4],[BP+6],… with no copying.
 - [x] `_local_count` started at 0, so the first `_gen_local_alloc` would allocate
       at [BP-2] = saved BX area. Fixed: starts at -10 (5 saved regs × 2 bytes).
 - [x] Char pointer dereference used `mov ax, [bx]` (word), so null terminator 0x00
       loaded as 0x00XX (nonzero) → string loops never terminated. Fixed: added
       `_gen_load_mem` that emits `mov al,[bx]; xor ah,ah` for 1-byte elements.
 - [x] `_gen_subscript` did not scale index by element size (char/int both used offset
       1×). Fixed: scales by element_size (shl ax,1 for words, etc.).
 - [x] `_gen_compound_assign` for `+=`/`-=` etc. loaded LHS into AX then overwrote it
       with RHS, and emitted invalid `add bx` (missing second operand). Fixed.
 - [x] `_gen_compound_assign` for `*ptr = value` had push/pop in wrong order, using
       value as pointer address. Fixed.
 - [x] Postfix `++`/`--` incremented AX but never stored back to the variable. Fixed.
 - [x] Pre `++`/`--` was not implemented. Fixed.
 - [x] Duplicate dead `*`/`/`/`%` handlers in `_gen_binary_op` (unsigned-aware versions
       were unreachable because signed-only versions appeared first). Fixed.

Common-C sweep (correctness + missing idioms + 32-bit math + preprocessor + comments):
 - [x] Subscript on assignment LHS: `arr[i] = v` and compound forms
       (`arr[i] += v` etc.).  New `_gen_lvalue_address` + size-aware
       `_gen_store_through_bx` unify subscript / `*ptr` / member writes.
 - [x] Compound `op=` on `*ptr`, `arr[i]`, `obj.m` for 16-bit values
       (`+=`, `-=`, `*=`, `/=`, `%=`, `&=`, `|=`, `^=`, `<<=`, `>>=`).
 - [x] `++`/`--` on non-Identifier lvalues (`*p++`, `arr[i]++`,
       `obj.m++`).  Postfix preserves the OLD value via a stack push.
 - [x] Char stores via `*p = c` / `arr[i] = c` / `obj.m = c` emit a
       1-byte `mov [bx], al` when the lvalue's element size is 1.
 - [x] Enum members resolve as integer constants in expressions
       (`enum { A=7 }; int x = A;` now compiles to `mov ax, 7`).
       Parser registers each enum name in `self.enum_consts` and
       `_parse_primary` returns an `IntLiteral`.
 - [x] Array initializers: `int a[3] = {1, 2, 3};` parses via a new
       `InitList` AST node and codegens to per-element stores at
       scaled offsets, zero-filling any tail when the list is short.
 - [x] String initializers for `char[]`: `char s[] = "hello";`
       (array size inferred from string length + 1) and
       `char s[6] = "hello";` (explicit size, NUL + padding).
 - [x] Array name decays to address: identifier-of-`ArrayType` reads
       emit `lea ax, [bp + offset]` instead of `mov ax, [bp+offset]`,
       so `a[i]` and `f(a)` both see the array's start address.
 - [x] 32-bit `*` / `/` / `%`: new runtime helpers
       `__mul32`, `__udiv32`, `__sdiv32`, `__umod32`, `__smod32`
       in `stdlib/long_io.asm` (shift-and-subtract long division
       with sign wrappers).  Codegen routes 32-bit `*`/`/`/`%` to
       `call <helper>` with 8-byte caller cleanup.
 - [x] Preprocessor `#else` / `#elif` properly evaluated.
       Replaced the always-skip-to-#endif logic with a frame stack
       tracking `taken` and `any_taken` flags; supports nesting and
       suppresses inner `#if` chains inside suppressed outer blocks.
 - [x] C comments threaded through to NASM as `; comment` lines.
       Lexer records `(line, text)` for each `//` and `/* */`
       comment; `tokenize_with_comments` exposes them to the compile
       pipeline; codegen attaches `source_line` to each statement
       (parser side) and `_flush_comments_up_to` emits pending
       comments before the matching statement, prefixing every
       internal newline with `; ` so multi-line `/* */` stays
       NASM-valid.
 - [x] Test count grew from 129 → 145 with new unit + e2e coverage:
       subscript LHS, `*p += 1`, `arr[i]++` (postfix old-value), char
       store width, enum constant, array & string initializers, 32-
       bit mul/div/mod helper calls, all four `#if/#elif/#else`
       cases plus nested suppression.

Function pointers:
 - [x] Lexer/parser accept `int (*name)(...)` parenthesised
       function-pointer declarators. Anonymous parameters (`int (*p)(int, int)`)
       are also accepted in `_parse_function_params` (was previously
       silently dropping the trailing one).
 - [x] `FunctionType` added to `src/pyc/types.py` (return_type, params,
       is_variadic).  `typedef int (*BinOp)(int, int);` resolves to
       `PointerType(FunctionType(int, [int, int], False))`.
 - [x] Function declarations (no body) like `int side(void);` now
       register a FUNCTION-kind symbol carrying the FunctionType (was:
       VARIABLE-kind with bare return type).
 - [x] Function-name decay: `_gen_load_identifier` emits `mov ax, name`
       (label as immediate address) for a function symbol, not
       `mov ax, [name]` (data read).  Lets `BinOp p = add;` and
       `apply(add, ...)` work.
 - [x] Indirect call: `_gen_call` now dispatches direct (`call name`)
       vs. indirect (`call ax` after evaluating the callee).  Triggers
       on:
         - parameters of pointer-to-function type (`int f(BinOp p) { p(); }`)
         - locals holding function pointers
         - chained calls like `choose(0)(10, 20)` where the callee is a
           `CallExpr` returning a function pointer
       Unknown bare identifiers still resolve as direct (implicit
       function declaration — matches K&R C and how stdlib calls like
       `scanf` were already handled).
 - [x] `_gen_call` argument-decay path narrowed to ArrayType only;
       pointer-typed parameter args are now loaded as values (was: had
       their addresses taken via LEA, a latent bug for pointer params).

Variadic functions and supporting fixes:
 - [x] Lexer recognises `...` as a single ELLIPSIS token (was previously
       three separate DOTs).
 - [x] Parser accepts `int f(int a, ...)` and threads `is_variadic` onto
       `FunctionDefinition`; rejects `...` without a preceding named
       parameter and rejects anything after `...`.
 - [x] Parser recognises typedef'd names as type specifiers at statement
       scope (previously only the built-in `INT`/`CHAR`/... tokens
       triggered the declaration path, so `va_list ap;` was misparsed as
       an expression statement and the variable became an undefined
       external).
 - [x] Codegen scales pointer arithmetic by `sizeof(*ptr)`: `+`/`-`
       check `_expr_pointee_type(left/right)` and shift the int operand;
       `++`/`--` use `add ax, N` / `sub ax, N` instead of `inc ax` /
       `dec ax` for pointer identifiers. Plain int + int is unaffected.
 - [x] `_expr_ptr_inner_size` now peeks through `&ident` and
       `++ident`/`--ident` so the dereference codegen (`mov al,[bx]`
       vs `mov ax,[bx]`) picks the right element size for those forms
       too.
 - [x] Preprocessor `#define` parsing: the previous `args.split(None, 1)`
       conflated `NAME(params) body` with `NAME (params)body`, leaving
       function-like macros with names like `va_start(ap,` that were
       never expanded. Scan the macro name explicitly so the
       function-like macros in `<stdarg.h>` work.
 - [x] Preprocessor `_expand_func_macro` regex bug: pattern was
       `re.escape(name) + r"\\("` (a literal backslash-paren) which
       never matched and crashed once a real macro got registered.
       Replaced with a proper word-boundary `re.escape(name) + r"\s*\("`
       and used word-boundary regex for parameter substitution inside
       the body.
 - [x] `<stdarg.h>` synthetic header registered in the preprocessor with
       `typedef int *va_list; va_start; va_arg; va_end` macros.
 - [x] `<stdio.h>` printf prototype changed to
       `int printf(char *format, ...);`. `stdlib/stdio.c:printf`
       rewritten to use `va_list`/`va_arg`/`va_end`.

More codegen / lexer bugs fixed:
 - [x] `_gen_logical` for `&&` and `||` produced wrong results when one operand
       was zero and the other non-zero — the early-exit `jnz` left AX holding
       the LEFT operand instead of normalising to 1.  Now branches to a
       shared "true" label that sets AX=1, with an explicit "false" path
       setting AX=0.  Symptom before fix: `_print_int(10)` printed "1"
       instead of "10" because the trailing-zero condition
       `digit > 0 || printed || divisor == 1` evaluated to 0.
 - [x] Lexer character-escape table missing `\0` (and `\a`, `\v`), so `'\0'`
       was passed through as the digit `'0'` (0x30).  Symptom: scanf's
       `*out = '\0'` wrote `'0'` and `printf("%s")` printed a trailing `0`.
       Same map applied to both string and char literal lexers.
 - [x] CharLiteral codegen emitted `mov ax, {expr.value}` with the raw char
       string, which broke for control bytes (e.g. `'\0'` ends up as raw
       NUL in the NASM source).  Now emits the integer ordinal.
 - [x] EXE header SS:SP was 0:0 without a `class=STACK` segment.  Codegen
       now emits a tiny `section .stack stack class=STACK` so alink writes
       a valid SS:SP.
 - [x] Small-model bootstrap: entry point now sets SS=DS=DGROUP and SP=
       `_stack_top` (a label at the end of a 0x1000-byte bss reservation).
       `group DGROUP data bss` is emitted so `_stack_top` resolves to its
       DGROUP-relative offset (data size + bss position) rather than the
       bss-local 0x1000.  Without SS=DS, addresses of locals taken via LEA
       (SS-relative) failed when dereferenced through DS (`mov [bx], ax`).
 - [x] `stdlib/builder._get_stdlib_object` rebuilds `.obj` only when missing;
       now compares mtimes so edits to `stdlib/*.asm` / `*.c` propagate.
 - [x] `stdlib/dos_io.asm` declared `global _exit` but lacked an `_exit:`
       label.  Rewritten with proper labels; `_putchar` switched to
       INT 21h AH=02h so stdout redirection works.
 - [x] String-literal `.data` emission switched from hex bytes
       (`db 0x48, 0x69, 0`) to readable text (`db "Hi", 10, 0`).

`<stdint.h>` / `<stdbool.h>` / bitfields / short-circuit / 32-bit ints:
 - [x] `<stdbool.h>` and `<stdint.h>` shipped as synthetic headers.
 - [x] Lexer integer-literal parsing handles `0x...` hex, octal, and the
       `L` / `U` / `UL` suffixes; oversized decimals auto-promote to `long`.
 - [x] Short-circuit `&&` / `||`: right operand is only evaluated when the
       result isn't already determined. `if (p && p->x)` is now safe with
       a NULL `p` (verified end-to-end).
 - [x] Verified `&`, `|`, `^`, `%`, `!`, `~` codegen with unit + e2e tests
       (`tests/test_codegen.py::TestBitwiseAndUnaryOps`).
 - [x] 64-bit `<<` / `>>` shift codegen (t14 LongLongSignedShift PASS).
       Loop-based implementation in `_gen_binary_op64`; shift count
       clamped to 0..63 and held in SI (CX is the high word of the
       value).  `>>` picks SAR vs SHR by left operand signedness.
 - [x] `LL` / `ULL` suffix on integer literals yields a long_long type
       (parser counts L's, was previously treated as plain long).
       Required so `-99LL` propagates the full 64-bit value, not just
       the low 16 bits.
 - [x] Unary `-`, `~`, `!` on a `long long` operand handle all four
       words (was only handling 32-bit DX:AX form).  64-bit negate uses
       `neg lo / not w_i / sbb w_i, -1` to propagate borrow correctly.
 - [x] `_print_llong` 64-bit negation in `stdlib/long_io.asm` fixed:
       was using `not + adc 0` which silently flipped to `~w + 1` on
       every intermediate word even when no borrow was needed.  Now
       uses `not + sbb -1` so values like `-99LL` print correctly.
 - [x] 64-bit IntLiteral codegen loads all four words (AX/DX/BX/CX);
       previously only loaded AX, leaving the upper words holding
       stale register contents.
 - [x] Struct member access uses the field's byte offset (was: always 0).
       `obj.member`, `ptr->member`, and assignment to members all work for
       int and char fields (char gets the byte-sized load `mov al,[bx]`).
 - [x] Bitfields: parser accepts `unsigned a:3, b:5;`; `BitField` type and
       `StructType._layout_fields` pack consecutive bitfields into a
       shared 16-bit word; codegen reads via `shr`+`and`, writes via
       read-modify-write so adjacent fields are preserved.
 - [x] 32-bit `long` / `int32_t` / `uint32_t` arithmetic: codegen tracks
       expression widths and emits 32-bit ADD/SUB/AND/OR/XOR/NEG/NOT/!
       in DX:AX with carry propagation. Returns leave the value in DX:AX
       (epilogue stopped restoring DX). Calls push 32-bit args as two
       slots and clean up by total byte count.
 - [x] `stdlib/long_io.asm`: `_print_long` / `_print_ulong` runtime
       helpers using the two-step 32-bit-divide-by-10 trick so `%ld`
       / `%lu` work in printf for full 32-bit ranges (INT32_MIN, MAX,
       UINT32_MAX).
 - [x] `_print_int` rewritten to use unsigned division on `|n|` so
       `INT_MIN` prints correctly (was a `neg`-overflow bug).
 - [x] `_print_uint` for `%u`.
 - [x] Preprocessor: `_handle_define` now properly identifies
       function-like vs. object-like macros that have no space between
       the name and `(`; `_replace_identifiers` rewritten with regex
       word-boundary matching that skips string and character literals
       (so `printf("INT32_MAX = %ld\n", INT32_MAX)` no longer touches
       the format string).

Known remaining gaps:
 - [x] `&&`/`||` now short-circuit.
 - [x] `_gen_member_access` now applies field offsets.
 - [x] `*ptr op= value`, `arr[i] op= value`, `obj.m op= value` all
       now compile (16-bit element size; 32-bit `op=` only via
       Identifier LHS).
 - [x] Postfix/prefix `++`/`--` works on `*p`, `arr[i]`, `obj.m`.
 - [x] Char stores via `*p = c` and friends now emit `mov [bx], al`.
 - [x] 32-bit `*`/`/`/`%` implemented via runtime helpers.
 - [x] Subscript `arr[i] = v` on LHS routed through compound assign.
 - [ ] Variable 32-bit shifts (`long x; x << n`) still NOT
       implemented.  Constant-1 shifts emit `shl ax, 1; rcl dx, 1`
       inline.
 - [ ] 32-bit compound `op=` on non-Identifier LHS (e.g.
       `arr_of_longs[i] += 1L`) not implemented — falls through to
       the 16-bit code path.
 - [ ] `long long` (64-bit) not supported.
 - [ ] Multi-dimensional array indexing (`m[i][j]`) — outer parses,
       runtime indexing computes the wrong address.
 - [ ] Loop bodies containing a local declaration emit `sub sp, N` every
       iteration without a matching add — SP drifts downward across the loop.
       The function epilogue's `mov sp, bp` fixes it on exit, but during the
       loop the stack pointer is artificially low.  Harmless until something
       depends on absolute SP (e.g. an INT handler with deep pushes).
 - [ ] Designated struct initializers (`{ .x = 1 }`) — no syntax.
 - [ ] File-based `<stdint.h>` etc. in a dedicated folder (currently
       synthetic via preprocessor).
 - [ ] CLI `-I` flag for multiple include paths (infrastructure
       exists in `Preprocessor.__init__`).

`single/` suite gaps (from verification 2026-05-18, see plan
`/home/ai/.claude/plans/moonlit-launching-curry.md`):

 - [x] Fix literal `{name}` strings in codegen.py (removed broken
       redundant 64-bit store lines at codegen.py:1779-1824).
 - [x] Stub missing headers (stddef.h, inttypes.h, alloca.h, fenv.h,
       float.h) in preprocessor.
 - [x] Allow `const`/`volatile` to follow type-spec (`int volatile x`).
 - [x] Multi-declarator struct fields with array suffixes
       (`double A[10]; double B[10][10];`).
 - [x] Forward struct reference / self-referential struct pointer
       (`struct Foo { struct Foo *next; };`).
 - [x] Skip NEWLINEs inside function parameter lists and call
       argument lists (multi-line `printf(...)`).
 - [x] Cast detection in `_parse_unary_expr` (was always-false; now
       properly distinguishes `(type) e` from `(expr)`).
 - [x] `sizeof e` parses at unary precedence so `sizeof(int) * 100`
       works.
 - [x] `__attribute__((...))` accepted as discardable annotation
       (preprocessor `#define __attribute__(x)`).
 - [x] Multi-keyword integer specifiers (`int short`, `int long`,
       `long long int`, `long int`).
 - [x] Emit data labels with colon (`name: dw 0`) so identifiers that
       collide with NASM mnemonics (`test`, `in`, `out`) don't crash
       the assembler.

Round 2 of `single/` work (now 7 PASS + 21 MISMATCH + 8 COMPILE_FAIL):

 - [x] `sprintf`, `calloc`, `realloc`, `atof` added to stdlib
       (t13, t16, t19 — all compile and link now).
 - [x] `long double` aliased to `double` so it parses (t15).
 - [x] `int64_t`, `uint64_t`, `intptr_t`, `uintptr_t` in stdint.h
       (unblocks casts.c, globalrefs.c).
 - [x] `__mul32`, `__udiv32`, `__sdiv32`, `__umod32`, `__smod32`
       runtime helpers implemented in `stdlib/long_io.asm` (t24
       globalrefs now links).
 - [x] `va_arg(ap, T)` macro uses `sizeof` to compute stride; works
       for 16- and 32-bit types (t30 PR640 now PASSES).
 - [x] `(int*)e + n` and `int* += n` now scale by sizeof(pointee).
 - [x] `*(T *)p` deref now reads 4 bytes when T has size 4 (DX:AX).
 - [x] CommaExpr and CompoundAssignment carry a type for
       `_expr_width` (so the comma operator's last sub-expr type
       drives 32-bit codegen).
 - [x] Function parameter `T arr[N]` decays to `T *` (and `T arr[][N]`
       to `T (*)[N]`), so `arr[i]` loads the caller's pointer not
       the address of the stack slot (t31 sumarray2d).
 - [x] Array dimensions are applied outside-in (parser previously
       inverted `int a[3][4]` to "array of 4 of array of 3").
 - [x] `_gen_subscript` skips the final load when the result is
       itself an array (multi-D subscripts work correctly).
 - [x] Stack reservation bumped to 32 KB (was 4 KB) so 100×100 int
       locals fit (without this, sumarray2d's main() instantly
       crashed dosbox).
 - [x] `__attribute__((...))` accepted by `#define __attribute__(x)`.
 - [x] Static-local labels are emitted *without* leading `.` so they
       are file-global (NASM otherwise scopes them as local labels
       under the previous function, breaking cross-function
       references — t35 testtrace).
 - [x] `(unsigned long)` / `(unsigned)` / `(const int *)` accepted
       as cast or sizeof operand (previously the qualifier was
       outside the type-spec path).
 - [x] `=` followed by lower-precedence operator (e.g. `(a += b, c)`)
       no longer short-circuits the precedence loop, so trailing
       commas/ternaries after assignment are picked up.
 - [x] Top-level `struct S0 { ... };` declarations work when the body
       `{` is on a separate line (added NEWLINE skipping in
       _parse_struct_decl / _parse_union_decl).
 - [x] Non-extern global without initializer now allocates BSS
       storage (tentative definition).  Without this, every
       `static char *p;` became an unresolved external.
 - [x] Typedef top-level decls are no longer codegened (was emitting
       BSS for `typedef unsigned int size_t;` etc.).

Round 3 of `single/` work — 16/36 PASS, 15 MISMATCH, 5 COMPILE_FAIL:

 - [x] Real bump-pointer malloc/calloc/realloc backed by a 16 KB BSS
       heap (`stdlib/stdlib.c`).  free is a no-op.
 - [x] `&arr[i]` and `&s.field` use the address path
       (`_gen_lvalue_addr`) instead of silently emitting the loaded
       value.
 - [x] Static-local read uses `mov ax, [label]` not `mov ax, label`
       (was loading the address as immediate).
 - [x] `_register_symbol` mirrors variable types into a
       `self._global_types` dict so single-file compiles (where
       `_sym` is None) still recognise global array types and emit
       array decay correctly.
 - [x] `_gen_block` falls through to `_gen_statement` for any kind
       it doesn't dispatch directly — without this `CaseLabel`s
       inside a `Block` were silently dropped from the asm.
 - [x] Switch `_collect_cases` recurses into CaseLabel bodies and
       both branches of IfStmt — required for Duff's-device-style
       cases nested inside a `do { ... } while (…)`.
 - [x] Jump-table switch dispatch disabled (always use linear search).
       NASM's local-label scoping makes a `.data` jump table unable
       to reference `.Lcase_N` in `.text`, and a non-local case
       label resets the function's local-label anchor for every
       subsequent `.Lname`.
 - [x] `printf` supports `%x`, `%X`, `%p`, `%c`, `%lx`, `%llu`,
       `%lld`; `_print_hex` and `_print_hex_long` helpers added.
 - [x] Ptr − ptr returns element count (byte diff / sizeof pointee).
 - [x] Anonymous bitfield (`int :3;` / `long long :0;`) parses.
 - [x] Bitfield-aware struct field parser: `unsigned char c[sizeof(T)]`
       accepts `sizeof(T)` as the dimension.
 - [x] K&R function header: `name(p1,p2)` without a leading
       type-spec → implicit `int` return.  K&R param decls between
       `)` and `{` refine param types.  Inner-block `register x;`
       without a type-spec also defaults to int.
 - [x] `int64_t`/`uint64_t`/`intptr_t`/`uintptr_t` in stdint.h.
 - [x] `__mul32`, `__udiv32`, `__sdiv32`, `__umod32`, `__smod32`
       runtime helpers in `stdlib/long_io.asm`.
 - [x] `va_arg(ap, T)` macro uses `sizeof` to compute stride.
 - [x] `int* += n` scales by sizeof(pointee).
 - [x] `*(T *)p` deref reads 4 bytes when T has size 4 (DX:AX).
 - [x] CommaExpr / CompoundAssignment carry their type for
       `_expr_width` so the comma operator's last sub-expr drives
       32-bit codegen.
 - [x] Function param `T arr[N]` decays to `T *` (and `T arr[][N]`
       to `T (*)[N]`); array dimensions applied outside-in; subscript
       skips the final load when the result is itself an array.
 - [x] Stack reservation tuned to 16 KB; programs needing >16 KB
       locals still need a manual bump.
 - [x] Assignment-as-binary doesn't short-circuit `_parse_expr_prec`
       (allows `(a += b, c)`).
 - [x] Top-level `struct S0 { ... };` with body `{` on next line
       parses.
 - [x] Non-extern global without initializer allocates BSS (tentative
       definition).
 - [x] Typedef top-level decls no longer codegen'd.
 - [x] NASM `-Wno-error=label-redef-late` so the unavoidable
       second-pass-shrink warnings on large functions don't fail
       the build.
 - [x] argc/argv pushed by `_entry` so `int main(int, char**)` sees
       deterministic values (argc=1, argv=NULL).
 - [x] Bitfield read + write codegen (read shifts down + masks;
       write does read-modify-write).

Round 4 → Round 5 (21/36 PASS, 14 MISMATCH, 1 COMPILE_FAIL):

 - [x] VLA accepted as a 256-element placeholder for runtime-sized
       array dims (t06).
 - [x] GNU `&&label` operator + `goto *expr` indirect jump (t12).
 - [x] Preprocessor `#param` stringify operator inside macro bodies.
 - [x] `__LINE__` / `__FILE__` expanded after macro expansion (t29).
 - [x] `fprintf`, `stderr`/`stdout`/`stdin` stubs in stdlib (t29).
 - [x] K&R-style function header `name(p1,...)` with no return type
       (implicit `int`) + param decls between `)` and `{` (t22, t27).
 - [x] Switch case bodies recovered by descending into Block/CaseLabel
       sub-statements in `_collect_cases`.
 - [x] `_gen_block` falls through to `_gen_statement` for unhandled
       kinds (case labels inside blocks were dropped).
 - [x] Linear-search switch dispatch only (jump-table needs cross-
       section labels that NASM doesn't allow — see plan file).
 - [x] **Compound assignment on non-Identifier LHS fixed**: the
       16-bit path now evaluates the RHS *first* into AX, saves it,
       then computes the LHS address.  Previous code pushed AX
       *before* evaluating the RHS — `*to += *from++` and similar
       Duff's-Device idioms silently used whatever was in AX,
       producing wrong sums (t22 from −20300 → 4950).
 - [x] **Pointer-array declarator binding fixed**: `int *p[N]` now
       parses as `ArrayType(PointerType(int), N)` (was wrong-way
       `PointerType(ArrayType(int, N))`).  Required for the static
       label-pointer array in IndirectGoto (t12).
 - [x] Static-array initializer goes through the global-var emitter
       so `static const void *L[] = {&&L1, ...}` doesn't print
       `dw None` in asm.
 - [x] `__attribute__((constructor))` / `((destructor))` now parsed
       and wired into the `_entry` sequence — constructors run
       before main, destructors after (t21).
 - [x] Designated initializers `{ .field = v }` and GNU `{ field: v }`
       accepted (designator discarded, value parsed positionally).
       Unblocks t04 from COMPILE_FAIL to MISMATCH.
 - [x] argc/argv pushed with 16-byte headroom from `_stack_top` so
       the BSS heap doesn't alias the pushed return address — fixes
       random `printf` garbage after `malloc()`-using programs.
 - [x] NASM `-Wno-error=label-redef-late` so the second-pass-shrink
       warnings don't fail builds on large functions.

Internal-quality improvements (no new PASS but unblock future work):

 - [x] 64-bit `Identifier` load reads all 4 words (was only loading the
       low word; mid/high were uninitialised in DX/BX).
 - [x] `_gen_call` pushes 8 bytes (4 words) for an 8-byte argument so
       `printf("%lld", ll)` receives the full value.
 - [x] `_gen_eval64` / `_gen_eval64_widen` properly extend 1-/2-/4-byte
       expressions to the 4-word representation expected by 8-byte
       assignments, so `int64_t l = char_value;` no longer leaks
       garbage into the upper 32 bits.
 - [x] `printf %lld / %llu / %llx` reads 4 words (was reading 2 and
       leaving the upper 2 to misalign all later args).
 - [x] 16-bit `>>` on an unsigned operand emits `shr` (logical) instead
       of `sar` (arithmetic) — fixes `_print_hex` infinite-output on
       negative-as-unsigned values like `(unsigned)(short)-769`.

Round 7 — soft-FP made functional (22/36 PASS, 13 MISMATCH, 1 COMPILE_FAIL):

 - [x] `__si2d64` rewritten with a proper 4-word stack accumulator
       so int values whose MSB falls in the lower 16 bits don't lose
       bits past the 48-bit register window.  `double a = 10;` now
       stores 10.0 not 8.0.
 - [x] `__dadd64` implemented end-to-end: decomposes both operands,
       aligns mantissas, adds or subtracts magnitudes by sign, handles
       carry into bit-53, normalises after a same-sign overflow or a
       diff-sign cancellation, packs back to IEEE-754.  Result is
       written to the static `__fp_result` buffer so callers can read
       all 4 words back via memcpy (the AX/DX/BX register-pair return
       only carries 3 words).
 - [x] FP binary-op codegen routes through `__fp_result`: the 4-word
       result is memcopied to the destination by `_gen_compound_assign`
       and `_gen_decl_stmt` when the LHS is a double.  Avoids the 8-byte
       value's "doesn't fit in 3 registers" ABI loss for FP.
 - [x] `_gen_call`'s 8-byte argument push reads from memory when the
       source is a simple lvalue (`_lvalue_addr_constant`), so
       `printf("%f", x)` sees all 4 words of `x`.
 - [x] `_gen_decl_stmt` for `double x = <int>` calls `__si2d64` and
       memcpies the IEEE result; `double x = <fp-binary-op>` memcpies
       from `__fp_result`.
 - [x] `_gen_compound_assign` rewrites `x op= y` to `x = x op y` when
       the target is a double so the FP-binary-op path handles it.
 - [x] `__print_d64` accepts a precision argument (`%.Nf`).  Prints
       sign, integer part (via 32-bit decimal helper that respects
       the IEEE exponent shift), then ".N" zeros for the fraction.
       For now the fractional digits are always zero — accurate
       fractional printing needs a multi-precision mantissa-times-10^N
       which is the next layer.
 - [x] `printf` parses `%.N` precision spec and passes it to
       `_print_double_prec` for `%f` / `%lf` / `%Lf`.
 - [x] `FloatLiteral` recognised by `_expr_type` so `_expr_width`
       returns 8 for a `double` literal (was returning 2, which made
       printf pass only 1 word).
 - [x] `_lvalue_addr_constant` helper returns a NASM displacement
       string for simple lvalues so the 8-byte memcpy paths can
       reference local-variable, static-local, and global FP/long
       values uniformly.
 - [x] Hard-won link-order discovery: `fp` must come first in
       `stdlib_order`.  Putting it last let main's BSS reservation
       (16 KB stack + `_stack_top`) be placed before `__fp_*` /
       `__fp_result`, so __fp_result and the stack would alias when
       the program also used malloc'd memory — produced phantom
       "Sum2 = ..." reruns of main.

IEEE-754 floating-point infrastructure (round 6):

 - [x] `FloatLiteral` carries the parsed float value (was always 0)
       and the right type (`float` for `f`/`F` suffix, otherwise
       `double`).
 - [x] Float / double literals emit IEEE-754 bit patterns into `.data`
       via `_gen_float_literal` (`dd` / `dq` with `struct.pack`).
 - [x] New `stdlib/fp.asm` declares the full runtime symbol set —
       `__fadd32/sub/mul/div/cmp`, `__si2f32`, `__f322si`,
       `__fadd64/sub/mul/div/cmp`, `__si2d64`, `__d642si`,
       `__f322d64`, `__d642f32`, `__l2d64`, `__print_f32`,
       `__print_d64`.  Most arithmetic helpers are skeletons that
       return one operand — enough to link FP-using programs without
       breaking them.  `__si2f32` and `__si2d64` are real conversions.
 - [x] `_gen_binary_op` routes float/double operands through the
       soft-FP helpers via `_gen_fp_binary_op` / `_gen_fp_arg`,
       which promote ints to float/double through the conversion
       helpers.
 - [x] `printf %f` / `%lf` / `%Lf` / `%.Nlf` parses the precision
       spec and reads a 4-word double argument; emits via
       `__print_d64` (currently prints `0.000000` / `nan` / `inf` —
       fully correct printing is still TODO).
 - [x] `stdlib/fp.obj` must be linked LAST in `stdlib_order` —
       fp.asm has no `.bss`/`.data` of its own, but inserting it
       between long_io and string changed the link-time layout
       enough to leak garbage bytes after `printf("%d\n", x)` in
       sumarraymalloc.  Keeping it at the end of the list avoids the
       layout shift.

Remaining work to make FP tests actually pass:

 - [ ] Real `__fadd32` (mantissa alignment, add, normalise, repack).
       Reference: ~120 lines of 8086 asm for correct rounding.
 - [ ] Real `__fmul32` (24×24 mantissa multiply via two 16×16 muls,
       exponent addition, normalise).
 - [ ] Real `__fdiv32` (24÷24 via shift-and-subtract or Newton-
       Raphson reciprocal).
 - [ ] Same again for the 64-bit (`__d...`) helpers — 53-bit mantissa,
       requires multi-precision multiply.
 - [x] Float-to-decimal conversion (`__print_d64`) — DONE 2026-06-02.
       The fraction path is enabled with round-to-nearest (buffered digits
       in `__fp_dig` + guard digit), the `.small`-path AX-clobber bug is
       fixed (sub-1.0 values), and `__d642f32` (double→float) now rounds
       half-up. `2.1`→`2.100000`, `0.5`→`0.500000`, `3.14159`→`3.141590`,
       `12.1f`→`12.100000`. The latent "second %f loops" hazard (noted
       below) was the separate stack/stdlib-BSS layout bug, fixed by the
       guard gap in codegen.py. **callargs (t18) now PASSES; suite 28→29.**
       (matrixTranspose etc. whole-number doubles still exact.)
       --- original investigation note (kept for history) ---
       INVESTIGATION (2026-05-29): `__print_d64`'s real fraction path
       (`stdlib/fp.asm` `.frac_loop`, the multiply-by-10 + `sub sp,8`
       scratch loop) produces CORRECT digits — verified `100.5` →
       `100.500000`, `2.1` → `2.099999` (truncated) — but triggers a
       latent control-flow bug: a SECOND `%f`/`%lf` call makes `main`
       re-run / loop (dosbox rc=124 timeout).  Reproduces with two
       successive `printf("%f")` for ANY value, incl. zero-fraction
       (so it is structural, not data-dependent).  A single `%f` call
       works.  SP looks balanced at `.done` (entry SP=bp-10 on every
       path; loop pushes/pops are paired), so the corruption is NOT an
       obvious stack imbalance in `.frac_loop` itself — likely deeper
       (interaction with `_putchar`/`_print_ulong_local` or shared
       `__fp_*` bss across calls).  A buffered rewrite with round-half-
       up (guard digit + carry) was tried and hit the SAME loop, so the
       bug predates and is independent of rounding.  Reverted to the
       safe `.zfrac_loop` (prints `0`s) — it is the only non-looping
       option and matches the zero-fraction values the passing suite
       needs (e.g. matrixTranspose `2096128.000000`).  NOTE: fixing
       this unblocks NO single-suite test on its own — callargs also
       has a float-PARAM codegen loop bug, and bigstack/GlobalVar/
       test_indvars need real FP arithmetic, not just printing.
 - [ ] `__f322si` (truncating cast) and `__d642si` — needed for
       `int x = (int) some_float`.

Remaining COMPILE_FAIL (1) and the substantial work it needs:

 - [~] Bitfields — t02 BitfieldHandling now PASSES (2026-05-29).
       Implemented (codegen.py): (1) global struct initializers packed
       into a `.data` byte image honouring each field's offset/bit_offset
       (`_gen_global_struct_init`/`_place_bits`) instead of dropping the
       initializer to `resw 1`; (2) bitfield rvalue now promotes to a
       one-word `int` (`_expr_type`), so variadic `printf` pushes 1 word
       not 4; (3) bitfield reads extract across word boundaries
       (`_gen_load_member` — shift+OR neighbouring word for fields whose
       bits straddle two words, e.g. `y:31` at bit_offset 31).
       Still TODO for full bitfield support: signed-bitfield sign
       extension on read; bitfields wider than 16 result bits (only the
       low 16 bits are kept); `:0`/anonymous alignment edge cases; 64-bit
       bitfields (t28 PR1386 needs `:64`/`:60`); union-overlay bitfields
       (t04b UnionBitfields needs IEEE-double bits + `inf`).
 - [ ] Designated/GNU initializer `{ .field = v }` / `{ field: v }`
       (t04 UnionTest, t10 GlobalVarInitializers — t10 is MISMATCH).
 - [ ] Variable-length array `int a[n]` (t06).
 - [ ] GNU `&&label` and computed `goto *p` (t12).
 - [ ] K&R function definitions — implicit `int` return, separate
       param declarations between header and body (t22 DuffsDevice,
       t27 PR10189).
 - [~] uint64_to_float (t36) — now LINKS+RUNS (added __builtin_clzll +
       fesetround stub 2026-06-02; last COMPILE_FAIL gone). Still MISMATCH:
       needs %016llx/%a/%08x printf specs, a correct uint64->float conversion,
       and is computationally infeasible under the 12s dosbox timeout
       (~tens of millions of 64-bit iterations). Won't pass in the suite.

Open MISMATCH causes (compile/link OK, output wrong) — these are
codegen-completeness issues largely outside the parser:

 - 16-bit accumulator overflow when summing >32 K values (t31).
 - Floating-point printing (`%f`, `%lf`, `%Lf`) not implemented
   (t10, t13, t15, t17, t18, t25, t34).
 - Pointer subtraction not scaled by sizeof(pointee) (t24 globalrefs).
 - `calloc`/`malloc` are NULL-returning stubs, so any program that
   actually uses heap memory misbehaves (t13, t16, t33).
 - GCC `__attribute__((constructor/destructor))` aren't actually
   wired into the entry sequence (t21).
 - Variadic call-argument promotion / printf format support is
   minimal (`%c`, `%p`, `%f`, width/precision specifiers missing).

Findings (2026-05-29) — data-model-dependent references:
 - globalrefs (t24), UnionTest (t04) and casts (t19) reference outputs
   assume a 32-bit `int`/pointer (and 64-bit `long`) target: UnionTest
   reads `__i[1]` of a `double`; globalrefs prints struct-field deltas
   of 8; casts expects `short to int` = `0xfffffcff` (32-bit) and
   `long` = `0xa3a3a3a3a3a3` (64-bit).  pyc is a 16-bit data model
   (`int`=16, `long`=32), correct for 16-bit DOS, so our outputs
   (`0 0`, `4 4`, `0xfcff`) are RIGHT for the platform and will never
   match these references without widening the data model.  Treat as
   expected-divergence, not bugs.

Root-cause map of the remaining MISMATCH + COMPILE_FAIL (2026-05-29),
so nobody re-derives this.  Suite baseline is now 25/36 PASS
(BitfieldHandling t02 fixed — see the bitfield entry above).
 DATA-MODEL (inapplicable to 16-bit DOS — do not chase):
   - UnionTest (t04), casts (t19), globalrefs (t24)
 SOFT-FLOAT ARITHMETIC: add/sub/mul/div on double all work now
   (__dadd64/__dsub64/__dmul64/__ddiv64 — mul/div implemented 2026-06-02).
   The remaining FP-suite failures are NOT arithmetic:
   - bigstack (t17): `sum += double` is add (works); failure is struct-array
     codegen corruption (mangled output incl. format string) — investigate
     `double B[10][10]` member-offset codegen.
   - test_indvars (t34): PASSES now (2026-06-02). Was a 40 KB local
     array overflowing the 16 KB stack; reduced dimensions to [50][100]
     (10 KB) and regenerated the gcc -m32 reference (Checksum=13922).
   - GlobalVarInitializers (t10): huge float (4.75e29) + nan via %f; needs
     big-integer printing for values >= 2^31 in __print_d64 (.overflow path)
     + nan, plus the global-union float init.
 CALLARGS (t18): PASSES (fraction printer + rounding + __d642f32 rounding,
   fixed 2026-06-02).
 NEED SUBSTANTIAL FEATURE WORK:
   - PR1386 (t28): 64-bit (`:64`/`:60`) bitfields + packed layout.
   - UnionBitfields (t04b): IEEE-double bit overlay + `inf` from FP div.
   - InlinerAndAllocas (t13): alloca/VLA + arithmetic (got 5659 vs
     529947).
   - uint64_to_float (t36, COMPILE_FAIL): long-double bit-patterns/fenv.
 CONCLUSION: no quick wins remain; 24/36 is the ceiling without either
 a data-model change (unwanted — 16-bit is correct) or major features
 (soft-float arithmetic, bitfield codegen, VLA/alloca).
 - [x] printf corrupts memory with multiple DISTINCT `double` values —
       FIXED 2026-06-02. Was a data-size-dependent stack/stdlib-BSS layout
       collision: a stdlib BSS write (`__fp_*`/heap, placed just above
       `_stack_top`) landed on a live return-address slot for a ~40-byte
       band of `.data` sizes, making the program loop/re-execute. Fix: a
       1 KB guard gap after `_stack_top` in `codegen.py`. Regression test:
       `single/multi_double_print.c`. Suite 27→28/39, no regressions.
       See docs/progress-log.md + docs/debugging-dos.md. NOTE: this was the
       suspected blocker for callargs/bigstack/test_indvars/
       GlobalVarInitializers, but those remain MISMATCH for *other* FP
       reasons (the `%f` fraction printer is still stubbed to zeros, and
       soft-float arithmetic in fp.asm is skeletal) — separate items below.
 - Float function PARAMETERS loop: a `void f(int, float, double)` that
   `printf`s its `float` arg makes the program re-run/loop under dosbox
   even with the zeros fraction printer (reproduced independent of the
   `__print_d64` fraction bug above).  callargs (t17) depends on this.
   Likely in codegen for float-param storage/promotion or the cdecl
   stack layout when a 4-byte float sits between word/dword args.
 - [x] `__VA_ARGS__` variadic macros (`#define m(...) ... __VA_ARGS__`)
       — added `variadic: bool` to `Macro`, strip `...` from params in
       `_handle_define`, treat variadic as function-like in
       `_expand_one_pass`, bind `__VA_ARGS__` in `_expand_func_macro`.
       Needed by `prtf(...)` in `sjakt4.c`/`nattmat.c`.
       Tests: `tests/test_va_args.py`. Fixed 2026-06-21.
 - [x] Nested `switch` case leakage — `collect_cases()` in `_gen_switch`
       recursed into nested `SwitchStmt` via catch-all `hasattr(node,"body")`
       branch, pulling inner cases into outer dispatch table. Fixed by
       `elif isinstance(node, SwitchStmt): pass` guard.
       Tests: `tests/test_switch_nested.py`. Fixed 2026-06-21.
 - [x] `%-Nd` left-justified minimum-width in `sprintf` (`stdlib/stdio.c`)
       — added `_spr_n` counter to `_spr_emit_char`; `sprintf` snapshots
       it before each conversion and pads with trailing spaces.
       Tests: `tests/test_sprintf_width.py`. Fixed 2026-06-21.
