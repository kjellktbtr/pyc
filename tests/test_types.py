"""Tests for the type system."""

import pytest

from src.pyc.types import (
    BaseType,
    PointerType,
    StructType,
    UnionType,
    EnumType,
    array_of,
    base_type,
    pointer_to,
    void_type,
)


class TestBaseType:
    def test_char_size(self) -> None:
        t = base_type("char")
        assert t.size == 1
        assert t.alignment == 1

    def test_short_size(self) -> None:
        t = base_type("short")
        assert t.size == 2
        assert t.alignment == 2

    def test_int_size(self) -> None:
        t = base_type("int")
        assert t.size == 2
        assert t.alignment == 2

    def test_long_size(self) -> None:
        t = base_type("long")
        assert t.size == 4
        assert t.alignment == 4

    def test_void_size(self) -> None:
        t = void_type()
        assert t.size == 0


class TestPointerType:
    def test_pointer_size(self) -> None:
        t = pointer_to(base_type("int"))
        assert t.size == 2
        assert t.is_pointer is True

    def test_pointer_to_pointer(self) -> None:
        t = pointer_to(pointer_to(base_type("char")))
        assert t.size == 2
        assert t.is_pointer is True


class TestArrayType:
    def test_array_size(self) -> None:
        t = array_of(base_type("int"), 10)
        assert t.size == 20  # 10 * 2
        assert t.alignment == 2

    def test_char_array_size(self) -> None:
        t = array_of(base_type("char"), 256)
        assert t.size == 256
        assert t.alignment == 1


class TestStructType:
    def test_simple_struct(self) -> None:
        s = StructType("S", [("a", base_type("char")), ("b", base_type("int"))])
        assert s.size >= 3  # char + padding + int
        assert s.field_offset("a") == 0
        assert s.field_offset("b") == 2  # aligned to 2

    def test_struct_with_ints(self) -> None:
        s = StructType("S", [("x", base_type("int")), ("y", base_type("int"))])
        assert s.size == 4
        assert s.field_offset("x") == 0
        assert s.field_offset("y") == 2

    def test_struct_alignment(self) -> None:
        s = StructType("S", [("a", base_type("char")), ("l", base_type("long"))])
        # char(1) + padding(1) + long(4) + padding(2 to align to 4)
        assert s.alignment == 4


class TestUnionType:
    def test_union_size(self) -> None:
        u = UnionType(
            "U",
            [("a", base_type("char")), ("b", base_type("int"))],
        )
        assert u.size == 2  # max of char(1) and int(2)

    def test_union_alignment(self) -> None:
        u = UnionType(
            "U",
            [("a", base_type("char")), ("l", base_type("long"))],
        )
        assert u.size == 4
        assert u.alignment == 4


class TestEnumType:
    def test_enum_size(self) -> None:
        e = EnumType("E", {"RED": 0, "GREEN": 1, "BLUE": 2})
        assert e.size == 2
        assert e.alignment == 2
