"""Tests for pointer/array indexing scaling in code generation.

These tests assert the desired generated assembly should scale index values by
the element size (e.g., multiply index by 2 for `int` on the 16-bit model).
They are xfail'd until the code generator uses element sizes when computing
addresses.
"""

import pytest

from src.pyc.lexer import tokenize
from src.pyc.parser import Parser
from src.pyc.codegen import CodeGenerator


def test_array_index_scaling_in_codegen() -> None:
    src = "int main() { int a[10]; a[1] = 3; return a[1]; }"
    tokens = tokenize(src)
    p = Parser(tokens)
    tu = p.parse()
    asm = CodeGenerator().generate(tu)
    # Expect shift/multiply by element size (2) when computing address
    # Uses 'shl ax, 1' for scaling by 2
    assert "shl ax, 1" in asm
