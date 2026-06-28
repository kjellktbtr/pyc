; 32-bit integer print helpers used by printf for %ld / %lu.
;
; Cdecl ABI: a 32-bit argument occupies two stack slots, low word first
; ([bp+4] = low, [bp+6] = high).  Both routines call _putchar to emit
; each character and use no return value.

[bits 16]

global _print_long
global _print_ulong
global _print_llong
global _print_ullong
global __mul32
global __mul64
global __ret64_hi
global __udiv32
global __sdiv32
global __umod32
global __smod32

extern _putchar

section .text

; void _print_ulong(uint32_t n);
_print_ulong:
    push bp
    mov bp, sp
    push bx
    push cx
    push si
    push di
    mov di, [bp + 4]        ; di = low word
    mov si, [bp + 6]        ; si = high word
    call _emit_ulong_di_si
    pop di
    pop si
    pop cx
    pop bx
    mov sp, bp
    pop bp
    ret

; void _print_long(int32_t n);
_print_long:
    push bp
    mov bp, sp
    push bx
    push cx
    push si
    push di
    mov di, [bp + 4]        ; di = low word
    mov si, [bp + 6]        ; si = high word
    test si, si
    jns .nonneg
    ; Negative: print '-' and negate (two's complement of di:si).
    push ax
    mov ax, '-'
    push ax
    call _putchar
    add sp, 2
    pop ax
    neg di
    adc si, 0
    neg si
.nonneg:
    call _emit_ulong_di_si
    pop di
    pop si
    pop cx
    pop bx
    mov sp, bp
    pop bp
    ret

; Internal helper: prints the unsigned 32-bit value in si:di (high:low) in
; decimal.  Uses BX, CX, DX as scratch; preserves nothing else explicitly.
_emit_ulong_di_si:
    ; Special-case zero so the digit loop always emits at least one char.
    mov ax, di
    or ax, si
    jnz .build
    mov ax, '0'
    push ax
    call _putchar
    add sp, 2
    ret
.build:
    xor cx, cx              ; digit count
    mov bx, 10
.div_loop:
    ; Divide si:di by 10 using the "two-step" division trick:
    ;   1) ax = si / 10, remainder in dx
    ;   2) dx:ax (=dx*65536 + di) / 10  →  ax = low quotient, dx = remainder
    mov ax, si
    xor dx, dx
    div bx                  ; ax = si/10, dx = si%10
    mov si, ax              ; new high word of quotient
    mov ax, di
    div bx                  ; dx:ax / 10 → ax = low quotient, dx = remainder
    mov di, ax              ; new low word of quotient
    add dl, '0'             ; convert remainder to ASCII digit
    xor dh, dh
    push dx                 ; save digit
    inc cx
    ; Loop while quotient (si:di) != 0.
    mov ax, si
    or ax, di
    jnz .div_loop
.emit:
    pop ax
    push cx
    push ax
    call _putchar
    add sp, 2
    pop cx
    loop .emit
    ret

; -----------------------------------------------------------------------------
; 32-bit integer math runtime helpers (cdecl, 8086):
;     uint32_t __mul32 (uint32_t a, uint32_t b);
;     uint32_t __udiv32(uint32_t a, uint32_t b);
;     int32_t  __sdiv32(int32_t  a, int32_t  b);
;     uint32_t __umod32(uint32_t a, uint32_t b);
;     int32_t  __smod32(int32_t  a, int32_t  b);
;
; Cdecl: each 32-bit argument occupies two stack slots, low word first.
; Stack on entry:
;   [bp+ 4] = LHS low,  [bp+ 6] = LHS high
;   [bp+ 8] = RHS low,  [bp+10] = RHS high
; Result returned in DX:AX (high:low).
; -----------------------------------------------------------------------------

; __mul32 — 32x32 → low-32 multiply (schoolbook: a_lo*b_lo + (a_lo*b_hi + a_hi*b_lo) << 16)
__mul32:
    push bp
    mov bp, sp
    push bx
    push cx
    push si
    mov ax, [bp + 4]            ; ax = a_lo
    mul word [bp + 8]           ; dx:ax = a_lo * b_lo
    mov bx, ax                  ; bx = low(result)
    mov cx, dx                  ; cx = high(a_lo * b_lo)
    mov ax, [bp + 4]            ; ax = a_lo
    mul word [bp + 10]          ; dx:ax = a_lo * b_hi (only low matters)
    add cx, ax
    mov ax, [bp + 6]            ; ax = a_hi
    mul word [bp + 8]           ; dx:ax = a_hi * b_lo (only low matters)
    add cx, ax
    mov ax, bx                  ; ax = low(result)
    mov dx, cx                  ; dx = high(result)
    pop si
    pop cx
    pop bx
    pop bp
    ret

