"""Initialized global pointer-arrays and sizeof of array-typed expressions.

Regression tests for two codegen bugs found while building the SJAKTENE/NATTMAT
DOS games with pyc:

* `const char *t[N][M] = {{"a",..},..}` (a string-pointer table) was emitted as
  uninitialized BSS (`resw <wrong>`) instead of an initialized `.data` table of
  pointers, so every string read back empty.
* `sizeof(arr)` on an array-typed *expression* returned a hardcoded 2 (pointer
  size) instead of the array's byte size, so e.g. `memset(grid, 0, sizeof(grid))`
  cleared only 2 bytes.
"""

from src.pyc.compiler import compile


def test_1d_pointer_array_emits_initialized_data() -> None:
    asm = compile('const char *a[3] = {"aa", "bb", "cc"};\n')
    # The array becomes a dw table of string-literal labels, not zeroed BSS.
    assert "a: dw _str_" in asm
    assert "a: resw" not in asm
    # Three distinct strings emitted in .data.
    assert '_str_1 db "aa", 0' in asm
    assert '_str_2 db "bb", 0' in asm
    assert '_str_3 db "cc", 0' in asm


def test_2d_pointer_array_flattens_row_major() -> None:
    asm = compile('const char *t[2][3] = {{"a","b","c"},{"d","e","f"}};\n')
    # 2x3 = 6 pointer words, all in one initialized table.
    line = next(ln for ln in asm.splitlines() if ln.startswith("t: dw "))
    assert line.count("_str_") == 6
    assert "t: resw" not in asm


def test_duplicate_strings_are_interned() -> None:
    asm = compile('const char *t[2][2] = {{"x","y"},{"x","y"}};\n')
    # "x" and "y" each defined once despite appearing twice in the table.
    assert asm.count('db "x", 0') == 1
    assert asm.count('db "y", 0') == 1
    line = next(ln for ln in asm.splitlines() if ln.startswith("t: dw "))
    assert line.count("_str_") == 4  # four table slots, two unique strings


def test_partial_initializer_zero_padded() -> None:
    asm = compile('int a[5] = {1, 2};\n')
    line = next(ln for ln in asm.splitlines() if ln.startswith("a: dw "))
    # 1, 2 then three zero words to fill the declared size.
    assert line == "a: dw 1, 2, 0, 0, 0"


def test_sizeof_1d_array_is_full_size() -> None:
    asm = compile("char g[48]; int f(void) { return (int)sizeof(g); }\n")
    assert "mov ax, 48" in asm


def test_sizeof_2d_array_is_full_size() -> None:
    asm = compile("char g[48][32]; int f(void) { return (int)sizeof(g); }\n")
    assert "mov ax, 1536" in asm


def test_sizeof_int_array_counts_element_width() -> None:
    asm = compile("int a[10]; int f(void) { return (int)sizeof(a); }\n")
    assert "mov ax, 20" in asm


def test_sizeof_pointer_variable_is_two() -> None:
    asm = compile("char *p; int f(void) { return (int)sizeof(p); }\n")
    assert "mov ax, 2" in asm
