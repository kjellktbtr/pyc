"""Tokenizer: converts C source text into a stream of Token objects."""

from __future__ import annotations

from src.pyc.tokens import KEYWORDS, Token, TokenKind


class LexerError(Exception):
    """Error during lexical analysis."""

    def __init__(self, message: str, line: int, column: int) -> None:
        self.line = line
        self.column = column
        super().__init__(f"Lexer error at L{line}C{column}: {message}")


class Lexer:
    """Single-pass tokenizer for C source text."""

    def __init__(self, source: str) -> None:
        self.source = source
        self.pos = 0
        self.line = 1
        self.column = 1
        self.tokens: list[Token] = []
        # Captured C comments (line and text) so codegen can stitch
        # them back into the emitted .asm as `; <text>` annotations.
        self.comments: list[tuple[int, str]] = []

    def _emit(self, kind: TokenKind, value: str, line: int | None = None, col: int | None = None) -> Token:
        token = Token(kind, value, line if line is not None else self.line, col if col is not None else self.column)
        self.tokens.append(token)
        return token

    def _peek(self, offset: int = 0) -> str:
        idx = self.pos + offset
        return self.source[idx] if idx < len(self.source) else ""

    def _advance(self) -> str:
        ch = self.source[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.column = 1
        else:
            self.column += 1
        return ch

    def _skip_whitespace(self) -> None:
        while self.pos < len(self.source) and self.source[self.pos] in " \t\r":
            self._advance()

    def _skip_comment(self) -> None:
        """Skip /* ... */ style comments, tracking line numbers and
        recording the comment text in `self.comments`."""
        start_line = self.line
        self._advance()  # consume '*'
        buf: list[str] = []
        while self.pos < len(self.source):
            if self._peek() == "*" and self._peek(1) == "/":
                self._advance()
                self._advance()
                self.comments.append((start_line, "".join(buf).strip()))
                return
            buf.append(self._advance())
        raise LexerError("Unterminated comment", self.line, self.column)

    def _skip_line_comment(self) -> None:
        """Skip // ... style comments (C99 extension), recording the
        text in `self.comments` for later emission as asm `;` lines."""
        start_line = self.line
        buf: list[str] = []
        while self.pos < len(self.source) and self._peek() != "\n":
            buf.append(self._advance())
        self.comments.append((start_line, "".join(buf).strip()))

    def _read_number(self) -> None:
        """Read an integer or floating-point literal."""
        start_col = self.column
        result = ""
        is_float = False

        # Check for hex
        if self._peek() == "0" and self._peek(1) in "xX":
            result = self._advance() + self._advance()
            while self.pos < len(self.source) and self._peek() in "0123456789abcdefABCDEF":
                result += self._advance()
        # Check for binary (GNU extension)
        elif self._peek() == "0" and self._peek(1) in "bB":
            result = self._advance() + self._advance()
            while self.pos < len(self.source) and self._peek() in "01":
                result += self._advance()
        else:
            # Octal or decimal
            while self.pos < len(self.source) and self._peek() in "0123456789":
                result += self._advance()

            # Check for float suffix or decimal point
            if self._peek() == ".":
                is_float = True
                result += self._advance()
                while self.pos < len(self.source) and self._peek() in "0123456789":
                    result += self._advance()

            # Check for exponent
            if self._peek() and self._peek() in "eE":
                is_float = True
                result += self._advance()
                if self._peek() in "+-":
                    result += self._advance()
                while self.pos < len(self.source) and self._peek() in "0123456789":
                    result += self._advance()

        # Check for suffixes (u, l, f, etc.)
        while self.pos < len(self.source) and self._peek() in "uUlLfF":
            is_float = is_float or self._peek() in "fF"
            result += self._advance()

        if is_float:
            self._emit(TokenKind.FLOAT_LITERAL, result)
        else:
            self._emit(TokenKind.INT_LITERAL, result)

    def _read_string(self) -> None:
        """Read a string literal "..." with escape sequences."""
        start_col = self.column
        self._advance()  # opening "
        result = ""
        while self.pos < len(self.source) and self._peek() != '"':
            ch = self._advance()
            if ch == "\\":
                if self.pos < len(self.source):
                    esc = self._advance()
                    escape_map: dict[str, str] = {
                        "n": "\n", "r": "\r", "t": "\t",
                        "b": "\b", "f": "\f", "\\": "\\",
                        '"': '"', "'": "'", "?": "?",
                        "0": "\0", "a": "\a", "v": "\v",
                    }
                    result += escape_map.get(esc, esc)
                else:
                    result += "\\"
            else:
                result += ch

        if self.pos >= len(self.source):
            raise LexerError("Unterminated string literal", self.line, start_col)

        self._advance()  # closing "
        self._emit(TokenKind.STRING_LITERAL, result)

    def _read_char_literal(self) -> None:
        """Read a character literal '...' with escape sequences."""
        start_col = self.column
        self._advance()  # opening '
        if self.pos >= len(self.source):
            raise LexerError("Unterminated char literal", self.line, start_col)

        ch = self._peek()
        if ch == "\\":
            self._advance()
            esc_ch = self._advance()
            escape_map: dict[str, str] = {
                "n": "\n", "r": "\r", "t": "\t",
                "b": "\b", "f": "\f", "\\": "\\",
                '"': '"', "'": "'", "?": "?",
                "0": "\0", "a": "\a", "v": "\v",
            }
            esc = escape_map.get(esc_ch, esc_ch)
        else:
            self._advance()
            esc = ch

        if self.pos >= len(self.source) or self._peek() != "'":
            raise LexerError("Unterminated char literal", self.line, start_col)

        self._advance()  # closing '
        self._emit(TokenKind.CHAR_LITERAL, esc)

    def tokenize(self) -> list[Token]:
        """Tokenize the entire source and return the token list."""
        while self.pos < len(self.source):
            self._skip_whitespace()
            if self.pos >= len(self.source):
                break

            ch = self._peek()

            # Comments
            if ch == "/" and self._peek(1) == "*":
                self._skip_comment()
                continue
            if ch == "/" and self._peek(1) == "/":
                self._skip_line_comment()
                continue

            # Newlines (important for preprocessor)
            if ch == "\n":
                self._emit(TokenKind.NEWLINE, "\n")
                self._advance()
                continue

            # String literal
            if ch == '"':
                self._read_string()
                continue

            # Character literal
            if ch == "'":
                self._read_char_literal()
                continue

            # Number
            if ch.isdigit():
                self._read_number()
                continue

            # Identifier or keyword
            if ch.isalpha() or ch == "_":
                self._read_identifier()
                continue

            # Multi-character operators (longest match first)
            two_ch = self.source[self.pos: self.pos + 2]
            multi_map: dict[str, TokenKind] = {
                "+=": TokenKind.PLUS_EQUAL,
                "-=": TokenKind.MINUS_EQUAL,
                "*=": TokenKind.STAR_EQUAL,
                "/=": TokenKind.SLASH_EQUAL,
                "%=": TokenKind.PERCENT_EQUAL,
                "&=": TokenKind.AMPERSAND_EQUAL,
                "|=": TokenKind.PIPE_EQUAL,
                "^=": TokenKind.CARET_EQUAL,
                "<<": TokenKind.LEFT_SHIFT,
                ">>": TokenKind.RIGHT_SHIFT,
                "<<=": TokenKind.LEFT_SHIFT_EQUAL,
                ">>=": TokenKind.RIGHT_SHIFT_EQUAL,
                "++": TokenKind.PLUS_PLUS,
                "--": TokenKind.MINUS_MINUS,
                "<=": TokenKind.LESS_EQUAL,
                ">=": TokenKind.GREATER_EQUAL,
                "==": TokenKind.EQUAL_EQUAL,
                "!=": TokenKind.EXCLAMATION_EQUAL,
                "&&": TokenKind.AMPERSAND_AMPERSAND,
                "||": TokenKind.PIPE_PIPE,
                "->": TokenKind.MINUS_GREATER,
                "##": TokenKind.HASH_HASH,
                # Type specifier: recognize "long long" as a keyword
                "long long": TokenKind.LONG_LONG,
            }

            # Check 3-char operators first
            three_ch = self.source[self.pos: self.pos + 3]
            if three_ch == "<<=":
                self._emit(TokenKind.LEFT_SHIFT_EQUAL, "<<=")
                self.pos += 3
                self.column += 3
                continue
            if three_ch == ">>=":
                self._emit(TokenKind.RIGHT_SHIFT_EQUAL, ">>=")
                self.pos += 3
                self.column += 3
                continue
            if three_ch == "...":
                self._emit(TokenKind.ELLIPSIS, "...")
                self.pos += 3
                self.column += 3
                continue

            if two_ch in multi_map:
                self._emit(multi_map[two_ch], two_ch)
                self.pos += 2
                self.column += 2
                continue

            # Single-character operators and delimiters
            single_map: dict[str, TokenKind] = {
                "+": TokenKind.PLUS,
                "-": TokenKind.MINUS,
                "*": TokenKind.STAR,
                "/": TokenKind.SLASH,
                "%": TokenKind.PERCENT,
                "&": TokenKind.AMPERSAND,
                "|": TokenKind.PIPE,
                "^": TokenKind.CARET,
                "~": TokenKind.TILDE,
                "!": TokenKind.BANG,
                "?": TokenKind.QUESTION,
                ":": TokenKind.COLON,
                ",": TokenKind.COMMA,
                ".": TokenKind.DOT,
                ";": TokenKind.SEMICOLON,
                "(": TokenKind.LPAREN,
                ")": TokenKind.RPAREN,
                "[": TokenKind.LBRACKET,
                "]": TokenKind.RBRACKET,
                "{": TokenKind.LBRACE,
                "}": TokenKind.RBRACE,
                "<": TokenKind.LESS,
                ">": TokenKind.GREATER,
                "#": TokenKind.HASH,
                "=": TokenKind.EQUAL,
            }

            if ch in single_map:
                kind = single_map[ch]
                self._emit(kind, ch)
                self._advance()
                continue

            raise LexerError(f"Unexpected character: {ch!r}", self.line, self.column)

        self._emit(TokenKind.EOF, "")
        return self.tokens

    def _read_identifier(self) -> None:
        """Read an identifier or keyword."""
        start_col = self.column
        result = ""
        while self.pos < len(self.source) and (
            self._peek().isalnum() or self._peek() == "_"
        ):
            result += self._advance()

        if result in KEYWORDS:
            self._emit(KEYWORDS[result], result, col=start_col)
        else:
            self._emit(TokenKind.IDENTIFIER, result, col=start_col)


def tokenize(source: str) -> list[Token]:
    """Tokenize C source text and return the token list."""
    return Lexer(source).tokenize()


def tokenize_with_comments(
    source: str,
) -> tuple[list[Token], list[tuple[int, str]]]:
    """Tokenize and also return the list of `(line, text)` C comments
    encountered, in source order.  Used by the compile pipeline to
    pass comments through to codegen for asm-level annotation."""
    lex = Lexer(source)
    toks = lex.tokenize()
    return toks, lex.comments
