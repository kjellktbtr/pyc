"""AST node definitions for the C compiler."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.pyc.types import CType


# --- Base classes ---

@dataclass
class Expr:
    """Base class for all expression nodes."""
    pass


@dataclass
class Stmt:
    """Base class for all statement nodes."""
    pass


# --- Program ---

@dataclass
class TranslationUnit:
    declarations: list[TopLevelDecl]
    # GCC __attribute__ markers captured from the parser.
    constructors: list[str] = field(default_factory=list)
    destructors: list[str] = field(default_factory=list)


@dataclass
class TopLevelDecl:
    """A top-level declaration or function definition."""
    specifiers: list[str]  # storage class: 'extern', 'static', etc.
    declarators: list[tuple[str, CType, Expr | None]]  # (name, type, init)
    body: FunctionDefinition | None = None


# --- Declarations ---

@dataclass
class Declarator:
    name: str
    type: CType
    qualifiers: list[str] = field(default_factory=list)


# --- Expressions ---

@dataclass
class IntLiteral(Expr):
    value: int
    type: CType


@dataclass
class FloatLiteral(Expr):
    value: float
    type: CType


@dataclass
class CharLiteral(Expr):
    value: int  # ASCII/ordinal value
    type: CType


@dataclass
class StringLiteral(Expr):
    value: str
    type: CType  # char[N+1]


@dataclass
class Identifier(Expr):
    name: str


@dataclass
class UnaryOp(Expr):
    op: str       # "-", "!", "~", "*", "&", "++", "--"
    operand: Expr
    pre: bool = True  # True for prefix, False for postfix ++/--


@dataclass
class BinaryOp(Expr):
    op: str       # "+", "-", "*", "/", "%", "<<", ">>", etc.
    left: Expr
    right: Expr


@dataclass
class TernaryExpr(Expr):
    condition: Expr
    true_branch: Expr
    false_branch: Expr


@dataclass
class CommaExpr(Expr):
    expressions: list[Expr]


@dataclass
class InitList(Expr):
    """A brace-enclosed initializer list: `{1, 2, 3}` or `{ .x = 1 }`.

    For now only positional initialisers are supported (no designated
    `.field = value` syntax).  Used as the RHS of an array or struct
    declaration's initialiser.
    """

    elements: list[Expr] = None  # type: ignore[assignment]


@dataclass
class CastExpr(Expr):
    target_type: CType
    operand: Expr


@dataclass
class SizeofExpr(Expr):
    operand: CType | Expr | None = None


@dataclass
class Subscript(Expr):
    array: Expr
    index: Expr


@dataclass
class CallExpr(Expr):
    function: Expr
    args: list[Expr]


@dataclass
class MemberAccess(Expr):
    object: Expr
    member: str
    indirect: bool = False  # False for '.', True for '->'


@dataclass
class CompoundAssignment(Expr):
    target: Expr  # must be an lvalue
    op: str
    value: Expr


# --- Statements ---

@dataclass
class Block(Stmt):
    statements: list[Stmt | DeclStmt]


@dataclass
class ExpressionStmt(Stmt):
    expr: Expr | None  # None for empty statement ";"


@dataclass
class DeclStmt(Stmt):
    """Variable declaration inside a block."""
    specifiers: list[str]
    declarations: list[tuple[str, CType, Expr | None]]  # (name, type, init)


@dataclass
class IfStmt(Stmt):
    condition: Expr
    then_branch: Stmt
    else_branch: Stmt | None = None


@dataclass
class SwitchStmt(Stmt):
    expression: Expr
    body: Stmt


@dataclass
class CaseLabel(Stmt):
    value: int | None  # None for 'default'
    body: Stmt


@dataclass
class WhileStmt(Stmt):
    condition: Expr
    body: Stmt


@dataclass
class DoWhileStmt(Stmt):
    condition: Expr
    body: Stmt


@dataclass
class ForStmt(Stmt):
    body: Stmt
    init: Stmt | None = None
    condition: Expr | None = None  # None means infinite
    increment: Expr | None = None


@dataclass
class BreakStmt(Stmt):
    pass


@dataclass
class ContinueStmt(Stmt):
    pass


@dataclass
class GotoStmt(Stmt):
    label: str


@dataclass
class ComputedGotoStmt(Stmt):
    """GNU `goto *expr` — jumps to the address held in `expr`."""
    target: Expr


@dataclass
class LabelAddress(Expr):
    """GNU `&&label` — yields the address of a code label."""
    label: str


@dataclass
class LabelStmt(Stmt):
    label: str
    stmt: Stmt


@dataclass
class ReturnStmt(Stmt):
    value: Expr | None


# --- Functions ---

@dataclass
class FunctionDefinition:
    name: str
    return_type: CType
    params: list[tuple[str, CType]]  # (name, type); name="" for unnamed
    body: Block
    is_variadic: bool = False
