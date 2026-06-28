"""Tests for the code generator."""

import pytest

from src.pyc.ast import (
    Block,
    FunctionDefinition,
    IntLiteral,
    ReturnStmt,
    TopLevelDecl,
    TranslationUnit,
)
from src.pyc.codegen import CodeGenerator
from src.pyc.compiler import compile
from src.pyc.types import base_type


class TestCodegenBasics:
    def test_empty_function(self) -> None:
        ast = TranslationUnit([
            TopLevelDecl(
                specifiers=[],
                declarators=[("main", base_type("int"), None)],
                body=FunctionDefinition(
                    name="main",
                    return_type=base_type("int"),
                    params=[],
                    body=Block([]),
                ),
            ),
        ])
        result = CodeGenerator().generate(ast)
        assert "[bits 16]" in result
        assert "section .text" in result
        assert "main:" in result

    def test_return_value(self) -> None:
        ast = TranslationUnit([
            TopLevelDecl(
                specifiers=[],
                declarators=[("main", base_type("int"), None)],
                body=FunctionDefinition(
                    name="main",
                    return_type=base_type("int"),
                    params=[],
                    body=Block([
                        ReturnStmt(IntLiteral(42, base_type("int"))),
                    ]),
                ),
            ),
        ])
        result = CodeGenerator().generate(ast)
        assert "mov ax, 42" in result
        assert "ret" in result

    def test_return_jumps_to_epilogue(self) -> None:
        """return must jump to the function epilogue, not inline mov sp,bp.

        Checked on unoptimized output: the peephole optimizer legitimately
        drops the jump for a trailing return (target label is the next line).
        """
        asm = compile("int f(void) { return 1; }", optimize=0)
        assert "jmp .f_ret" in asm
        assert "mov sp, bp" not in asm.split(".f_ret:")[0]

    def test_segment_initialization(self) -> None:
        # Bootstrap code is only emitted when main() is defined.
        # DS must be initialised via a SEG relocation against the data
        # section (the loader sets SS:SP from the EXE header / class=STACK
        # segment, so the entry point must NOT touch SP).
        ast = TranslationUnit([
            TopLevelDecl(
                specifiers=[],
                declarators=[("main", base_type("int"), None)],
                body=FunctionDefinition(
                    name="main",
                    return_type=base_type("int"),
                    params=[],
                    body=Block([]),
                ),
            ),
        ])
        result = CodeGenerator().generate(ast)
        assert "mov ax, seg _data_start" in result
        assert "_data_start:" in result
        assert "mov ds, ax" in result
        # Must NOT clobber the loader-set SP, must NOT take DS from CS or SS.
        assert "mov sp, 0x" not in result
        assert "mov ax, cs" not in result
        assert "mov ax, ss" not in result
        # Stack segment is required so alink writes a valid SS:SP.
        assert "section .stack stack class=STACK" in result

    def test_params_at_natural_offsets(self) -> None:
        """Parameters must be accessed at [bp+4],[bp+6],... without copying."""
        asm = compile("int add(int a, int b) { return a + b; }")
        assert "[bp + 4]" in asm   # first param
        assert "[bp + 6]" in asm   # second param
        # No sub sp for parameter copies (registers are saved below BP, not params)
        lines = [l.strip() for l in asm.splitlines()]
        add_body = "\n".join(lines)
        # Ensure params are not being copied (no store to [bp - 0])
        assert "[bp - 0]" not in add_body

    def test_epilogue_restores_registers_from_fixed_offsets(self) -> None:
        """Epilogue must use mov from [bp-N], not pop, to restore saved registers."""
        asm = compile("int f(void) { return 0; }")
        assert "mov bx, [bp - 2]" in asm
        assert "mov cx, [bp - 4]" in asm
        assert "mov di, [bp - 10]" in asm
        # No bare pop of callee-saved regs (those come from wrong addresses after ret)
        assert "pop bx" not in asm
        assert "pop di" not in asm


