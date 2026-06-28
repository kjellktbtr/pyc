"""Parser tests for `typedef` and `switch`/`case` parsing (xfail for planned features)."""

import pytest

from src.pyc.lexer import tokenize
from src.pyc.parser import Parser
from src.pyc.types import BaseType
from src.pyc.ast import CaseLabel


def test_typedef_alias_resolves_to_type() -> None:
    src = "typedef int myint; myint x;"
    tu = Parser(tokenize(src)).parse()
    # Expect the typedef to create an alias so that `x` has type `int`.
    decls = [d for d in tu.declarations if d.declarators]
    assert any(d.declarators[0][0] == "x" for d in decls)
    dtype = [d.declarators[0][1] for d in decls if d.declarators[0][0] == "x"][0]
    assert isinstance(dtype, BaseType) and dtype.name == "int"


def test_switch_case_parsed() -> None:
    src = "int main(){ int x=0; switch(x){ case 0: return 1; default: return 2; } }"
    tu = Parser(tokenize(src)).parse()

    found = False

    def walk(stmt):
        nonlocal found
        if isinstance(stmt, CaseLabel):
            found = True
            return
        if hasattr(stmt, "body") and stmt.body is not None:
            body = stmt.body
            if hasattr(body, "statements"):
                for s in body.statements:
                    walk(s)

    for d in tu.declarations:
        if d.body:
            for s in d.body.body.statements:
                walk(s)

    assert found
