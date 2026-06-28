"""Tests for parsing storage-class specifiers and qualifiers."""

from src.pyc.lexer import tokenize
from src.pyc.parser import Parser
from src.pyc.ast import TranslationUnit


def _parse(source: str) -> TranslationUnit:
    tokens = tokenize(source)
    return Parser(tokens).parse()


def test_top_level_specifiers_present() -> None:
    tu = _parse("static int x = 1; const int c = 2; extern int y;")
    assert len(tu.declarations) == 3

    static_decl = tu.declarations[0]
    assert "static" in static_decl.specifiers
    assert static_decl.declarators[0][0] == "x"

    const_decl = tu.declarations[1]
    assert "const" in const_decl.specifiers
    assert const_decl.declarators[0][0] == "c"

    extern_decl = tu.declarations[2]
    assert "extern" in extern_decl.specifiers
    assert extern_decl.declarators[0][0] == "y"


def test_qualifier_after_type_spec() -> None:
    """Qualifiers (const/volatile) may follow the type-spec (e.g. `int volatile x`)."""
    tu = _parse(
        "extern int volatile test;\n"
        "int volatile test = 0;\n"
        "char const *p;\n"
        "int *volatile q;\n"
    )
    assert len(tu.declarations) == 4
    assert tu.declarations[0].declarators[0][0] == "test"
    assert tu.declarations[1].declarators[0][0] == "test"
    assert tu.declarations[2].declarators[0][0] == "p"
    assert tu.declarations[3].declarators[0][0] == "q"
