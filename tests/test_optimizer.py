"""Tests for the peephole optimizer."""

import pytest
from src.pyc.optimizer import (
    optimize,
    OptStats,
    _pass_push_pop_cancel,
    _pass_redundant_mov,
    _pass_zero_arith,
    _pass_stack_balance,
    _pass_store_reload,
    _pass_jmp_to_next,
)


class TestPushPopCancel:
    """Test push/pop cancellation pass."""

    def test_adjacent_push_pop_same_reg(self):
        """push ax / pop ax → eliminated."""
        lines = ["push ax", "pop ax"]
        stats = OptStats()
        result = _pass_push_pop_cancel(lines, stats)
        assert result == []
        assert stats.push_pop_cancel == 2

    def test_nested_push_pop_lifo(self):
        """push ax; push bx; pop bx; pop ax → all eliminated (LIFO)."""
        lines = ["push ax", "push bx", "pop bx", "pop ax"]
        stats = OptStats()
        result = _pass_push_pop_cancel(lines, stats)
        assert result == []
        assert stats.push_pop_cancel == 4

    def test_mismatched_pop_keeps_all(self):
        """push ax; push bx; pop cx → mismatch, keep all."""
        lines = ["push ax", "push bx", "pop cx"]
        stats = OptStats()
        result = _pass_push_pop_cancel(lines, stats)
        assert len(result) == 3
        assert stats.push_pop_cancel == 0

    def test_call_breaks_tracking(self):
        """call breaks push/pop tracking."""
        lines = ["push ax", "call foo", "pop ax"]
        stats = OptStats()
        result = _pass_push_pop_cancel(lines, stats)
        assert len(result) == 3
        assert stats.push_pop_cancel == 0

    def test_label_breaks_tracking(self):
        """Labels are kept and break tracking."""
        lines = ["push ax", ".my_label:", "pop ax"]
        stats = OptStats()
        result = _pass_push_pop_cancel(lines, stats)
        assert len(result) == 3
        assert ".my_label:" in result

    def test_partial_cancel_with_other_instr(self):
        """push ax; push bx; pop bx; mov cx, 1; pop ax → cancel push/pop bx, keep rest."""
        lines = ["push ax", "push bx", "pop bx", "mov cx, 1", "pop ax"]
        stats = OptStats()
        result = _pass_push_pop_cancel(lines, stats)
        # push bx / pop bx cancelled (adjacent, intervening=0)
        # push ax / pop ax kept (intervening mov cx,1 means not adjacent)
        assert len(result) == 3
        assert result == ["push ax", "mov cx, 1", "pop ax"]
        assert stats.push_pop_cancel == 2

    def test_nonadjacent_push_pop_kept(self):
        """push ax; mov ax, 1; pop ax → kept (not adjacent, intervening instr)."""
        lines = ["push ax", "mov ax, 1", "pop ax"]
        stats = OptStats()
        result = _pass_push_pop_cancel(lines, stats)
        assert len(result) == 3
        assert stats.push_pop_cancel == 0

    def test_nested_push_pop_with_intervening(self):
        """push ax; push bx; mov ax, 5; pop bx; pop ax → bx pair kept (intervening mov), ax pair kept."""
        lines = ["push ax", "push bx", "mov ax, 5", "pop bx", "pop ax"]
        stats = OptStats()
        result = _pass_push_pop_cancel(lines, stats)
        # pop bx: intervening=1 (mov ax,5) → not adjacent → keep all
        # pop ax: also kept
        assert len(result) == 5
        assert stats.push_pop_cancel == 0

    def test_directive_breaks_window(self):
        """section directive breaks the push/pop window."""
        lines = ["push ax", "section .data", "pop ax"]
        stats = OptStats()
        result = _pass_push_pop_cancel(lines, stats)
        assert len(result) == 3

    def test_comment_breaks_window(self):
        """Comment line breaks the push/pop window."""
        lines = ["push ax", "; comment", "pop ax"]
        stats = OptStats()
        result = _pass_push_pop_cancel(lines, stats)
        assert len(result) == 3

    def test_blank_line_breaks_window(self):
        """Blank line breaks the push/pop window."""
        lines = ["push ax", "", "pop ax"]
        stats = OptStats()
        result = _pass_push_pop_cancel(lines, stats)
        assert len(result) == 3

    def test_multiple_regs(self):
        """push si; push di; pop di; pop si → all eliminated."""
        lines = ["push si", "push di", "pop di", "pop si"]
        stats = OptStats()
        result = _pass_push_pop_cancel(lines, stats)
        assert result == []
        assert stats.push_pop_cancel == 4

    def test_case_insensitive(self):
        """Push/pop matching is case-insensitive."""
        lines = ["PUSH AX", "pop ax"]
        stats = OptStats()
        result = _pass_push_pop_cancel(lines, stats)
        assert result == []


