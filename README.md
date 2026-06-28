# pyc — C Compiler for 16-bit DOS

A C compiler written in Python 3.12+ that compiles C source code to 16-bit NASM assembly, producing DOS `.EXE` files via the `alink` linker.

## Quick Start

```bash
# Install dependencies
uv sync

# Compile a single C file to assembly only
uv run python -m src.pyc hello.c -S

# Full build: compile → assemble → link → .EXE
uv run python -m src.pyc hello.c

# Compile to object file only (no linking)
uv run python -m src.pyc hello.c -c

# Multiple source files (auto-links stdlib)
uv run python -m src.pyc main.c utils.c -o program.exe

# Specify include paths and entry point
uv run python -m src.pyc main.c -I include/ -e _start

# Verbose output
uv run python -m src.pyc hello.c -v
```

See `uv run python -m src.pyc --help` for all options.

## Architecture

The compiler is a four-stage pipeline:

```
C source → Preprocessor → Lexer → Parser → AST → Code Generator → NASM assembly
```

### Source Files

| File | Purpose |
|---|---|
| `src/pyc/preprocessor.py` | `#include`, `#define`, `#ifdef` directive processing |
| `src/pyc/lexer.py` | Tokenization (identifiers, keywords, operators, literals) |
| `src/pyc/tokens.py` | Token type definitions |
| `src/pyc/parser.py` | Recursive-descent parser, builds AST |
| `src/pyc/ast.py` | AST node definitions (dataclasses) |
| `src/pyc/types.py` | C type system (`int`, `char`, `*`, arrays, structs) |
| `src/pyc/symbols.py` | Symbol table for variable/function tracking |
| `src/pyc/codegen.py` | AST → 16-bit NASM assembly code generation |
| `src/pyc/compiler.py` | Pipeline orchestrator (`compile()`, `compile_file()`) |
| `src/pyc/builder.py` | Build system: assemble with NASM, link with `alink` |
| `src/pyc/__main__.py` | CLI entry point (`uv run python -m src.pyc`) |

### Execution Flow

1. **Preprocessor** resolves `#include` and `#define` directives
2. **Lexer** produces a token stream from preprocessed source
3. **Parser** builds an AST from tokens (recursive descent)
4. **Code Generator** walks AST, emits 16-bit NASM assembly
5. **Builder** calls `nasm` to assemble `.asm → .obj`, then `alink` to link `.obj → .exe`

### Standard Library

The `stdlib/` directory contains C implementations of runtime functions linked into every build:

| File | Functions |
|---|---|
| `stdlib.c` | Memory allocation, utility functions |
| `stdio.c` | `printf`, `putchar`, `gets`, `puts` |
| `string.c` | `strcpy`, `strlen`, `strcat`, `strcmp`, `memset` |
| `dos_io.asm` | Low-level DOS I/O primitives |

These are compiled to `.obj` files and linked by `builder.get_stdlib_objects()`.

## Dependencies

- **Python 3.12+** — compiler runtime
- **NASM** — assembles generated `.asm` to 16-bit `.obj` files
- **alink** — links object files into DOS `.EXE` (from DOS SDK)
- **uv** — package/project manager (optional, recommended)

## Target Platform

- **16-bit x86 real mode** (DOS)
- **NASM syntax** with `[bits 16]`
- **DOS `.EXE`** format (MZ header)
- Uses DOS interrupts for runtime services (INT 21h for file I/O, memory, etc.)

### Program Entry Point

Every compiled program includes a `_entry` stub that:
1. Sets `DS`/`ES`/`SS` to `CS` (flat segment model)
2. Initializes stack pointer
3. Calls `main()`
4. Exits via `INT 21h/AH=4Ch` with `main()` return value

## Testing

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src/pyc --cov-report=term-missing

# Run specific test file
uv run pytest tests/test_codegen.py -v
```

Tests are in `tests/` and cover: lexer, parser, type system, codegen, end-to-end compilation, control flow, pointer arithmetic, structs, and more.

## Code Style

- Python 3.12+ with type hints
- PEP 8 compliant
- `pathlib.Path` for all file paths
- Context managers for resource management
- Modern Python practices (dataclasses, type unions, `from __future__ import annotations`)
