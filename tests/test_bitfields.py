"""Tests for bitfield parsing, layout, and codegen."""

from src.pyc.codegen import CodeGenerator
from src.pyc.lexer import tokenize
from src.pyc.parser import Parser
from src.pyc.types import BitField


def _parse(src: str) -> Parser:
    p = Parser(tokenize(src))
    p.parse()
    return p


def test_parse_struct_bitfields() -> None:
    p = _parse("struct S { unsigned a:3; unsigned b:5; };")
    assert "S" in p.structs
    s = p.structs["S"]
    fa = s.field_type("a")
    fb = s.field_type("b")
    assert isinstance(fa, BitField) and fa.width == 3 and fa.bit_offset == 0
    assert isinstance(fb, BitField) and fb.width == 5 and fb.bit_offset == 3
    # Both pack into a single 2-byte int.
    assert s.field_offset("a") == 0
    assert s.field_offset("b") == 0


def test_bitfields_overflow_word_starts_new() -> None:
    """A field that would cross the 16-bit boundary starts a new word."""
    p = _parse("struct S { unsigned a:12; unsigned b:8; };")
    s = p.structs["S"]
    assert s.field_offset("a") == 0
    # 'b' (8 bits) doesn't fit alongside a (12 bits) → new word at offset 2.
    assert s.field_offset("b") == 2
    assert s.field_type("b").bit_offset == 0


def _compile(src: str) -> str:
    tokens = tokenize(src)
    tu = Parser(tokens).parse()
    return CodeGenerator().generate(tu)


def test_bitfield_read_emits_shr_and_mask() -> None:
    asm = _compile(
        "struct S { unsigned a:3; unsigned b:5; };"
        "int main() { struct S s; return s.b; }"
    )
    # b's bit_offset is 3, width 5 → mask 0x1F (31).
    assert "shr ax, cl" in asm
    assert "and ax, 31" in asm


def test_bitfield_write_read_modify_write() -> None:
    asm = _compile(
        "struct S { unsigned a:3; unsigned b:5; };"
        "int main() { struct S s; s.b = 17; return 0; }"
    )
    # Writing b should mask the new value, shift, and OR-merge with the
    # cleared bits of the storage word.
    assert "and ax, 31" in asm        # mask new value
    assert "shl ax, cl" in asm        # shift into bit_offset
    assert "or ax, dx" in asm         # merge with preserved bits
