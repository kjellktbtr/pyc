// stdio.c - Standard I/O library for pyc
#include <stdio.h>

/* DOS I/O helper declarations */
void _print(char *str);
char _getchar(void);
void _putchar(char c);
void _readline(char *buf, int max);

/* --- printf --- */
/* Minimal printf: supports %d (decimal int), %s (string), %% (literal %) */

static void _emit_char(char c) {
    _putchar(c);
}

static void _emit_string(char *s) {
    while (*s) {
        _putchar(*s);
        s = s + 1;
    }
}

/* Convert integer to decimal string */
static void _print_uint(unsigned int u) {
    unsigned int divisor = 10000;
    int printed = 0;
    while (divisor > 0) {
        unsigned int digit = u / divisor;
        u = u % divisor;
        if (digit > 0 || printed || divisor == 1) {
            _emit_char(digit + '0');
            printed = 1;
        }
        divisor = divisor / 10;
    }
}

static void _print_int(int n) {
    /* Print the absolute value via UNSIGNED division so that the
       INT_MIN case (where `-INT_MIN` overflows back to INT_MIN in two's
       complement) still produces a positive divisor.  Bit-pattern
       negate is equivalent to two's complement: in 16 bits, -INT_MIN
       has the bit pattern 0x8000, which when read unsigned is 32768 —
       exactly |INT_MIN|. */
    if (n < 0) {
        _emit_char('-');
        n = -n;
    }
    unsigned int u = n;
    unsigned int divisor = 10000;
    int printed = 0;
    while (divisor > 0) {
        unsigned int digit = u / divisor;
        u = u % divisor;
        if (digit > 0 || printed || divisor == 1) {
            _emit_char(digit + '0');
            printed = 1;
        }
        divisor = divisor / 10;
    }
}

/* Emit `u` in hex.  No width or zero-padding — the caller's format
   string controls that (we don't parse width specs yet).  */
static void _print_hex(unsigned int u) {
    char buf[8];
    int n = 0;
    if (u == 0) {
        _emit_char('0');
        return;
    }
    while (u > 0) {
        unsigned int d = u & 0xF;
        if (d < 10) {
            buf[n] = d + '0';
        } else {
            buf[n] = d - 10 + 'a';
        }
        u = u >> 4;
        n = n + 1;
    }
    while (n > 0) {
        n = n - 1;
        _emit_char(buf[n]);
    }
}

static void _print_hex_long(int low, int high) {
    unsigned int hi = high;
    unsigned int lo = low;
    if (hi != 0) {
        _print_hex(hi);
        /* Pad low half to 4 hex digits. */
        char buf[4];
        int n = 0;
        unsigned int u = lo;
        int i;
        for (i = 0; i < 4; i = i + 1) {
            unsigned int d = u & 0xF;
            if (d < 10) {
                buf[i] = d + '0';
            } else {
                buf[i] = d - 10 + 'a';
            }
            u = u >> 4;
        }
        for (i = 3; i >= 0; i = i - 1) {
            _emit_char(buf[i]);
        }
    } else {
        _print_hex(lo);
    }
}

/* Variadic printf: supports
     %d, %i        signed int (decimal)
     %u            unsigned int (decimal)
     %ld, %li      signed long (32-bit decimal)
     %lu           unsigned long (32-bit decimal)
     %s            null-terminated string
     %%            literal '%'

   16-bit args consume one va_list slot (advancing `ap` by one int).
   32-bit args consume two slots; we manually read the low/high words
   and pass them to _print_long/_print_ulong, which expect a long on the
   stack (cdecl: low at [bp+4], high at [bp+6]). */
#include <stdarg.h>
/* The 32-bit print helpers live in long_io.asm.  Declaring them as
   `(int low, int high)` lines the cdecl call layout up with the helper
   body, which reads low at [bp+4] and high at [bp+6] — the same
   layout a `long` argument would produce. */
