"""Tests for the preprocessor."""

import pytest

from src.pyc.preprocessor import Preprocessor


class TestInclude:
    def test_builtin_stdio(self) -> None:
        source = '#include <stdio.h>\nint main() { return 0; }'
        pp = Preprocessor()
        result = pp.preprocess(source)
        assert "printf" in result

    def test_builtin_stdlib(self) -> None:
        source = '#include <stdlib.h>\nint main() { return 0; }'
        pp = Preprocessor()
        result = pp.preprocess(source)
        # NULL macro is expanded by preprocessor, so check for expansion result
        assert "exit" in result
        assert "malloc" in result
        assert "size_t" in result


class TestMultilineMacroCall:
    def test_multiline_variadic_invocation(self) -> None:
        """A function-like macro call whose argument list spans multiple
        physical lines must still expand (standard C).  Regression for
        butikk.c's multi-line `prtf(...)` HUD calls."""
        source = (
            "#define prtf(...) do { sprintf(buf, __VA_ARGS__); } while (0)\n"
            "void f(void) {\n"
            '    prtf("x=%d y=%d",\n'
            "         a, b);\n"
            "}\n"
        )
        pp = Preprocessor()
        result = pp.preprocess(source)
        assert "prtf(" not in result          # macro fully expanded
        assert "sprintf(buf" in result
        assert "a, b" in result

    def test_multiline_object_macro_args(self) -> None:
        """Multi-line call with nested parens across lines."""
        source = (
            "#define ADD(a, b) ((a) + (b))\n"
            "int x = ADD(1,\n"
            "            2);\n"
        )
        pp = Preprocessor()
        result = pp.preprocess(source)
        flat = result.replace("\n", " ")
        assert "ADD(" not in result
        assert "(1)" in flat and "(2)" in flat and "+" in flat


class TestDefine:
    def test_object_macro(self) -> None:
        source = '#define MAX 100\nint x = MAX;'
        pp = Preprocessor()
        result = pp.preprocess(source)
        assert "MAX" not in result
        assert "100" in result

    def test_multiple_macros(self) -> None:
        source = '#define A 1\n#define B 2\nint x = A + B;'
        pp = Preprocessor()
        result = pp.preprocess(source)
        assert "A" not in result
        assert "B" not in result


class TestConditional:
    def test_defined(self) -> None:
        source = '#define FOO\n#ifdef FOO\nint x = 1;\n#endif'
        pp = Preprocessor()
        result = pp.preprocess(source)
        assert "int x = 1" in result

    def test_not_defined(self) -> None:
        source = '#ifndef BAR\nint y = 2;\n#endif'
        pp = Preprocessor()
        result = pp.preprocess(source)
        assert "int y = 2" in result

    def test_nested_conditionals(self) -> None:
        source = (
            '#define A\n#define B\n'
            '#ifdef A\n'
            '  #ifdef B\n'
            '  int z = 3;\n'
            '  #endif\n'
            '#endif'
        )
        pp = Preprocessor()
        result = pp.preprocess(source)
        assert "int z = 3" in result


class TestUndef:
    def test_undef_removes_macro(self) -> None:
        source = '#define X 42\n#undef X\nint y = X;'
        pp = Preprocessor()
        result = pp.preprocess(source)
        # After undef, X is no longer expanded
        assert "int y = X" in result


class TestConditionals:
    def test_if_else_takes_first_when_true(self) -> None:
        src = "#if 1\nIF\n#else\nELSE\n#endif"
        pp = Preprocessor()
        result = pp.preprocess(src)
        assert "IF" in result
        assert "ELSE" not in result

    def test_if_else_takes_else_when_false(self) -> None:
        src = "#if 0\nIF\n#else\nELSE\n#endif"
        pp = Preprocessor()
        result = pp.preprocess(src)
        assert "IF" not in result
        assert "ELSE" in result

    def test_elif_branch_taken(self) -> None:
        src = "#if 0\nA\n#elif 1\nB\n#else\nC\n#endif"
        pp = Preprocessor()
        result = pp.preprocess(src)
        assert "A" not in result
        assert "B" in result
        assert "C" not in result

    def test_only_first_true_branch_keeps(self) -> None:
        """When multiple branches would be true, only the first one
        is kept — subsequent `#elif`/`#else` are suppressed."""
        src = "#if 1\nA\n#elif 1\nB\n#else\nC\n#endif"
        pp = Preprocessor()
        result = pp.preprocess(src)
        assert "A" in result
        assert "B" not in result
        assert "C" not in result

    def test_nested_if_inside_suppressed_block_stays_suppressed(self) -> None:
        """An #if/#else inside a suppressed outer #if is itself
        suppressed regardless of which branch would otherwise win."""
        src = "#if 0\n#if 1\nINNER\n#else\nINNER_ELSE\n#endif\n#endif"
        pp = Preprocessor()
        result = pp.preprocess(src)
        assert "INNER" not in result
        assert "INNER_ELSE" not in result