class TestRedundantMov:
    """Test redundant move elimination."""

    def test_mov_reg_reg_eliminated(self):
        lines = ["mov ax, ax"]
        stats = OptStats()
        result = _pass_redundant_mov(lines, stats)
        assert result == []
        assert stats.redundant_mov == 1

    def test_mov_different_regs_kept(self):
        lines = ["mov ax, bx"]
        stats = OptStats()
        result = _pass_redundant_mov(lines, stats)
        assert len(result) == 1

    def test_mov_reg_reg_case_insensitive(self):
        lines = ["MOV AX, ax"]
        stats = OptStats()
        result = _pass_redundant_mov(lines, stats)
        assert result == []


class TestZeroArith:
    """Test zero add/sub/xor elimination (flag-aware)."""

    def test_add_zero_dropped_when_flags_dead(self):
        # Following `cmp` overwrites the flags `add ax, 0` would set → safe.
        lines = ["add ax, 0", "cmp bx, cx"]
        stats = OptStats()
        result = _pass_zero_arith(lines, stats)
        assert result == ["cmp bx, cx"]
        assert stats.zero_add_sub == 1

    def test_sub_zero_dropped_when_flags_dead(self):
        lines = ["sub bx, 0", "cmp ax, dx"]
        stats = OptStats()
        result = _pass_zero_arith(lines, stats)
        assert result == ["cmp ax, dx"]

    def test_xor_zero_dropped_when_flags_dead(self):
        lines = ["xor cx, 0", "test ax, ax"]
        stats = OptStats()
        result = _pass_zero_arith(lines, stats)
        assert result == ["test ax, ax"]

    def test_kept_before_flag_reader(self):
        # `jz` consumes ZF that `add ax, 0` writes → must not delete.
        lines = ["add ax, 0", "jz .L"]
        stats = OptStats()
        result = _pass_zero_arith(lines, stats)
        assert result == lines
        assert stats.zero_add_sub == 0

    def test_kept_at_end_of_stream(self):
        # No following flag-clobber proves the flags are dead → conservatively keep.
        lines = ["add ax, 0"]
        stats = OptStats()
        result = _pass_zero_arith(lines, stats)
        assert result == ["add ax, 0"]
        assert stats.zero_add_sub == 0

    def test_dropped_across_neutral_instruction(self):
        # mov is flag-neutral; the later cmp still kills the flags → safe.
        lines = ["add ax, 0", "mov dx, 5", "cmp bx, cx"]
        stats = OptStats()
        result = _pass_zero_arith(lines, stats)
        assert result == ["mov dx, 5", "cmp bx, cx"]
        assert stats.zero_add_sub == 1

    def test_add_nonzero_kept(self):
        lines = ["add ax, 1", "cmp bx, cx"]
        stats = OptStats()
        result = _pass_zero_arith(lines, stats)
        assert "add ax, 1" in result


class TestStackBalance:
    """Test stack balance cancellation."""

    def test_add_sub_cancel(self):
        lines = ["add sp, 4", "sub sp, 4", "cmp ax, bx"]
        stats = OptStats()
        result = _pass_stack_balance(lines, stats)
        assert result == ["cmp ax, bx"]
        assert stats.stack_balance == 2

    def test_sub_add_cancel(self):
        lines = ["sub sp, 2", "add sp, 2", "test ax, ax"]
        stats = OptStats()
        result = _pass_stack_balance(lines, stats)
        assert result == ["test ax, ax"]

    def test_kept_before_flag_reader(self):
        # `jz` reads ZF; cancelling the pair would alter it → must not cancel.
        lines = ["add sp, 4", "sub sp, 4", "jz .L"]
        stats = OptStats()
        result = _pass_stack_balance(lines, stats)
        assert result == lines
        assert stats.stack_balance == 0

    def test_mismatch_kept(self):
        lines = ["add sp, 4", "sub sp, 2"]
        stats = OptStats()
        result = _pass_stack_balance(lines, stats)
        assert len(result) == 2

    def test_non_adjacent_kept(self):
        lines = ["add sp, 4", "mov ax, 1", "sub sp, 4"]
        stats = OptStats()
        result = _pass_stack_balance(lines, stats)
        assert len(result) == 3