class TestPointerArithmetic:
    def test_int_pointer_plus_scales_by_two(self) -> None:
        """`int *p; p + 1` must scale the integer by sizeof(int) = 2."""
        asm = compile("int f(int *p) { p = p + 1; return 0; }")
        # The right operand sits in BX and is shifted left by 1 before add.
        assert "shl bx, 1" in asm

    def test_char_pointer_plus_does_not_scale(self) -> None:
        """`char *p; p + 1` must not scale (sizeof(char) = 1)."""
        asm = compile("int f(char *p) { p = p + 1; return 0; }")
        assert "shl bx," not in asm

    def test_int_addition_unaffected(self) -> None:
        """Plain `int + int` must not gain spurious scaling."""
        asm = compile("int f(int a, int b) { return a + b; }")
        assert "shl bx," not in asm
        assert "shl ax," not in asm

    def test_int_pointer_postincrement_advances_by_two(self) -> None:
        """`int *p; p++` advances by 2 bytes."""
        asm = compile("int f(int *p) { p++; return 0; }")
        assert "add ax, 2" in asm
        # And not via the single-byte inc encoding.
        assert "inc ax" not in asm.split(".f_ret")[0]

    def test_char_pointer_postincrement_uses_inc(self) -> None:
        """`char *p; p++` keeps the cheaper `inc ax` (step = 1)."""
        asm = compile("int f(char *p) { p++; return 0; }")
        assert "inc ax" in asm
        assert "add ax, 1" not in asm


class TestBitwiseAndUnaryOps:
    def test_bitwise_and(self) -> None:
        asm = compile("int f(int a, int b) { return a & b; }")
        assert "and ax, bx" in asm

    def test_bitwise_or(self) -> None:
        asm = compile("int f(int a, int b) { return a | b; }")
        assert "or ax, bx" in asm

    def test_bitwise_xor(self) -> None:
        asm = compile("int f(int a, int b) { return a ^ b; }")
        assert "xor ax, bx" in asm

    def test_modulo_signed(self) -> None:
        asm = compile("int f(int a, int b) { return a % b; }")
        assert "idiv bx" in asm
        # remainder is moved from DX into AX
        assert "mov ax, dx" in asm

    def test_modulo_unsigned(self) -> None:
        asm = compile("int f(unsigned a, unsigned b) { return a % b; }")
        assert "div bx" in asm
        assert "idiv" not in asm
        assert "mov ax, dx" in asm

    def test_logical_not(self) -> None:
        asm = compile("int f(int a) { return !a; }")
        # `!a` tests AX and emits a 0/1, not bitwise.
        assert "test ax, ax" in asm
        assert "mov ax, 1" in asm
        assert "mov ax, 0" in asm

    def test_bitwise_not(self) -> None:
        asm = compile("int f(int a) { return ~a; }")
        assert "not ax" in asm

    def test_hex_literal(self) -> None:
        asm = compile("int f(void) { return 0xFF; }")
        assert "mov ax, 255" in asm


class TestShortCircuit:
    def test_and_skips_right_when_left_zero(self) -> None:
        """`a && side_effect()` must not emit the right-hand call in
        the path taken when `a == 0` — i.e. the call must come AFTER a
        conditional jump out, not before it.
        """
        asm = compile(
            "int side(void); int f(int a) { return a && side(); }"
        )
        # Find the first jz (the && short-circuit out) and the call to
        # `side`.  The jz must come BEFORE the call in source order.
        jz_idx = asm.find("jz ")
        call_idx = asm.find("call side")
        assert jz_idx != -1, "expected a jz for short-circuit"
        assert call_idx != -1, "expected a call to side"
        assert jz_idx < call_idx, "right-hand call should be guarded by jz"

    def test_or_skips_right_when_left_nonzero(self) -> None:
        """`a || side_effect()`: a jnz must come before the side call."""
        asm = compile(
            "int side(void); int f(int a) { return a || side(); }"
        )
        jnz_idx = asm.find("jnz ")
        call_idx = asm.find("call side")
        assert jnz_idx != -1
        assert call_idx != -1
        assert jnz_idx < call_idx

    def test_and_normalises_to_zero_or_one(self) -> None:
        asm = compile("int f(int a, int b) { return a && b; }")
        assert "mov ax, 1" in asm
        assert "mov ax, 0" in asm


