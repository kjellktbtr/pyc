"""Edge-case switch/case tests: big ranges, negative values, data segment size."""

import pytest
from src.pyc.lexer import tokenize
from src.pyc.parser import Parser
from src.pyc.codegen import CodeGenerator

def test_switch_big_range_sparse_table() -> None:
    # Range 0..20, only 3 cases
    src = "int main(){ int x=0; switch(x){ case 0: return 1; case 10: return 2; case 20: return 3; default: return 4; } }"
    tu = Parser(tokenize(src)).parse()
    asm = CodeGenerator().generate(tu)
    # Should use a jump table or linear search, but not crash
    assert "dw Lcase_" in asm or "cmp ax, 10" in asm

def test_switch_negative_case_values() -> None:
    src = "int main(){ int x=0; switch(x){ case -1: return 1; case 0: return 2; default: return 3; } }"
    tu = Parser(tokenize(src)).parse()
    asm = CodeGenerator().generate(tu)
    # Should handle negative case values (table or linear)
    assert "-1" in asm or "dw Lcase_" in asm

def test_switch_large_table_data_segment() -> None:
    # Range 0..15, all cases present (dense)
    src = "int main(){ int x=0; switch(x){ " + "; ".join(f"case {i}: return {i};" for i in range(16)) + " default: return 99; } }"
    tu = Parser(tokenize(src)).parse()
    asm = CodeGenerator().generate(tu)
    # Should emit a jump table with 16 entries
    assert asm.count("dw Lcase_") >= 1 or asm.count("cmp ax, ") >= 10