; Unsigned 32-bit divide: returns DX:AX = a / b.
__udiv32:
    push bp
    mov bp, sp
    push bx
    push cx
    push si
    push di
    mov si, [bp + 8]            ; divisor low
    mov di, [bp + 10]           ; divisor high
    ; Build a 2-word frame for the core: low at [new_bp+4], high at [new_bp+6].
    push word [bp + 6]          ; dividend high
    push word [bp + 4]          ; dividend low
    call __udiv32_core_entry
    add sp, 4
    pop di
    pop si
    pop cx
    pop bx
    pop bp
    ret

; Stack on entry to this trampoline:
;   [bp+ 4] = dividend low
;   [bp+ 6] = dividend high
;   DI:SI   = divisor
; Returns: DX:AX = quotient.
__udiv32_core_entry:
    push bp
    mov bp, sp
    ; Inline the core: long-division by repeated shift-subtract.
    sub sp, 2                   ; scratch high word
    mov ax, [bp + 6]
    mov [bp - 2], ax            ; scratch = dividend high
    mov ax, [bp + 4]            ; ax = dividend low (and quotient low)
    xor cx, cx                  ; remainder low
    xor bx, bx                  ; remainder high
    mov dx, 32
.bitloop2:
    shl ax, 1
    rcl word [bp - 2], 1
    rcl cx, 1
    rcl bx, 1
    cmp bx, di
    jb .skip2
    ja .sub2
    cmp cx, si
    jb .skip2
.sub2:
    sub cx, si
    sbb bx, di
    or ax, 1
.skip2:
    dec dx
    jnz .bitloop2
    mov dx, [bp - 2]            ; quotient high
    ; remainder is in BX:CX — caller's __umod32 wants it; expose via static cells.
    mov [__last_rem_lo], cx
    mov [__last_rem_hi], bx
    mov sp, bp
    pop bp
    ret

; Unsigned 32-bit modulo: returns DX:AX = a % b.
__umod32:
    push bp
    mov bp, sp
    push bx
    push cx
    push si
    push di
    push word [bp + 10]
    push word [bp + 8]
    push word [bp + 6]
    push word [bp + 4]
    call __udiv32
    add sp, 8
    mov ax, [__last_rem_lo]
    mov dx, [__last_rem_hi]
    pop di
    pop si
    pop cx
    pop bx
    pop bp
    ret

; Signed 32-bit divide: handle signs, dispatch to unsigned.
__sdiv32:
    push bp
    mov bp, sp
    push bx
    push cx
    push si
    push di
    xor cx, cx                  ; cx = sign flags (bit 0 dividend, bit 1 divisor)
    mov ax, [bp + 6]
    test ax, ax
    jns .div_pos
    mov ax, [bp + 4]
    neg ax
    mov [bp + 4], ax
    mov ax, [bp + 6]
    not ax
    adc ax, 0
    mov [bp + 6], ax
    or cx, 1
.div_pos:
    mov ax, [bp + 10]
    test ax, ax
    jns .div_call
    mov ax, [bp + 8]
    neg ax
    mov [bp + 8], ax
    mov ax, [bp + 10]
    not ax
    adc ax, 0
    mov [bp + 10], ax
    or cx, 2
.div_call:
    push word [bp + 10]
    push word [bp + 8]
    push word [bp + 6]
    push word [bp + 4]
    call __udiv32
    add sp, 8
    ; If exactly one input was negated, negate result.
    test cx, 3
    jpe .div_done               ; even parity → both or neither set
    neg ax
    not dx
    adc dx, 0
.div_done:
    pop di
    pop si
    pop cx
    pop bx
    pop bp
    ret