class TestLongArithmetic:
    def test_long_add_uses_adc(self) -> None:
        """`long + long` emits the 32-bit carry-propagating sequence."""
        asm = compile("long f(long a, long b) { return a + b; }")
        assert "add ax, bx" in asm
        assert "adc dx, cx" in asm

    def test_long_sub_uses_sbb(self) -> None:
        asm = compile("long f(long a, long b) { return a - b; }")
        assert "sub ax, bx" in asm
        assert "sbb dx, cx" in asm

    def test_long_literal_loads_dx_ax(self) -> None:
        """A 32-bit literal must load both the low and high words."""
        asm = compile("long f(void) { return 100000L; }")
        # 100000 = 0x186A0 → low 0x86A0 = 34464, high 0x0001 = 1.
        assert "mov ax, 34464" in asm
        assert "mov dx, 1" in asm

    def test_long_local_reads_two_words(self) -> None:
        asm = compile("long f(long x) { return x; }")
        # Parameter `x` (long) sits at [bp+4], its high word at [bp+6].
        assert "mov ax, [bp + 4]" in asm
        assert "mov dx, [bp + 6]" in asm

    def test_long_unary_negate(self) -> None:
        asm = compile("long f(long a) { return -a; }")
        assert "neg ax" in asm
        assert "adc dx, 0" in asm
        assert "neg dx" in asm

    def test_long_return_does_not_restore_dx(self) -> None:
        """The epilogue must not clobber DX (it holds the high word of
        a 32-bit return value)."""
        asm = compile("long f(void) { return 0L; }")
        assert "mov dx, [bp - 6]" not in asm


class TestStdintAndLiteralSuffixes:
    def test_hex_literal_negative_int(self) -> None:
        """0xFFFF in source loads as 65535 (an int-sized constant)."""
        asm = compile("int f(void) { return 0xFFFF; }")
        assert "mov ax, 65535" in asm

    def test_long_literal_suffix(self) -> None:
        """`100L` parses with `long` type so the codegen emits DX too."""
        asm = compile("long f(void) { return 100L; }")
        assert "mov ax, 100" in asm
        assert "mov dx, 0" in asm

    def test_oversized_int_auto_promotes_to_long(self) -> None:
        """`1000000` doesn't fit in 16-bit int → promote to long."""
        asm = compile("long f(void) { return 1000000; }")
        # 1000000 = 0xF4240 → low 0x4240=16960, high 0xF=15.
        assert "mov ax, 16960" in asm
        assert "mov dx, 15" in asm


class TestFunctionPointers:
    def test_direct_call_uses_call_name(self) -> None:
        """A call to a function defined in the same TU emits a direct
        `call name`, not an indirect call via a register."""
        asm = compile(
            "int add(int a, int b) { return a + b; }"
            "int main(void) { return add(1, 2); }"
        )
        assert "call add" in asm
        assert "call ax" not in asm

    def test_indirect_call_via_param(self) -> None:
        """Calling through a function-pointer parameter emits
        `call ax` (the indirect-near-call form)."""
        asm = compile(
            "typedef int (*BinOp)(int, int);"
            "int apply(BinOp f, int a, int b) { return f(a, b); }"
        )
        assert "call ax" in asm

    def test_function_decay_loads_label_address(self) -> None:
        """Assigning a function name to a function pointer loads the
        function's label as an immediate address (`mov ax, add`), not
        as a memory read (`mov ax, [add]`)."""
        asm = compile(
            "int add(int a, int b) { return a + b; }"
            "typedef int (*BinOp)(int, int);"
            "int main(void) { BinOp p = add; return 0; }"
        )
        assert "mov ax, add" in asm
        assert "mov ax, [add]" not in asm

    def test_function_pointer_in_arg_list(self) -> None:
        """Passing a function name as an argument also decays to the
        function's address."""
        asm = compile(
            "int add(int a, int b) { return a + b; }"
            "typedef int (*BinOp)(int, int);"
            "int apply(BinOp f, int a, int b) { return f(a, b); }"
            "int main(void) { return apply(add, 1, 2); }"
        )
        # The `add` argument is loaded as a label address before push.
        assert "mov ax, add" in asm


class TestLvalueOps:
    def test_subscript_lhs_stores(self) -> None:
        """`arr[i] = v` emits a store at the indexed address."""
        asm = compile("int f(int *a) { a[1] = 99; return 0; }")
        # The store must use [bx] with a value that came from the
        # RHS evaluation (99), with the address computed via shl+add.
        assert "mov [bx], ax" in asm
        assert "mov ax, 99" in asm

    def test_deref_compound_assign_load_modify_store(self) -> None:
        """`*p += 1` reads via [bx], adds, writes back via [bx]."""
        asm = compile("int f(int *p) { *p += 1; return 0; }")
        assert "mov ax, [bx]" in asm
        assert "add ax, bx" in asm
        # Address is preserved across the load via push/pop.
        assert "push bx" in asm

    def test_arr_postincrement_returns_old(self) -> None:
        """`arr[i]++` emits store-back AND yields the old value."""
        asm = compile("int f(int *a) { return a[0]++; }")
        # The OLD value is saved on the stack, popped into CX, and
        # placed into AX via `mov ax, cx`.
        assert "push ax" in asm
        assert "mov ax, cx" in asm

    def test_char_pointer_store_uses_al(self) -> None:
        """`*p = c` for `char *p` writes a single byte via `[bx], al`."""
        asm = compile("int f(char *p) { *p = 65; return 0; }")
        assert "mov [bx], al" in asm
        # Wider stores would use AX.
        assert "mov [bx], ax" not in asm


