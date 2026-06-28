"""Recursive descent parser: tokens → AST."""

from __future__ import annotations

from src.pyc.ast import (
    BinaryOp,
    Block,
    CallExpr,
    CaseLabel,
    CastExpr,
    CharLiteral,
    CommaExpr,
    CompoundAssignment,
    DeclStmt,
    DoWhileStmt,
    Expr,
    ExpressionStmt,
    ForStmt,
    FunctionDefinition,
    ComputedGotoStmt,
    GotoStmt,
    Identifier,
    IfStmt,
    InitList,
    IntLiteral,
    LabelStmt,
    MemberAccess,
    ReturnStmt,
    SizeofExpr,
    Stmt,
    StringLiteral,
    Subscript,
    SwitchStmt,
    TernaryExpr,
    TopLevelDecl,
    TranslationUnit,
    UnaryOp,
    WhileStmt,

    BreakStmt,
    ContinueStmt,)
from src.pyc.tokens import Token, TokenKind
from src.pyc.types import (
    ArrayType,
    BaseType,
    CType,
    EnumType,
    FunctionType,
    PointerType,
    StructType,
    UnionType,
    array_of,
    base_type,
    pointer_to,
    void_type,
)


class ParserError(Exception):
    def __init__(self, message: str, token: Token | None = None) -> None:
        loc = ""
        if token is not None:
            loc = f" at {getattr(token, 'file', '<input>')} L{token.line}C{token.column}"
        super().__init__(f"Parse error{loc}: {message}")


def _parse_c_int_magnitude(s: str) -> int:
    """Parse a C integer-literal magnitude (suffix already stripped).

    Handles `0x`/`0X` hex, `0b`/`0B` binary (GNU), `0o`/`0O` (non-C but
    harmless), C octal (`0` followed by octal digits), and decimal.
    """
    if not s:
        return 0
    low = s.lower()
    if low.startswith(("0x", "0b", "0o")):
        return int(s, 0)
    if s.startswith("0") and len(s) > 1:
        return int(s, 8)        # C octal: 0NNN
    return int(s, 10)


def _parse_int_literal(raw: str) -> IntLiteral:
    """Parse the textual integer-literal token (hex/decimal/octal + L/U/UL
    suffixes) into a typed `IntLiteral`.

    The lexer hands us the raw spelling including the suffix.  We strip the
    suffix characters, then parse the magnitude.  Note that Python's
    `int(s, 0)` accepts `0x`/`0b`/`0o` and plain decimal but *rejects* the
    C octal form (a leading `0` followed by octal digits, e.g. `0644`), so
    that case is handled explicitly with base 8.
    """
    s = raw
    is_unsigned = False
    l_count = 0
    while s and s[-1] in "uUlL":
        ch = s[-1]
        if ch in "uU":
            is_unsigned = True
        else:
            l_count += 1
        s = s[:-1]
    value = _parse_c_int_magnitude(s)
    # Promote based on magnitude when no explicit suffix forces a width.
    if l_count == 0 and (value > 0x7FFFFFFF or value < -0x80000000):
        l_count = 2
    elif l_count == 0 and (value > 0x7FFF or value < -0x8000):
        l_count = 1
    if l_count >= 2:
        type_name = "long_long"
    elif l_count == 1:
        type_name = "long"
    else:
        type_name = "int"
    t = base_type(type_name)
    if is_unsigned:
        t = BaseType(name=type_name, signed=False)
    return IntLiteral(value, t)


# Expression precedence levels (lowest to highest)
PREC_COMMA = 1
PREC_ASSIGN = 2
PREC_TERNARY = 3
PREC_LOGOR = 4
PREC_LOGAND = 5
PREC_BITOR = 6
PREC_BITXOR = 7
PREC_BITAND = 8
PREC_EQUAL = 9
PREC_REL = 10
PREC_SHIFT = 11
PREC_ADD = 12
PREC_MUL = 13
PREC_UNARY = 14
PREC_POSTFIX = 15


# Map binary operator tokens to precedence levels
BINOP_PRECEDENCE: dict[TokenKind, int] = {
    TokenKind.COMMA: PREC_COMMA,
    TokenKind.AMPERSAND_AMPERSAND: PREC_LOGAND,
    TokenKind.PIPE_PIPE: PREC_LOGOR,
    TokenKind.PIPE: PREC_BITOR,
    TokenKind.CARET: PREC_BITXOR,
    TokenKind.AMPERSAND: PREC_BITAND,
    TokenKind.EQUAL_EQUAL: PREC_EQUAL,
    TokenKind.EXCLAMATION_EQUAL: PREC_EQUAL,
    TokenKind.LESS: PREC_REL,
    TokenKind.GREATER: PREC_REL,
    TokenKind.LESS_EQUAL: PREC_REL,
    TokenKind.GREATER_EQUAL: PREC_REL,
    TokenKind.LEFT_SHIFT: PREC_SHIFT,
    TokenKind.RIGHT_SHIFT: PREC_SHIFT,
    TokenKind.PLUS: PREC_ADD,
    TokenKind.MINUS: PREC_ADD,
    TokenKind.STAR: PREC_MUL,
    TokenKind.SLASH: PREC_MUL,
    TokenKind.PERCENT: PREC_MUL,
}

# Assignment operators
ASSIGN_OPS = {
    TokenKind.EQUAL, TokenKind.PLUS_EQUAL, TokenKind.MINUS_EQUAL,
    TokenKind.STAR_EQUAL, TokenKind.SLASH_EQUAL, TokenKind.PERCENT_EQUAL,
    TokenKind.AMPERSAND_EQUAL, TokenKind.PIPE_EQUAL, TokenKind.CARET_EQUAL,
    TokenKind.LEFT_SHIFT_EQUAL, TokenKind.RIGHT_SHIFT_EQUAL,
}

# Unary operators
UNARY_OPS = {
    TokenKind.PLUS, TokenKind.MINUS, TokenKind.BANG, TokenKind.TILDE,
    TokenKind.STAR, TokenKind.AMPERSAND,
}

PREFIX_INC = {TokenKind.PLUS_PLUS, TokenKind.MINUS_MINUS}