class TestStoreReload:
    """Test store/reload elimination."""

    def test_reload_into_same_reg_dropped(self):
        lines = ["mov [bp - 2], ax", "mov ax, [bp - 2]"]
        stats = OptStats()
        result = _pass_store_reload(lines, stats)
        assert result == ["mov [bp - 2], ax"]
        assert stats.store_reload == 1

    def test_reload_into_other_reg_becomes_regmove(self):
        lines = ["mov [bp - 2], ax", "mov bx, [bp - 2]"]
        stats = OptStats()
        result = _pass_store_reload(lines, stats)
        assert result == ["mov [bp - 2], ax", "mov bx, ax"]
        assert stats.store_reload == 1

    def test_different_memory_kept(self):
        lines = ["mov [bp - 2], ax", "mov bx, [bp - 4]"]
        stats = OptStats()
        result = _pass_store_reload(lines, stats)
        assert result == lines
        assert stats.store_reload == 0

    def test_size_mismatch_kept(self):
        # Byte store then word reload reads an unwritten high byte → must not fold.
        lines = ["mov [bp - 2], al", "mov ax, [bp - 2]"]
        stats = OptStats()
        result = _pass_store_reload(lines, stats)
        assert result == lines
        assert stats.store_reload == 0

    def test_non_adjacent_kept(self):
        lines = ["mov [bp - 2], ax", "nop", "mov ax, [bp - 2]"]
        stats = OptStats()
        result = _pass_store_reload(lines, stats)
        assert len(result) == 3
        assert stats.store_reload == 0


class TestJmpToNext:
    """Test jump-to-next-line elimination."""

    def test_jmp_to_following_label_dropped(self):
        lines = ["jmp .L1", ".L1:"]
        stats = OptStats()
        result = _pass_jmp_to_next(lines, stats)
        assert result == [".L1:"]
        assert stats.jmp_to_next == 1

    def test_jmp_skips_blank_and_comment(self):
        lines = ["jmp .ret", "", "; epilogue", ".ret:"]
        stats = OptStats()
        result = _pass_jmp_to_next(lines, stats)
        assert "jmp .ret" not in result
        assert ".ret:" in result
        assert stats.jmp_to_next == 1

    def test_jmp_to_other_label_kept(self):
        lines = ["jmp .far", ".near:", ".far:"]
        stats = OptStats()
        result = _pass_jmp_to_next(lines, stats)
        assert "jmp .far" in result
        assert stats.jmp_to_next == 0

    def test_jmp_with_intervening_instruction_kept(self):
        lines = ["jmp .L", "mov ax, 1", ".L:"]
        stats = OptStats()
        result = _pass_jmp_to_next(lines, stats)
        assert "jmp .L" in result
        assert stats.jmp_to_next == 0

    def test_indirect_jmp_kept(self):
        lines = ["jmp word [bx]", ".L:"]
        stats = OptStats()
        result = _pass_jmp_to_next(lines, stats)
        assert "jmp word [bx]" in result
        assert stats.jmp_to_next == 0


class TestFullOptimize:
    """Test the full optimize() API."""

    def test_push_pop_in_full_asm(self):
        asm = """section .text
push ax
push bx
pop bx
pop ax
mov cx, 1"""
        optimized, stats = optimize(asm)
        assert "push ax" not in optimized
        assert "push bx" not in optimized
        assert "pop bx" not in optimized
        assert "pop ax" not in optimized
        assert "mov cx, 1" in optimized

    def test_stats_tracking(self):
        # Trailing `cmp` makes `add cx, 0`'s flags dead so it is removed too.
        asm = "push ax\npop ax\nmov bx, bx\nadd cx, 0\ncmp ax, bx"
        optimized, stats = optimize(asm)
        assert stats.total >= 4  # push/pop (2) + mov bx,bx (1) + add cx,0 (1)

    def test_no_change_returns_early(self):
        """Assembly with no optimizable patterns returns unchanged."""
        asm = "mov ax, 1\npush ax\ncall foo\npop ax"
        optimized, stats = optimize(asm)
        assert stats.total == 0
        assert optimized == asm
