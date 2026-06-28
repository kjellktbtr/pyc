"""Compiler pipeline: preprocess → lex → parse → generate.

Supports both single-file compilation and multi-file compilation with a shared
symbol table for cross-file symbol resolution.
"""

from __future__ import annotations

import logging
from pathlib import Path

from src.pyc.ast import TranslationUnit
from src.pyc.codegen import CodeGenerator
from src.pyc.lexer import tokenize_with_comments
from src.pyc.optimizer import optimize as optimize_asm
from src.pyc.parser import parse as parse_ast
from src.pyc.preprocessor import Preprocessor
from src.pyc.symbols import SymbolKind, SymbolTable

log = logging.getLogger(__name__)


def compile(
    source: str,
    filename: Path = Path("<input>"),
    symbol_table: SymbolTable | None = None,
    include_paths: list[Path] | None = None,
    optimize: int = 1,
) -> str:
    """Compile C source code to 16-bit NASM assembly.

    Args:
        source: C source code text.
        filename: Source file path for error messages and include resolution.
        symbol_table: Optional shared symbol table for multi-file compilation.
        include_paths: List of include search paths (default: [filename.parent]).
        optimize: Optimization level (0 = off, 1 = on, default).

    Returns:
        NASM assembly source text.
    """
    if symbol_table is not None:
        symbol_table.set_file(str(filename))

    # Phase 1: Preprocess
    pp = Preprocessor(include_paths=include_paths or [filename.parent])
    preprocessed = pp.preprocess(source, filename)

    # Phase 2: Lex (also capture comments for asm annotation).
    tokens, comments = tokenize_with_comments(preprocessed)

    # Phase 3: Parse
    ast = parse_ast(tokens)

    # Phase 4: Generate code
    generator = CodeGenerator(symbol_table=symbol_table, comments=comments)
    asm = generator.generate(ast)

    # Phase 5: Optimize
    if optimize:
        optimized, stats = optimize_asm(asm)
        if stats.total > 0:
            log.info("Optimizer eliminated %d instructions", stats.total)
        return optimized
    return asm


def compile_file(
    path: Path,
    symbol_table: SymbolTable | None = None,
    include_paths: list[Path] | None = None,
    optimize: int = 1,
) -> str:
    """Read a C source file and compile it to 16-bit NASM assembly.

    Args:
        path: Path to the C source file.
        symbol_table: Optional shared symbol table for multi-file compilation.
        include_paths: List of include search paths (default: [path.parent]).
        optimize: Optimization level (0 = off, 1 = on, default).

    Returns:
        NASM assembly source text.
    """
    source = path.read_text()
    return compile(source, path, symbol_table, include_paths, optimize)


def compile_files(
    paths: list[Path],
    include_paths: list[Path] | None = None,
    optimize: int = 1,
) -> str:
    """Compile multiple C source files and link them into a single NASM file.

    Each file is compiled separately with a shared symbol table. The generated
    assembly files are then merged, with global/extrn directives resolved.

    Args:
        paths: List of C source files to compile.
        include_paths: List of include search paths (default: [path.parent] for each).

    Returns:
        Merged NASM assembly source text ready for assembly.
    """
    symbol_table = SymbolTable()
    parts: list[str] = []

    # First pass: compile each file
    file_asms: list[tuple[str, str]] = []
    for path in paths:
        asm = compile_file(path, symbol_table, include_paths, optimize)
        file_asms.append((str(path), asm))

    # Second pass: merge all assembly into one file
    merged = ["; === Merged by pyc multi-file linker ==="]
    merged.append("[bits 16]")

    # Collect all globals and extrns
    all_globals: set[str] = set()
    for path in paths:
        fname = str(path)
        all_globals.update(symbol_table.globals_for(fname))

    if all_globals:
        merged.append("")
        for name in sorted(all_globals):
            merged.append(f"global {name}")

    # Emit extrn directives for symbols that are referenced but defined elsewhere
    all_extrns: set[str] = set()
    for path in paths:
        fname = str(path)
        extrns = symbol_table.extrns_for(fname)
        all_extrns.update(extrns - all_globals)

    if all_extrns:
        merged.append("")
        for name in sorted(all_extrns):
            merged.append(f"extern {name}")

    # Bootstrap code - only emit once
    merged.append("")
    merged.append("section .text")
    merged.append("_start:")
    # Small-model bootstrap (SS=DS=DGROUP) so LEA on locals stays valid.
    merged.append("mov ax, seg _data_start")
    merged.append("mov ds, ax")
    merged.append("mov es, ax")
    merged.append("cli")
    merged.append("mov ss, ax")
    merged.append("mov sp, _stack_top")
    merged.append("sti")

    all_data_lines: list[str] = []
    all_bss_lines: list[str] = []

    # Merge all code sections
    for fname, asm in file_asms:
        lines = asm.split("\n")
        in_data = False
        in_bss = False
        skip_block = False

        for line in lines:
            stripped = line.strip()

            # Track section boundaries but skip directives
            if stripped.startswith("section .text"):
                in_data = False
                in_bss = False
                skip_block = False
                continue
            elif stripped.startswith("section .data"):
                in_data = True
                in_bss = False
                skip_block = False
                continue
            elif stripped.startswith("section .bss"):
                in_data = False
                in_bss = True
                # Skip BSS from individual files - globals are handled by codegen
                skip_block = True
                continue
            elif stripped.startswith("global ") or stripped.startswith("extern "):
                continue

            # Skip bootstrap/entry blocks from individual files
            if stripped == "_entry:" or stripped == "_start:":
                skip_block = True
                continue

            if skip_block:
                # Reset when we hit another section or label
                if stripped.startswith("section ") or (stripped.endswith(":") and not stripped.startswith(".")):
                    skip_block = False
                continue

            # Skip boilerplate from individual files
            if stripped.startswith("[bits") or stripped.startswith("; ==="):
                continue

            # Skip empty lines and comments outside of data sections
            if not stripped or stripped.startswith(";"):
                if not in_data:
                    continue

            # Data and BSS lines from individual files
            if in_data:
                if stripped and not stripped.startswith(";"):
                    all_data_lines.append(line)
                continue

            # Code lines - only actual instructions and labels
            merged.append(line)

    # Data section
    if all_data_lines:
        merged.append("")
        merged.append("section .data")
        merged.extend(all_data_lines)

    # BSS section
    if all_bss_lines:
        merged.append("")
        merged.append("section .bss")
        merged.extend(all_bss_lines)

    return "\n".join(merged)