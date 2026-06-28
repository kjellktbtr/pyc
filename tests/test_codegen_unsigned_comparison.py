"""Tests that unsigned comparisons generate unsigned jump instructions."""

from src.pyc.lexer import tokenize
from src.pyc.parser import Parser
from src.pyc.codegen import CodeGenerator


def test_unsigned_comparison_generates_unsigned_jump() -> None:
    src = "int main(){ unsigned int a; unsigned int b; if (a < b) return 1; return 0; }"
    tu = Parser(tokenize(src)).parse()
    cg = CodeGenerator()
    asm = cg.generate(tu)

    # For unsigned '<' we expect 'jb' (jump below / unsigned less-than)
    assert "cmp ax, " in asm
    assert "jb " in asm or "ja " in asm or "jbe " in asm or "jae " in asm
