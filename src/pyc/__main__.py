"""CLI entry point for the pyc compiler."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.pyc.builder import assemble, build, compile_to_asm
from src.pyc.compiler import compile_file


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pyc",
        description="Minimal C compiler generating 16-bit NASM assembly",
    )
    parser.add_argument(
        "input",
        type=Path,
        nargs="+",
        help="Input C source file(s)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output file",
    )
    parser.add_argument(
        "-I", "--include",
        action="append",
        default=[],
        type=Path,
        help="Include search path",
    )
    parser.add_argument(
        "-S", "--asm-only",
        action="store_true",
        help="Generate assembly only, do not assemble or link",
    )
    parser.add_argument(
        "-c", "--no-link",
        action="store_true",
        help="Compile and assemble to .obj, do not link",
    )
    parser.add_argument(
        "-e", "--entry",
        default="_entry",
        help="Entry point symbol (default: _entry)",
    )
    parser.add_argument(
        "-O",
        choices=["0", "1"],
        default="1",
        help="Optimization level: 0 (off), 1 (on, default)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")

    inputs = args.input
    opt_level = int(args.O)

    # Build include paths: -I flags plus default parent directory
    include_paths = args.include or [inputs[0].parent] if args.include else [inputs[0].parent]

    # Single-file, asm only
    if args.asm_only and len(inputs) == 1:
        asm = compile_file(inputs[0], include_paths=include_paths, optimize=opt_level)
        output = args.output or inputs[0].with_suffix(".asm")
        output.write_text(asm)
        if args.verbose:
            print(f"Generated {output} ({len(asm)} bytes)")
        return

    # Single-file, compile + assemble to obj
    if args.no_link and len(inputs) == 1:
        asm_path = compile_to_asm(inputs[0], args.output and args.output.with_suffix(".asm"), include_paths, opt_level)
        obj_path = assemble(asm_path, args.output)
        print(f"Generated {obj_path}")
        return

    # Multiple files or single file -> full build with link
    exe = build(
        sources=inputs,
        output=args.output or (inputs[0].parent / (inputs[0].stem + ".exe")),
        entry=args.entry,
        include_paths=include_paths,
        optimize=opt_level,
    )
    print(f"Built {exe}")


if __name__ == "__main__":
    main()
