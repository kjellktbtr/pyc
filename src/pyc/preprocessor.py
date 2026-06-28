"""C preprocessor: #include, #define, conditional compilation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Macro:
    """Represents a preprocessor macro."""
    name: str
    body: str
    params: list[str] = field(default_factory=list)  # empty for object-like
    file: Path = Path("<builtin>")
    variadic: bool = False  # True when params ends with `...`


@dataclass
class PreprocessorState:
    defines: dict[str, Macro] = field(default_factory=dict)
    include_paths: list[Path] = field(default_factory=list)
    current_file: Path = Path("<input>")
    include_stack: list[Path] = field(default_factory=list)
    line_map: list[tuple[str, int]] = field(
        default_factory=list
    )  # (source_segment, line_offset)


class PreprocessorError(Exception):
    def __init__(self, message: str, line: int = 0, file: str = "") -> None:
        loc = f"{file}:L{line}: " if file and line else ""
        super().__init__(f"Preprocessor error {loc}{message}")


class Preprocessor:
    """Handles #include, #define, #undef, and conditional compilation."""

    def __init__(
        self,
        include_paths: list[Path] | None = None,
        builtins: dict[str, Macro] | None = None,
    ) -> None:
        self.state = PreprocessorState(
            include_paths=include_paths or [],
            defines=builtins or {},
        )
        self._headers: dict[str, str] = {}
        self._register_builtin_headers()
        self._register_builtin_defines()

    def _register_builtin_defines(self) -> None:
        """Register macros that exist in every translation unit.

        `__attribute__((...))` is a GNU extension the codegen has no use
        for.  Defining it as an empty function-like macro lets sources
        that use it (often for `((packed))`, `((constructor))`, etc.)
        preprocess away cleanly.  Likewise for the bare-keyword forms
        `__inline__` / `__restrict__` etc. that the parser doesn't
        understand.
        """
        # `__attribute__` used to be defined as an empty macro to strip
        # the GCC extension entirely.  We now keep it in the source so
        # the parser can recognize `((constructor))` / `((destructor))`
        # and wire the function into the entry/exit sequence.
        for kw in ("__inline__", "__inline", "__restrict__", "__restrict"):
            if kw not in self.state.defines:
                self.state.defines[kw] = Macro(kw, "")

    def _register_builtin_headers(self) -> None:
        """Register stub headers that the compiler provides."""
        self._headers["stdio.h"] = self._stdio_h()
        self._headers["stdlib.h"] = self._stdlib_h()
        self._headers["string.h"] = self._string_h()
        self._headers["ctype.h"] = self._ctype_h()
        self._headers["math.h"] = self._math_h()
        self._headers["stdarg.h"] = self._stdarg_h()
        self._headers["stdbool.h"] = self._stdbool_h()
        self._headers["stdint.h"] = self._stdint_h()
        self._headers["stddef.h"] = self._stddef_h()
        self._headers["inttypes.h"] = self._inttypes_h()
        self._headers["alloca.h"] = self._alloca_h()
        self._headers["fenv.h"] = self._fenv_h()
        self._headers["float.h"] = self._float_h()
        self._headers["fcntl.h"] = self._fcntl_h()
        self._headers["unistd.h"] = self._unistd_h()
        self._headers["errno.h"] = self._errno_h()
        self._headers["serial.h"] = self._serial_h()
        self._headers["dos.h"] = self._dos_h()

    # --- Builtin header stubs ---

    @staticmethod
    def _stdio_h() -> str:
        return """\
#ifndef STDIO_H
#define STDIO_H
#define EOF (-1)
#define BUFSIZ 1024
int printf(char *format, ...);
int sprintf(char *buf, char *format, ...);
int fprintf(int *stream, char *format, ...);
extern int *stderr;
extern int *stdout;
extern int *stdin;
int getchar(void);
int putchar(int c);
int puts(char *s);
#endif
"""

    @staticmethod
    def _fcntl_h() -> str:
        # POSIX-style low-level open(). The O_* flag values are pyc's own
        # encoding; stdlib/posix_io.asm decodes them. Only the low two bits
        # (access mode) map directly to the DOS AH=3Dh AL byte.
        return """\
#ifndef FCNTL_H
#define FCNTL_H
#define O_RDONLY 0x0000
#define O_WRONLY 0x0001
#define O_RDWR   0x0002
#define O_CREAT  0x0100
#define O_TRUNC  0x0200
#define O_APPEND 0x0400
int open(char *path, int flags, ...);
#endif
"""

    @staticmethod
    def _unistd_h() -> str:
        return """\
#ifndef UNISTD_H
#define UNISTD_H
#define SEEK_SET 0
#define SEEK_CUR 1
#define SEEK_END 2
int read(int fd, void *buf, unsigned int count);
int write(int fd, void *buf, unsigned int count);
int close(int fd);
long lseek(int fd, long offset, int whence);
#endif
"""

    @staticmethod
    def _errno_h() -> str:
        return """\
#ifndef ERRNO_H
#define ERRNO_H
extern int errno;
#endif
"""

    @staticmethod
    def _dos_h() -> str:
        # DOS directory ops (stdlib/dos_dir.asm). find_first/find_next fill the
        # 128-byte DTA set via set_dta(); parse it with the DTA_* offsets.
        return """\
#ifndef DOS_H
#define DOS_H
#define FA_NORMAL 0x00
#define FA_DIREC  0x10
/* DTA field offsets after find_first/find_next */
#define DTA_ATTR  21
#define DTA_SIZE  26
#define DTA_NAME  30
int mkdir(char *path);
int set_dta(void *dta);
int find_first(char *spec, int attr);
int find_next(void);
#endif
"""

    @staticmethod
    def _serial_h() -> str:
        # Raw BIOS INT 14h serial layer. `port` is 0-based (0 = COM1).
        # `params` is the INT 14h/AH=00h line-control byte: bits 7-5 baud,
        # 4-3 parity, 2 stop bits, 1-0 word length.
        return """\
#ifndef SERIAL_H
#define SERIAL_H
/* word length */
#define SER_5BITS 0x00
#define SER_6BITS 0x01
#define SER_7BITS 0x02
#define SER_8BITS 0x03
/* stop bits */
#define SER_1STOP 0x00
#define SER_2STOP 0x04
/* parity */
#define SER_NOPARITY   0x00
#define SER_ODDPARITY  0x08
#define SER_EVENPARITY 0x18
/* baud (bits 7-5) */
#define SER_110   0x00
#define SER_150   0x20
#define SER_300   0x40
#define SER_600   0x60
#define SER_1200  0x80
#define SER_2400  0xA0
#define SER_4800  0xC0
#define SER_9600  0xE0
/* common combo: 9600 baud, 8 data bits, no parity, 1 stop bit */
#define SER_8N1 (SER_8BITS | SER_1STOP | SER_NOPARITY)
int serial_init(int port, int params);
int serial_putc(int port, int ch);
int serial_getc(int port);
int serial_status(int port);
/* Direct UART access by I/O base (0x3F8 = COM1, 0x2F8 = COM2). Polled,
   reliable for an ack/nak framed protocol. */
#define COM1_BASE 0x3F8
#define COM2_BASE 0x2F8
int uart_init(int base);
int uart_rx_ready(int base);
int uart_getc(int base);
int uart_putc(int base, int c);
#endif
"""

    @staticmethod
    def _stdarg_h() -> str:
        # 16-bit cdecl: every pushed argument occupies one word, so va_list
        # is just a word pointer.  va_arg's `type` parameter is accepted for
        # source compatibility but ignored — the macro reads one word and
        # advances by sizeof(int) thanks to pointer-arithmetic scaling in
        # the codegen.
        return """\
#ifndef STDARG_H
#define STDARG_H
typedef int *va_list;
#define va_start(ap, last) ((ap) = (int *)&(last) + 1)
/* Advance `ap` by enough int-sized slots to cover `sizeof(type)` bytes,
   then dereference the previous location as the requested type.  Works
   for any type whose size is a multiple of sizeof(int) (16-bit int, so
   unsigned long → 2 slots, char → still 1 slot per default promotion). */
#define va_arg(ap, type)   ( \
    (ap) += (sizeof(type) + sizeof(int) - 1) / sizeof(int), \
    *(type *)((ap) - (sizeof(type) + sizeof(int) - 1) / sizeof(int)) \
)
#define va_end(ap)
#endif
"""

    @staticmethod
    def _stdlib_h() -> str:
        return """\
#ifndef STDLIB_H
#define STDLIB_H
#define NULL 0
#define EXIT_FAILURE 1
#define EXIT_SUCCESS 0

typedef unsigned int size_t;  // Added typedef for size_t

void exit(int code);
int atoi(char *nptr);
long atol(char *nptr);
double atof(char *nptr);
void *malloc(int size);
void *calloc(int nmemb, int size);
void *realloc(void *ptr, int size);
void free(void *ptr);
int rand(void);
void srand(unsigned int seed);
/* abs is a macro to avoid conflict with NASM reserved word 'abs' */
#define abs(x) ((x) < 0 ? -(x) : (x))
#endif
"""

    @staticmethod
    def _string_h() -> str:
        return """\
#ifndef STRING_H
#define STRING_H
int strlen(char *s);
char *strcpy(char *dest, char *src);
char *strncpy(char *dest, char *src, int n);
char *strcat(char *dest, char *src);
int strcmp(char *s1, char *s2);
int strncmp(char *s1, char *s2, int n);
void *memcpy(void *dest, void *src, int n);
void *memset(void *s, int c, int n);
#endif
"""

    @staticmethod
    def _ctype_h() -> str:
        return """\
#ifndef CTYDE_H
#define CTYDE_H
int isalpha(int c);
int isdigit(int c);
int isalnum(int c);
int islower(int c);
int isupper(int c);
int tolower(int c);
int toupper(int c);
#endif
"""

    @staticmethod
    def _math_h() -> str:
        return """\
#ifndef MATH_H
#define MATH_H
double sin(double x);
double cos(double x);
double sqrt(double x);
double fabs(double x);
double floor(double x);
double ceil(double x);
#endif
"""

    @staticmethod
    def _stdbool_h() -> str:
        # `_Bool` is the actual C99 keyword; `bool` is a typedef alias.
        # Both resolve to int because the compiler has no narrower native
        # boolean type and every conditional context already normalises
        # truth values to 0/1.
        return """\
#ifndef STDBOOL_H
#define STDBOOL_H
typedef int _Bool;
typedef int bool;
#define true 1
#define false 0
#endif
"""

    @staticmethod
    def _stdint_h() -> str:
        # 8/16-bit typedefs are honest today; 32-bit ones become honest once
        # slice 7 of the codegen plan lands.  Limits use the standard
        # `(-MAX - 1)` form so they remain expressible as constant
        # expressions of the right type.
        return """\
#ifndef STDINT_H
#define STDINT_H
typedef signed char        int8_t;
typedef unsigned char      uint8_t;
typedef short              int16_t;
typedef unsigned short     uint16_t;
typedef long               int32_t;
typedef unsigned long      uint32_t;
typedef long long          int64_t;
typedef unsigned long long uint64_t;
typedef unsigned int       uintptr_t;
typedef int                intptr_t;
#define INT8_MIN    (-128)
#define INT8_MAX    127
#define UINT8_MAX   255
#define INT16_MIN   (-32767 - 1)
#define INT16_MAX   32767
#define UINT16_MAX  65535U
#define INT32_MIN   (-2147483647L - 1)
#define INT32_MAX   2147483647L
#define UINT32_MAX  4294967295UL
#endif
"""

    @staticmethod
    def _stddef_h() -> str:
        return """\
#ifndef STDDEF_H
#define STDDEF_H
#ifndef NULL
#define NULL ((void*)0)
#endif
typedef unsigned int size_t;
typedef int ptrdiff_t;
typedef unsigned short wchar_t;
#define offsetof(t, m) ((size_t)&(((t*)0)->m))
#endif
"""

    @staticmethod
    def _inttypes_h() -> str:
        # Re-export stdint typedefs plus the PRI*/SCN* format macros.
        # On a 16-bit DOS target int=16, long=32, long long=64.
        return """\
#ifndef INTTYPES_H
#define INTTYPES_H
#include <stdint.h>
#define PRId8  "d"
#define PRIi8  "i"
#define PRIu8  "u"
#define PRIx8  "x"
#define PRId16 "d"
#define PRIi16 "i"
#define PRIu16 "u"
#define PRIx16 "x"
#define PRId32 "ld"
#define PRIi32 "li"
#define PRIu32 "lu"
#define PRIx32 "lx"
#define PRId64 "lld"
#define PRIi64 "lli"
#define PRIu64 "llu"
#define PRIx64 "llx"
#endif
"""

    @staticmethod
    def _alloca_h() -> str:
        # alloca is handled as an intrinsic in codegen (_gen_call):
        # it emits `sub sp, n; mov ax, sp` so allocations are freed
        # automatically when the calling function returns.
        return """\
#ifndef ALLOCA_H
#define ALLOCA_H
void *alloca(unsigned int n);
#endif
"""

    @staticmethod
    def _fenv_h() -> str:
        # Stub: the runtime has no FPU emulation, so floating-point
        # environment manipulation is a no-op.  Declared so #include
        # succeeds and any constants referenced compile.
        return """\
#ifndef FENV_H
#define FENV_H
typedef int fenv_t;
typedef int fexcept_t;
#define FE_TONEAREST  0
#define FE_DOWNWARD   1
#define FE_UPWARD     2
#define FE_TOWARDZERO 3
#define FE_ALL_EXCEPT 0
int feclearexcept(int excepts);
int fegetenv(fenv_t *envp);
int fesetenv(const fenv_t *envp);
int feraiseexcept(int excepts);
int fegetround(void);
int fesetround(int round);
#endif
"""

    @staticmethod
    def _float_h() -> str:
        # IEEE-754 single/double limits.  Constants only — no FPU runtime.
        return """\
#ifndef FLOAT_H
#define FLOAT_H
#define FLT_RADIX        2
#define FLT_MANT_DIG     24
#define FLT_DIG          6
#define FLT_MIN_EXP      (-125)
#define FLT_MAX_EXP      128
#define FLT_EPSILON      1.19209290e-7F
#define FLT_MIN          1.17549435e-38F
#define FLT_MAX          3.40282347e+38F
#define DBL_MANT_DIG     53
#define DBL_DIG          15
#define DBL_MIN_EXP      (-1021)
#define DBL_MAX_EXP      1024
#define DBL_EPSILON      2.2204460492503131e-16
#define DBL_MIN          2.2250738585072014e-308
#define DBL_MAX          1.7976931348623157e+308
#endif
"""

    def preprocess(self, source: str, filename: Path = Path("<input>")) -> str:
        """Process directives and return preprocessed source text.

        Conditional compilation (`#if`/`#ifdef`/`#ifndef`/`#elif`/
        `#else`/`#endif`) is handled by a frame stack: each opening
        directive pushes a frame whose `taken` flag drives whether
        subsequent lines are emitted, and whose `any_taken` flag
        prevents later branches from re-activating once one branch
        has been kept.  All frames must be `taken` for output to
        flow.
        """
        self.state.current_file = filename
        # Only reset the include stack on a top-level invocation.  Nested
        # calls from `_preprocess_header` already pushed `filename` and
        # rely on the parent stack staying intact for circular-include
        # detection and a balanced pop in the caller's `finally`.
        if not self.state.include_stack:
            self.state.include_stack = [filename]
        lines = source.split("\n")
        result: list[str] = []
        # Each frame: {"taken": bool, "any_taken": bool}.  "taken"
        # is the active flag for the current branch; "any_taken" is
        # True if any branch in this chain has already been kept.
        cond_stack: list[dict[str, bool]] = []

        def emitting() -> bool:
            return all(f["taken"] for f in cond_stack)

        i = 0
        while i < len(lines):
            line = lines[i].lstrip()
            if line.startswith("#"):
                directive = self._parse_directive(line)
                if directive is None:
                    i += 1
                    continue
                kind, args = directive
                # Conditional directives are always parsed (even when
                # not emitting) so the frame stack stays accurate.
                if kind in ("if", "ifdef", "ifndef"):
                    if not emitting():
                        # Outer conditional already false → push a
                        # never-taken frame so #else/#elif inside
                        # can't reopen the suppressed block.
                        cond_stack.append({"taken": False, "any_taken": True})
                    else:
                        if kind == "if":
                            cond = self._eval_if_expr(args)
                        elif kind == "ifdef":
                            cond = args.strip() in self.state.defines
                        else:
                            cond = args.strip() not in self.state.defines
                        cond_stack.append({"taken": cond, "any_taken": cond})
                elif kind == "elif":
                    if not cond_stack:
                        raise PreprocessorError("#elif without #if", i, str(filename))
                    f = cond_stack[-1]
                    if f["any_taken"]:
                        f["taken"] = False
                    else:
                        # Only evaluate the elif condition if the
                        # outer frames are emitting.
                        outer_emitting = all(
                            ff["taken"] for ff in cond_stack[:-1]
                        )
                        cond = outer_emitting and self._eval_if_expr(args)
                        f["taken"] = cond
                        if cond:
                            f["any_taken"] = True
                elif kind == "else":
                    if not cond_stack:
                        raise PreprocessorError("#else without #if", i, str(filename))
                    f = cond_stack[-1]
                    if f["any_taken"]:
                        f["taken"] = False
                    else:
                        outer_emitting = all(
                            ff["taken"] for ff in cond_stack[:-1]
                        )
                        f["taken"] = outer_emitting
                        if outer_emitting:
                            f["any_taken"] = True
                elif kind == "endif":
                    if not cond_stack:
                        raise PreprocessorError("#endif without #if", i, str(filename))
                    cond_stack.pop()
                elif emitting():
                    # Non-conditional directives only execute when
                    # the current branch is active.
                    if kind == "include":
                        included = self._handle_include(args, filename, i)
                        result.append(included)
                    elif kind == "define":
                        self._handle_define(args)
                    elif kind == "undef":
                        self._handle_undef(args)
                    elif kind == "line":
                        pass  # Line number tracking, ignored for now
                    # elif kind == "error":  # Could add later
                    elif kind:
                        pass  # Unknown directive, skip silently
            elif emitting():
                # A function-like macro invocation may span multiple physical
                # lines (its argument list runs to the matching `)`).  Pull in
                # continuation lines until the call is closed before expanding,
                # so the line-oriented expander sees the whole invocation.
                while self._open_func_macro_invocation(line) and i + 1 < len(lines):
                    i += 1
                    line = line + "\n" + lines[i]
                # Expand macros, then replace `__LINE__` / `__FILE__` in
                # the result.  Doing it after expansion lets these
                # appear inside macro bodies (e.g. `#define ASSERT(x)
                # assert_fail(#x, __LINE__)` — common idiom).
                expanded = self._expand_macros(line)
                expanded = self._replace_identifiers(
                    expanded, "__LINE__", str(i + 1)
                )
                expanded = self._replace_identifiers(
                    expanded, "__FILE__", f'"{filename}"'
                )
                result.append(expanded)
            i += 1

        if cond_stack:
            raise PreprocessorError(
                "missing #endif at end of file", len(lines), str(filename)
            )
        return "\n".join(result)

    def _parse_directive(self, line: str) -> tuple[str, str] | None:
        """Parse a preprocessor directive line. Returns (kind, args) or None."""
        parts = line[1:].split(None, 1)  # Skip #
        if not parts:
            return None
        kind = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        return kind, args

    def _handle_include(self, args: str, filename: Path, line: int) -> str:
        """Handle #include directive. Returns included source text."""
        args = args.strip()
        system = args.startswith("<")

        if system:
            header = args[1:-1] if args.endswith(">") else args[1:]
        else:
            header = args.strip('"')

        # Check builtin headers first
        if header in self._headers:
            return self._preprocess_header(self._headers[header], Path(header))

        # Search include paths
        search_paths = [filename.parent] + self.state.include_paths
        for search_path in search_paths:
            candidate = search_path / header
            if candidate.is_file():
                return self._preprocess_header(
                    candidate.read_text(), candidate
                )

        raise PreprocessorError(
            f"Cannot include file: {header!r}", line, str(filename)
        )

    def _preprocess_header(self, source: str, filename: Path) -> str:
        """Recursively preprocess an included header."""
        if filename in self.state.include_stack:
            return ""  # Circular include guard
        self.state.include_stack.append(filename)
        try:
            return self.preprocess(source, filename)
        finally:
            self.state.include_stack.pop()

    def _handle_define(self, args: str) -> None:
        """Handle #define directive.

        C distinguishes object-like from function-like macros by what
        immediately follows the name: `#define X(a) ...` is function-like
        (no space before `(`) while `#define X (a) ...` is object-like
        with body `(a) ...`.  A plain whitespace split conflates the two
        when the params are listed without an intervening space, e.g.
        `#define va_start(ap, last) ...` (which is how stdarg.h is
        conventionally written).  Scan the identifier explicitly.
        """
        s = args.lstrip()
        i = 0
        while i < len(s) and (s[i].isalnum() or s[i] == "_"):
            i += 1
        name = s[:i]
        rest = s[i:]

        if rest.startswith("("):
            # Function-like macro: NAME(params) body
            depth = 0
            j = 0
            while j < len(rest):
                if rest[j] == "(":
                    depth += 1
                elif rest[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            params_str = rest[1:j]
            body = rest[j + 1:].lstrip()
            params = [p.strip() for p in params_str.split(",") if p.strip()]
            variadic = params[-1] == "..." if params else False
            if variadic:
                params = params[:-1]  # drop `...`; variadic flag is set below
            self.state.defines[name] = Macro(name, body, params, variadic=variadic)
        else:
            self.state.defines[name] = Macro(name, rest.lstrip())

    def _handle_undef(self, args: str) -> None:
        """Handle #undef directive."""
        name = args.strip()
        self.state.defines.pop(name, None)

    def _open_func_macro_invocation(self, line: str) -> bool:
        """True if `line` contains a function-like macro invocation whose
        closing `)` is missing — i.e. the argument list continues on a later
        physical line.  Standard C allows a macro call's arguments to span
        newlines; the line-oriented expander needs the whole call on one
        logical line, so the main loop uses this to pull in continuation
        lines first.  Mirrors the paren scan in `_expand_func_macro`.
        """
        import re
        for name, macro in self.state.defines.items():
            if not (macro.params or macro.variadic):
                continue
            if name not in line:
                continue
            pattern = r"(?<![A-Za-z0-9_])" + re.escape(name) + r"\s*\("
            for m in re.finditer(pattern, line):
                depth = 1
                i = m.end()
                while i < len(line):
                    c = line[i]
                    if c == "(":
                        depth += 1
                    elif c == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    i += 1
                if depth != 0:
                    return True  # ran off the end → unterminated
        return False

    def _expand_macros(self, line: str) -> str:
        """Expand all macro references in a line of text."""
        max_iterations = 100  # Prevent infinite expansion
        for _ in range(max_iterations):
            expanded = self._expand_one_pass(line)
            if expanded == line:
                break
            line = expanded
        return line

    def _expand_one_pass(self, line: str) -> str:
        """Single pass of macro expansion."""
        result = line
        for name, macro in list(self.state.defines.items()):
            if name in result:
                if macro.params or macro.variadic:
                    # Function-like macro (basic expansion)
                    result = self._expand_func_macro(result, macro)
                else:
                    # Object-like macro
                    result = self._replace_identifiers(result, name, macro.body)
        return result

    def _replace_identifiers(self, text: str, name: str, replacement: str) -> str:
        """Replace whole-word occurrences of `name` with `replacement`,
        skipping the interiors of string and character literals.

        The C preprocessor does not expand identifiers inside `"..."` or
        `'...'`.  We chunk the line by literal-vs-code and only do the
        regex substitution on code chunks.
        """
        import re
        pattern = (
            r"(?<![A-Za-z0-9_])"
            + re.escape(name)
            + r"(?![A-Za-z0-9_])"
        )
        out: list[str] = []
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            if ch == '"' or ch == "'":
                # Copy the literal verbatim (handle backslash escapes).
                quote = ch
                start = i
                i += 1
                while i < n and text[i] != quote:
                    if text[i] == "\\" and i + 1 < n:
                        i += 2
                    else:
                        i += 1
                if i < n:
                    i += 1  # closing quote
                out.append(text[start:i])
                continue
            # Copy a run of code characters and substitute identifiers.
            start = i
            while i < n and text[i] != '"' and text[i] != "'":
                i += 1
            out.append(re.sub(pattern, lambda _m: replacement, text[start:i]))
        return "".join(out)

    def _expand_func_macro(self, text: str, macro: Macro) -> str:
        """Expand function-like macro invocations.

        Finds whole-word occurrences of `macro.name` directly followed by
        `(`, parses the argument list (respecting nested parens), and
        substitutes parameter occurrences in the macro body using whole-
        word matching so that e.g. a parameter named `ap` does not match
        inside `tap` or `apple` within the macro body.
        """
        import re
        # Whole-word match for `<name>(`, with `(` allowed to have leading
        # spaces (C allows whitespace between the name and `(`).
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(macro.name) + r"\s*\("
        match = re.search(pattern, text)
        if not match:
            return text

        start = match.start()
        depth = 1
        i = match.end()  # position just after the opening `(`
        args: list[str] = []
        arg_start = i
        while i < len(text):
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    args.append(text[arg_start:i])
                    break
            elif ch == "," and depth == 1:
                args.append(text[arg_start:i])
                arg_start = i + 1
            i += 1
        else:
            return text  # unterminated invocation

        # Trim each captured arg.
        args = [a.strip() for a in args]
        # Handle 0-arg invocation: `NAME()` produced one empty arg.
        if len(args) == 1 and args[0] == "" and not macro.params:
            args = []

        # Whole-word parameter substitution in the body.  Handle the
        # `#param` (stringify) operator first so the raw argument text
        # — not its expanded form — is what gets quoted.  C requires
        # the argument to be stringified verbatim (after the macro
        # invocation's whitespace normalisation).
        body = macro.body

        # For variadic macros, bind __VA_ARGS__ to the extra arguments
        # (all arguments beyond the named params, joined with ", ").
        if macro.variadic:
            va_args = ", ".join(args[len(macro.params):])
            body = re.sub(
                r"__VA_ARGS__",
                lambda _: va_args,
                body,
            )

        for param, arg in zip(macro.params, args):
            # `#param` → "arg" (with backslashes and quotes escaped).
            escaped = arg.replace("\\", "\\\\").replace('"', '\\"')
            quoted = '"' + escaped + '"'
            body = re.sub(
                r"#\s*" + re.escape(param) + r"(?![A-Za-z0-9_])",
                lambda _, q=quoted: q,
                body,
            )
            body = re.sub(
                r"(?<![A-Za-z0-9_])" + re.escape(param) + r"(?![A-Za-z0-9_])",
                lambda _, a=arg: a,
                body,
            )

        return text[:start] + body + text[i + 1:]

    def _eval_if_expr(self, expr: str) -> bool:
        """Evaluate #if constant expression."""
        try:
            # Simple evaluation - replace common defined() usage
            expr = expr.strip()
            if "defined " in expr or "defined(" in expr:
                # Handle defined(expr) form
                expr = expr.replace("defined ", "").replace("defined(", "").replace(")", "")
                return expr.strip() in self.state.defines
            # Simple arithmetic expression
            return bool(eval(expr, {"__builtins__": {}}, self.state.defines))
        except Exception:
            return False

    def _skip_to_endif(self, start: int, lines: list[str]) -> int:
        """Skip lines until matching #endif, handling nesting."""
        depth = 1
        i = start
        while i < len(lines) and depth > 0:
            stripped = lines[i].lstrip()
            if stripped.startswith("#"):
                directive = self._parse_directive(stripped)
                if directive:
                    kind = directive[0]
                    if kind in ("if", "ifdef", "ifndef"):
                        depth += 1
                    elif kind == "endif":
                        depth -= 1
            i += 1
        return i - 1  # Return index of #endif
