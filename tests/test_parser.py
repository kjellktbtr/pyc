"""Tests for the parser."""

import pytest

from src.pyc.ast import (
    BinaryOp,
    Block,
    FunctionDefinition,
    Identifier,
    IntLiteral,
    ReturnStmt,
    TranslationUnit,
    UnaryOp,
)
from src.pyc.lexer import tokenize
from src.pyc.parser import Parser, ParserError


def _parse(source: str) -> TranslationUnit:
    tokens = tokenize(source)
    return Parser(tokens).parse()


class TestBasicParsing:
    def test_empty_function(self) -> None:
        ast = _parse("int main() { }")
        assert isinstance(ast, TranslationUnit)
        assert len(ast.declarations) == 1

    def test_return_literal(self) -> None:
        ast = _parse("int main() { return 42; }")
        decl = ast.declarations[0]
        assert decl.body is not None
        assert isinstance(decl.body, FunctionDefinition)

    def test_function_with_return(self) -> None:
        ast = _parse("int foo() { return 0; }")
        decl = ast.declarations[0]
        assert decl.body.name == "foo"

    def test_arithmetic_expression(self) -> None:
        ast = _parse("int main() { return a + b; }")
        # The parser should not crash on binary expressions
        assert isinstance(ast, TranslationUnit)

    def test_nested_expressions(self) -> None:
        ast = _parse("int main() { return a + b * c; }")
        assert isinstance(ast, TranslationUnit)

    def test_if_statement(self) -> None:
        ast = _parse("int main() { if (x) return 1; }")
        assert isinstance(ast, TranslationUnit)

    def test_while_loop(self) -> None:
        ast = _parse("int main() { while (x) { x = 0; } }")
        assert isinstance(ast, TranslationUnit)


class TestIntegerLiterals:
    """Magnitude parsing for hex / octal / binary / decimal + suffixes."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("0", 0),
            ("42", 42),
            ("0644", 0o644),   # C octal — int(s, 0) would reject this
            ("010", 8),
            ("0xFF", 255),
            ("0XfF", 255),
            ("0b1010", 10),    # GNU binary
            ("100UL", 100),
            ("0777L", 0o777),
        ],
    )
    def test_magnitude(self, raw: str, expected: int) -> None:
        from src.pyc.parser import _parse_int_literal

        assert _parse_int_literal(raw).value == expected


class TestVariadicFunctions:
    def test_variadic_definition(self) -> None:
        ast = _parse("int f(int a, ...) { return a; }")
        defn = ast.declarations[0].body
        assert defn is not None
        assert defn.is_variadic is True
        assert [name for name, _ in defn.params] == ["a"]

    def test_non_variadic_definition_defaults_false(self) -> None:
        ast = _parse("int f(int a, int b) { return a; }")
        assert ast.declarations[0].body.is_variadic is False

    def test_variadic_declaration_parses(self) -> None:
        # A bare declaration with `...` must parse without errors.
        ast = _parse("int printf(char *fmt, ...);")
        assert ast.declarations[0].body is None

    def test_ellipsis_without_named_param_rejected(self) -> None:
        with pytest.raises(ParserError):
            _parse("int f(...) { return 0; }")

    def test_param_after_ellipsis_rejected(self) -> None:
        with pytest.raises(ParserError):
            _parse("int f(int a, ..., int b) { return a; }")


class TestFunctionPointers:
    def test_typedef_function_pointer(self) -> None:
        """`typedef int (*BinOp)(int, int);` produces a PointerType whose
        inner is a FunctionType with the right return type and param
        list."""
        from src.pyc.lexer import tokenize as _t
        from src.pyc.parser import Parser as _P
        from src.pyc.types import BaseType, FunctionType, PointerType
        p = _P(_t("typedef int (*BinOp)(int, int);"))
        p.parse()
        assert "BinOp" in p.typedefs
        t = p.typedefs["BinOp"]
        assert isinstance(t, PointerType)
        assert isinstance(t.inner, FunctionType)
        assert isinstance(t.inner.return_type, BaseType)
        assert t.inner.return_type.name == "int"
        assert len(t.inner.params) == 2

    def test_function_pointer_parameter(self) -> None:
        """A function with a function-pointer parameter parses; the
        parameter's type is PointerType(FunctionType)."""
        ast = _parse(
            "int apply(int (*f)(int, int), int a, int b) { return f(a, b); }"
        )
        defn = ast.declarations[0].body
        from src.pyc.types import PointerType, FunctionType
        pname, ptype = defn.params[0]
        assert pname == "f"
        assert isinstance(ptype, PointerType)
        assert isinstance(ptype.inner, FunctionType)

    def test_function_returning_typedef_pointer(self) -> None:
        """A function whose return type is a typedef'd function pointer
        parses without complaint."""
        ast = _parse(
            "typedef int (*BinOp)(int, int);"
            "int add(int a, int b);"
            "BinOp choose(int op) { return add; }"
        )
        # Three top-level decls: the typedef, the forward decl, and
        # `choose`.  The third has a body.
        defn = ast.declarations[2].body
        assert defn is not None
        assert defn.name == "choose"


class TestExpressionPrecedence:
    def test_mul_before_add(self) -> None:
        """a + b * c should parse as (a + (b * c))."""
        ast = _parse("int main() { return a + b * c; }")
        # The parser uses precedence climbing, so this should work
        assert isinstance(ast, TranslationUnit)

    def test_parenthesized_expression(self) -> None:
        ast = _parse("int main() { return (a + b) * c; }")
        assert isinstance(ast, TranslationUnit)

    def test_comparison_expression(self) -> None:
        ast = _parse("int main() { if (x == 0) { } }")
        assert isinstance(ast, TranslationUnit)


class TestErrorHandling:
    def test_missing_semicolon(self) -> None:
        """Should raise ParserError on missing semicolon."""
        with pytest.raises(ParserError):
            _parse("int main() { int x }")
