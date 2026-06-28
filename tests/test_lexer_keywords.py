"""Lexer keyword recognition tests (including planned coverage for `auto`/`register`)."""

import pytest

from src.pyc.lexer import tokenize
from src.pyc.tokens import TokenKind
import src.pyc.tokens as tokens


def test_common_keywords_tokenized() -> None:
    toks = tokenize("if else int return while")
    kinds = [t.kind for t in toks if t.kind not in (TokenKind.EOF, TokenKind.NEWLINE)]
    assert TokenKind.IF in kinds
    assert TokenKind.ELSE in kinds
    assert TokenKind.INT in kinds
    assert TokenKind.RETURN in kinds
    assert TokenKind.WHILE in kinds


def test_auto_register_in_keywords() -> None:
    # Future: lexer.KEYWORDS should contain 'auto' and 'register'
    assert "auto" in tokens.KEYWORDS
    assert "register" in tokens.KEYWORDS