void _print_long(int low, int high);
void _print_ulong(int low, int high);
void _print_llong(int w0, int w1, int w2, int w3);
void _print_ullong(int w0, int w1, int w2, int w3);
int printf(char *format, ...) {
    va_list ap;
    va_start(ap, format);
    char *s = format;
    while (*s) {
        if (*s == '%') {
            s = s + 1;
            int precision = -1;
            if (*s == '.') {
                s = s + 1;
                precision = 0;
                while (*s >= '0' && *s <= '9') {
                    precision = precision * 10 + (*s - '0');
                    s = s + 1;
                }
            }
            if (*s == 'L') {
                /* `%Lf` — long double formatting.  Our long double is
                   aliased to double; treat the same as `%f` (4-word
                   double argument). */
                s = s + 1;
                int w0 = *ap; ap = ap + 1;
                int w1 = *ap; ap = ap + 1;
                int w2 = *ap; ap = ap + 1;
                int w3 = *ap; ap = ap + 1;
                _print_double_prec(w0, w1, w2, w3, precision);
            } else if (*s == 'l') {
                /* Long-modifier prefix: %ld / %li / %lu / %lx.  Pull
                   the two word slots that make up the 32-bit value.
                   For %lld / %llu / %llx (long long), advance over the
                   second 'l' and consume two extra words; we only print
                   the low 32 bits via the same helpers — sufficient
                   for values that fit in 32 bits.
                   For `%lf` — long form of %f — read a 4-word double. */
                s = s + 1;
                int is_long_long = 0;
                if (*s == 'l') { s = s + 1; is_long_long = 1; }
                if (*s == 'f') {
                    int w0 = *ap; ap = ap + 1;
                    int w1 = *ap; ap = ap + 1;
                    int w2 = *ap; ap = ap + 1;
                    int w3 = *ap; ap = ap + 1;
                    _print_double_prec(w0, w1, w2, w3, precision);
                } else if (is_long_long) {
                    int w0 = *ap; ap = ap + 1;
                    int w1 = *ap; ap = ap + 1;
                    int w2 = *ap; ap = ap + 1;
                    int w3 = *ap; ap = ap + 1;
                    if (*s == 'd' || *s == 'i') {
                        _print_llong(w0, w1, w2, w3);
                    } else if (*s == 'u') {
                        _print_ullong(w0, w1, w2, w3);
                    } else if (*s == 'x' || *s == 'X') {
                        /* No dedicated 64-bit hex helper yet; fall back to
                           the low 32 bits. */
                        _print_hex_long(w0, w1);
                    }
                } else {
                    int low = *ap; ap = ap + 1;
                    int high = *ap; ap = ap + 1;
                    if (*s == 'd' || *s == 'i') {
                        _print_long(low, high);
                    } else if (*s == 'u') {
                        _print_ulong(low, high);
                    } else if (*s == 'x' || *s == 'X') {
                        _print_hex_long(low, high);
                    }
                }
            } else if (*s == 'd' || *s == 'i') {
                _print_int(va_arg(ap, int));
            } else if (*s == 'u') {
                _print_uint(va_arg(ap, int));
            } else if (*s == 'x' || *s == 'X') {
                _print_hex(va_arg(ap, int));
            } else if (*s == 'p') {
                /* Near pointer: 16-bit hex. */
                _emit_char('0');
                _emit_char('x');
                _print_hex(va_arg(ap, int));
            } else if (*s == 'c') {
                _emit_char(va_arg(ap, int));
            } else if (*s == 'f') {
                /* %f — 64-bit double in cdecl arg slot.  Pull 4 words. */
                int w0 = *ap; ap = ap + 1;
                int w1 = *ap; ap = ap + 1;
                int w2 = *ap; ap = ap + 1;
                int w3 = *ap; ap = ap + 1;
                _print_double_prec(w0, w1, w2, w3, precision);
            } else if (*s == 's') {
                _emit_string(va_arg(ap, char *));
            } else if (*s == '%') {
                _emit_char('%');
            }
        } else {
            _emit_char(*s);
        }
        s = s + 1;
    }
    va_end(ap);
    return 0;
}

/* --- sprintf --- */
/* Minimal sprintf: same format support as printf, writes to a buffer.
   The buffer must be large enough — no bounds checking. */
/* External: floating-point printer from `stdlib/fp.asm`.  Reads the
   four 16-bit words of the double off the cdecl-style argument frame
   ([bp+4..+10]) plus a precision word at [bp+12], and emits via
   `_putchar`.  precision: number of fractional digits (-1 = default 6). */
void __print_d64(int w0, int w1, int w2, int w3, int precision);

static void _print_double_words(int w0, int w1, int w2, int w3) {
    __print_d64(w0, w1, w2, w3, -1);
}

static void _print_double_prec(int w0, int w1, int w2, int w3, int prec) {
    __print_d64(w0, w1, w2, w3, prec);
}

static char *_spr_out;
static int _spr_n;  /* running count of chars emitted by _spr_emit_char */

static void _spr_emit_char(char c) {
    *_spr_out = c;
    _spr_out = _spr_out + 1;
    _spr_n = _spr_n + 1;
}

static void _spr_emit_string(char *s) {
    while (*s) {
        _spr_emit_char(*s);
        s = s + 1;
    }
}