class TestEnumConstants:
    def test_enum_constant_resolves(self) -> None:
        """An enum member appears as an integer literal in expressions."""
        asm = compile("enum { A = 7 }; int f(void) { return A; }")
        assert "mov ax, 7" in asm

    def test_enum_default_starts_at_zero_increments(self) -> None:
        asm = compile("enum { Z, O, T }; int f(void) { return T; }")
        # T = 2 by default sequencing.
        assert "mov ax, 2" in asm


class TestArrayAndStringInit:
    def test_int_array_init_three_stores(self) -> None:
        """`int a[3] = {1, 2, 3};` writes each element at its
        respective stack offset."""
        asm = compile("int main(void) { int a[3] = {1, 2, 3}; return 0; }")
        # Three stores, adjacent by 2 bytes.
        assert "mov ax, 1" in asm
        assert "mov ax, 2" in asm
        assert "mov ax, 3" in asm

    def test_char_array_string_init_inferred_size(self) -> None:
        """`char s[] = "ab";` allocates 3 bytes and writes 'a', 'b',
        and the NUL terminator."""
        asm = compile('int main(void) { char s[] = "ab"; return 0; }')
        # Bytes for 'a' (97), 'b' (98), and the NUL via xor al,al + store.
        assert "mov byte [bp + -13], 97" in asm
        assert "mov byte [bp + -12], 98" in asm
        assert "xor al, al" in asm
        # 3-byte allocation (inferred 2 chars + NUL).
        assert "sub sp, 3" in asm


class TestLong32MulDiv:
    def test_long_mul_calls_helper(self) -> None:
        asm = compile("long f(long a, long b) { return a * b; }")
        assert "call __mul32" in asm
        assert "add sp, 8" in asm

    def test_long_div_signed_helper(self) -> None:
        asm = compile("long f(long a, long b) { return a / b; }")
        assert "call __sdiv32" in asm

    def test_long_mod_unsigned_helper(self) -> None:
        asm = compile("unsigned long f(unsigned long a, unsigned long b) { return a % b; }")
        assert "call __umod32" in asm


class TestBitfieldGlobalInit:
    """Global struct initializers with bitfields are packed into .data."""

    def test_packed_bitfield_image(self) -> None:
        # code(short)=2 at offset 0; mode(:8)=7 at offset 2; x(:31)=1 at
        # offset 8.  pyc lays the long-long unit on an 8-byte boundary, so
        # the struct is 16 bytes → 8 words: [2, 7, 0, 0, 1, 0, 0, 0].
        asm = compile(
            "struct R { unsigned short code; long long :3; int mode:8; "
            "long long :0; long long x:31; long long y:31; } "
            "N = {2, 7, 1};"
        )
        assert "N: dw 2, 7, 0, 0, 1, 0, 0, 0" in asm

    def test_simple_bitfield_pack(self) -> None:
        # Two adjacent bitfields in one byte: a=1 (bit0), b=2 (bits1-2) →
        # byte 0 = 0b101 = 5.  char unit ⇒ 1 byte struct ⇒ 1 word "5".
        asm = compile(
            "struct S { unsigned char a:1; unsigned char b:2; } "
            "v = {1, 2};"
        )
        assert "v: dw 5" in asm

    def test_non_constant_struct_init_falls_back_to_bss(self) -> None:
        # A non-constant element can't be packed at compile time → reserve
        # zeroed BSS sized to the struct rather than emitting bad data.
        asm = compile(
            "extern int g; "
            "struct T { int a; int b; } t = {g, 1};"
        )
        assert "t: resw" in asm


class TestBitfieldRead:
    """Bitfield reads promote to a one-word int and extract across words."""

    def test_wide_field_read_is_single_word(self) -> None:
        # A long-long bitfield read must not push 4 words; the promoted
        # int result means a straddling field combines two words.
        asm = compile(
            "struct R { long long x:31; long long y:31; } N; "
            "int f(void) { return (int)N.y; }"
        )
        # y starts at bit 31 of the 64-bit unit → straddles words; the
        # extraction shifts and ORs in the neighbouring word.
        assert "or ax, dx" in asm