; Signed 32-bit modulo: result takes sign of dividend.
__smod32:
    push bp
    mov bp, sp
    push bx
    push cx
    push si
    push di
    xor cx, cx                  ; cx bit 0 = dividend negative
    mov ax, [bp + 6]
    test ax, ax
    jns .mod_pos
    mov ax, [bp + 4]
    neg ax
    mov [bp + 4], ax
    mov ax, [bp + 6]
    not ax
    adc ax, 0
    mov [bp + 6], ax
    or cx, 1
.mod_pos:
    mov ax, [bp + 10]
    test ax, ax
    jns .mod_call
    mov ax, [bp + 8]
    neg ax
    mov [bp + 8], ax
    mov ax, [bp + 10]
    not ax
    adc ax, 0
    mov [bp + 10], ax
.mod_call:
    push word [bp + 10]
    push word [bp + 8]
    push word [bp + 6]
    push word [bp + 4]
    call __umod32
    add sp, 8
    test cx, 1
    jz .mod_done
    neg ax
    not dx
    adc dx, 0
.mod_done:
    pop di
    pop si
    pop cx
    pop bx
    pop bp
    ret

; -----------------------------------------------------------------------------
; 64-bit integer math runtime helpers (cdecl, 8086):
;     uint64_t __mul64(uint64_t a, uint64_t b);
;
; Cdecl: each 64-bit argument occupies four stack slots, low word first.
; Stack on entry:
;   [bp+ 4] = a word 0 (lo), [bp+ 6] = a word 1, [bp+ 8] = a word 2, [bp+10] = a word 3 (hi)
;   [bp+12] = b word 0 (lo), [bp+14] = b word 1, [bp+16] = b word 2, [bp+18] = b word 3 (hi)
; Return convention: low 32 bits in DX:AX, high 32 bits in [__ret64_hi]/[__ret64_hi+2].
; -----------------------------------------------------------------------------

; __mul64 — 64x64 -> low-64 multiply via schoolbook 16x16 partial products.
__mul64:
    push bp
    mov bp, sp
    push bx
    push cx
    push si
    push di
    sub sp, 8                       ; result buffer at [bp-12..bp-5]
                                    ; words: [bp-12]=r0 lo, [bp-10]=r1, [bp-8]=r2, [bp-6]=r3 hi
    xor ax, ax
    mov [bp-12], ax
    mov [bp-10], ax
    mov [bp-8], ax
    mov [bp-6], ax

    ; A[0]*B[0] -> r[0..1]
    mov ax, [bp+4]
    mul word [bp+12]
    add [bp-12], ax
    adc [bp-10], dx
    adc word [bp-8], 0
    adc word [bp-6], 0
    ; A[0]*B[1] -> r[1..2]
    mov ax, [bp+4]
    mul word [bp+14]
    add [bp-10], ax
    adc [bp-8], dx
    adc word [bp-6], 0
    ; A[0]*B[2] -> r[2..3]
    mov ax, [bp+4]
    mul word [bp+16]
    add [bp-8], ax
    adc [bp-6], dx
    ; A[0]*B[3] -> r[3] (low word only)
    mov ax, [bp+4]
    mul word [bp+18]
    add [bp-6], ax
    ; A[1]*B[0] -> r[1..2]
    mov ax, [bp+6]
    mul word [bp+12]
    add [bp-10], ax
    adc [bp-8], dx
    adc word [bp-6], 0
    ; A[1]*B[1] -> r[2..3]
    mov ax, [bp+6]
    mul word [bp+14]
    add [bp-8], ax
    adc [bp-6], dx
    ; A[1]*B[2] -> r[3]
    mov ax, [bp+6]
    mul word [bp+16]
    add [bp-6], ax
    ; A[2]*B[0] -> r[2..3]
    mov ax, [bp+8]
    mul word [bp+12]
    add [bp-8], ax
    adc [bp-6], dx
    ; A[2]*B[1] -> r[3]
    mov ax, [bp+8]
    mul word [bp+14]
    add [bp-6], ax
    ; A[3]*B[0] -> r[3]
    mov ax, [bp+10]
    mul word [bp+12]
    add [bp-6], ax

    ; Stash high 32 bits in __ret64_hi for the caller to pick up.
    mov ax, [bp-8]
    mov [__ret64_hi], ax
    mov ax, [bp-6]
    mov [__ret64_hi + 2], ax
    ; Low 32 bits returned in DX:AX (high word of low half in DX).
    mov ax, [bp-12]
    mov dx, [bp-10]

    add sp, 8
    pop di
    pop si
    pop cx
    pop bx
    pop bp
    ret