static void _spr_print_uint(unsigned int u) {
    unsigned int divisor = 10000;
    int printed = 0;
    while (divisor > 0) {
        unsigned int digit = u / divisor;
        u = u % divisor;
        if (digit > 0 || printed || divisor == 1) {
            _spr_emit_char(digit + '0');
            printed = 1;
        }
        divisor = divisor / 10;
    }
}

static void _spr_print_int(int n) {
    if (n < 0) {
        _spr_emit_char('-');
        n = -n;
    }
    _spr_print_uint(n);
}

int sprintf(char *buf, char *format, ...) {
    va_list ap;
    va_start(ap, format);
    _spr_out = buf;
    char *s = format;
    while (*s) {
        if (*s == '%') {
            s = s + 1;
            /* Parse optional '-' flag (left-justify). */
            int left_just = 0;
            if (*s == '-') {
                left_just = 1;
                s = s + 1;
            }
            /* Parse optional minimum field width. */
            int width = 0;
            while (*s >= '0' && *s <= '9') {
                width = width * 10 + (*s - '0');
                s = s + 1;
            }
            /* Snapshot char counter; after emit, measure how many were written. */
            int snap = _spr_n;
            if (*s == 'd' || *s == 'i') {
                _spr_print_int(va_arg(ap, int));
            } else if (*s == 'u') {
                _spr_print_uint(va_arg(ap, int));
            } else if (*s == 's') {
                _spr_emit_string(va_arg(ap, char *));
            } else if (*s == 'c') {
                _spr_emit_char(va_arg(ap, int));
            } else if (*s == '%') {
                _spr_emit_char('%');
            }
            /* Left-justify: pad with trailing spaces to reach width. */
            if (left_just && width > 0) {
                int printed = _spr_n - snap;
                while (printed < width) {
                    _spr_emit_char(' ');
                    printed = printed + 1;
                }
            }
        } else {
            _spr_emit_char(*s);
        }
        s = s + 1;
    }
    *_spr_out = 0;
    va_end(ap);
    return 0;
}

/* --- fprintf: minimal implementation, ignores stream and writes to stdout. */
/* This compiler has no real FILE* — `stderr` is just an opaque pointer. */
int fprintf(int *stream, char *format, ...) {
    /* TODO: route to a real stream.  For now reuse the printf logic by
       formatting into a buffer and emitting. */
    va_list ap;
    va_start(ap, format);
    char *s = format;
    while (*s) {
        if (*s == '%') {
            s = s + 1;
            if (*s == 'd' || *s == 'i') {
                _print_int(va_arg(ap, int));
            } else if (*s == 'u') {
                _print_uint(va_arg(ap, int));
            } else if (*s == 's') {
                _emit_string(va_arg(ap, char *));
            } else if (*s == 'c') {
                _emit_char(va_arg(ap, int));
            } else if (*s == '%') {
                _emit_char('%');
            }
        } else {
            _emit_char(*s);
        }
        s = s + 1;
    }
    va_end(ap);
    return 0;
}

/* `stderr` and `stdout` are token symbols in this minimal runtime —
   fprintf ignores them anyway. */
int *stderr = 0;
int *stdout = 0;
int *stdin  = 0;

/* --- puts --- */
int puts(char *s) {
    while (*s) {
        _putchar(*s);
        s = s + 1;
    }
    _putchar('\n');
    return 0;
}

/* --- putchar --- */
int putchar(int c) {
    _putchar(c);
    return c;
}

/* --- getchar --- */
int getchar(void) {
    return _getchar();
}

/* Minimal scanf supporting a single "%Ns" or "%s" specifier.
   This is intentionally tiny: it reads a word into the provided buffer
   using the low-level `_getchar` helper. Returns the number of items
   successfully read (0 or 1).
*/
int scanf(char *format, char *buf) {
    int width = 0;
    char *p = format;
    /* Find %% and parse optional width */
    while (*p && *p != '%') p++;
    if (*p != '%') return 0;
    p++;
    while (*p >= '0' && *p <= '9') {
        width = width * 10 + (*p - '0');
        p++;
    }
    if (*p != 's') return 0;
    if (width == 0) width = 1024;

    /* Skip leading whitespace */
    char c;
    do {
        c = _getchar();
    } while (c == ' ' || c == '\n' || c == '\t' || c == '\r');

    int remaining = width - 1; /* leave room for NUL */
    char *out = buf;
    while (remaining > 0 && c != ' ' && c != '\n' && c != '\t' && c != '\r' && c != 0) {
        *out++ = c;
        remaining--;
        c = _getchar();
    }
    *out = '\0';
    return 1;
}
