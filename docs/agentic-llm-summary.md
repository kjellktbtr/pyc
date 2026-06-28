Agentic LLM Summary — pyc (C → 16-bit NASM for DOS)
=====================================================

Purpose
-------
This document is an agent- and developer-friendly summary of the repository and
the constraints required to implement and extend a C compiler written in
Python that emits 16-bit NASM assembly for MS-DOS. It is concise, machine-
readable friendly, and contains canonical AST→ASM templates and a verification
checklist for rapid, agentic development.

Quick index
-----------
- Project rules & constraints — where to look in the repo
- Target platform constraints (16-bit DOS)
- Prioritized C features (MUST / SHOULD / MAY)
- Mapping: feature → compiler component
- Canonical AST→ASM templates (copy-ready)
- Edge cases & mitigations
- Verification checklist and recommended tests
- Short implementation plan

1) Project rules & constraints
--------------------------------
- Target: a C compiler in Python producing 16-bit NASM assembly and linked
  with `alink`. See `CLAUDE.md` for overall project rules and coding style.
- Toolchain: C → NASM (object .obj) → `alink` (linker). `nasm -f obj` is used
  by the builder (`src/pyc/builder.py`); `alink` requires non-interactive
  invocation (see `docs/alink-usage.md` and `CLAUDE.md`).
- Python code-style and runtime: Python 3.12, PEP‑8, type hints, `pathlib`,
  and context managers (see `CLAUDE.md`).
- Multi-file compilation and symbol linking are implemented by
  `src/pyc/builder.py` and `src/pyc/compiler.py`.

2) Target platform constraints (16-bit NASM / DOS)
--------------------------------------------------
- Data model (as used in `src/pyc/types.py`): `char=1`, `short=2`, `int=2`,
  `long=4`, `float=4`, `double=8`.
- Pointer model: near pointers (2 bytes) by default. `PointerType.size == 2`.
  Segmented / far-pointer support is not implemented; assume single-segment
  model where `DS` = `CS` unless explicitly changed in codegen (`src/pyc/codegen.py`).
- Calling convention (matches current codegen): arguments pushed
  right-to-left, caller cleans the stack, return value in `AX`.
  See `_gen_call` and `_gen_function` in `src/pyc/codegen.py`.
- Bootstrap & runtime: emitted assembly uses 16-bit mode (`[bits 16]`), sets
  up `DS`/`ES`, and exits via DOS `int 0x21` AH=0x4C (see `src/pyc/codegen.py`).
- Assembler & linker: `nasm -f obj` produces `.obj` files; `alink` links
  objects into DOS executables. Avoid interactive `alink` help by piping
  two newlines: `printf "\n\n" | alink` (see `docs/alink-usage.md`).

3) Prioritized C language features to support
--------------------------------------------
MUST (minimum usable compiler):
- Basic scalar types, integer arithmetic, relational and bitwise operators
- Control flow: `if/else`, `for`, `while`, `do/while`, `switch`, `break`, `continue`, `return`, `goto`
- Functions (definitions & calls), local / global variables, stack frames
- Pointers and arrays (basic subscripting)
- Preprocessor support: `#include`, `#define`, `#ifdef` family
- Multi-file linking (`extern`/global symbols)

SHOULD (next priority):
- `struct` layout and member access with correct offsets
- String handling and basic `stdio` functions (provided by `stdlib/` stubs)
- Pointer arithmetic using element size scaling
- Minimal dynamic memory (`malloc`/`free`) backed by stdlib or DOS services

MAY (deferred or optional):
- Varargs (`printf`), full floating-point codegen, far pointers / segmented
  addressing, aggressive macro features, full C99+ features

4) Mapping: language features → compiler components
---------------------------------------------------
- Lexing: `src/pyc/lexer.py` and `src/pyc/tokens.py` (token definitions).
- Preprocessing: `src/pyc/preprocessor.py` (handles `#include`, `#define`,
  conditional directives). Current macro expansion is ad-hoc and should be
  token-aware.
- Parsing: `src/pyc/parser.py` (recursive-descent parser) produces AST nodes
  defined in `src/pyc/ast.py` (`FunctionDefinition`, `BinaryOp`, `UnaryOp`, `Subscript`, etc.).
- Semantic analysis: (recommended) a separate pass that annotates AST nodes
  with `CType` from `src/pyc/types.py`, computes struct layouts, and
  resolves pointer scaling before codegen.
