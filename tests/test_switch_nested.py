"""Nested switch: inner switch cases must not appear in outer dispatch."""

from src.pyc.lexer import tokenize
from src.pyc.parser import Parser
from src.pyc.codegen import CodeGenerator


def test_nested_switch_no_duplicate_dispatch() -> None:
    """Outer switch must not contain case labels from the inner switch."""
    src = """
int main() {
    int x = 1;
    int y = 2;
    int r = 0;
    switch (x) {
        case 1:
            switch (y) {
                case 2: r = 10; break;
                case 3: r = 20; break;
            }
            break;
        case 4: r = 99; break;
    }
    return r;
}
"""
    tu = Parser(tokenize(src)).parse()
    asm = CodeGenerator().generate(tu)

    # Count how many times 'cmp ax, 2' appears — should be exactly once
    # (in the inner switch dispatch, not duplicated in the outer dispatch)
    cmp2_count = asm.count("cmp ax, 2")
    assert cmp2_count == 1, (
        f"'cmp ax, 2' appeared {cmp2_count} times — "
        "inner switch cases leaked into outer dispatch"
    )
    # Outer dispatch must see case 1 and case 4 only
    assert "cmp ax, 1" in asm
    assert "cmp ax, 4" in asm


def test_nested_switch_with_fallthrough_groups() -> None:
    """Multi-case fall-through in inner switch must not pollute outer dispatch."""
    src = """
int main() {
    int outer = 0;
    int inner = 0;
    int r = 0;
    switch (outer) {
        case 0:
        case 1:
            switch (inner) {
                case 10: case 11: r = 1; break;
                case 20: r = 2; break;
            }
            break;
        case 5: r = 99; break;
    }
    return r;
}
"""
    tu = Parser(tokenize(src)).parse()
    asm = CodeGenerator().generate(tu)

    # 'cmp ax, 10' and 'cmp ax, 11' should appear exactly once (inner switch)
    assert asm.count("cmp ax, 10") == 1, "case 10 duplicated from inner to outer"
    assert asm.count("cmp ax, 11") == 1, "case 11 duplicated from inner to outer"
    # Outer dispatch sees 0, 1, 5
    assert "cmp ax, 5" in asm
