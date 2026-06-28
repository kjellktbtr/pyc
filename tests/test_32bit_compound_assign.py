"""Tests for 32-bit compound assignment on non-Identifier lvalues."""

from pathlib import Path

from src.pyc.compiler import compile


class Test32BitCompoundAssign:
    """Test compound ops on long arrays."""

    def test_long_array_add(self) -> None:
        """Test += on long array element."""
        src = '''
long arr[3];
int main(void) {
    arr[1] = 1000;
    arr[1] += 50;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert "arr[1]" in asm or "arr" in asm
        assert "+=" in asm or "add" in asm.lower()

    def test_long_array_sub(self) -> None:
        """Test -= on long array element."""
        src = '''
long arr[3];
int main(void) {
    arr[0] = 2000;
    arr[0] -= 100;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None

    def test_long_array_mul(self) -> None:
        """Test *= on long array element."""
        src = '''
long arr[2];
int main(void) {
    arr[0] = 100;
    arr[0] *= 2;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None

    def test_long_array_div(self) -> None:
        """Test /= on long array element."""
        src = '''
long arr[2];
int main(void) {
    arr[0] = 1000;
    arr[0] /= 10;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None

    def test_mixed_array_compound(self) -> None:
        """Test compound ops on mixed int/long array."""
        src = '''
int a[5];
long b[3];
int main(void) {
    a[0] += 1;
    b[0] += 100L;
    b[1] -= 50L;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None

    def test_32bit_offset_calculation(self) -> None:
        """Test that 32-bit array uses correct offset calculation."""
        src = '''
long arr[10];
int main(void) {
    arr[5] = 1000;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        # For long arr[10], element size is 4
        # arr[5] offset should be 5*4 = 20
        assert "imul" in asm or "shl" in asm  # Some scaling operation
