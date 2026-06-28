"""Tests for signed/unsigned semantics (xfail until signedness is applied to CType)."""

import pytest

from src.pyc.lexer import tokenize
from src.pyc.parser import Parser
from src.pyc.types import BaseType


def test_unsigned_int_results_in_unsigned_base_type() -> None:
    tu = Parser(tokenize("unsigned int x; ")).parse()
    decl = tu.declarations[0]
    dtype = decl.declarators[0][1]
    assert isinstance(dtype, BaseType)
    assert dtype.signed is False