; -----------------------------------------------------------------------------
; 64-bit integer print helpers used by printf for %llu/%lld.
; -----------------------------------------------------------------------------
_print_llong:
    push bp
    mov bp, sp
    push bx
    push cx
    push si
    push di
    mov ax, [bp+10]                 ; test sign of high word
    test ax, ax
    jns .pll_nonneg
    ; Negative: print '-' and negate the 64-bit value in the stack frame.
    push ax
    mov ax, '-'
    push ax
    call _putchar
    add sp, 2
    pop ax
    ; two's complement: negate w0 (sets CF=1 iff w0 was non-zero),
    ; then ~w_i - (-1) - CF for each upper word propagates the borrow
    ; correctly even when intermediate words were 0xFFFF.
    mov ax, [bp+4]
    neg ax
    mov [bp+4], ax
    mov ax, [bp+6]
    not ax
    sbb ax, -1
    mov [bp+6], ax
    mov ax, [bp+8]
    not ax
    sbb ax, -1
    mov [bp+8], ax
    mov ax, [bp+10]
    not ax
    sbb ax, -1
    mov [bp+10], ax
.pll_nonneg:
    ; Fall through to the unsigned emitter with the same stack frame.
    push word [bp+10]
    push word [bp+8]
    push word [bp+6]
    push word [bp+4]
    call _print_ullong
    add sp, 8
    pop di
    pop si
    pop cx
    pop bx
    mov sp, bp
    pop bp
    ret

; void _print_ullong(uint64_t n);
_print_ullong:
    push bp
    mov bp, sp
    push bx
    push cx
    push si
    push di
    sub sp, 8                       ; scratch copy of the value at [bp-12..bp-5]
                                    ; [bp-12]=w0 lo .. [bp-6]=w3 hi
    mov ax, [bp+4]
    mov [bp-12], ax
    mov ax, [bp+6]
    mov [bp-10], ax
    mov ax, [bp+8]
    mov [bp-8], ax
    mov ax, [bp+10]
    mov [bp-6], ax

    ; Special-case zero so the digit loop always emits at least one char.
    mov ax, [bp-12]
    or ax, [bp-10]
    or ax, [bp-8]
    or ax, [bp-6]
    jnz .pull_build
    mov ax, '0'
    push ax
    call _putchar
    add sp, 2
    jmp .pull_done

.pull_build:
    xor cx, cx                      ; digit count
    mov bx, 10
.pull_div_loop:
    ; Long-division by 10: walk from the high word down, carrying remainder in DX.
    xor dx, dx
    mov ax, [bp-6]                  ; w3
    div bx
    mov [bp-6], ax
    mov ax, [bp-8]                  ; w2 (with carry from w3 in dx)
    div bx
    mov [bp-8], ax
    mov ax, [bp-10]                 ; w1
    div bx
    mov [bp-10], ax
    mov ax, [bp-12]                 ; w0
    div bx
    mov [bp-12], ax
    ; dx now holds the remainder (current low digit).
    add dl, '0'
    xor dh, dh
    push dx                         ; save digit
    inc cx
    ; Loop while quotient != 0
    mov ax, [bp-12]
    or ax, [bp-10]
    or ax, [bp-8]
    or ax, [bp-6]
    jnz .pull_div_loop

.pull_emit:
    pop ax
    push cx
    push ax
    call _putchar
    add sp, 2
    pop cx
    loop .pull_emit

.pull_done:
    add sp, 8
    pop di
    pop si
    pop cx
    pop bx
    mov sp, bp
    pop bp
    ret

; Static storage for the last division remainder so __umod32 can
; recover it after __udiv32 returns.  Placed in .data with explicit
; initial zero so it lives in DGROUP alongside the rest of the program
; data and is addressable via DS without segment overrides.
section .data
__last_rem_lo: dw 0
__last_rem_hi: dw 0

section .bss
__ret64_hi: resw 2

; Assign data/bss to DGROUP so the linker places them with the program's
; DGROUP rather than at a fixed offset that can overlap a large program's
; in-BSS stack/heap.
group DGROUP data bss
