"""Symbol table for multi-file compilation.

Tracks which symbols are defined, declared (extern), or referenced in each
translation unit so the code generator can emit the right global/extrn
directives and the linker can resolve cross-file references.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class SymbolKind(Enum):
    FUNCTION = auto()
    VARIABLE = auto()
    PARAMETER = auto()
    LOCAL = auto()


@dataclass
class Symbol:
    name: str
    kind: SymbolKind
    type: object  # CType – stored as object to avoid circular import
    defined: bool = False  # True if this TU has a definition (not just a decl)
    file: str = ""


class SymbolTable:
    """Global symbol table shared across translation units."""

    def __init__(self) -> None:
        self._symbols: dict[str, Symbol] = {}
        self._current_file: str = ""
        # Per-file tracking
        self._file_globals: dict[str, set[str]] = {}
        self._file_extrns: dict[str, set[str]] = {}
        self._file_locals: dict[str, list[tuple[str, int]]] = {}

    def set_file(self, filename: str) -> None:
        self._current_file = filename
        self._file_globals.setdefault(filename, set())
        self._file_extrns.setdefault(filename, set())
        self._file_locals.setdefault(filename, [])

    def add_symbol(
        self,
        name: str,
        kind: SymbolKind,
        ctype: object,
        defined: bool = False,
    ) -> None:
        sym = Symbol(name, kind, ctype, defined=defined, file=self._current_file)
        existing = self._symbols.get(name)
        if existing and existing.defined and defined:
            return  # Already defined, skip redefinition
        self._symbols[name] = sym
        if defined:
            self._file_globals[self._current_file].add(name)

    def reference(self, name: str) -> None:
        """Mark a symbol as referenced (used) in the current file."""
        if name not in self._symbols:
            self._file_extrns[self._current_file].add(name)

    def add_local(self, name: str, stack_offset: int) -> None:
        self._file_locals[self._current_file].append((name, stack_offset))

    def get(self, name: str) -> Symbol | None:
        return self._symbols.get(name)

    def globals_for(self, filename: str) -> set[str]:
        return self._file_globals.get(filename, set())

    def extrns_for(self, filename: str) -> set[str]:
        """Symbols used in this file but not defined here."""
        globals_set = self.globals_for(filename)
        all_refs = self._file_extrns.get(filename, set())
        return all_refs - globals_set

    def all_symbols(self) -> dict[str, Symbol]:
        return self._symbols

    def all_definitions(self) -> list[Symbol]:
        return [s for s in self._symbols.values() if s.defined]