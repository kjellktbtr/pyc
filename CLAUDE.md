This is a C compiler written in Python targeting MS-DOS 16-bit NASM assembly.
Astral uv is used to run and manage the project.
Support for compilation multiple files to assembly. Then execution of NASM to create object files. Finally linking with alink.
Warning: executing alink with no arguments shows help and the help required the user to push enter twice to end. Therefore always run alink like this when using no arguments: `printf "\n\n" | alink` else it never terminates.
The code style should be pep-8 compliant with type-hints, usage of pathlib.Path, context managers and modern best practices and target python 3.12.
Refer todo.md for remaining tasks and things to verify. If it is discovered that something is missing (unhandled keywords or features of C or other things) and it to the todo list so it isn't forgotten. Check finished tasks in the todo list (but don't delete them so what that has been done is tracked.)

Documentation discipline (so things aren't rediscovered):
 - `docs/progress-log.md` is a dated log of changes and discoveries (newest first). Append an entry whenever you complete a meaningful change or learn something non-obvious about how the compiler/runtime behaves.
 - When you work out how a subsystem works, capture it in a durable `docs/<topic>.md` reference (not just the progress log) and add a one-line pointer to it from this CLAUDE.md "Key documentation" list below, so the next session finds it. Existing durable references: `docs/runtime-library.md`, `docs/real-mode.md`, `docs/single-suite-testing.md`, `docs/agentic-llm-summary.md`.

Key documentation:
 - `docs/runtime-library.md`: how the `stdlib/` runtime works — build/link model, symbol naming, cdecl calling convention, memory model, the DOS/BIOS interrupts in use, the module map, file I/O + serial APIs, headers, and known runtime limitations. Read before touching any `stdlib/*.asm`.
 - `docs/progress-log.md`: dated progress + discoveries log.
 - `docs/single-suite-testing.md`: the `single/` integration-test procedure.
 - `docs/debugging-dos.md`: running generated `.exe`s under qemu/bochs with a real DOS for runtime debugging (FAT12 injector `tools/fat12img.py`, qemu monitor/serial/gdb, bochs magic breaks). Use when the DOSBox suite harness can't reach a runtime bug.
 - `serial_xfer/README.md`: host⇄DOS serial file-transfer protocol (COBS+CRC+ACK, 8.3 filename mangling, upload/download); built with pyc + the `uart_*` runtime layer, tested under QEMU.
 - `docs/real-mode.md`: 16-bit real-mode codegen reference.
The folder `interrupts/` contains Ralf Brown's Interrupt List Release 61 (~152K lines, 8500+ entries).
See `interrupts/dos_int_ref.md` for the indexed DOS interrupt reference organized by C runtime
functionality (stdio, malloc/free, file I/O, directory ops, time/date, video, keyboard, disk I/O,
memory map, PSP/MCB/EXEC data structures). Each table entry includes the source file and line number
(e.g., `INTERRUP.G:5049`) for detail lookup in the original Ralf Brown files.
Use these DOS interrupts for the C standard library runtime. For example, INT 21/AH=48h (allocate memory)
and AH=49h (free memory) form the basis for malloc/free, INT 21/AH=3Ch-43h for file I/O, etc.
The project is under version control with git.
When implementing new features, the workflow should normally be:
1. Create a unit test for the feature
2. See that the unit test fails due to lack of implementation
3. Implement feature
4. Iteratively execute unit tests and fix until it pass

Rules:
 - When stating facts, refer repository file by name and chapter, section or line number (whatever that makes sense)
 - Don't mention facts that cannot be backed by repository files.

Integration test suite
----------------------
- `single/`: 40 self-contained C programs, each paired with a `*.reference_output` file.
  See `docs/single-suite-testing.md` for the full test procedure — how to compile, run under
  DOSBox with stdout capture, diff against the reference, and run the entire suite at once.

Runtime library (`stdlib/`)
---------------------------
- C-visible runtime functions are exported as `global <cname>` **without** a leading
  underscore (e.g. `global malloc`); underscore-prefixed symbols (`_putchar`,
  `_print_int`) are internal helpers. The compiler auto-emits `extern` for any
  undefined call target, and `builder.py:get_stdlib_objects()` links every
  `stdlib/*.obj` unconditionally, so adding a runtime function = define the symbol
  in an `.asm` listed in `stdlib_order` + declare its prototype in a built-in header.
- POSIX file I/O: `stdlib/posix_io.asm` provides `open`/`close`/`read`/`write`/`lseek`
  + `errno` over INT 21h handle calls; headers `<fcntl.h>`, `<unistd.h>`, `<errno.h>`.
- Serial: `stdlib/serial.asm` provides raw INT 14h `serial_init`/`serial_putc`/
  `serial_getc`/`serial_status`; header `<serial.h>`. Opening `"COM1"`/`AUX` through
  the POSIX layer also works (DOS treats them as character devices).

Platform reference
------------------
- `docs/real-mode.md`: distilled 16-bit real-mode reference for code generation — covers data model, segment register roles, 16-bit addressing mode restrictions (only BX/BP/SI/DI as base/index), stack layout, pointer types (near vs far), and a key-constraints summary. Read this before implementing or modifying codegen for memory access, function calls, or pointer arithmetic.

Agentic LLM summary files
-------------------------
A concise agent-focused summary and machine index have been added to the repository to assist automated agents and human maintainers implementing and extending the compiler:

- `docs/agentic-llm-summary.md`: human-readable agentic summary with platform constraints, prioritized features, canonical AST→ASM templates, blockers, and verification checklist.
- `docs/agentic-llm-summary.json`: machine-readable index (types, templates, parser/codegen mappings, and recommended tests) intended for programmatic consumption by LLM agents.

Purpose: These files consolidate repository-specific constraints and canonical codegen templates so LLM-based automation can reason about, plan, and perform compiler changes reliably.
