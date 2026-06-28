"""char literal in case: _eval_const_expr must handle CharLiteral.value as int."""

from src.pyc.lexer import tokenize
from src.pyc.parser import Parser
from src.pyc.codegen import CodeGenerator


def test_switch_char_case_compiles() -> None:
    """switch on a char with char-literal case labels must not crash."""
    src = r"""
int main() {
    char c = 'A';
    switch (c) {
        case 'A': return 1;
        case 'B': return 2;
        default:  return 0;
    }
}
"""
    tu = Parser(tokenize(src)).parse()
    asm = CodeGenerator().generate(tu)
    # 'A' == 65, 'B' == 66 — one must appear in the generated assembly
    assert "65" in asm or "0x41" in asm or "cmp ax, 65" in asm


def test_switch_char_case_correct_value() -> None:
    """Char case label 'Z' (90) must use the correct ordinal."""
    src = r"""
int main() {
    int c = 90;
    switch (c) {
        case 'Z': return 99;
        default:  return 0;
    }
}
"""
    tu = Parser(tokenize(src)).parse()
    asm = CodeGenerator().generate(tu)
    assert "90" in asm or "0x5a" in asm or "cmp ax, 90" in asm