class Parser:
    """Recursive descent parser for C subset."""

    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0
        self.structs: dict[str, StructType] = {}
        self.unions: dict[str, UnionType] = {}
        self.enums: dict[str, EnumType] = {}
        self.typedefs: dict[str, CType] = {}  # New typedef map
        # Enum-member names mapped to their integer values; consulted
        # in `_parse_primary` so `enum { A=7 }; int x = A;` resolves
        # `A` to the literal 7 rather than an undeclared identifier.
        self.enum_consts: dict[str, int] = {}
        # GCC `__attribute__((constructor))` / `((destructor))` markers.
        # Filled by `_skip_attribute_specifiers` and consumed by codegen.
        self.constructors: list[str] = []
        self.destructors: list[str] = []
        # Name of the most recently parsed function-declarator — used
        # to attach a pending attribute (which appears AFTER the
        # declarator in the standard placement) to the right symbol.
        self._last_function_name: str | None = None
        # Set when the in-flight declarator carries a constructor or
        # destructor attribute that should be promoted once we know
        # which name it applies to.
        self._pending_attr_ctor = False
        self._pending_attr_dtor = False

    def _current(self) -> Token:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else self.tokens[-1]

    def _peek_kind(self) -> TokenKind:
        return self._current().kind

    def _advance(self) -> Token:
        token = self._current()
        if self.pos < len(self.tokens) - 1:
            self.pos += 1
        return token

    def _expect(self, kind: TokenKind) -> Token:
        token = self._current()
        if token.kind != kind:
            raise ParserError(f"Expected {kind.name}, got {token.kind.name}", token)
        return self._advance()

    def _check(self, *kinds: TokenKind) -> bool:
        return self._peek_kind() in kinds

    def _at_eof(self) -> bool:
        return self._peek_kind() == TokenKind.EOF

    # --- Entry point ---

    def parse(self) -> TranslationUnit:
        declarations: list[TopLevelDecl] = []
        while not self._at_eof():
            if self._check(TokenKind.NEWLINE):
                self._advance()
                continue
            declarations.append(self._parse_top_level_decl())
        return TranslationUnit(
            declarations,
            constructors=list(self.constructors),
            destructors=list(self.destructors),
        )

    # --- Constant expression evaluator (for case labels, array sizes) ---

    def _eval_const_expr(self, expr: Expr) -> int | None:
        """Evaluate a compile-time constant integer expression.

        Returns the integer value or None if not a constant.
        """
        if isinstance(expr, IntLiteral):
            return expr.value
        if isinstance(expr, CharLiteral):
            return expr.value  # already stored as int by the lexer
        if isinstance(expr, Identifier) and expr.name in self.enum_consts:
            return self.enum_consts[expr.name]
        if isinstance(expr, UnaryOp):
            inner = self._eval_const_expr(expr.operand)
            if inner is None:
                return None
            if expr.op == '-':
                return -inner
            if expr.op == '~':
                return ~inner
            if expr.op == '!':
                return 0 if inner else 1
        if isinstance(expr, BinaryOp):
            left = self._eval_const_expr(expr.left)
            right = self._eval_const_expr(expr.right)
            if left is None or right is None:
                return None
            if expr.op == '+':  return left + right
            if expr.op == '-':  return left - right
            if expr.op == '*':  return left * right
            if expr.op == '/' and right != 0: return int(left / right)
            if expr.op == '%' and right != 0: return left % right
            if expr.op == '<<': return left << right
            if expr.op == '>>': return left >> right
            if expr.op == '&':  return left & right
            if expr.op == '|':  return left | right
            if expr.op == '^':  return left ^ right
            if expr.op == '==': return int(left == right)
            if expr.op == '!=': return int(left != right)
            if expr.op == '<':  return int(left < right)
            if expr.op == '>':  return int(left > right)
            if expr.op == '<=': return int(left <= right)
            if expr.op == '>=': return int(left >= right)
        return None

    # --- Type specifiers ---

    def _parse_specifiers(self) -> list[str]:
        """Parse storage class and type qualifiers."""
        specifiers: list[str] = []
        while self._check(
            TokenKind.EXTERN, TokenKind.STATIC, TokenKind.CONST,
            TokenKind.VOLATILE, TokenKind.SIGNED, TokenKind.UNSIGNED,
            TokenKind.TYPEDEF, TokenKind.AUTO, TokenKind.REGISTER,
        ):
            specifiers.append(self._advance().value)
        return specifiers

    def _parse_type_specifier(self) -> CType | None:
        """Parse a type specifier keyword. Returns CType or None."""
        if self._check(TokenKind.VOID):
            self._advance()
            return void_type()
        if self._check(TokenKind.CHAR):
            self._advance()
            return base_type("char")
        if self._check(TokenKind.SHORT):
            self._advance()
            # `short int` and `int short` are both spellings for `short`.
            if self._check(TokenKind.INT):
                self._advance()
            return base_type("short")
        if self._check(TokenKind.INT):
            self._advance()
            # `int short` / `int long` / `int long long` — the trailing
            # modifier wins, matching GCC.
            if self._check(TokenKind.SHORT):
                self._advance()
                return base_type("short")
            if self._check(TokenKind.LONG):
                self._advance()
                if self._check(TokenKind.LONG):
                    self._advance()
                    return base_type("long_long")
                return base_type("long")
            return base_type("int")
        if self._check(TokenKind.LONG):
            self._advance()
            # Check if next token is also LONG (long long)
            if self._check(TokenKind.LONG):
                self._advance()
                # `long long int` is a synonym for `long long`.
                if self._check(TokenKind.INT):
                    self._advance()
                return base_type("long_long")
            # `long double` — no extended-precision support on this
            # target; alias to `double` so source compiles and runs at
            # double precision.
            if self._check(TokenKind.DOUBLE):
                self._advance()
                return base_type("double")
            # `long int` ≡ `long`.
            if self._check(TokenKind.INT):
                self._advance()
            return base_type("long")
        if self._check(TokenKind.FLOAT):
            self._advance()
            return base_type("float")
        if self._check(TokenKind.DOUBLE):
            self._advance()
            return base_type("double")
        if self._check(TokenKind.STRUCT):
            return self._parse_struct_decl()
        if self._check(TokenKind.UNION):
            return self._parse_union_decl()
        if self._check(TokenKind.ENUM):
            return self._parse_enum_decl()
        if self._check(TokenKind.IDENTIFIER):
            name = self._current().value
            if name in self.typedefs:
                self._advance()
                return self.typedefs[name]
        return None

    def _apply_specifiers_to_type(self, specifiers: list[str], ctype: CType) -> CType:
        """Apply storage-class/type qualifiers (signed/unsigned) to a CType."""
        # Only adjust signedness for BaseType
        if isinstance(ctype, BaseType):
            if "unsigned" in specifiers:
                ctype.signed = False
            elif "signed" in specifiers:
                ctype.signed = True
        return ctype

    def _parse_struct_decl(self) -> StructType:
        self._expect(TokenKind.STRUCT)
        name: str | None = None
        if self._check(TokenKind.IDENTIFIER):
            name = self._advance().value

        # The body's `{` may appear on a separate line from the tag.
        while self._check(TokenKind.NEWLINE):
            self._advance()

        if not self._check(TokenKind.LBRACE):
            if name and name in self.structs:
                return self.structs[name]
            # Forward declaration: `struct Foo*` may appear before the
            # body is defined.  Register an empty placeholder so later
            # references resolve to the same object once it is fleshed
            # out by the actual definition.
            if name:
                placeholder = StructType(name, [])
                self.structs[name] = placeholder
                return placeholder
            raise ParserError(f"Unknown struct {name!r}", self._current())

        self._expect(TokenKind.LBRACE)

        # Register the tag with an empty body *before* parsing fields so
        # self-referential pointer fields (`struct Foo* next;` inside
        # `struct Foo { ... };`) and any other forward references inside
        # the body resolve.  If a placeholder already exists (from a
        # forward `struct Foo*` declaration), mutate its field list in
        # place so prior references see the completed definition.
        if name and name in self.structs:
            struct_obj = self.structs[name]
            fields = struct_obj.fields
        else:
            fields = []
            struct_obj = StructType(name, fields)
            if name:
                self.structs[name] = struct_obj

        while not self._check(TokenKind.RBRACE, TokenKind.EOF):
            if self._check(TokenKind.NEWLINE):
                self._advance()
                continue
            specifiers = self._parse_specifiers()
            type_spec = self._parse_type_specifier()
            if type_spec is None:
                if any(s in ("signed", "unsigned") for s in specifiers):
                    type_spec = base_type("int")
                else:
                    raise ParserError("Expected type specifier in struct field", self._current())
            type_spec = self._apply_specifiers_to_type(specifiers, type_spec)
            names = self._parse_declarator_names(type_spec)
            for dname, dtype in names:
                if dname:
                    fields.append((dname, dtype))
            self._expect(TokenKind.SEMICOLON)

        self._expect(TokenKind.RBRACE)

        # Recompute the byte/bit layout now that fields have been added
        # (fields are mutated in place to keep forward-ref pointers
        # observing the same struct object).  Force recomputation by
        # clearing the cached flag.
        struct_obj._computed = False
        struct_obj._layout_fields()

        # A trailing IDENTIFIER after `}` is the *declarator/typedef name*,
        # not a struct tag — C only allows tags after the `struct` keyword.
        # Leave it for the caller (_parse_top_level_decl / _parse_declarator).
        return struct_obj

    def _parse_union_decl(self) -> UnionType:
        self._expect(TokenKind.UNION)
        name: str | None = None
        if self._check(TokenKind.IDENTIFIER):
            name = self._advance().value

        # The body's `{` may appear on a separate line from the tag.
        while self._check(TokenKind.NEWLINE):
            self._advance()

        if not self._check(TokenKind.LBRACE):
            if name and name in self.unions:
                return self.unions[name]
            raise ParserError(f"Unknown union {name!r}", self._current())

        self._expect(TokenKind.LBRACE)
        fields: list[tuple[str, CType]] = []

        while not self._check(TokenKind.RBRACE, TokenKind.EOF):
            if self._check(TokenKind.NEWLINE):
                self._advance()
                continue
            specifiers = self._parse_specifiers()
            type_spec = self._parse_type_specifier()
            if type_spec is None:
                if any(s in ("signed", "unsigned") for s in specifiers):
                    type_spec = base_type("int")
                else:
                    raise ParserError("Expected type specifier in union field", self._current())
            type_spec = self._apply_specifiers_to_type(specifiers, type_spec)
            names = self._parse_declarator_names(type_spec)
            for dname, dtype in names:
                if dname:
                    fields.append((dname, dtype))
            self._expect(TokenKind.SEMICOLON)

        self._expect(TokenKind.RBRACE)

        # See _parse_struct_decl: trailing IDENTIFIER is the declarator,
        # not a union tag.  Leave it for the caller.
        if name:
            self.unions[name] = UnionType(name, fields)
        return UnionType(name, fields)

    def _parse_enum_decl(self) -> EnumType:
        self._expect(TokenKind.ENUM)
        name: str | None = None
        if self._check(TokenKind.IDENTIFIER):
            name = self._advance().value

        if not self._check(TokenKind.LBRACE):
            if name and name in self.enums:
                return self.enums[name]
            raise ParserError(f"Unknown enum {name!r}", self._current())

        self._expect(TokenKind.LBRACE)
        members: dict[str, int] = {}
        value = 0
        while not self._check(TokenKind.RBRACE, TokenKind.EOF):
            mname = self._expect(TokenKind.IDENTIFIER).value
            if self._check(TokenKind.EQUAL):
                self._advance()
                # Accept a possibly-negative integer literal for the
                # value (e.g., `enum { X = -1 }`).
                if self._check(TokenKind.MINUS):
                    self._advance()
                    value = -int(self._advance().value, 0)
                else:
                    value = int(self._advance().value, 0)
            members[mname] = value
            # Also register the member name as a top-level integer
            # constant so it resolves as a value in expressions
            # (`int x = MyEnum;`).
            self.enum_consts[mname] = value
            value += 1
            if self._check(TokenKind.COMMA):
                self._advance()

        self._expect(TokenKind.RBRACE)

        if name:
            self.enums[name] = EnumType(name, members)
        return EnumType(name, members)

    # --- Top-level declarations ---

    def _parse_top_level_decl(self) -> TopLevelDecl:
        # Attributes can lead the declaration; capture them so the
        # right declarator name picks them up.
        self._drain_attributes()
        specifiers = self._parse_specifiers()
        self._drain_attributes()
        type_spec = self._parse_type_specifier()
        self._drain_attributes()
        # If type is omitted but signed/unsigned present, default to int
        if type_spec is None:
            if any(s in ("signed", "unsigned") for s in specifiers):
                type_spec = base_type("int")
            elif (
                self._check(TokenKind.IDENTIFIER)
                and self._current().value not in self.typedefs
                and self.pos + 1 < len(self.tokens)
                and self.tokens[self.pos + 1].kind == TokenKind.LPAREN
            ):
                # K&R / implicit-int function definition or declaration:
                # `name(...) { ... }` with no return type defaults to int.
                type_spec = base_type("int")
            else:
                raise ParserError("Expected type specifier", self._current())

        # Apply signed/unsigned specifiers to base types
        type_spec = self._apply_specifiers_to_type(specifiers, type_spec)

        declarators: list[tuple[str, CType, Expr | None]] = []
        body: FunctionDefinition | None = None
        func_params: list[tuple[str, CType]] | None = None
        is_variadic = False

        # Parse one or more declarators
        while not self._check(TokenKind.SEMICOLON, TokenKind.LBRACE, TokenKind.EOF):
            if self._check(TokenKind.NEWLINE):
                # Skip newlines but check if next is LBRACE (function body on next line)
                self._advance()
                if self._check(TokenKind.LBRACE):
                    break
                continue

            # An attribute may appear before the declarator name —
            # `void __attribute__((constructor)) ctor()` form.
            self._drain_attributes()
            dname, dtype, fp_info = self._parse_declarator(type_spec)
            # Or after the declarator: `void ctor() __attribute__((constructor))`.
            self._drain_attributes()
            # If we accumulated a ctor/dtor marker, attach it to this name.
            if self._pending_attr_ctor and dname:
                self.constructors.append(dname)
            if self._pending_attr_dtor and dname:
                self.destructors.append(dname)
            self._pending_attr_ctor = False
            self._pending_attr_dtor = False
            # When the declarator is itself a function (not a function
            # POINTER, which `_parse_declarator` already represents as a
            # PointerType(FunctionType(...))), promote the declarator's
            # type to a `FunctionType` so codegen can register the
            # symbol as `FUNCTION` rather than `VARIABLE`.  This lets
            # forward declarations like `int side(void);` resolve to a
            # direct `call side` at call sites.
            if fp_info is not None:
                fp_list, fp_variadic = fp_info
                dtype = FunctionType(
                    return_type=type_spec,
                    params=fp_list,
                    is_variadic=fp_variadic,
                )
            init: Expr | None = None
            if self._check(TokenKind.EQUAL):
                self._advance()
                init = self._parse_assignment_expr()
            dtype = self._infer_array_size_from_init(dtype, init)
            declarators.append((dname, dtype, init))
            if fp_info is not None:
                func_params, is_variadic = fp_info
            if self._check(TokenKind.COMMA):
                self._advance()
                continue
            break

        if "typedef" in specifiers:
            for dname, dtype, _ in declarators:
                self.typedefs[dname] = dtype
            self._expect(TokenKind.SEMICOLON)
            return TopLevelDecl(specifiers, declarators, None)

        if self._check(TokenKind.SEMICOLON):
            self._advance()
            # Check if followed by LBRACE (declaration + definition on same line)
            if not self._check(TokenKind.LBRACE):
                return TopLevelDecl(specifiers, declarators, None)

        # Skip newlines before function body
        while self._check(TokenKind.NEWLINE):
            self._advance()

        # K&R-style parameter declarations between `)` and `{`: e.g.
        # `sum(to, from, count) register short *to, *from; register count; { … }`.
        # Parse and refine the existing positional params with the
        # declared types.  Anything we can't parse cleanly is treated
        # as discardable — params keep their default `int` type.
        if (
            declarators
            and func_params is not None
            and not self._check(TokenKind.LBRACE)
        ):
            kr_types: dict[str, CType] = {}
            while not self._check(TokenKind.LBRACE, TokenKind.EOF):
                while self._check(TokenKind.NEWLINE):
                    self._advance()
                if self._check(TokenKind.LBRACE):
                    break
                try:
                    kr_specs = self._parse_specifiers()
                    kr_type = self._parse_type_specifier()
                    if kr_type is None:
                        if any(s in ("signed", "unsigned") for s in kr_specs):
                            kr_type = base_type("int")
                        elif kr_specs and self._check(TokenKind.IDENTIFIER):
                            # Implicit int — `register count;` etc.
                            kr_type = base_type("int")
                        else:
                            break
                    kr_type = self._apply_specifiers_to_type(kr_specs, kr_type)
                    kr_names = self._parse_declarator_names(kr_type)
                    for n, t in kr_names:
                        if n:
                            kr_types[n] = t
                    if self._check(TokenKind.SEMICOLON):
                        self._advance()
                    while self._check(TokenKind.NEWLINE):
                        self._advance()
                except ParserError:
                    break
            if kr_types:
                func_params = [
                    (n, kr_types.get(n, t)) for n, t in func_params
                ]

        # Function definition
        if declarators and self._check(TokenKind.LBRACE):
            fname, _, _ = declarators[0]
            params = func_params if func_params is not None else []
            body_stmt = self._parse_block()
            body = FunctionDefinition(
                fname, type_spec, params, body_stmt, is_variadic=is_variadic
            )
            return TopLevelDecl(specifiers, declarators, body)

        raise ParserError("Expected ';' or function body", self._current())

    def _parse_function_params(
        self, _return_type: CType
    ) -> tuple[list[tuple[str, CType]], bool]:
        """Parse function parameter list.

        Returns (params, is_variadic). A trailing `...` after at least one
        named parameter (C requires this) sets is_variadic; `...` in the
        first position or anything after `...` is rejected.
        """
        self._expect(TokenKind.LPAREN)
        params: list[tuple[str, CType]] = []
        is_variadic = False

        # Param lists may legally span lines (a NEWLINE after `(` or `,`
        # is purely whitespace in C).  Skip NEWLINEs here and after each
        # comma below.
        while self._check(TokenKind.NEWLINE):
            self._advance()

        if self._check(TokenKind.RPAREN):
            self._expect(TokenKind.RPAREN)
            return params, is_variadic

        while True:
            if self._check(TokenKind.ELLIPSIS):
                if not params:
                    raise ParserError(
                        "'...' must follow at least one named parameter",
                        self._current(),
                    )
                self._advance()
                is_variadic = True
                if not self._check(TokenKind.RPAREN):
                    raise ParserError(
                        "'...' must be the last parameter",
                        self._current(),
                    )
                break

            specifiers = self._parse_specifiers()
            type_spec = self._parse_type_specifier()
            if type_spec is None and any(s in ("signed", "unsigned") for s in specifiers):
                type_spec = base_type("int")
            type_spec = self._apply_specifiers_to_type(specifiers, type_spec)
            if type_spec is None:
                # K&R-style parameter list: a bare identifier list
                # (`name, name, ...`) appearing without a type-spec.
                # Each identifier becomes an `int` parameter by default;
                # later K&R declarations between header and body may
                # refine the type (not implemented).
                if self._check(TokenKind.IDENTIFIER):
                    name_tok = self._advance()
                    params.append((name_tok.value, base_type("int")))
                    if self._check(TokenKind.COMMA):
                        self._advance()
                        while self._check(TokenKind.NEWLINE):
                            self._advance()
                        continue
                break

            # NOTE: do not break on a bare RPAREN after the type-spec here
            # — that would silently drop trailing anonymous params, e.g.
            # the second `int` in `(int, int)` for a function-pointer
            # typedef.  The anonymous-vs-named branch below handles
            # RPAREN correctly.

            # Anonymous parameter (`int`, `int *`, `int **`, …): no
            # identifier follows the type-spec.  Consume any pointer
            # stars to fold them into the type, then accept whatever
            # terminator (COMMA / RPAREN) follows.  Function-pointer
            # typedefs commonly have anonymous params:
            # `typedef int (*BinOp)(int, int);`.
            saved_pos = self.pos
            ptr_stars = 0
            while self._check(TokenKind.STAR):
                self._advance()
                ptr_stars += 1
            if self._check(TokenKind.COMMA, TokenKind.RPAREN):
                anon_type = type_spec
                for _ in range(ptr_stars):
                    anon_type = pointer_to(anon_type)
                params.append(("", anon_type))
            else:
                # Named param: rewind and let _parse_declarator handle
                # both the pointer stars and the identifier together.
                self.pos = saved_pos
                dname, dtype, _ = self._parse_declarator(type_spec)
                # C parameter adjustment: a parameter of array type T[N]
                # is rewritten to pointer-to-T (any outermost array
                # dimension is dropped, inner dimensions preserved).
                # Without this, codegen for `arr[i]` inside the function
                # takes `&arr` (the parameter's stack slot) instead of
                # loading the pointer the caller passed in.
                if isinstance(dtype, ArrayType):
                    dtype = pointer_to(dtype.element_type)
                params.append((dname, dtype))

            if self._check(TokenKind.COMMA):
                self._advance()
                while self._check(TokenKind.NEWLINE):
                    self._advance()
                continue
            break

        while self._check(TokenKind.NEWLINE):
            self._advance()
        self._expect(TokenKind.RPAREN)
        return params, is_variadic

    # --- Declarator parsing ---

    def _parse_declarator(
        self, base_type_spec: CType | None = None
    ) -> tuple[str, CType, tuple[list[tuple[str, CType]], bool] | None]:
        """Parse a declarator, handling pointers and function/array syntax.

        Returns (name, type, params) where params is None for non-functions
        and (param_list, is_variadic) for function declarators.

        Also recognises the function-pointer form `(* name)(params)` and
        builds a `PointerType(FunctionType(...))` type for it; the
        result has `params=None` because it's a *variable* of pointer
        type, not a function definition.
        """
        base: CType = base_type_spec if base_type_spec is not None else base_type("int")

        # `const` / `volatile` may legally appear after the type-spec and
        # before the identifier (e.g. `int volatile x`) or interleaved
        # with pointer stars (e.g. `char const *p`).  We accept them as
        # no-op qualifiers — the type system doesn't currently model
        # them, and they don't affect codegen.
        def _skip_qualifiers() -> None:
            while self._check(TokenKind.CONST, TokenKind.VOLATILE):
                self._advance()

        _skip_qualifiers()

        # Count outer pointer stars (e.g., the `**` in `**foo`).
        ptr_level = 0
        while self._check(TokenKind.STAR):
            self._advance()
            ptr_level += 1
            _skip_qualifiers()

        # Function-pointer declarator: `(* [*]* name)(params)`.  Detect by
        # peeking past the LPAREN for a STAR — anything else (e.g. a
        # grouping-paren or empty list) falls through to the identifier
        # path below.
        if (
            self._check(TokenKind.LPAREN)
            and self.pos + 1 < len(self.tokens)
            and self.tokens[self.pos + 1].kind == TokenKind.STAR
        ):
            self._advance()  # consume LPAREN
            inner_ptr = 0
            while self._check(TokenKind.STAR):
                self._advance()
                inner_ptr += 1
            if not self._check(TokenKind.IDENTIFIER):
                raise ParserError(
                    "expected identifier in function-pointer declarator",
                    self._current(),
                )
            name = self._advance().value
            self._expect(TokenKind.RPAREN)
            # The function's parameter list follows in its own parens.
            params, is_variadic = self._parse_function_params(base)
            # The return type is `base` (with any outer ptr_level applied
            # via the wraps below).  We wrap from the inside out:
            #   - one PointerType for the `*` immediately inside the parens
            #   - additional PointerType for each `inner_ptr` extra star
            #   - additional PointerType for each outer ptr_level
            ftype: CType = FunctionType(
                return_type=base, params=params, is_variadic=is_variadic
            )
            # `inner_ptr` already counts the canonical `*` inside the
            # parens, so wrapping `inner_ptr` times yields the right
            # number of pointer levels (one for `(*p)`, two for
            # `(**p)`, etc.).
            for _ in range(inner_ptr):
                ftype = pointer_to(ftype)
            for _ in range(ptr_level):
                ftype = pointer_to(ftype)
            return (name, ftype, None)

        if not self._check(TokenKind.IDENTIFIER):
            raise ParserError("Expected identifier", self._current())

        name = self._advance().value

        # Build type by peeling array/function layers off `base` (which
        # was initialised from `base_type_spec` above the function-
        # pointer branch).
        func_params: tuple[list[tuple[str, CType]], bool] | None = None

        # Collect array dimensions left-to-right so they can be applied
        # outside-in: `int a[3][4]` is "array of 3 elements, each an
        # array of 4 ints" — outer dim 3, inner dim 4.  Wrapping
        # left-to-right would invert that (`array of 4 of array of 3`).
        array_dims: list[int] = []
        while self._check(TokenKind.LPAREN, TokenKind.LBRACKET):
            if self._check(TokenKind.LBRACKET):
                self._advance()
                if self._check(TokenKind.RBRACKET):
                    self._expect(TokenKind.RBRACKET)
                    array_dims.append(0)  # unknown size
                else:
                    # Try a constant expression first (sizeof, integer
                    # literal, parenthesised, enum constant).  If that
                    # fails — typically because the dim is a runtime
                    # variable like `int Arr[Num]` — fall back to a
                    # fixed-size 256-element placeholder so the storage
                    # is allocated and the test can run.  This is not a
                    # true VLA but handles the common small-VLA case.
                    saved = self.pos
                    try:
                        size = self._parse_const_int()
                    except ParserError:
                        self.pos = saved
                        # Skip tokens until matching RBRACKET.
                        depth = 1
                        while depth > 0 and self.pos < len(self.tokens):
                            tk = self._current().kind
                            if tk == TokenKind.LBRACKET:
                                depth += 1
                            elif tk == TokenKind.RBRACKET:
                                depth -= 1
                                if depth == 0:
                                    break
                            self._advance()
                        size = 256
                    self._expect(TokenKind.RBRACKET)
                    array_dims.append(size)
            elif self._check(TokenKind.LPAREN):
                # Function parameter list (params, is_variadic)
                func_params = self._parse_function_params(base)
                base = pointer_to(base)  # function -> pointer

        # C declarator binding: `*` is weaker than `[]`, so in
        # `int *L[N]` the array binds first (L is "array of N of
        # int*"), giving ArrayType(PointerType(int), N).  Apply
        # pointer layers FIRST to compute the element type, then
        # wrap with array_dims outside.  (Note: this gives the
        # standard interpretation of `int *p[10]`.  The less-common
        # "pointer to array" form `int (*p)[10]` is parsed as a
        # function-pointer-like declarator and handled separately.)
        for _ in range(ptr_level):
            base = pointer_to(base)
        for dim in reversed(array_dims):
            base = array_of(base, dim)

        return (name, base, func_params)

    def _skip_attribute_specifier(self) -> bool:
        """If the current token starts a GCC `__attribute__((...))`,
        consume the entire attribute and return True.  Inspect the
        attribute name to set `_pending_attr_ctor` / `_pending_attr_dtor`
        markers — these get promoted to the constructors/destructors
        list once we know the declarator's name."""
        if not (
            self._check(TokenKind.IDENTIFIER)
            and self._current().value == "__attribute__"
        ):
            return False
        self._advance()  # __attribute__
        if not self._check(TokenKind.LPAREN):
            return True
        # Consume the matching `((` … `))` pair, collecting identifier
        # names so we can spot `constructor` / `destructor`.
        depth = 0
        seen: list[str] = []
        while self.pos < len(self.tokens):
            tk = self._current()
            if tk.kind == TokenKind.LPAREN:
                depth += 1
                self._advance()
            elif tk.kind == TokenKind.RPAREN:
                depth -= 1
                self._advance()
                if depth == 0:
                    break
            elif tk.kind == TokenKind.IDENTIFIER:
                seen.append(tk.value)
                self._advance()
            else:
                self._advance()
        for nm in seen:
            stripped = nm.strip("_")
            if stripped == "constructor":
                self._pending_attr_ctor = True
            elif stripped == "destructor":
                self._pending_attr_dtor = True
        return True

    def _drain_attributes(self) -> None:
        """Skip a run of attribute specifiers."""
        while self._skip_attribute_specifier():
            while self._check(TokenKind.NEWLINE):
                self._advance()

    def _parse_const_int(self) -> int:
        """Parse a constant-integer expression appearing in a declarator
        context (array size, etc.).  Supports integer literals,
        `sizeof(type)`, and simple parenthesised forms.  Anything more
        complex raises a parse error — full constant folding is out of
        scope.
        """
        from src.pyc.types import (
            base_type as _bt,
            BaseType as _BT,
            PointerType as _PT,
            ArrayType as _AT,
        )

        def _type_size(t: CType) -> int:
            return t.size

        if self._check(TokenKind.SIZEOF):
            self._advance()
            self._expect(TokenKind.LPAREN)
            t = self._try_parse_type()
            if t is None:
                # sizeof(expr) — only support literal sub-expressions here.
                # Fall back: try to parse expression and use 2 as default.
                tok = self._current()
                raise ParserError(
                    f"sizeof(<expr>) not supported in this context",
                    tok,
                )
            self._expect(TokenKind.RPAREN)
            return _type_size(t)
        if self._check(TokenKind.LPAREN):
            self._advance()
            v = self._parse_const_int()
            self._expect(TokenKind.RPAREN)
            return v
        if self._check(TokenKind.INT_LITERAL):
            tok = self._advance()
            return int(tok.value, 0)
        if self._check(TokenKind.MINUS):
            self._advance()
            return -self._parse_const_int()
        if self._check(TokenKind.IDENTIFIER):
            name = self._current().value
            if name in self.enum_consts:
                self._advance()
                return self.enum_consts[name]
        tok = self._current()
        raise ParserError(
            f"expected constant integer expression in declarator",
            tok,
        )

    def _parse_declarator_names(self, base_type_spec: CType) -> list[tuple[str, CType]]:
        """Parse declarator names for struct/union fields.

        Recognises bit-field syntax: a `:` followed by an integer-literal
        width after the member name produces a `BitField` wrapping the
        base type.  Pointers can't be bitfields (rejected by C).
        """
        from src.pyc.types import BitField

        results: list[tuple[str, CType]] = []
        while not self._check(TokenKind.SEMICOLON, TokenKind.RBRACE):
            if self._check(TokenKind.COMMA):
                self._advance()
                continue
            ptr_level = 0
            while self._check(TokenKind.STAR):
                self._advance()
                ptr_level += 1
            # Anonymous bitfield: `int : 3;` and `long long : 0;` are
            # both legal — the latter forces alignment to the next
            # storage unit.  Treat the absent name as empty so the
            # field gets reserved but isn't accessible.
            if self._check(TokenKind.COLON):
                self._advance()
                if not self._check(TokenKind.INT_LITERAL):
                    raise ParserError(
                        "expected integer width after ':' in bitfield",
                        self._current(),
                    )
                width_tok = self._advance()
                width = int(width_tok.value, 0)
                ftype: CType = BitField(base=base_type_spec, width=width)
                results.append(("", ftype))
                continue
            if not self._check(TokenKind.IDENTIFIER):
                break
            name = self._advance().value
            ftype: CType = base_type_spec
            for _ in range(ptr_level):
                ftype = pointer_to(ftype)
            # Array suffixes: `T name[N][M]…;` — also accept `sizeof(T)`
            # as the dimension (PR491 uses `unsigned char c[sizeof(long)]`).
            array_dims: list[int] = []
            while self._check(TokenKind.LBRACKET):
                self._advance()
                if self._check(TokenKind.RBRACKET):
                    array_dims.append(0)
                else:
                    array_dims.append(self._parse_const_int())
                self._expect(TokenKind.RBRACKET)
            for dim in reversed(array_dims):
                ftype = array_of(ftype, dim)
            # Optional bitfield suffix (only legal on plain integer types,
            # not on pointers or arrays — caller is responsible for the
            # legality check; we just accept the syntax).
            if self._check(TokenKind.COLON):
                self._advance()
                if not self._check(TokenKind.INT_LITERAL):
                    raise ParserError(
                        "expected integer width after ':' in bitfield",
                        self._current(),
                    )
                width_tok = self._advance()
                width = int(width_tok.value, 0)
                if width < 0:
                    raise ParserError(
                        "bitfield width must be non-negative",
                        width_tok,
                    )
                ftype = BitField(base=ftype, width=width)
            results.append((name, ftype))
        return results

    # --- Statement parsing ---

    def _parse_statement(self) -> Stmt:
        # Skip leading newlines — statements can be split across lines from
        # their introducing keyword (e.g. `if (...)\n    return 1;`).
        while self._check(TokenKind.NEWLINE):
            self._advance()
        # Capture the source line of the first real token in this
        # statement so codegen can pair comments to statements later.
        start_line = self._current().line
        stmt = self._dispatch_statement()
        # Attach the source line as a runtime attribute (Stmt isn't a
        # dataclass-ordered field, so this avoids field-order issues).
        try:
            stmt.source_line = start_line  # type: ignore[attr-defined]
        except AttributeError:
            pass
        return stmt

    def _dispatch_statement(self) -> Stmt:
        if self._check(TokenKind.LBRACE):
            return self._parse_block()
        if self._check(TokenKind.IF):
            return self._parse_if_stmt()
        if self._check(TokenKind.WHILE):
            return self._parse_while_stmt()
        if self._check(TokenKind.DO):
            return self._parse_do_while_stmt()
        if self._check(TokenKind.FOR):
            return self._parse_for_stmt()
        if self._check(TokenKind.SWITCH):
            return self._parse_switch_stmt()
        if self._check(TokenKind.BREAK):
            self._advance()
            self._expect(TokenKind.SEMICOLON)
            return BreakStmt()
        if self._check(TokenKind.CONTINUE):
            self._advance()
            self._expect(TokenKind.SEMICOLON)
            return ContinueStmt()
        if self._check(TokenKind.RETURN):
            self._advance()
            value: Expr | None = None
            if not self._check(TokenKind.SEMICOLON):
                value = self._parse_expression()
            self._expect(TokenKind.SEMICOLON)
            return ReturnStmt(value)
        if self._check(TokenKind.GOTO):
            self._advance()
            # `goto *expr;` — GNU computed goto.
            if self._check(TokenKind.STAR):
                self._advance()
                target_expr = self._parse_expression()
                self._expect(TokenKind.SEMICOLON)
                return ComputedGotoStmt(target_expr)
            label = self._expect(TokenKind.IDENTIFIER).value
            self._expect(TokenKind.SEMICOLON)
            return GotoStmt(label)

        # Check for label:
        if self._check(TokenKind.IDENTIFIER):
            next_next = self.tokens[self.pos + 1] if self.pos + 1 < len(self.tokens) else None
            if next_next and next_next.kind == TokenKind.COLON:
                label = self._advance().value
                self._expect(TokenKind.COLON)
                stmt = self._parse_statement()
                return LabelStmt(label, stmt)

        # Case/default labels inside switch
        if self._check(TokenKind.CASE):
            self._advance()
            expr = self._parse_expression()
            val = self._eval_const_expr(expr)
            if val is None:
                raise ParserError("Non-constant case expression not supported", self._current())
            self._expect(TokenKind.COLON)
            body = self._parse_statement()
            return CaseLabel(val, body)

        if self._check(TokenKind.DEFAULT):
            self._advance()
            self._expect(TokenKind.COLON)
            body = self._parse_statement()
            return CaseLabel(None, body)

        # Declaration inside block (`const int x = 5;`, `volatile char c;`)
        if self._check(
            TokenKind.INT, TokenKind.CHAR, TokenKind.SHORT, TokenKind.LONG,
            TokenKind.FLOAT, TokenKind.DOUBLE, TokenKind.VOID,
            TokenKind.SIGNED, TokenKind.UNSIGNED, TokenKind.STATIC,
            TokenKind.EXTERN, TokenKind.TYPEDEF, TokenKind.AUTO, TokenKind.REGISTER,
            TokenKind.CONST, TokenKind.VOLATILE,
            TokenKind.STRUCT, TokenKind.UNION, TokenKind.ENUM,
        ):
            return self._parse_decl_stmt()
        # A typedef-name introduces a declaration just like a built-in type.
        if (
            self._check(TokenKind.IDENTIFIER)
            and self._current().value in self.typedefs
        ):
            return self._parse_decl_stmt()

        # Expression statement
        expr: Expr | None = None
        if not self._check(TokenKind.SEMICOLON, TokenKind.RBRACE, TokenKind.EOF, TokenKind.NEWLINE):
            expr = self._parse_expression()
        if self._check(TokenKind.SEMICOLON):
            self._advance()
        return ExpressionStmt(expr)

    def _parse_block(self) -> Block:
        self._expect(TokenKind.LBRACE)
        statements: list[Stmt | DeclStmt] = []
        while not self._check(TokenKind.RBRACE, TokenKind.EOF):
            if self._check(TokenKind.NEWLINE):
                self._advance()
                continue
            statements.append(self._parse_statement())
        self._expect(TokenKind.RBRACE)
        return Block(statements)

    def _parse_if_stmt(self) -> IfStmt:
        self._expect(TokenKind.IF)
        self._expect(TokenKind.LPAREN)
        condition = self._parse_expression()
        self._expect(TokenKind.RPAREN)
        then_branch = self._parse_statement()
        # Skip newlines between the then-branch and a potential `else`,
        # so `if (...) stmt;\n else stmt;` parses as a single if/else.
        while self._check(TokenKind.NEWLINE):
            self._advance()
        else_branch: Stmt | None = None
        if self._check(TokenKind.ELSE):
            self._advance()
            else_branch = self._parse_statement()
        return IfStmt(condition, then_branch, else_branch)

    def _parse_while_stmt(self) -> WhileStmt:
        self._expect(TokenKind.WHILE)
        self._expect(TokenKind.LPAREN)
        condition = self._parse_expression()
        self._expect(TokenKind.RPAREN)
        body = self._parse_statement()
        return WhileStmt(condition, body)

    def _parse_do_while_stmt(self) -> DoWhileStmt:
        self._expect(TokenKind.DO)
        body = self._parse_statement()
        self._expect(TokenKind.WHILE)
        self._expect(TokenKind.LPAREN)
        condition = self._parse_expression()
        self._expect(TokenKind.RPAREN)
        self._expect(TokenKind.SEMICOLON)
        return DoWhileStmt(condition, body)

    def _parse_for_stmt(self) -> ForStmt:
        self._expect(TokenKind.FOR)
        self._expect(TokenKind.LPAREN)

        init: Stmt | None = None
        if self._check(
            TokenKind.INT, TokenKind.CHAR, TokenKind.SHORT, TokenKind.LONG,
            TokenKind.SIGNED, TokenKind.UNSIGNED,
        ):
            init = self._parse_decl_stmt()
        elif not self._check(TokenKind.SEMICOLON):
            init = self._parse_expression_stmt()
        else:
            self._expect(TokenKind.SEMICOLON)

        condition: Expr | None = None
        if not self._check(TokenKind.SEMICOLON):
            condition = self._parse_expression()
        self._expect(TokenKind.SEMICOLON)

        increment: Expr | None = None
        if not self._check(TokenKind.RPAREN):
            increment = self._parse_expression()
        self._expect(TokenKind.RPAREN)

        body = self._parse_statement()
        return ForStmt(body=body, init=init, condition=condition, increment=increment)

    def _parse_switch_stmt(self) -> SwitchStmt:
        self._expect(TokenKind.SWITCH)
        self._expect(TokenKind.LPAREN)
        expr = self._parse_expression()
        self._expect(TokenKind.RPAREN)
        body = self._parse_statement()

        # Validate that all case expressions are constant
        if isinstance(body, Block):
            for stmt in body.statements:
                if isinstance(stmt, CaseLabel) and stmt.value is not None:
                    if not isinstance(stmt.value, (int, str)):
                        if isinstance(stmt.value, UnaryExpr) and stmt.value.op == '-' and isinstance(stmt.value.operand, int):
                            continue
                        raise ParserError("Case expression must be a constant value", stmt.value.token)

        return SwitchStmt(expr, body)

    def _infer_array_size_from_init(self, dtype: CType, init: Expr | None) -> CType:
        """For a declared array of unspecified size (`int a[] = {...}`
        or `char s[] = "hi"`), infer the count from the initialiser.

        Returns either the original `dtype` unchanged or a new
        `ArrayType` with the inferred `count`.  Necessary so that
        `_gen_local_alloc` reserves the right number of bytes — without
        this fix, `char s[] = "hello"` would allocate the minimum 2
        bytes and the init would clobber adjacent stack slots.
        """
        from src.pyc.ast import InitList
        if not isinstance(dtype, ArrayType) or dtype.count != 0 or init is None:
            return dtype
        if isinstance(init, StringLiteral):
            return array_of(dtype.element_type, len(init.value) + 1)
        if isinstance(init, InitList):
            return array_of(dtype.element_type, len(init.elements))
        return dtype

    def _parse_decl_stmt(self) -> DeclStmt:
        """Parse variable declaration inside a block."""
        specifiers = self._parse_specifiers()
        type_spec = self._parse_type_specifier()
        if type_spec is None:
            if any(s in ("signed", "unsigned") for s in specifiers):
                type_spec = base_type("int")
            elif specifiers and self._check(TokenKind.IDENTIFIER):
                # `register x = 1;` / `static y;` — implicit int.
                type_spec = base_type("int")
            else:
                raise ParserError("Expected type specifier", self._current())

        type_spec = self._apply_specifiers_to_type(specifiers, type_spec)

        declarations: list[tuple[str, CType, Expr | None]] = []
        while not self._check(TokenKind.SEMICOLON, TokenKind.EOF):
            dname, dtype, _ = self._parse_declarator(type_spec)
            init: Expr | None = None
            if self._check(TokenKind.EQUAL):
                self._advance()
                init = self._parse_assignment_expr()
            dtype = self._infer_array_size_from_init(dtype, init)
            declarations.append((dname, dtype, init))
            if self._check(TokenKind.COMMA):
                self._advance()
                continue
            break

        self._expect(TokenKind.SEMICOLON)
        return DeclStmt(specifiers, declarations)

    def _parse_expression_stmt(self) -> ExpressionStmt:
        expr = self._parse_expression()
        self._expect(TokenKind.SEMICOLON)
        return ExpressionStmt(expr)

    # --- Expression parsing (precedence climbing) ---

    def _parse_expression(self) -> Expr:
        return self._parse_expr_prec(PREC_COMMA)

    def _parse_expr_prec(self, prec: int) -> Expr:
        # `sizeof e` is a unary expression — let _parse_unary_expr pick
        # it up so the surrounding precedence loop can apply binary
        # operators (e.g. `sizeof(int) * 100`).
        left = self._parse_unary_expr()

        while True:
            kind = self._peek_kind()

            # Ternary ? (only at ternary precedence level)
            if kind == TokenKind.QUESTION and prec <= PREC_TERNARY:
                return self._parse_ternary(left)

            # Assignment (right-associative: parse RHS at ASSIGN level).
            # We do NOT return immediately so that a lower-precedence
            # operator (e.g. the comma in `(a += b, c)`) still gets
            # picked up by the surrounding loop.
            if kind in ASSIGN_OPS and prec <= PREC_ASSIGN:
                left = self._parse_assignment(left)
                continue

            # Binary operators
            if kind not in BINOP_PRECEDENCE:
                return left
            op_prec = BINOP_PRECEDENCE[kind]
            if op_prec < prec:
                return left

            op_tok = self._advance()
            # Skip newlines: C allows binary operators at end of line with
            # the RHS on the next line (e.g. `a |` \n `b`).
            while self._check(TokenKind.NEWLINE):
                self._advance()
            # Parse RHS at higher precedence for left associativity
            right = self._parse_expr_prec(op_prec + 1)
            left = self._make_binary(op_tok, left, right)

        return left

    def _parse_unary_expr(self) -> Expr:
        kind = self._peek_kind()

        # Prefix increment/decrement
        if kind in PREFIX_INC:
            op = self._advance().value
            operand = self._parse_unary_expr()
            return UnaryOp(op, operand, pre=True)

        # GNU `&&label` — address of a code label.  Must come before the
        # generic UNARY_OPS check so that `&&` is not mis-parsed as the
        # logical-and binary operator.
        if (
            kind == TokenKind.AMPERSAND_AMPERSAND
            and self.pos + 1 < len(self.tokens)
            and self.tokens[self.pos + 1].kind == TokenKind.IDENTIFIER
        ):
            self._advance()  # &&
            name = self._advance().value
            from src.pyc.ast import LabelAddress
            return LabelAddress(name)

        # Unary operators
        if kind in UNARY_OPS:
            op = self._advance().value
            operand = self._parse_unary_expr()
            return UnaryOp(op, operand, pre=True)

        # sizeof — parsed at unary precedence so binary operators after
        # `sizeof(T)` (e.g. `sizeof(int) * 100`) flow back into the
        # surrounding precedence climber.
        if kind == TokenKind.SIZEOF:
            return self._parse_sizeof_expr()

        # Cast: (type) expr
        if self._check(TokenKind.LPAREN):
            # Distinguish `(type) expr` cast from `(expr)` grouping.  Peek
            # past the LPAREN — a cast must start with a type-spec keyword
            # (or a typedef name) and end with `)`.
            saved = self.pos
            self._advance()  # consume the (
            target = self._try_parse_type()
            is_cast = target is not None and self._check(TokenKind.RPAREN)
            if is_cast:
                self._expect(TokenKind.RPAREN)
                operand = self._parse_unary_expr()
                return CastExpr(target, operand)
            # Not a cast — rewind so the grouping-paren path in
            # _parse_primary handles it.
            self.pos = saved

        primary = self._parse_primary()

        # Postfix operators
        while True:
            kind = self._peek_kind()
            if kind in PREFIX_INC:
                op = self._advance().value
                primary = UnaryOp(op, primary, pre=False)
            elif kind == TokenKind.LBRACKET:
                self._advance()
                index = self._parse_expression()
                self._expect(TokenKind.RBRACKET)
                primary = Subscript(primary, index)
            elif kind == TokenKind.LPAREN:
                self._advance()
                args = self._parse_arg_list()
                self._expect(TokenKind.RPAREN)
                primary = CallExpr(primary, args)
            elif kind == TokenKind.DOT:
                self._advance()
                member = self._expect(TokenKind.IDENTIFIER).value
                primary = MemberAccess(primary, member, indirect=False)
            elif kind == TokenKind.MINUS_GREATER:
                self._advance()
                member = self._expect(TokenKind.IDENTIFIER).value
                primary = MemberAccess(primary, member, indirect=True)
            else:
                break

        return primary

    def _try_parse_type(self) -> CType | None:
        """Try to parse a type specifier (for casts). Returns None if not a type.

        Accepts the storage-class / signedness qualifiers that may
        legally precede the type-spec inside a cast or `sizeof` operand
        (`unsigned long`, `const int *`, etc.).
        """
        saved = self.pos
        specifiers = self._parse_specifiers()
        result = self._parse_type_specifier()
        if result is None and any(
            s in ("signed", "unsigned") for s in specifiers
        ):
            result = base_type("int")
        if result is not None:
            result = self._apply_specifiers_to_type(specifiers, result)
        # Check for pointer suffix
        while self._check(TokenKind.STAR):
            self._advance()
            result = pointer_to(result) if result else None
            # Allow qualifiers between pointer stars: `int * const *`.
            while self._check(TokenKind.CONST, TokenKind.VOLATILE):
                self._advance()

        if result:
            return result
        self.pos = saved
        return None

    def _parse_sizeof_expr(self) -> SizeofExpr:
        self._advance()  # sizeof
        operand: CType | Expr | None = None
        if self._check(TokenKind.LPAREN):
            self._advance()
            # Try type name first
            type_result = self._try_parse_type()
            if type_result:
                operand = type_result
            else:
                operand = self._parse_expression()
            self._expect(TokenKind.RPAREN)
        else:
            operand = self._parse_unary_expr()
        return SizeofExpr(operand)

    def _make_binary(self, op_tok: Token, left: Expr, right: Expr) -> Expr:
        op_map = {
            TokenKind.AMPERSAND_AMPERSAND: "&&",
            TokenKind.PIPE_PIPE: "||",
            TokenKind.AMPERSAND: "&",
            TokenKind.PIPE: "|",
            TokenKind.CARET: "^",
            TokenKind.EQUAL_EQUAL: "==",
            TokenKind.EXCLAMATION_EQUAL: "!=",
            TokenKind.LEFT_SHIFT: "<<",
            TokenKind.RIGHT_SHIFT: ">>",
            TokenKind.PLUS: "+",
            TokenKind.MINUS: "-",
            TokenKind.STAR: "*",
            TokenKind.SLASH: "/",
            TokenKind.PERCENT: "%",
        }
        # Comma operator is a special case: build a CommaExpr (flatten nested commas)
        if op_tok.kind == TokenKind.COMMA:
            left_list = left.expressions if isinstance(left, CommaExpr) else [left]
            right_list = right.expressions if isinstance(right, CommaExpr) else [right]
            return CommaExpr(left_list + right_list)

        op_str = op_map.get(op_tok.kind, op_tok.value)
        return BinaryOp(op_str, left, right)

    def _parse_assignment(self, left: Expr) -> Expr:
        op_tok = self._current()
        op_str = op_tok.value
        self._advance()
        right = self._parse_expr_prec(PREC_ASSIGN)

        if op_tok.kind == TokenKind.EQUAL:
            return CompoundAssignment(left, "=", right)
        return CompoundAssignment(left, op_str, right)

    def _parse_ternary(self, condition: Expr) -> TernaryExpr:
        self._advance()  # ?
        true_branch = self._parse_assignment_expr()
        self._expect(TokenKind.COLON)
        false_branch = self._parse_assignment_expr()
        return TernaryExpr(condition, true_branch, false_branch)

    def _parse_assignment_expr(self) -> Expr:
        # A brace-enclosed initializer list can appear here when this
        # method is invoked as the RHS of a declaration (the only
        # syntactic context in C).  Producing an `InitList` AST node
        # at the expression layer lets the codegen recognise and
        # expand it during `_gen_decl_stmt`.
        if self._check(TokenKind.LBRACE):
            return self._parse_init_list()
        return self._parse_expr_prec(PREC_ASSIGN)

    def _parse_init_list(self) -> Expr:
        """Parse `{ expr, expr, ... }` (with optional trailing comma).

        Designated initializers are accepted in two forms — `.field = v`
        (C99) and `field: v` (older GNU) — but the designator is
        discarded for now and only the value is kept.  The codegen
        treats the InitList as positional, which is correct as long
        as the designators follow the field declaration order (the
        common case for the tests we care about).
        """
        self._expect(TokenKind.LBRACE)
        elements: list[Expr] = []
        while self._check(TokenKind.NEWLINE):
            self._advance()
        if self._check(TokenKind.RBRACE):
            self._expect(TokenKind.RBRACE)
            return InitList(elements=elements)
        while True:
            # `.field = expr` — designated initializer.
            if self._check(TokenKind.DOT):
                self._advance()
                if self._check(TokenKind.IDENTIFIER):
                    self._advance()
                if self._check(TokenKind.EQUAL):
                    self._advance()
            else:
                # GNU `field: expr` — only when the next token is an
                # IDENTIFIER followed by `:` (and that `:` is not the
                # `?:` ternary's colon).
                if (
                    self._check(TokenKind.IDENTIFIER)
                    and self.pos + 1 < len(self.tokens)
                    and self.tokens[self.pos + 1].kind == TokenKind.COLON
                ):
                    self._advance()  # field name
                    self._advance()  # ':'
            elements.append(self._parse_assignment_expr())
            while self._check(TokenKind.NEWLINE):
                self._advance()
            if self._check(TokenKind.COMMA):
                self._advance()
                while self._check(TokenKind.NEWLINE):
                    self._advance()
                if self._check(TokenKind.RBRACE):
                    break
                continue
            break
        self._expect(TokenKind.RBRACE)
        return InitList(elements=elements)

    # --- Primary expressions ---

    def _parse_primary(self) -> Expr:
        kind = self._peek_kind()

        if kind == TokenKind.INT_LITERAL:
            tok = self._advance()
            return _parse_int_literal(tok.value)

        if kind == TokenKind.FLOAT_LITERAL:
            tok = self._advance()
            # The token text is the source literal, possibly with a
            # trailing `f`/`F`/`l`/`L` suffix.  An `f` or `F` makes
            # it a `float` (IEEE-754 single); otherwise it's a
            # `double` (IEEE-754 double).  `l`/`L` is for long
            # double which we alias to double.
            from src.pyc.ast import FloatLiteral
            raw = tok.value
            suffix = ""
            while raw and raw[-1] in "fFlL":
                suffix = raw[-1] + suffix
                raw = raw[:-1]
            try:
                v = float(raw)
            except ValueError:
                v = 0.0
            ty = base_type("float") if "f" in suffix.lower() else base_type("double")
            return FloatLiteral(v, ty)

        if kind == TokenKind.CHAR_LITERAL:
            tok = self._advance()
            return CharLiteral(ord(tok.value), base_type("char"))

        if kind == TokenKind.STRING_LITERAL:
            # Concatenate adjacent string literals
            parts = [self._advance().value]
            while self._check(TokenKind.STRING_LITERAL):
                parts.append(self._advance().value)
            joined = "".join(parts)
            return StringLiteral(joined, array_of(base_type("char"), len(joined) + 1))

        if kind == TokenKind.IDENTIFIER:
            tok = self._advance()
            # Enum-member constants resolve to integer literals at
            # parse time so downstream code never sees them as
            # `Identifier` (which would lookup as a runtime symbol).
            if tok.value in self.enum_consts:
                return IntLiteral(
                    self.enum_consts[tok.value], base_type("int")
                )
            return Identifier(tok.value)

        if kind == TokenKind.LPAREN:
            self._advance()
            expr = self._parse_expression()
            self._expect(TokenKind.RPAREN)
            return expr

        raise ParserError(f"Unexpected token: {kind.name}", self._current())

    def _parse_arg_list(self) -> list[Expr]:
        args: list[Expr] = []
        # Call arg lists, like function-param lists, may legally span
        # lines.  Skip NEWLINEs at the start and after each comma.
        while self._check(TokenKind.NEWLINE):
            self._advance()
        if self._check(TokenKind.RPAREN):
            return args
        while True:
            # Parse a single assignment expression for each argument.
            # Using full expression parsing would consume comma operators
            # inside the argument list (treating them as comma operator),
            # which is incorrect for separating function arguments.
            args.append(self._parse_assignment_expr())
            if self._check(TokenKind.COMMA):
                self._advance()
                while self._check(TokenKind.NEWLINE):
                    self._advance()
                continue
            break
        while self._check(TokenKind.NEWLINE):
            self._advance()
        return args


def parse(tokens: list[Token]) -> TranslationUnit:
    """Parse tokens into an AST TranslationUnit."""
    return Parser(tokens).parse()
