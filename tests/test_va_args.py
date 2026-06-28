"""__VA_ARGS__ variadic macro expansion in the preprocessor."""

from src.pyc.preprocessor import Preprocessor
from pathlib import Path


def test_variadic_macro_no_named_params() -> None:
    """prtf(...) style: macro with only ... (no named params)."""
    pp = Preprocessor()
    src = (
        "#define prtf(...) sprintf(buf, __VA_ARGS__)\n"
        'prtf("hello %d", x)\n'
    )
    out = pp.preprocess(src, Path("<test>"))
    lines = [l for l in out.split("\n") if l.strip()]
    assert 'sprintf(buf, "hello %d", x)' in lines[-1]


def test_variadic_macro_with_named_params() -> None:
    """printf-wrapper with a named format param + variadic rest."""
    pp = Preprocessor()
    src = (
        "#define WRAP(fmt, ...) my_printf(fmt, __VA_ARGS__)\n"
        'WRAP("x=%d", val)\n'
    )
    out = pp.preprocess(src, Path("<test>"))
    lines = [l for l in out.split("\n") if l.strip()]
    assert 'my_printf("x=%d", val)' in lines[-1]


def test_variadic_macro_multiple_extra_args() -> None:
    """Multiple variadic arguments are all captured."""
    pp = Preprocessor()
    src = (
        "#define LOG(...) log_write(__VA_ARGS__)\n"
        'LOG("a=%d b=%d", a, b)\n'
    )
    out = pp.preprocess(src, Path("<test>"))
    lines = [l for l in out.split("\n") if l.strip()]
    assert 'log_write("a=%d b=%d", a, b)' in lines[-1]


def test_do_while_variadic_expansion() -> None:
    """do { ... } while(0) wrapper with __VA_ARGS__ expands correctly."""
    pp = Preprocessor()
    src = (
        "#define prtf(...) do { sprintf(pbuf, __VA_ARGS__); prt(pbuf); } while(0)\n"
        'prtf("HP:%d/%d", hp, maxHp);\n'
    )
    out = pp.preprocess(src, Path("<test>"))
    # Should NOT have __VA_ARGS__ in output, and should have the actual args
    assert "__VA_ARGS__" not in out
    assert '"HP:%d/%d", hp, maxHp' in out
