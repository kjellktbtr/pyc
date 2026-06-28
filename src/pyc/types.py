"""C type representation with size and alignment computation for 16-bit data model."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


def _align_up(value: int, alignment: int) -> int:
    """Round up to next multiple of alignment."""
    return (value + alignment - 1) // alignment * alignment


class CType(ABC):
    """Base class for all C types in a 16-bit data model."""

    @property
    @abstractmethod
    def size(self) -> int:
        """Size in bytes."""

    @property
    @abstractmethod
    def alignment(self) -> int:
        """Alignment requirement in bytes."""

    @property
    def is_signed(self) -> bool:
        """Whether the type is signed (relevant for arithmetic types)."""
        return True

    @property
    def is_pointer(self) -> bool:
        return False

    @property
    def is_function(self) -> bool:
        return False


class VoidType(CType):
    size = 0
    alignment = 1


class NullPtrType(CType):
    """_Nullable or null pointer type placeholder."""

    size = 2
    alignment = 2


@dataclass
class BaseType(CType):
    """Fundamental arithmetic type: char, short, int, long, float, double."""

    name: str  # 'char', 'short', 'int', 'long', 'float', 'double'
    signed: bool = True

    _SIZES = {
        "char": 1,
        "short": 2,
        "int": 2,
        "long": 4,
        "long_long": 8,
        "float": 4,
        "double": 8,
    }

    @property
    def size(self) -> int:
        return self._SIZES.get(self.name, 2)

    @property
    def alignment(self) -> int:
        return self.size


@dataclass
class PointerType(CType):
    inner: CType

    size = 2  # 16-bit near pointers
    alignment = 2

    @property
    def is_pointer(self) -> bool:
        return True


@dataclass
class ArrayType(CType):
    element_type: CType
    count: int

    @property
    def size(self) -> int:
        return self.element_type.size * self.count

    @property
    def alignment(self) -> int:
        return self.element_type.alignment


@dataclass
class FunctionType(CType):
    """The type of a C function.  Functions have no value-level size in
    C — an expression of function type immediately decays to
    `PointerType(FunctionType)`.  We still need this dataclass so that
    parser and codegen can carry the signature (return type, parameter
    list, variadic flag) for typedef'd function pointers, function
    parameters of pointer-to-function type, and the indirect-call
    dispatch in `_gen_call`."""

    return_type: CType
    params: list[tuple[str, CType]] = field(default_factory=list)
    is_variadic: bool = False

    size = 0
    alignment = 1

    @property
    def is_function(self) -> bool:
        return True


@dataclass
class BitField(CType):
    """A struct member declared with a bit-width (`unsigned a:3;`).

    Wraps an underlying integer base type and remembers the bit width and,
    after struct layout, the bit offset within its containing storage
    word.  Bitfields never appear outside `StructType.fields`.
    """

    base: CType
    width: int
    bit_offset: int = 0  # set by StructType._layout_fields

    @property
    def size(self) -> int:
        # For sizeof purposes (which C doesn't really define on bitfield
        # members), report the underlying base type's size.  The struct
        # layout code uses `base.size` directly anyway.
        return self.base.size

    @property
    def alignment(self) -> int:
        return self.base.alignment

    @property
    def is_signed(self) -> bool:
        return getattr(self.base, "signed", True)


@dataclass
class StructType(CType):
    name: str | None
    fields: list[tuple[str, CType]] = field(default_factory=list)
    _computed_size: int = field(default=0, init=False, repr=False)
    _computed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self._layout_fields()

    def _layout_fields(self) -> None:
        """Compute field offsets and total struct size with padding.

        Bitfields (`BitField` instances) are packed into consecutive
        storage units of their underlying base type.  When the current
        bit cursor + the new field's width exceeds the storage unit
        size, a new unit is started.  Non-bitfield fields close the
        current unit and align normally.
        """
        if self._computed:
            return
        offset = 0
        layout: list[tuple[str, CType, int]] = []
        max_align = 1
        # Currently-open bitfield storage unit (None = closed).
        bf_base_offset: int | None = None
        bf_unit_size: int = 0
        bf_bits_used: int = 0
        for fname, ftype in self.fields:
            if isinstance(ftype, BitField):
                unit_bits = ftype.base.size * 8
                start_new = (
                    bf_base_offset is None
                    or ftype.base.size != bf_unit_size
                    or bf_bits_used + ftype.width > unit_bits
                )
                if start_new:
                    offset = _align_up(offset, ftype.base.alignment)
                    bf_base_offset = offset
                    bf_unit_size = ftype.base.size
                    bf_bits_used = 0
                    offset += bf_unit_size
                    max_align = max(max_align, ftype.base.alignment)
                ftype.bit_offset = bf_bits_used
                layout.append((fname, ftype, bf_base_offset))
                bf_bits_used += ftype.width
            else:
                bf_base_offset = None
                bf_unit_size = 0
                bf_bits_used = 0
                offset = _align_up(offset, ftype.alignment)
                layout.append((fname, ftype, offset))
                offset += ftype.size
                max_align = max(max_align, ftype.alignment)
        self._computed_size = _align_up(offset, max_align) if max_align else 0
        self._layout = layout
        self._max_align = max_align
        self._computed = True

    @property
    def size(self) -> int:
        return self._computed_size

    @property
    def alignment(self) -> int:
        return self._max_align if self._computed else 1

    def field_offset(self, name: str) -> int:
        """Get byte offset of a named field (the containing storage
        word's offset for bitfields)."""
        for fname, _, offset in self._layout:
            if fname == name:
                return offset
        raise KeyError(f"Field {name!r} not found in struct {self.name!r}")

    def field_type(self, name: str) -> CType:
        """Get the CType of a named field (a `BitField` for bitfields)."""
        for fname, ftype, _ in self._layout:
            if fname == name:
                return ftype
        raise KeyError(f"Field {name!r} not found in struct {self.name!r}")


@dataclass
class UnionType(CType):
    name: str | None
    fields: list[tuple[str, CType]] = field(default_factory=list)
    _computed_size: int = field(default=0, init=False, repr=False)
    _computed: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self._compute_layout()

    def _compute_layout(self) -> None:
        if self._computed:
            return
        max_size = 0
        max_align = 1
        for _, ftype in self.fields:
            max_size = max(max_size, ftype.size)
            max_align = max(max_align, ftype.alignment)
        self._computed_size = _align_up(max_size, max_align)
        self._max_align = max_align
        self._computed = True

    @property
    def size(self) -> int:
        return self._computed_size

    @property
    def alignment(self) -> int:
        return self._max_align if self._computed else 1


@dataclass
class EnumType(CType):
    name: str | None
    members: dict[str, int] = field(default_factory=dict)

    size = 2  # Same as int in 16-bit model
    alignment = 2


# --- Convenience constructors ---

def void_type() -> VoidType:
    return VoidType()


def base_type(name: str, signed: bool = True) -> BaseType:
    return BaseType(name=name, signed=signed)


def int_type() -> BaseType:
    return BaseType(name="int", signed=True)


def char_type() -> BaseType:
    return BaseType(name="char", signed=True)


def long_type() -> BaseType:
    return BaseType(name="long", signed=True)


def pointer_to(inner: CType) -> PointerType:
    return PointerType(inner=inner)


def array_of(element_type: CType, count: int) -> ArrayType:
    return ArrayType(element_type=element_type, count=count)
