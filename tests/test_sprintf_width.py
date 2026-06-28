"""sprintf width and left-justify formatting: %-Nd, %Nd."""

from src.pyc.preprocessor import Preprocessor
from src.pyc.builder import build
from pathlib import Path
import subprocess
import tempfile
import os
import sys


def _run_sprintf_prog(c_src: str) -> str:
    """Compile + run a small C program that uses sprintf, return stdout."""
    import pytest
    import shutil
    if not shutil.which("nasm") or not shutil.which("dosbox-x"):
        pytest.skip("nasm or dosbox-x not available")

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "test.c"
        src.write_text(c_src)
        exe = Path(tmp) / "TEST.EXE"
        try:
            build(sources=[src], output=exe, out_dir=Path(tmp))
        except Exception as e:
            pytest.fail(f"Build failed: {e}")
        # Run under DOSBox — skip if not available
        # This is an integration test; most CI runs stop at build.
        return ""


# ── Unit tests: test the stdio.c sprintf logic through the C preprocessor
# We can test the output formatting by compiling and linking.
# For pure-Python tests, we instead test via the single-file build + run loop.
# Since that requires DOSBox, the meaningful tests here are:
#   1. That the _format_ strings compile without error
#   2. Output checks via the preprocessor (limited)

# The real validation is build + dosbox run. Here we at least verify the
# C source compiles through pyc without exceptions.

def _build_only(c_src: str, tmp_dir: Path) -> Path:
    """Compile to ASM only; assert no exception."""
    from src.pyc.compiler import compile
    asm = compile(c_src, Path("<test>"))
    out = tmp_dir / "test.asm"
    out.write_text(asm)
    return out


def test_sprintf_left_justify_compiles() -> None:
    """sprintf("%-10d", 42) source compiles without errors."""
    import tempfile
    src = (
        "#include <stdio.h>\n"
        "#include <stdlib.h>\n"
        "int main(void) {\n"
        "    char buf[32];\n"
        "    sprintf(buf, \"%-10d\", 42);\n"
        "    return 0;\n"
        "}\n"
    )
    from src.pyc.compiler import compile
    asm = compile(src, Path("<test>"))
    assert "sprintf" in asm


def test_sprintf_width_and_left_justify_compiles() -> None:
    """Multiple width specs compile: %-10d, %-8d, %-9d."""
    src = (
        "#include <stdio.h>\n"
        "int main(void) {\n"
        "    char buf[64];\n"
        "    int depth = 3;\n"
        "    int collected = 5;\n"
        "    int quota = 10;\n"
        "    int score = 1234;\n"
        "    sprintf(buf, \"%-10d\", depth);\n"
        "    sprintf(buf, \"%-8d\", collected);\n"
        "    sprintf(buf, \"%-9d\", score);\n"
        "    return 0;\n"
        "}\n"
    )
    from src.pyc.compiler import compile
    asm = compile(src, Path("<test>"))
    assert "sprintf" in asm
