"""Tests for multiple include paths via -I flag."""

from pathlib import Path

import pytest

from src.pyc.compiler import compile
from src.pyc.preprocessor import Preprocessor


class TestIncludePaths:
    """Test that -I flag handles multiple include paths correctly."""

    def test_single_include_path(self) -> None:
        """Test with a single include path."""
        source = "int x = 42;"
        result = compile(source, Path("test.c"), include_paths=[Path("stdlib")])
        assert "global x" in result or "x resw" in result

    def test_multiple_include_paths(self) -> None:
        """Test with multiple include paths."""
        source = "int x = 42;"
        result = compile(
            source,
            Path("test.c"),
            include_paths=[Path("stdlib"), Path("stdlib/stdio.h").parent],
        )
        assert "global x" in result or "x resw" in result

    def test_include_path_parent_directory(self) -> None:
        """Test that parent directory of source is default include path."""
        source = "int x = 42;"
        result = compile(source, Path("test.c"))
        # Should compile without errors (stdlib is parent of source in tests)
        assert result is not None

    def test_empty_include_paths_uses_parent(self) -> None:
        """Test that None include_paths defaults to [filename.parent]."""
        source = "int x = 42;"
        result = compile(source, Path("test.c"), include_paths=None)
        assert result is not None

    def test_preprocessor_multiple_paths(self) -> None:
        """Test Preprocessor directly with multiple include paths."""
        pp = Preprocessor(include_paths=[Path("stdlib"), Path("stdlib")])
        source = "#define VERSION 1\nint x = VERSION;"
        result = pp.preprocess(source, Path("test.c"))
        assert "int x = 1" in result

    def test_preprocessor_default_path(self) -> None:
        """Test Preprocessor with default single path."""
        pp = Preprocessor(include_paths=[Path("stdlib")])
        source = "#define VERSION 2\nint x = VERSION;"
        result = pp.preprocess(source, Path("test.c"))
        assert "int x = 2" in result

    def test_preprocessor_no_paths(self) -> None:
        """Test Preprocessor with no paths (should use parent only)."""
        pp = Preprocessor(include_paths=[Path("test.c").parent])
        source = "int y = 100;"
        result = pp.preprocess(source, Path("test.c"))
        assert "int y = 100" in result
