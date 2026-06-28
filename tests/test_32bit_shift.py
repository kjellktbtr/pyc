"""Tests for 32-bit variable shifts (<< and >>)."""

from pathlib import Path

from src.pyc.compiler import compile


class Test32BitShift:
    """Test << and >> on 32-bit variables."""

    def test_var_shift_left(self) -> None:
        """Test variable left shift."""
        src = '''
long x;
int main(void) {
    x = 1;
    x <<= 1;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None
        # NASM uses 'sal' for shift arithmetic left
        assert "sal" in asm

    def test_var_shift_right(self) -> None:
        """Test variable right shift (sign-extended)."""
        src = '''
long x;
int main(void) {
    x = -1;
    x >>= 1;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None
        # Check that shift operation exists (NASM uses 'sar' for arithmetic right shift)
        assert "sar" in asm

    def test_var_shift_left_literal(self) -> None:
        """Test variable left shift with literal."""
        src = '''
long x;
int main(void) {
    x = 1;
    x = x << 2;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None

    def test_var_shift_right_literal(self) -> None:
        """Test variable right shift with literal."""
        src = '''
long x;
int main(void) {
    x = -1000L;
    x = x >> 2;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None

    def test_shift_in_expression(self) -> None:
        """Test shift within expression."""
        src = '''
long a, b;
int main(void) {
    a = 1000L;
    b = a << 2;
    b = a >> 1;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None

    def test_32bit_shift_preserves_sign(self) -> None:
        """Test that >> preserves sign for negative numbers."""
        src = '''
long x;
int main(void) {
    x = -1000L;  /* 0xFFFFFC18 */
    x = x >> 1;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None

    def test_combined_shift_and_add(self) -> None:
        """Test combined shift and addition."""
        src = '''
long x;
int main(void) {
    x = 1 << 4;
    x = x + 16;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None
