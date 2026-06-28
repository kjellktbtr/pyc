"""Tests for `break` and `continue` parsing in loops."""

from src.pyc.lexer import tokenize
from src.pyc.parser import Parser
from src.pyc.ast import BreakStmt, ContinueStmt, Block


def test_break_and_continue_parsed() -> None:
    tu = Parser(tokenize("int main(){ while(1){ break; continue; } } ")).parse()

    found_break = False
    found_continue = False

    def walk(stmt):
        nonlocal found_break, found_continue
        if isinstance(stmt, BreakStmt):
            found_break = True
            return
        if isinstance(stmt, ContinueStmt):
            found_continue = True
            return
        if isinstance(stmt, Block):
            for s in stmt.statements:
                walk(s)
        elif hasattr(stmt, "body") and stmt.body is not None:
            walk(stmt.body)

    for d in tu.declarations:
        if d.body:
            walk(d.body)

    assert found_break and found_continue
