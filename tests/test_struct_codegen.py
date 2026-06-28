"""Tests for struct member access code generation."""

from src.pyc.lexer import tokenize
from src.pyc.parser import Parser
from src.pyc.codegen import CodeGenerator


def _compile(src: str) -> str:
    tokens = tokenize(src)
    tu = Parser(tokens).parse()
    return CodeGenerator().generate(tu)


def test_struct_member_access_uses_offset() -> None:
    """`s.b` for `struct S { char a; int b; }` reads at offset 2 after
    the padding/alignment for `a`."""
    asm = _compile(
        "struct S { char a; int b; };"
        "int main() { struct S s; s.b = 3; return s.b; }"
    )
    # The read of s.b adds the byte offset 2 before the load.
    assert "add ax, 2" in asm


def test_struct_first_member_no_offset_added() -> None:
    """Member at offset 0 must NOT emit a spurious `add ax, 0`."""
    asm = _compile(
        "struct S { int a; int b; };"
        "int main() { struct S s; s.a = 5; return s.a; }"
    )
    # The first field needs no offset bias.
    assert "add ax, 0" not in asm


def test_arrow_uses_offset() -> None:
    """`p->b` evaluates p, then adds the field offset before loading."""
    asm = _compile(
        "struct S { int a; int b; };"
        "int f(struct S *p) { return p->b; }"
    )
    assert "add ax, 2" in asm


def test_char_member_uses_byte_load() -> None:
    """A `char` field is loaded with `mov al,[bx]` / `xor ah,ah`."""
    asm = _compile(
        "struct S { char a; char b; };"
        "int f(void) { struct S s; s.b = 1; return s.b; }"
    )
    assert "mov al, [bx]" in asm
    assert "xor ah, ah" in asm
