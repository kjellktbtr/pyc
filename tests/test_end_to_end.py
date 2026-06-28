"""End-to-end tests: compile C source and verify NASM output."""

import pytest

from src.pyc.compiler import compile


class TestSmoke:
    def test_minimal_program(self) -> None:
        source = "int main() { return 42; }"
        assembly = compile(source)
        assert "[bits 16]" in assembly
        assert "section .text" in assembly
        assert "main:" in assembly
        assert "mov ax, 42" in assembly

    def test_program_structure(self) -> None:
        source = "int main() { return 0; }"
        assembly = compile(source)
        # Check NASM directives
        assert "section .text" in assembly
        # Check function framework
        assert "push bp" in assembly
        assert "mov bp, sp" in assembly
        assert "pop bp" in assembly
        assert "ret" in assembly
