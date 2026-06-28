"""Build system: compile C files, assemble to OBJ, link with alink."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from src.pyc.compiler import compile, compile_files
from src.pyc.symbols import SymbolTable

log = logging.getLogger(__name__)

# Path to the stdlib directory (relative to this package)
stdlib_dir = Path(__file__).parent.parent.parent / "stdlib"
_stdlib_obj_cache: dict[str, Path | None] = {}


def _is_stale(target: Path, *sources: Path) -> bool:
    """True if target is missing or older than any of the sources."""
    if not target.is_file():
        return True
    target_mtime = target.stat().st_mtime
    return any(s.is_file() and s.stat().st_mtime > target_mtime for s in sources)


def _get_stdlib_object(name: str) -> Path | None:
    """Get a pre-assembled stdlib .obj file, (re)assembling if stale."""
    if name in _stdlib_obj_cache:
        return _stdlib_obj_cache[name]

    # Try to find the C source and compile+assemble it
    c_path = stdlib_dir / f"{name}.c"
    if not c_path.is_file():
        # Try .asm
        asm_path = stdlib_dir / f"{name}.asm"
        if not asm_path.is_file():
            _stdlib_obj_cache[name] = None
            return None

        obj_path = asm_path.with_suffix(".obj")
        if _is_stale(obj_path, asm_path):
            try:
                assemble(asm_path, obj_path)
            except RuntimeError:
                _stdlib_obj_cache[name] = None
                return None
        _stdlib_obj_cache[name] = obj_path
        return obj_path

    # Compile C to ASM, then assemble
    from src.pyc.compiler import compile
    asm_path = c_path.with_suffix(".asm")
    obj_path = c_path.with_suffix(".obj")
    try:
        if _is_stale(asm_path, c_path):
            asm = compile(c_path.read_text(), c_path)
            asm_path.write_text(asm)
        if _is_stale(obj_path, asm_path):
            assemble(asm_path, obj_path)
        _stdlib_obj_cache[name] = obj_path
        return obj_path
    except Exception as e:
        log.warning("Failed to compile stdlib/%s: %s", name, e)
        _stdlib_obj_cache[name] = None
        return None


def get_stdlib_objects(exclude: list[str] | None = None) -> list[Path]:
    """Return the available stdlib .obj files in link order.

    ``exclude`` names modules to omit (without extension), e.g. ``["fp"]`` to
    drop the ~9 KB soft-float runtime.  Dropping `fp` keeps a float-free program
    under alink's ~32 KB near-call limit, but any unresolved float symbol it
    pulls (chiefly stdio's `__print_d64`, the `%f` printer) must be satisfied by
    a caller-supplied stub passed via ``extra_objects``.
    """
    excluded = set(exclude or ())
    stdlib_order = [
        "fp", "dos_io", "posix_io", "dos_dir", "serial", "long_io",
        "string", "stdlib", "stdio",
    ]
    result: list[Path] = []
    for name in stdlib_order:
        if name in excluded:
            continue
        obj = _get_stdlib_object(name)
        if obj is not None:
            result.append(obj)
    return result


def _find_tool(name: str) -> Path | None:
    """Locate an executable in PATH."""
    path = shutil.which(name)
    if path is None:
        log.warning("%s not found in PATH", name)
    return Path(path) if path else None


def _find_wlink() -> Path | None:
    """Locate the Open Watcom linker (wlink).

    Searches PATH first, then the standard Open Watcom install layout (honouring
    $WATCOM).  wlink is needed for programs whose combined code exceeds 32 KB:
    alink mis-links near calls whose self-relative displacement overflows the
    signed 16-bit range, whereas wlink emits the correct mod-65536 displacement.
    """
    found = shutil.which("wlink")
    if found:
        return Path(found)
    roots = []
    watcom = os.environ.get("WATCOM")
    if watcom:
        roots.append(Path(watcom))
    roots += [Path("/opt/watcom"), Path("/usr/bin/watcom")]
    for root in roots:
        for sub in ("binl64", "binl", "binnt64", "binnt"):
            cand = root / sub / "wlink"
            if cand.exists():
                return cand
    return None


def compile_to_asm(
    source: Path,
    output: Path | None = None,
    include_paths: list[Path] | None = None,
    optimize: int = 1,
) -> Path:
    """Compile a single C file to NASM assembly.

    Args:
        source: Path to the C source file.
        output: Optional output path for the assembly file.
        include_paths: Include search paths for the preprocessor.
        optimize: Optimization level (0 = off, 1 = on, default).

    Returns:
        Path to the generated assembly file.
    """
    out = output or source.with_suffix(".asm")
    asm = compile(source.read_text(), source, include_paths=include_paths, optimize=optimize)
    out.write_text(asm)
    log.info("Compiled %s -> %s", source, out)
    return out


def assemble(asm_path: Path, obj_path: Path | None = None) -> Path:
    """Assemble a .asm file to a .obj file using nasm -f obj."""
    nasm = _find_tool("nasm")
    if nasm is None:
        raise RuntimeError("nasm not found — install NASM")

    out = obj_path or asm_path.with_suffix(".obj")
    result = subprocess.run(
        [
            str(nasm), "-f", "obj",
            # Demote the "label changed during code generation" warning
            # from error — NASM raises it when a forward jump resolves
            # to a shorter encoding on a later pass, which is harmless
            # for our codegen patterns (large nested switches in
            # particular).
            "-Wno-error=label-redef-late",
            "-o", str(out), str(asm_path),
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"nasm failed:\n{result.stderr}")
    log.info("Assembled %s -> %s", asm_path, out)
    return out


def link(
    obj_files: list[Path],
    output: Path | None = None,
    entry: str = "_entry",
    fmt: str = "EXE",
    with_stdlib: bool = True,
    linker: str = "alink",
    exclude_stdlib: list[str] | None = None,
) -> Path:
    """Link .obj files into a DOS executable.

    ``linker`` selects the backend:
      * ``"alink"`` (default) — fine for programs whose combined code stays under
        ~32 KB.  alink mis-links a near call whose self-relative displacement
        overflows the signed 16-bit range (it does not wrap mod 65536), so a low
        function calling a high routine >32 KB away jumps to the wrong address.
        Keep the program small (see ``exclude_stdlib``) to stay within range.
      * ``"wlink"`` — the Open Watcom linker, which links >32 KB code correctly
        (handles the full 64 KB segment); needs Open Watcom installed.

    ``exclude_stdlib`` drops stdlib modules from the link (e.g. ``["fp"]`` to
    shed the soft-float runtime for a float-free, alink-friendly program).
    """
    all_objs = list(obj_files)
    if with_stdlib:
        all_objs.extend(get_stdlib_objects(exclude=exclude_stdlib))
    out = output or Path("a.exe")

    if linker == "wlink":
        return _link_wlink(all_objs, out, entry, fmt)

    alink = _find_tool("alink")
    if alink is None:
        raise RuntimeError("alink not found — install ALINK")
    cmd = [
        str(alink),
        *[str(o) for o in all_objs],
        "-o", str(out),
        "-o" + fmt.upper(),
        "-entry", entry,
    ]
    result = subprocess.run(cmd, input="\n\n\n", capture_output=True, text=True)
    log.debug("alink stdout:\n%s", result.stdout)
    log.debug("alink stderr:\n%s", result.stderr)
    if result.returncode != 0:
        raise RuntimeError(
            f"alink failed (exitcode={result.returncode}):\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    log.info("Linked %s -> %s", obj_files, out)
    return out


def _link_wlink(all_objs: list[Path], out: Path, entry: str, fmt: str) -> Path:
    """Link with the Open Watcom linker (handles >32 KB code; see ``link``)."""
    wlink = _find_wlink()
    if wlink is None:
        raise RuntimeError(
            "wlink not found — install Open Watcom (set $WATCOM) for large programs"
        )
    if fmt.upper() != "EXE":
        raise RuntimeError(f"wlink backend only emits DOS EXE, not {fmt!r}")
    file_list = ",".join(str(o) for o in all_objs)
    cmd = [
        str(wlink),
        "format", "dos",
        "option", f"start={entry}",
        "option", "quiet",
        "name", str(out),
        "file", file_list,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    log.debug("wlink stdout:\n%s", result.stdout)
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(
            f"wlink failed (exitcode={result.returncode}):\n"
            f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    log.info("Linked (wlink) %s -> %s", all_objs, out)
    return out


def _compile_multi_to_asm(
    sources: list[Path],
    out_dir: Path,
    include_paths: list[Path] | None = None,
    optimize: int = 1,
) -> list[Path]:
    """Compile multiple files independently, each with its own symbol table.

    Each file is compiled with a fresh symbol table so its own definitions are
    emitted as `global` and cross-file references become `extern`.  Header
    declarations (e.g. engine.h `extern int monX[…]`) supply the type info
    needed to generate correct code without a shared symbol table.

    Returns list of asm file paths.
    """
    asm_paths: list[Path] = []
    for src in sources:
        out = out_dir / src.with_suffix(".asm").name
        source_text = src.read_text()
        # Use a fresh per-file symbol table.  Passing a non-None table
        # suppresses the _entry bootstrap in codegen (builder.py injects
        # it into the first file instead), while keeping definitions local
        # to each file avoids the double-global / extern-instead-of-global
        # bug that the old shared-table approach caused.
        per_file_sym = SymbolTable()
        asm = compile(source_text, src, per_file_sym, include_paths=include_paths, optimize=optimize)
        out.write_text(asm)
        log.info("Compiled %s -> %s", src, out)
        asm_paths.append(out)

    return asm_paths


def _merge_asm_modules(asm_texts: list[str]) -> str:
    """Merge per-TU asm into one assembly module (one DGROUP).

    Multi-file builds otherwise link several object modules that each declare
    ``group DGROUP data bss``.  NASM resolves a module's own .bss symbol
    group-relative (adding *that module's* .data size), but alink resolves a
    *cross-module* extern reference to the same symbol .bss-segment-relative
    (no .data base).  The two disagree by the defining module's .data size, so
    a global array defined in one TU and used from another lands at the wrong
    DGROUP offset and silently overlaps other data.  This is never exercised by
    the single-file `single/` suite, so it stayed latent until a real two-file
    program (engine.c + game.c) hit it.

    Merging all TUs into one module makes every cross-TU reference intra-module,
    so the layout is identical to a single-file program — the only configuration
    in which the group offsets are reliable.  Per-file symbol tables already
    produced correct ``global``/``extern`` markers; here we union the globals,
    drop externs now satisfied internally, concatenate each section, and emit a
    single bootstrap, stack reserve and DGROUP.

    Compiler-generated string labels (``_str_<n>``) are numbered per TU, so they
    are renamed with a per-TU prefix to avoid collisions; only the exact
    ``_str_<digits>`` token is rewritten, leaving user identifiers untouched.
    """
    globals_order: list[str] = []
    globals_set: set[str] = set()
    externs: set[str] = set()
    text_lines: list[str] = []
    data_lines: list[str] = []
    bss_lines: list[str] = []

    for idx, text in enumerate(asm_texts):
        text = re.sub(r"\b_str_(\d+)\b", rf"_str_{idx}_\1", text)

        section: str | None = None
        for raw in text.split("\n"):
            s = raw.strip()
            if s.startswith(("[bits", "; ===", "; ---")):
                continue
            if s.startswith("global "):
                name = s.split(None, 1)[1].strip()
                if name != "_entry" and name not in globals_set:
                    globals_set.add(name)
                    globals_order.append(name)
                continue
            if s.startswith("extern "):
                externs.add(s.split(None, 1)[1].strip())
                continue
            if s.startswith("section .text"):
                section = "text"
                continue
            if s.startswith("section .data"):
                section = "data"
                continue
            if s.startswith("section .bss"):
                section = "bss"
                continue
            if s.startswith("section .stack"):
                section = "stack"
                continue
            if s.startswith("group "):
                continue
            if section == "text":
                text_lines.append(raw)
            elif section == "data":
                if s == "_data_start:":
                    continue  # emitted canonically below
                data_lines.append(raw)
            elif section == "bss":
                # the canonical stack reserve lives only in the main TU; it is
                # re-emitted at the end of the combined .bss below
                if s in ("_stack_top:", "resb 0x4000", "resb 0x400"):
                    continue
                bss_lines.append(raw)
            # `stack` section body and out-of-section blank lines are dropped

    externs -= globals_set
    externs.difference_update({"_data_start", "_stack_top", "_entry"})

    out: list[str] = ["; === Generated by pyc (merged multi-file) ===", "[bits 16]\n"]
    out.append("; --- Exported symbols ---")
    out.append("global _entry")
    out.extend(f"global {g}" for g in globals_order)
    out.append("\n; --- Imported symbols ---")
    out.extend(f"extern {e}" for e in sorted(externs))
    out.append("\n; --- Code Segment ---")
    out.append("section .text\n")
    out += [
        "_entry:",
        "mov ax, seg _data_start",
        "mov ds, ax",
        "mov es, ax",
        "cli",
        "mov ss, ax",
        "mov sp, _stack_top",
        "sti",
        "call main",
        "mov ah, 0x4C",
        "int 0x21",
    ]
    out.extend(text_lines)
    out.append("\n; --- Data Segment ---")
    out.append("section .data\n")
    out.append("_data_start:")
    out.extend(data_lines)
    out.append("\n; --- BSS Segment ---")
    out.append("section .bss\n")
    out.extend(bss_lines)
    out += ["resb 0x4000", "_stack_top:", "resb 0x400"]
    out.append("\n; --- Stack Segment ---")
    out.append("section .stack stack class=STACK")
    out.append("resb 0x10")
    out.append("\ngroup DGROUP data bss")
    return "\n".join(out)


def build(
    sources: list[Path],
    output: Path | None = None,
    entry: str = "_entry",
    out_dir: Path | None = None,
    include_paths: list[Path] | None = None,
    extra_objects: list[Path] | None = None,
    linker: str = "alink",
    exclude_stdlib: list[str] | None = None,
    optimize: int = 1,
) -> Path:
    """Full build: compile C files, assemble, link to DOS .EXE.

    Args:
        sources: List of C source files.
        output: Output .exe path (default: first source stem).
        entry: Entry point symbol name.
        out_dir: Directory for intermediate files (default: per-source).
        include_paths: List of include search paths for the preprocessor.
        extra_objects: Additional pre-assembled .obj files to link (e.g. hand-
            written NASM backends).  Linked after source objects, before stdlib.
        linker: ``"alink"`` (default) or ``"wlink"`` (for >32 KB code; see ``link``).
        exclude_stdlib: stdlib modules to omit, e.g. ``["fp"]`` to drop the
            soft-float runtime (provide any resulting stub via ``extra_objects``).
        optimize: Optimization level (0 = off, 1 = on, default).

    Returns:
        Path to the produced .exe file.
    """
    if not sources:
        raise ValueError("At least one source file required")

    dir = out_dir or sources[0].parent
    obj_files: list[Path] = []

    if len(sources) == 1:
        # Single file: compile with entry point emitted
        asm_path = compile_to_asm(sources[0], dir / sources[0].with_suffix(".asm").name, include_paths, optimize)
    else:
        # Multi-file: compile each TU separately (per-file symbol tables give
        # correct global/extern markers), then MERGE the per-TU asm into a
        # single module so the whole program links as one DGROUP — identical to
        # a single-file program, the only configuration in which the OMF group
        # offsets are reliable.  See _merge_asm_modules for why separate object
        # modules mis-resolve cross-TU .bss symbols.
        asm_paths = _compile_multi_to_asm(sources, dir, include_paths, optimize)
        merged = _merge_asm_modules([p.read_text() for p in asm_paths])
        asm_path = dir / (sources[0].stem + "_merged.asm")
        asm_path.write_text(merged)

    obj_path = assemble(asm_path, dir / sources[0].with_suffix(".obj").name)
    obj_files.append(obj_path)

    if extra_objects:
        obj_files.extend(extra_objects)

    exe = output or dir / (sources[0].stem + ".exe")
    return link(obj_files, exe, entry=entry, linker=linker, exclude_stdlib=exclude_stdlib)
