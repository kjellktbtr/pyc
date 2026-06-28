"""Tests for multi-dimensional array subscripting."""

from pathlib import Path

from src.pyc.compiler import compile


class TestMultiDimensionalArrays:
    """Test m[i][j] subscripting."""

    def test_m2d_read(self) -> None:
        """Test reading from 2D array."""
        src = '''
int m[3][4];
int test(void) {
    return m[1][2];
}
'''
        asm = compile(src, Path("<test>"))
        # m[1][2] should compute offset: 1*row_size + 2*col_size
        # row_size = 4*2 = 8, col_size = 2
        # offset = 1*8 + 2*2 = 12
        # Check that offset calculation uses row_size (8) for first dimension
        # First dim: shl ax, 3 (for *8) or equivalent
        # Second dim: shl ax, 1 (for *2)
        # Verify 2D computation is present
        assert "m" in asm
        # First dim scales by row size = 4 * sizeof(int) = 8 (codegen emits
        # `mov bx, 8; imul bx` for the non-power-of-2-shiftable case).
        # Second dim scales by sizeof(int) = 2 (`shl ax, 1`).
        assert "mov bx, 8" in asm and "imul bx" in asm
        assert "shl ax, 1" in asm

    def test_m2d_correct_offset_size(self) -> None:
        """Test that 2D array uses correct row size for first dimension."""
        src = '''
int m[3][4];
int test(void) {
    return m[1][2];
}
'''
        asm = compile(src, Path("<test>"))
        # First dimension should use row_size=8, so index*8
        # This means 3x shifts (shl ax, 3) or imul with 8
        # Second dimension uses element_size=2, so index*2
        # Verify the pattern exists
        lines = asm.split("\n")
        # Find the two multiply operations
        mul_count = 0
        for line in lines:
            if "shl" in line or "imul" in line:
                mul_count += 1
        # Should have at least 2 scale operations
        assert mul_count >= 2

    def test_m2d_write(self) -> None:
        """Test writing to 2D array."""
        src = '''
int m[3][4];
int test(void) {
    m[1][2] = 77;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert "m" in asm
        assert "77" in asm
        # Verify write operation exists
        assert "mov [" in asm or "mov [" in asm

    def test_m2d_increment(self) -> None:
        """Test incrementing 2D array element."""
        src = '''
int m[3][4];
int test(void) {
    m[1][2] += 1;
    return 0;
}
'''
        asm = compile(src, Path("<test>"))
        assert "m" in asm
        # First dim: `mov bx, 8; imul bx` (×8 row stride).
        # Second dim: `shl ax, 1` (×2 element).
        assert "mov bx, 8" in asm and "imul bx" in asm
        assert "shl ax, 1" in asm

    def test_m2d_decl_and_use(self) -> None:
        """Test 2D array declared and used."""
        src = '''
int main(void) {
    int m[3][4];
    m[0][0] = 1;
    m[1][2] = 2;
    m[2][3] = 3;
    return m[1][1];
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None

    def test_m2d_read_write(self) -> None:
        """Test reading and writing different elements."""
        src = '''
int main(void) {
    int m[5][5];
    m[0][0] = 1;
    int x = m[4][4];
    return x;
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None

    def test_m2d_char_write_is_byte_store(self) -> None:
        """Storing to a 2D *char* array must use a byte store (`mov [bx], al`),
        not a word store (`mov [bx], ax`).  A word store writes the high byte
        (0) into the adjacent element, corrupting it.

        Regression for the SJAKTENE fog-of-war bug: RevealAround's
        `seen[tx][ty] = 1` (seen is `char[48][32]`) clobbered `seen[tx][ty+1]`,
        turning previously-revealed tiles black when moving.
        """
        src = '''
char m[4][4];
int test(int i, int j) {
    m[i][j] = 1;
    return 0;
}
'''
        asm = compile(src, Path("<test>"), optimize=0)
        assert "mov [bx], al" in asm, "2D char store must be a byte store"
        assert "mov [bx], ax" not in asm, "2D char store must not be a word store"

    def test_m2d_compound_ops(self) -> None:
        """Test compound operations on 2D array."""
        src = '''
int main(void) {
    int m[3][4];
    m[1][1] += 1;
    m[1][1] -= 2;
    return m[1][1];
}
'''
        asm = compile(src, Path("<test>"))
        assert asm is not None
