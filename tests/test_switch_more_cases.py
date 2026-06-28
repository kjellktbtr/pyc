"""Additional switch/case tests: multiple cases, fall-through, and non-constant case expressions."""

import pytest

from src.pyc.lexer import tokenize
from src.pyc.parser import Parser
from src.pyc.codegen import CodeGenerator


def test_switch_multiple_cases_codegen() -> None:
    src = "int main(){ int x=0; switch(x){ case 1: return 1; case 2: return 2; default: return 3; } }"
    tu = Parser(tokenize(src)).parse()
    asm = CodeGenerator().generate(tu)

    # Accept either linear compares or a jump-table implementation
    has_linear = ("cmp ax, 1" in asm) and ("cmp ax, 2" in asm)
    has_table = "dw Lcase_" in asm or "jmp word [" in asm
    assert has_linear or has_table


def test_switch_fallthrough_codegen() -> None:
    src = "int main(){ int x=0; switch(x){ case 1: ; case 2: return 2; default: return 3; } }"
    tu = Parser(tokenize(src)).parse()
    asm = CodeGenerator().generate(tu)

    # Expect at least two case labels emitted for case 1 and case 2
    assert asm.count("Lcase_") >= 2


@pytest.mark.xfail(reason="non-constant case expressions not supported")
def test_non_constant_case_xfail() -> None:
    src = "int main(){ int x=0; int y=1; switch(x){ case y: return 1; } }"
    Parser(tokenize(src)).parse()
