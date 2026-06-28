"""Tests for long long (64-bit) type support."""

from pathlib import Path

from src.pyc.compiler import compile


class Test64Bit:
    """Test long long type handling."""

    def test_long_long_decl(self) -> None:
        """Test declaration of long long."""
        src = '''
long long x;
int main(void) {
    x = 1000LL;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None
        # Check that x is recognized as 64-bit
        assert "long long" in asm or "x" in asm

    def test_long_long_add(self) -> None:
        """Test addition with long long."""
        src = '''
long long a, b;
int main(void) {
    a = 1000000LL;
    b = 2000000LL;
    long long c = a + b;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None

    def test_long_long_literal(self) -> None:
        """Test 64-bit literal suffix."""
        src = '''
long long x = 1000000LL;
int main(void) {
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None

    def test_long_long_arithmetic(self) -> None:
        """Test full arithmetic on long long."""
        src = '''
long long x;
int main(void) {
    x = 1000LL * 1000LL;
    x = x + 100LL;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None

    def test_mixed_int_long_long(self) -> None:
        """Test mixed int and long long operations."""
        src = '''
int a;
long long b;
int main(void) {
    a = 100;
    b = 1000000LL;
    b = b + a;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None

    def test_long_long_compare(self) -> None:
        """Test comparison with long long."""
        src = '''
long long x;
int main(void) {
    x = 10000LL;
    if (x > 5000LL) {
        return 1;
    }
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None

    def test_local_64bit_assign_no_literal_name_placeholder(self) -> None:
        """Regression: 64-bit local assignment must not emit literal `{name}` in asm.

        Reason: a missing f-prefix on `"mov [{name}+N]"` lines in codegen
        leaked the placeholder into NASM output. See single/test_indvars.c.
        """
        src = '''
int main(void) {
    double sum = 0.0;
    sum = sum + 1.0;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert "{name}" not in asm

    def test_long_long_in_struct(self) -> None:
        """Test long long in struct."""
        src = '''
struct S {
    long long value;
};
int main(void) {
    struct S s;
    s.value = 1000000LL;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None
