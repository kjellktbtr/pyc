"""Tests for the lexer."""

import pytest

from src.pyc.lexer import Lexer, LexerError, tokenize
from src.pyc.tokens import TokenKind


class TestKeywords:
    def test_int_keyword(self) -> None:
        tokens = tokenize("int")
        assert tokens[0].kind == TokenKind.INT
        assert tokens[0].value == "int"

    def test_return_keyword(self) -> None:
        tokens = tokenize("return")
        assert tokens[0].kind == TokenKind.RETURN

    def test_if_else_keywords(self) -> None:
        tokens = tokenize("if else")
        assert tokens[0].kind == TokenKind.IF
        assert tokens[1].kind == TokenKind.ELSE


class TestIdentifiers:
    def test_simple_identifier(self) -> None:
        tokens = tokenize("main")
        assert tokens[0].kind == TokenKind.IDENTIFIER
        assert tokens[0].value == "main"

    def test_underscore_identifier(self) -> None:
        tokens = tokenize("_private")
        assert tokens[0].kind == TokenKind.IDENTIFIER

    def test_mixed_identifier(self) -> None:
        tokens = tokenize("var_123")
        assert tokens[0].kind == TokenKind.IDENTIFIER


class TestLiterals:
    def test_int_literal(self) -> None:
        tokens = tokenize("42")
        assert tokens[0].kind == TokenKind.INT_LITERAL
        assert tokens[0].value == "42"

    def test_hex_literal(self) -> None:
        tokens = tokenize("0xFF")
        assert tokens[0].kind == TokenKind.INT_LITERAL
        assert tokens[0].value == "0xFF"

    def test_binary_literal(self) -> None:
        tokens = tokenize("0b1010")
        assert tokens[0].kind == TokenKind.INT_LITERAL
        assert tokens[0].value == "0b1010"

    def test_binary_literal_uppercase_b(self) -> None:
        tokens = tokenize("0B100")
        assert tokens[0].kind == TokenKind.INT_LITERAL
        assert tokens[0].value == "0B100"

    def test_char_literal(self) -> None:
        tokens = tokenize("'a'")
        assert tokens[0].kind == TokenKind.CHAR_LITERAL
        assert tokens[0].value == "a"

    def test_escape_char_literal(self) -> None:
        tokens = tokenize("'\\n'")
        assert tokens[0].kind == TokenKind.CHAR_LITERAL
        assert tokens[0].value == "\n"

    def test_string_literal(self) -> None:
        tokens = tokenize('"hello"')
        assert tokens[0].kind == TokenKind.STRING_LITERAL
        assert tokens[0].value == "hello"

    def test_string_with_escapes(self) -> None:
        tokens = tokenize('"hello\\nworld"')
        assert tokens[0].kind == TokenKind.STRING_LITERAL
        assert tokens[0].value == "hello\nworld"

    def test_float_literal(self) -> None:
        tokens = tokenize("3.14")
        assert tokens[0].kind == TokenKind.FLOAT_LITERAL


class TestOperators:
    def test_arithmetic_operators(self) -> None:
        tokens = tokenize("+ - * / %")
        kinds = [t.kind for t in tokens]
        assert TokenKind.PLUS in kinds
        assert TokenKind.MINUS in kinds
        assert TokenKind.STAR in kinds
        assert TokenKind.SLASH in kinds
        assert TokenKind.PERCENT in kinds

    def test_compound_operators(self) -> None:
        tokens = tokenize("+=")
        assert tokens[0].kind == TokenKind.PLUS_EQUAL

    def test_comparison_operators(self) -> None:
        tokens = tokenize("== != < > <= >=")
        kinds = [t.kind for t in tokens]
        assert TokenKind.EQUAL_EQUAL in kinds
        assert TokenKind.EXCLAMATION_EQUAL in kinds
        assert TokenKind.LESS_EQUAL in kinds
        assert TokenKind.GREATER_EQUAL in kinds

    def test_logical_operators(self) -> None:
        tokens = tokenize("&& ||")
        assert tokens[0].kind == TokenKind.AMPERSAND_AMPERSAND
        assert tokens[1].kind == TokenKind.PIPE_PIPE

    def test_shift_operators(self) -> None:
        tokens = tokenize("<< >>")
        assert tokens[0].kind == TokenKind.LEFT_SHIFT
        assert tokens[1].kind == TokenKind.RIGHT_SHIFT

    def test_increment_decrement(self) -> None:
        tokens = tokenize("++ --")
        assert tokens[0].kind == TokenKind.PLUS_PLUS
        assert tokens[1].kind == TokenKind.MINUS_MINUS

    def test_ellipsis(self) -> None:
        # Three consecutive dots tokenise as a single ELLIPSIS, not three
        # DOTs.  Used by variadic function declarations.
        tokens = tokenize("int f(int a, ...);")
        kinds = [t.kind for t in tokens]
        assert TokenKind.ELLIPSIS in kinds
        # Make sure no stray DOT slipped in.
        assert TokenKind.DOT not in kinds


class TestDelimiters:
    def test_parentheses(self) -> None:
        tokens = tokenize("()")
        assert tokens[0].kind == TokenKind.LPAREN
        assert tokens[1].kind == TokenKind.RPAREN

    def test_brackets(self) -> None:
        tokens = tokenize("[]")
        assert tokens[0].kind == TokenKind.LBRACKET
        assert tokens[1].kind == TokenKind.RBRACKET

    def test_braces(self) -> None:
        tokens = tokenize("{}")
        assert tokens[0].kind == TokenKind.LBRACE
        assert tokens[1].kind == TokenKind.RBRACE


class TestComments:
    def test_block_comment(self) -> None:
        tokens = tokenize("/* comment */")
        assert tokens[0].kind == TokenKind.EOF

    def test_line_comment(self) -> None:
        tokens = tokenize("// comment")
        assert tokens[0].kind == TokenKind.EOF

    def test_multiline_comment(self) -> None:
        tokens = tokenize("/* multi\nline\ncomment */")
        assert tokens[0].kind == TokenKind.EOF


class TestSimpleProgram:
    def test_minimal_program(self) -> None:
        source = "int main() { return 0; }"
        tokens = tokenize(source)
        kinds = [t.kind for t in tokens]
        assert TokenKind.INT in kinds
        assert TokenKind.IDENTIFIER in kinds
        assert TokenKind.RETURN in kinds
        assert TokenKind.INT_LITERAL in kinds
        assert TokenKind.EOF in kinds


class TestLineTracking:
    def test_line_numbers(self) -> None:
        tokens = tokenize("int\nmain")
        assert tokens[0].line == 1  # int
        assert tokens[0].column == 1
        # tokens[1] is NEWLINE
        assert tokens[2].line == 2  # main
        assert tokens[2].column == 1
