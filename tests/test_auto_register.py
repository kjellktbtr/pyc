"""Tests for `auto` and `register` storage-class specifiers parsing."""

from src.pyc.lexer import tokenize
from src.pyc.parser import Parser
from src.pyc.ast import DeclStmt


def test_auto_register_parsed_in_local_decls() -> None:
    src = "int main(){ auto int a; register int b; return 0; }"
    tu = Parser(tokenize(src)).parse()

    top = next(d for d in tu.declarations if d.body)
    func = top.body
    found_auto = False
    found_register = False

    for stmt in func.body.statements:
        if isinstance(stmt, DeclStmt):
            if "auto" in stmt.specifiers:
                found_auto = True
            if "register" in stmt.specifiers:
                found_register = True

    assert found_auto and found_register
