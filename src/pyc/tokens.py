"""Token types and token dataclass for the C lexer."""

from dataclasses import dataclass
from enum import Enum, auto


class TokenKind(Enum):
    """All token kinds recognized by the lexer."""

    # --- Keywords ---
    BREAK = auto()
    CASE = auto()
    CHAR = auto()
    CONST = auto()
    CONTINUE = auto()
    DEFAULT = auto()
    DO = auto()
    DOUBLE = auto()
    ELSE = auto()
    ENUM = auto()
    EXTERN = auto()
    FLOAT = auto()
    FOR = auto()
    GOTO = auto()
    IF = auto()
    INT = auto()
    LONG = auto()
    RETURN = auto()
    SHORT = auto()
    SIGNED = auto()
    SIZEOF = auto()
    STATIC = auto()
    STRUCT = auto()
    SWITCH = auto()
    TYPEDEF = auto()
    AUTO = auto()
    REGISTER = auto()
    UNION = auto()
    UNSIGNED = auto()
    VOID = auto()
    VOLATILE = auto()
    WHILE = auto()
    LONG_LONG = auto()  # long long

    # --- Identifiers and Literals ---
    IDENTIFIER = auto()
    INT_LITERAL = auto()
    FLOAT_LITERAL = auto()
    CHAR_LITERAL = auto()
    STRING_LITERAL = auto()

    # --- Single-character operators and delimiters ---
    PLUS = auto()          # +
    MINUS = auto()         # -
    STAR = auto()          # *
    SLASH = auto()         # /
    PERCENT = auto()       # %
    AMPERSAND = auto()     # &
    PIPE = auto()          # |
    CARET = auto()         # ^
    TILDE = auto()         # ~
    BANG = auto()          # !
    QUESTION = auto()      # ?
    COLON = auto()         # :
    COMMA = auto()         # ,
    DOT = auto()           # .
    SEMICOLON = auto()     # ;
    LPAREN = auto()        # (
    RPAREN = auto()        # )
    LBRACKET = auto()      # [
    RBRACKET = auto()      # ]
    LBRACE = auto()        # {
    RBRACE = auto()        # }
    LESS = auto()          # <
    GREATER = auto()       # >
    EQUAL = auto()         # =

    # --- Multi-character operators ---
    PLUS_EQUAL = auto()       # +=
    MINUS_EQUAL = auto()      # -=
    STAR_EQUAL = auto()       # *=
    SLASH_EQUAL = auto()      # /=
    PERCENT_EQUAL = auto()    # %=
    AMPERSAND_EQUAL = auto()  # &=
    PIPE_EQUAL = auto()       # |=
    CARET_EQUAL = auto()      # ^=
    LEFT_SHIFT = auto()       # <<
    RIGHT_SHIFT = auto()      # >>
    LEFT_SHIFT_EQUAL = auto()  # <<=
    RIGHT_SHIFT_EQUAL = auto() # >>=
    PLUS_PLUS = auto()        # ++
    MINUS_MINUS = auto()      # --
    LESS_EQUAL = auto()       # <=
    GREATER_EQUAL = auto()    # >=
    EQUAL_EQUAL = auto()      # ==
    EXCLAMATION_EQUAL = auto() # !=
    AMPERSAND_AMPERSAND = auto()  # &&
    PIPE_PIPE = auto()        # ||
    MINUS_GREATER = auto()    # ->
    ELLIPSIS = auto()         # ...

    # --- Preprocessor ---
    HASH = auto()       # #
    HASH_HASH = auto()  # ##

    # --- Special ---
    EOF = auto()
    NEWLINE = auto()


KEYWORDS: dict[str, TokenKind] = {
    "break": TokenKind.BREAK,
    "case": TokenKind.CASE,
    "char": TokenKind.CHAR,
    "const": TokenKind.CONST,
    "continue": TokenKind.CONTINUE,
    "default": TokenKind.DEFAULT,
    "do": TokenKind.DO,
    "double": TokenKind.DOUBLE,
    "else": TokenKind.ELSE,
    "enum": TokenKind.ENUM,
    "extern": TokenKind.EXTERN,
    "float": TokenKind.FLOAT,
    "for": TokenKind.FOR,
    "goto": TokenKind.GOTO,
    "if": TokenKind.IF,
    "int": TokenKind.INT,
    "long": TokenKind.LONG,
    "return": TokenKind.RETURN,
    "short": TokenKind.SHORT,
    "signed": TokenKind.SIGNED,
    "sizeof": TokenKind.SIZEOF,
    "static": TokenKind.STATIC,
    "struct": TokenKind.STRUCT,
    "switch": TokenKind.SWITCH,
    "typedef": TokenKind.TYPEDEF,
    "auto": TokenKind.AUTO,
    "register": TokenKind.REGISTER,
    "union": TokenKind.UNION,
    "unsigned": TokenKind.UNSIGNED,
    "void": TokenKind.VOID,
    "volatile": TokenKind.VOLATILE,
    "while": TokenKind.WHILE,
    "long long": TokenKind.LONG_LONG,
}


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    value: str
    line: int
    column: int

    def __str__(self) -> str:
        return f"Token({self.kind.name}, {self.value!r}, L{self.line}C{self.column})"
