"""pyc: A minimal C compiler generating 16-bit NASM assembly."""

from __future__ import annotations

from pathlib import Path

from src.pyc.compiler import compile, compile_file

__version__ = "0.1.0"
__all__ = ["compile", "compile_file"]