- Code generation: `src/pyc/codegen.py` maps AST nodes to NASM templates.
- Symbol/linking: `src/pyc/symbols.py` and `src/pyc/builder.py` manage
  symbol tables and multi-file object linking.

5) Canonical AST → ASM templates (copy-ready snippets)
-----------------------------------------------------
- Function prologue

    {func_name}:
        push bp
        mov bp, sp
        push bx
        push cx
        push dx
        push si
        push di

- Function epilogue / return

        pop di
        pop si
        pop dx
        pop cx
        pop bx
        mov sp, bp
        pop bp
        ret

- Call and cleanup (caller cleans stack)

    ; push args right-to-left
    push argN
    ...
    push arg1
    call {symbol}
    add sp, {args_bytes}

- Local allocation and access

    sub sp, {local_bytes}
    ; local at [bp - offset]
    mov [bp - {offset}], ax

- Global variable (data)

    section .data
    {symbol} dw {initial_value}

- String literal

    section .data
    ._str_{n} db 72,101,108,108,111,0 ; "Hello\0"

6) Edge cases & blockers (with mitigations)
--------------------------------------------
- Preprocessor: current macro expansion is fragile — implement token-aware
  macro expansion and safer `#if` evaluation.
- Pointer arithmetic: ensure index scaling by element size; implement a
  semantic pass that annotates expression types and scales indices.
- Struct offsets: compute layout in `StructType` and use offsets in
  `_gen_member_access` instead of ad-hoc loads/stores.
- Varargs / `printf`: either provide a limited `printf` shim in `stdlib/`
  for common formats or implement proper varargs handling (higher effort).
- Function pointers / indirect calls: add codegen path to evaluate function
  expression and `call [addr]` semantics.
- Far pointers / segmentation: document as out-of-scope for initial release
  (near pointers only), unless explicit segmentation support is added.

7) Suggested structure for agentic consumption
---------------------------------------------
- Human doc: `docs/agentic-llm-summary.md` (this file)
- Machine index: `docs/agentic-llm-summary.json` (keyed schema with types,
  templates, priorities, and tests — programmatic agents should consume this).

Index schema (recommended keys):
- `project`, `target`, `constraints`, `types`, `calling_convention`,
  `features` (array of {name, priority, parser, ast, codegen}),
  `templates` (re-usable ASM patterns), `tests` (smoke examples).

8) Verification checklist (smoke tests and unit tests)
----------------------------------------------------
- Run existing tests: `pytest -q` (see `tests/`).
- Smoke compile examples through the builder (example commands):

```bash
python -m src.pyc.__main__ examples/return_42.c  # emit ASM
nasm -f obj -o return_42.obj return_42.asm
printf "\n\n" | alink return_42.obj -o return_42.exe
```

- Minimal smoke examples to include as tests:
  - `int main(){ return 42; }` — verify `mov ax, 42`/return.
  - Function call: `foo` returns constant, `main` calls `foo` — verify call/cleanup and return in `AX`.
  - Array indexing: `int a[3]; a[1]=2; return a[1];` — verify index scaling.
  - Struct field access: `struct S { int a; } s; s.a = 3; return s.a;` — verify offsets.

9) Short implementation plan (high priority)
-----------------------------------------
1. Stabilize preprocessor: token-aware macro expansion and safe `#if` eval.
2. Add a semantic/type-analysis pass that annotates AST nodes with `CType`.
3. Fix pointer arithmetic and `_gen_subscript` to scale by element size.
4. Implement struct field offset usage in codegen.
5. Add indirect call support (function pointers).
6. Improve stdlib: `malloc` shim and stronger `printf` fallback.
7. Harden `nasm`/`alink` invocation in `src/pyc/builder.py` and add tests.

References
----------
- Implementation files: `src/pyc/lexer.py`, `src/pyc/preprocessor.py`,
  `src/pyc/parser.py`, `src/pyc/ast.py`, `src/pyc/types.py`,
  `src/pyc/codegen.py`, `src/pyc/builder.py`, `stdlib/`.
- Language summary reference: `docs/c-language-description.md` (useful for
  mapping language features to parser/AST shapes).

Next step
---------
Use `docs/agentic-llm-summary.json` for programmatic agent workflows and
follow the short implementation plan above. Add unit tests for pointer,
struct, and preprocessor cases as early regression tests.
