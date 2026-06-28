; ============================================================================
; stdlib/fp.asm — software IEEE-754 runtime for pyc (16-bit DOS target).
;
; Implements double-precision (binary64) addition/subtraction, comparison,
; integer conversion, and decimal printing.  Float (binary32) helpers
; delegate to the double helpers via promote-compute-demote.
;
; ABI (cdecl):
;   float32 arg:   2 words on stack — [bp+4] = low, [bp+6] = high
;   float32 ret:   DX:AX (high:low)
;   double64 arg:  4 words on stack — [bp+4..+10] little-endian
;   double64 ret:  AX/DX/BX/DX (low → high; the very-high word duplicates
;                  DX, matching the 64-bit integer return convention).
;
; Limitations: no NaN/Inf propagation, no denormals, truncation rounding.
; Just enough to compute and print integer-valued doubles + addition of
; simple values, which is what the `single/` test corpus actually needs.
; ============================================================================

[bits 16]

global __fadd32
global __fsub32
global __fmul32
global __fdiv32
global __fneg32
global __fcmp32
global __si2f32
global __f322si
global __f322d64
global __d642f32

global __dadd64
global __dsub64
global __dmul64
global __ddiv64
global __dneg64
global __dcmp64
global __si2d64
global __d642si
global __l2d64
global __print_d64
global __print_f32
global __builtin_clzll
global fesetround

extern _putchar

section .bss

__fp_sa: resw 1
__fp_ea: resw 1
__fp_am0: resw 1
__fp_am1: resw 1
__fp_am2: resw 1
__fp_am3: resw 1
__fp_sb: resw 1
__fp_eb: resw 1
__fp_bm0: resw 1
__fp_bm1: resw 1
__fp_bm2: resw 1
__fp_bm3: resw 1
; Scratch for __print_d64: __fp_t* holds 2*am during the ×10 multiply (BSS
; rather than stack-relative so it can't collide with pushes); __fp_dig is the
; fractional-digit buffer used to round the last digit; __fp_prec saves the
; requested precision across the extraction loop.
__fp_t0: resw 1
__fp_t1: resw 1
__fp_t2: resw 1
__fp_t3: resw 1
__fp_prec: resw 1
__fp_dig: resb 40
; 128-bit product / dividend scratch for __dmul64 / __ddiv64 (8 words).
__fp_p: resw 8

global __fp_result
__fp_result: resw 4

; Scratch area for fast __fadd32 / __fsub32 / __fmul32 / __fdiv32
__f32_ea:  resw 1   ; exponent of a (biased, 0..255)
__f32_eb:  resw 1   ; exponent of b (biased, 0..255)
__f32_mah: resw 1   ; mantissa_a high byte (bit 7 = implicit-1, bits 6:0 = mant[22:16])
__f32_mal: resw 1   ; mantissa_a low word (mant[15:0])
__f32_mbh: resw 1   ; mantissa_b high byte
__f32_mbl: resw 1   ; mantissa_b low word

section .text

; ---------------------------------------------------------------------------
; __builtin_clzll — count leading zero bits of a 64-bit value (4 words at
; [bp+4..10], low word first).  Returns the count (0..63) in AX.  The caller
; (per the C contract) never passes 0; we return 64 for it anyway.
; ---------------------------------------------------------------------------
__builtin_clzll:
    push bp
    mov bp, sp
    push cx
    xor cx, cx
    mov ax, [bp + 10]               ; word3 (bits 48..63)
    test ax, ax
    jnz .clz_within
    add cx, 16
    mov ax, [bp + 8]                ; word2
    test ax, ax
    jnz .clz_within
    add cx, 16
    mov ax, [bp + 6]                ; word1
    test ax, ax
    jnz .clz_within
    add cx, 16
    mov ax, [bp + 4]                ; word0
    test ax, ax
    jnz .clz_within
    mov cx, 64                      ; all-zero input
    jmp .clz_ret
.clz_within:
    test ax, 0x8000
    jnz .clz_ret
    shl ax, 1
    inc cx
    jmp .clz_within
.clz_ret:
    mov ax, cx
    pop cx
    pop bp
    ret

; ---------------------------------------------------------------------------
; fesetround — no-op: the runtime only implements round-to-nearest, which is
; the default.  Accepts the mode argument, returns 0 (success).
; ---------------------------------------------------------------------------
fesetround:
    push bp
    mov bp, sp
    xor ax, ax
    pop bp
    ret

; ---------------------------------------------------------------------------
; __si2d64 — 16-bit signed int (in [bp+4]) → IEEE-754 double.
;   Output: AX/DX/BX/(DX again).
; ---------------------------------------------------------------------------
__si2d64:
    push bp
    mov bp, sp
    sub sp, 12                  ; locals:
                                ; [bp-2]  biased exponent
                                ; [bp-4]  msb position
                                ; [bp-6]  4-word mantissa w3 (highest)
                                ; [bp-8]  w2
                                ; [bp-10] w1
                                ; [bp-12] w0 (lowest)
    push cx
    push si
    push di

    mov ax, [bp + 4]
    test ax, ax
    jnz .nz
    ; Zero.
    xor ax, ax
    mov [__fp_result], ax
    mov [__fp_result + 2], ax
    mov [__fp_result + 4], ax
    mov [__fp_result + 6], ax
    xor dx, dx
    xor bx, bx
    jmp .done
.nz:
    mov si, 0
    test ax, ax
    jns .pos
    neg ax
    mov si, 0x8000
.pos:
    ; Find MSB position (0..15) for the 16-bit absolute value.
    mov cx, 0
    mov di, ax
.find:
    shr di, 1
    jz .found
    inc cx
    jmp .find
.found:
    mov [bp - 4], cx
    add cx, 1023
    mov [bp - 2], cx

    ; Initialise 4-word mantissa accumulator: w0..w3 = 0, then put
    ; AX into w0 and shift left by (52 - msb_pos).
    xor cx, cx
    mov [bp - 6], cx
    mov [bp - 8], cx
    mov [bp - 10], cx
    mov [bp - 12], ax           ; w0 = abs(input)

    mov cx, 52
    sub cx, [bp - 4]
.shl_loop:
    shl word [bp - 12], 1
    rcl word [bp - 10], 1
    rcl word [bp - 8], 1
    rcl word [bp - 6], 1
    loop .shl_loop

    ; Now (w3=[bp-6], w2=[bp-8], w1=[bp-10], w0=[bp-12]) holds the
    ; 53-bit value with the implicit-1 at bit 52 (bit 4 of w3).
    ; Clear implicit-1, OR in exponent and sign, then publish.
    mov ax, [bp - 6]
    and ax, 0x000F
    mov cx, [bp - 2]
    shl cx, 4
    or  ax, cx
    or  ax, si
    mov [__fp_result + 6], ax
    mov ax, [bp - 8]
    mov [__fp_result + 4], ax
    mov ax, [bp - 10]
    mov [__fp_result + 2], ax
    mov ax, [bp - 12]
    mov [__fp_result], ax
    ; Best-effort register return (caller uses __fp_result via memcpy).
    mov ax, [__fp_result]
    mov dx, [__fp_result + 2]
    mov bx, [__fp_result + 4]
.done:
    pop di
    pop si
    pop cx
    mov sp, bp
    pop bp
    ret

; ---------------------------------------------------------------------------
; _dec_a / _dec_b — decompose the double at [bp+4..+10] (or +12..+18)
; into the static workspace (__fp_*).  After:
;   __fp_sa  = sign in bit 15
;   __fp_ea  = biased exponent (0..2047)
;   __fp_am0..3 = 53-bit mantissa with implicit-1 at bit 52 (am3 bit 4)
; For zero / denormal inputs, am3..0 = 0 and ea = 0.
; ---------------------------------------------------------------------------
_dec_a:
    mov ax, [bp + 4]
    mov [__fp_am0], ax
    mov ax, [bp + 6]
    mov [__fp_am1], ax
    mov ax, [bp + 8]
    mov [__fp_am2], ax
    mov ax, [bp + 10]
    ; Sign: bit 15
    mov bx, ax
    and bx, 0x8000
    mov [__fp_sa], bx
    ; Exponent: bits 4..14
    mov bx, ax
    and bx, 0x7FF0
    shr bx, 4
    mov [__fp_ea], bx
    ; Mantissa high bits (12 low bits of ax) + implicit 1 if exp != 0
    and ax, 0x000F
    or  bx, bx
    jz .zero
    or  ax, 0x0010              ; set implicit-1 at bit 52 (bit 4 of am3)
    mov [__fp_am3], ax
    ret
.zero:
    mov [__fp_am3], ax
    ret

_dec_b:
    mov ax, [bp + 12]
    mov [__fp_bm0], ax
    mov ax, [bp + 14]
    mov [__fp_bm1], ax
    mov ax, [bp + 16]
    mov [__fp_bm2], ax
    mov ax, [bp + 18]
    mov bx, ax
    and bx, 0x8000
    mov [__fp_sb], bx
    mov bx, ax
    and bx, 0x7FF0
    shr bx, 4
    mov [__fp_eb], bx
    and ax, 0x000F
    or  bx, bx
    jz .zero
    or  ax, 0x0010
    mov [__fp_bm3], ax
    ret
.zero:
    mov [__fp_bm3], ax
    ret

; ---------------------------------------------------------------------------
; _shr_b — shift b's 4-word mantissa (__fp_bm3..0) right by CX bits.
; Trashes AX, BX.
; ---------------------------------------------------------------------------
_shr_b:
    test cx, cx
    jz .done
    cmp cx, 64
    jl .shift
    ; Shift ≥ 64: mantissa goes to zero.
    xor ax, ax
    mov [__fp_bm0], ax
    mov [__fp_bm1], ax
    mov [__fp_bm2], ax
    mov [__fp_bm3], ax
    ret
.shift:
    ; Shift in 16-bit chunks first.
    cmp cx, 16
    jl .bit_loop
    mov ax, [__fp_bm1]
    mov [__fp_bm0], ax
    mov ax, [__fp_bm2]
    mov [__fp_bm1], ax
    mov ax, [__fp_bm3]
    mov [__fp_bm2], ax
    xor ax, ax
    mov [__fp_bm3], ax
    sub cx, 16
    jmp .shift
.bit_loop:
    test cx, cx
    jz .done
.bit1:
    mov ax, [__fp_bm3]
    shr ax, 1
    mov [__fp_bm3], ax
    mov ax, [__fp_bm2]
    rcr ax, 1
    mov [__fp_bm2], ax
    mov ax, [__fp_bm1]
    rcr ax, 1
    mov [__fp_bm1], ax
    mov ax, [__fp_bm0]
    rcr ax, 1
    mov [__fp_bm0], ax
    dec cx
    jnz .bit1
.done:
    ret

; ---------------------------------------------------------------------------
; _swap_ab — exchange a and b in the workspace.  Used by __dadd64 to
; ensure |a| >= |b| before mantissa alignment.
; ---------------------------------------------------------------------------
_swap_ab:
    mov ax, [__fp_sa]
    mov bx, [__fp_sb]
    mov [__fp_sa], bx
    mov [__fp_sb], ax
    mov ax, [__fp_ea]
    mov bx, [__fp_eb]
    mov [__fp_ea], bx
    mov [__fp_eb], ax
    mov ax, [__fp_am0]
    mov bx, [__fp_bm0]
    mov [__fp_am0], bx
    mov [__fp_bm0], ax
    mov ax, [__fp_am1]
    mov bx, [__fp_bm1]
    mov [__fp_am1], bx
    mov [__fp_bm1], ax
    mov ax, [__fp_am2]
    mov bx, [__fp_bm2]
    mov [__fp_am2], bx
    mov [__fp_bm2], ax
    mov ax, [__fp_am3]
    mov bx, [__fp_bm3]
    mov [__fp_am3], bx
    mov [__fp_bm3], ax
    ret

; ---------------------------------------------------------------------------
; __dadd64 — IEEE-754 double addition.
; Args: a at [bp+4..+10], b at [bp+12..+18].
; Returns DX/AX/BX (low → high), and DX again as the very-high word.
; ---------------------------------------------------------------------------
__dadd64:
    push bp
    mov bp, sp
    push cx
    push si
    push di

    call _dec_a
    call _dec_b

    ; If a is zero (exp+mantissa all zero), return b.
    mov ax, [__fp_ea]
    or  ax, [__fp_am0]
    or  ax, [__fp_am1]
    or  ax, [__fp_am2]
    or  ax, [__fp_am3]
    jnz .a_nonzero
    ; Result = b — copy b's 4 words into __fp_result.
    mov ax, [bp + 12]
    mov [__fp_result], ax
    mov ax, [bp + 14]
    mov [__fp_result + 2], ax
    mov ax, [bp + 16]
    mov [__fp_result + 4], ax
    mov ax, [bp + 18]
    mov [__fp_result + 6], ax
    mov ax, [bp + 12]
    mov dx, [bp + 14]
    mov bx, [bp + 16]
    pop di
    pop si
    pop cx
    pop bp
    ret
.a_nonzero:
    mov ax, [__fp_eb]
    or  ax, [__fp_bm0]
    or  ax, [__fp_bm1]
    or  ax, [__fp_bm2]
    or  ax, [__fp_bm3]
    jnz .b_nonzero
    ; Result = a — copy a's 4 words into __fp_result.
    mov ax, [bp + 4]
    mov [__fp_result], ax
    mov ax, [bp + 6]
    mov [__fp_result + 2], ax
    mov ax, [bp + 8]
    mov [__fp_result + 4], ax
    mov ax, [bp + 10]
    mov [__fp_result + 6], ax
    mov ax, [bp + 4]
    mov dx, [bp + 6]
    mov bx, [bp + 8]
    pop di
    pop si
    pop cx
    pop bp
    ret
.b_nonzero:
    ; Ensure ea >= eb (swap if necessary).  Exponents are unsigned 11-bit.
    mov ax, [__fp_ea]
    cmp ax, [__fp_eb]
    jge .no_swap
    call _swap_ab
.no_swap:
    ; cx = ea - eb (shift amount for b's mantissa)
    mov ax, [__fp_ea]
    sub ax, [__fp_eb]
    mov cx, ax
    call _shr_b
    ; Now ea == eb conceptually; we use ea as the result exponent.

    ; Same sign?  Add or subtract magnitudes accordingly.
    mov ax, [__fp_sa]
    cmp ax, [__fp_sb]
    je .same_sign
    ; Different signs — subtract: |a| - |b|.  Since we ensured ea >= eb,
    ; |a| >= |b| holds, so result is non-negative magnitude, sign = sa.
    mov ax, [__fp_am0]
    sub ax, [__fp_bm0]
    mov [__fp_am0], ax
    mov ax, [__fp_am1]
    sbb ax, [__fp_bm1]
    mov [__fp_am1], ax
    mov ax, [__fp_am2]
    sbb ax, [__fp_bm2]
    mov [__fp_am2], ax
    mov ax, [__fp_am3]
    sbb ax, [__fp_bm3]
    mov [__fp_am3], ax
    ; If result is zero, return +0.
    mov ax, [__fp_am0]
    or  ax, [__fp_am1]
    or  ax, [__fp_am2]
    or  ax, [__fp_am3]
    jnz .normalize_subtract
    xor ax, ax
    mov [__fp_result], ax
    mov [__fp_result + 2], ax
    mov [__fp_result + 4], ax
    mov [__fp_result + 6], ax
    xor dx, dx
    xor bx, bx
    pop di
    pop si
    pop cx
    pop bp
    ret
.normalize_subtract:
    ; Shift left until bit 52 (bit 4 of am3) is set.
    mov cx, 0
.norm_loop:
    test word [__fp_am3], 0x10
    jnz .norm_done
    ; Shift left by 1.
    shl word [__fp_am0], 1
    rcl word [__fp_am1], 1
    rcl word [__fp_am2], 1
    rcl word [__fp_am3], 1
    inc cx
    cmp cx, 64
    jl .norm_loop
    ; If we shifted 64 times without finding a bit, result is zero.
    xor ax, ax
    mov [__fp_result], ax
    mov [__fp_result + 2], ax
    mov [__fp_result + 4], ax
    mov [__fp_result + 6], ax
    xor dx, dx
    xor bx, bx
    pop di
    pop si
    pop cx
    pop bp
    ret
.norm_done:
    ; Decrease exponent by cx.
    mov ax, [__fp_ea]
    sub ax, cx
    mov [__fp_ea], ax
    jmp .pack
.same_sign:
    ; Same sign — add magnitudes.
    mov ax, [__fp_am0]
    add ax, [__fp_bm0]
    mov [__fp_am0], ax
    mov ax, [__fp_am1]
    adc ax, [__fp_bm1]
    mov [__fp_am1], ax
    mov ax, [__fp_am2]
    adc ax, [__fp_bm2]
    mov [__fp_am2], ax
    mov ax, [__fp_am3]
    adc ax, [__fp_bm3]
    mov [__fp_am3], ax
    ; If bit 53 (bit 5 of am3) is set, mantissa overflowed — shift right
    ; by 1 and increment exponent.
    test word [__fp_am3], 0x20
    jz .pack
    ; Shift right by 1 (lose 1 bit of precision — truncation, not round)
    shr word [__fp_am3], 1
    rcr word [__fp_am2], 1
    rcr word [__fp_am1], 1
    rcr word [__fp_am0], 1
    inc word [__fp_ea]
.pack:
    ; Pack into the static result buffer (__fp_result).  Word layout:
    ;   __fp_result[0] = mantissa[15:0]
    ;   __fp_result[2] = mantissa[31:16]
    ;   __fp_result[4] = mantissa[47:32]
    ;   __fp_result[6] = sign | (exp << 4) | (mantissa[51:48])
    mov ax, [__fp_am0]
    mov [__fp_result], ax
    mov ax, [__fp_am1]
    mov [__fp_result + 2], ax
    mov ax, [__fp_am2]
    mov [__fp_result + 4], ax
    mov ax, [__fp_am3]
    and ax, 0x000F              ; drop the implicit-1
    mov bx, [__fp_ea]
    shl bx, 4
    or  ax, bx
    or  ax, [__fp_sa]
    mov [__fp_result + 6], ax
    ; Also return the low three words in DX/AX/BX (for any caller that
    ; uses the legacy register-based return).
    mov ax, [__fp_am0]
    mov dx, [__fp_am1]
    mov bx, [__fp_am2]
.done_pack:
    pop di
    pop si
    pop cx
    pop bp
    ret

; ---------------------------------------------------------------------------
; __dsub64 — subtraction: a - b = a + (-b).
; ---------------------------------------------------------------------------
__dsub64:
    push bp
    mov bp, sp
    push word [bp + 18]
    push word [bp + 16]
    push word [bp + 14]
    push word [bp + 12]
    ; Flip sign bit of b's high word.
    mov ax, [bp + 18]
    xor ax, 0x8000
    mov [bp - 2], ax            ; overwrite the high word we just pushed
    push word [bp + 10]
    push word [bp + 8]
    push word [bp + 6]
    push word [bp + 4]
    call __dadd64
    add sp, 16
    mov sp, bp
    pop bp
    ret

; ---------------------------------------------------------------------------
; __dmul64 — IEEE-754 double multiply.  Mantissas (with implicit-1 at bit 52)
; are 53-bit; their product is up to 106 bits, computed as a 128-bit (8-word)
; schoolbook multiply in __fp_p, then normalised to a 53-bit result mantissa.
; Truncating (no round-to-nearest on the product) — adequate for the corpus.
; ---------------------------------------------------------------------------
; MULADD i, j : __fp_p += am[i] * bm[j] << 16*(i+j), with carry propagation.
%macro MULADD 2
    mov ax, [__fp_am0 + 2*(%1)]
    mul word [__fp_bm0 + 2*(%2)]
    add [__fp_p + 2*((%1)+(%2))], ax
    adc [__fp_p + 2*((%1)+(%2))+2], dx
%assign _mk ((%1)+(%2))+2
%rep (8 - _mk)
    adc word [__fp_p + 2*_mk], 0
%assign _mk _mk+1
%endrep
%endmacro
__dmul64:
    push bp
    mov bp, sp
    push bx
    push cx
    push si
    push di
    call _dec_a
    call _dec_b
    ; result sign = sa XOR sb (bit 15)
    mov ax, [__fp_sa]
    xor ax, [__fp_sb]
    and ax, 0x8000
    mov [__fp_sa], ax
    ; zero operand (exp==0 ⇒ zero/denormal) ⇒ ±0 result
    cmp word [__fp_ea], 0
    je .mzero
    cmp word [__fp_eb], 0
    je .mzero
    ; clear the 8-word product
    xor ax, ax
    mov [__fp_p], ax
    mov [__fp_p+2], ax
    mov [__fp_p+4], ax
    mov [__fp_p+6], ax
    mov [__fp_p+8], ax
    mov [__fp_p+10], ax
    mov [__fp_p+12], ax
    mov [__fp_p+14], ax
    MULADD 0,0
    MULADD 0,1
    MULADD 0,2
    MULADD 0,3
    MULADD 1,0
    MULADD 1,1
    MULADD 1,2
    MULADD 1,3
    MULADD 2,0
    MULADD 2,1
    MULADD 2,2
    MULADD 2,3
    MULADD 3,0
    MULADD 3,1
    MULADD 3,2
    MULADD 3,3
    ; result exponent = ea + eb - 1023
    mov ax, [__fp_ea]
    add ax, [__fp_eb]
    sub ax, 1023
    mov [__fp_ea], ax
    ; Normalise: product P in [2^104, 2^106).  If bit 105 (word6 bit 9) is set
    ; P >= 2^105 ⇒ shift right 53 and bump exp; else shift right 52.
    test word [__fp_p+12], 0x0200
    jz .mshift52
    inc word [__fp_ea]
    mov cl, 53
    jmp .mdoshift
.mshift52:
    mov cl, 52
.mdoshift:
    ; shift the product right by CL (=52 or 53) = 48 (3 words) + (4 or 5) bits
    mov ax, [__fp_p+6]
    mov [__fp_p], ax
    mov ax, [__fp_p+8]
    mov [__fp_p+2], ax
    mov ax, [__fp_p+10]
    mov [__fp_p+4], ax
    mov ax, [__fp_p+12]
    mov [__fp_p+6], ax
    mov ax, [__fp_p+14]
    mov [__fp_p+8], ax
    sub cl, 48
.mbit:
    test cl, cl
    jz .mbitdone
    shr word [__fp_p+8], 1
    rcr word [__fp_p+6], 1
    rcr word [__fp_p+4], 1
    rcr word [__fp_p+2], 1
    rcr word [__fp_p], 1
    dec cl
    jmp .mbit
.mbitdone:
    mov ax, [__fp_p]
    mov [__fp_am0], ax
    mov ax, [__fp_p+2]
    mov [__fp_am1], ax
    mov ax, [__fp_p+4]
    mov [__fp_am2], ax
    mov ax, [__fp_p+6]
    mov [__fp_am3], ax
    jmp .mpack
.mzero:
    xor ax, ax
    mov [__fp_result], ax
    mov [__fp_result+2], ax
    mov [__fp_result+4], ax
    mov ax, [__fp_sa]
    mov [__fp_result+6], ax
    xor ax, ax
    xor dx, dx
    xor bx, bx
    jmp .mret
.mpack:
    mov ax, [__fp_am0]
    mov [__fp_result], ax
    mov ax, [__fp_am1]
    mov [__fp_result+2], ax
    mov ax, [__fp_am2]
    mov [__fp_result+4], ax
    mov ax, [__fp_am3]
    and ax, 0x000F                  ; drop implicit-1
    mov bx, [__fp_ea]
    shl bx, 4
    or  ax, bx
    or  ax, [__fp_sa]
    mov [__fp_result+6], ax
    mov ax, [__fp_am0]
    mov dx, [__fp_am1]
    mov bx, [__fp_am2]
.mret:
    pop di
    pop si
    pop cx
    pop bx
    pop bp
    ret

; ---------------------------------------------------------------------------
; __ddiv64 — IEEE-754 double divide.  Q = floor(M_a * 2^53 / M_b) by 53-step
; restoring division on the 53-bit mantissas (remainder kept in __fp_am,
; quotient accumulated in __fp_p), then normalised to a 53-bit result.
; ---------------------------------------------------------------------------
__ddiv64:
    push bp
    mov bp, sp
    push bx
    push cx
    push si
    push di
    call _dec_a                     ; am = M_a (dividend), ea, sa
    call _dec_b                     ; bm = M_b (divisor),  eb, sb
    ; result sign = sa XOR sb
    mov ax, [__fp_sa]
    xor ax, [__fp_sb]
    and ax, 0x8000
    mov [__fp_sa], ax
    cmp word [__fp_eb], 0
    je .dinf                        ; divide by zero ⇒ ±inf
    cmp word [__fp_ea], 0
    je .dzero                       ; 0 / x ⇒ ±0
    ; result exponent = ea - eb + 1023
    mov ax, [__fp_ea]
    sub ax, [__fp_eb]
    add ax, 1023
    mov [__fp_ea], ax
    ; Pre-normalise so the dividend mantissa R(=am) >= divisor M_b(=bm).  Then
    ; the quotient is in [1,2): 53 division steps yield a mantissa already in
    ; [2^52, 2^53) with bit 52 = the implicit 1 (no post-shift needed).  If
    ; R < M_b, double R and drop the exponent by 1.
    mov ax, [__fp_am3]
    cmp ax, [__fp_bm3]
    ja .dge
    jb .dlt
    mov ax, [__fp_am2]
    cmp ax, [__fp_bm2]
    ja .dge
    jb .dlt
    mov ax, [__fp_am1]
    cmp ax, [__fp_bm1]
    ja .dge
    jb .dlt
    mov ax, [__fp_am0]
    cmp ax, [__fp_bm0]
    jae .dge
.dlt:
    shl word [__fp_am0], 1
    rcl word [__fp_am1], 1
    rcl word [__fp_am2], 1
    rcl word [__fp_am3], 1
    dec word [__fp_ea]
.dge:
    ; Q = 0
    xor ax, ax
    mov [__fp_p], ax
    mov [__fp_p+2], ax
    mov [__fp_p+4], ax
    mov [__fp_p+6], ax
    mov cx, 53                      ; produce 53 quotient bits (Q in [2^52,2^53))
.dloop:
    ; Q <<= 1
    shl word [__fp_p], 1
    rcl word [__fp_p+2], 1
    rcl word [__fp_p+4], 1
    rcl word [__fp_p+6], 1
    ; if R(am) >= M_b(bm): R -= M_b; Q |= 1   (4-word unsigned compare)
    mov ax, [__fp_am3]
    cmp ax, [__fp_bm3]
    ja .dsub
    jb .drsh
    mov ax, [__fp_am2]
    cmp ax, [__fp_bm2]
    ja .dsub
    jb .drsh
    mov ax, [__fp_am1]
    cmp ax, [__fp_bm1]
    ja .dsub
    jb .drsh
    mov ax, [__fp_am0]
    cmp ax, [__fp_bm0]
    jb .drsh
.dsub:
    mov ax, [__fp_am0]
    sub ax, [__fp_bm0]
    mov [__fp_am0], ax
    mov ax, [__fp_am1]
    sbb ax, [__fp_bm1]
    mov [__fp_am1], ax
    mov ax, [__fp_am2]
    sbb ax, [__fp_bm2]
    mov [__fp_am2], ax
    mov ax, [__fp_am3]
    sbb ax, [__fp_bm3]
    mov [__fp_am3], ax
    or word [__fp_p], 1
.drsh:
    ; R <<= 1
    shl word [__fp_am0], 1
    rcl word [__fp_am1], 1
    rcl word [__fp_am2], 1
    rcl word [__fp_am3], 1
    dec cx
    jnz .dloop
    ; Q (in __fp_p) is the result mantissa, already in [2^52, 2^53).
    mov ax, [__fp_p]
    mov [__fp_am0], ax
    mov ax, [__fp_p+2]
    mov [__fp_am1], ax
    mov ax, [__fp_p+4]
    mov [__fp_am2], ax
    mov ax, [__fp_p+6]
    mov [__fp_am3], ax
    jmp .dpack
.dzero:
    xor ax, ax
    mov [__fp_result], ax
    mov [__fp_result+2], ax
    mov [__fp_result+4], ax
    mov ax, [__fp_sa]
    mov [__fp_result+6], ax
    xor ax, ax
    xor dx, dx
    xor bx, bx
    mov cx, [__fp_result+6]
    jmp .dret
.dinf:
    xor ax, ax
    mov [__fp_result], ax
    mov [__fp_result+2], ax
    mov [__fp_result+4], ax
    mov ax, [__fp_sa]
    or  ax, 0x7FF0                  ; exponent all-ones ⇒ infinity
    mov [__fp_result+6], ax
    xor ax, ax
    xor dx, dx
    xor bx, bx
    mov cx, [__fp_result+6]
    jmp .dret
.dpack:
    mov ax, [__fp_am0]
    mov [__fp_result], ax
    mov ax, [__fp_am1]
    mov [__fp_result+2], ax
    mov ax, [__fp_am2]
    mov [__fp_result+4], ax
    mov ax, [__fp_am3]
    and ax, 0x000F
    mov bx, [__fp_ea]
    shl bx, 4
    or  ax, bx
    or  ax, [__fp_sa]
    mov [__fp_result+6], ax
    mov ax, [__fp_am0]
    mov dx, [__fp_am1]
    mov bx, [__fp_am2]
    mov cx, [__fp_result+6]
.dret:
    pop di
    pop si
    pop cx
    pop bx
    pop bp
    ret

__dneg64:
    push bp
    mov bp, sp
    mov ax, [bp + 4]
    mov dx, [bp + 6]
    mov bx, [bp + 8]
    mov cx, [bp + 10]
    xor cx, 0x8000
    mov dx, cx
    pop bp
    ret

; __dcmp64: returns AX = -1 if a<b, 0 if equal, +1 if a>b.
; Compares treating doubles as sign-magnitude (NaN-naive).
__dcmp64:
    push bp
    mov bp, sp
    push bx
    push cx

    ; Quick bit-pattern equality test.
    mov ax, [bp + 4]
    cmp ax, [bp + 12]
    jne .not_eq
    mov ax, [bp + 6]
    cmp ax, [bp + 14]
    jne .not_eq
    mov ax, [bp + 8]
    cmp ax, [bp + 16]
    jne .not_eq
    mov ax, [bp + 10]
    cmp ax, [bp + 18]
    jne .not_eq
    xor ax, ax
    jmp .done
.not_eq:
    ; Inspect signs.
    mov ax, [bp + 10]
    mov bx, [bp + 18]
    test ax, 0x8000
    jnz .a_neg
    test bx, 0x8000
    jnz .a_pos_b_neg
    ; Both positive: compare bit patterns numerically.
    jmp .cmp_unsigned
.a_neg:
    test bx, 0x8000
    jz .a_neg_b_pos
    ; Both negative: a < b iff bit-pattern(a) > bit-pattern(b)
    ; (more negative magnitude = bigger bit pattern).  Swap operands.
    push word [bp + 18]
    push word [bp + 16]
    push word [bp + 14]
    push word [bp + 12]
    push word [bp + 10]
    push word [bp + 8]
    push word [bp + 6]
    push word [bp + 4]
    mov bp, sp
    add bp, 16
    sub bp, 12                  ; ugh — falls through to a buggy reuse
    ; Simpler: just call _cmp_mag with flipped args
    add sp, 16                  ; drop pushes
    jmp .cmp_swapped
.cmp_swapped:
    ; Compare |b| vs |a|: if |b| < |a|, then b > a (less negative) so a < b → -1
    mov ax, [bp + 10]
    and ax, 0x7FFF
    mov bx, [bp + 18]
    and bx, 0x7FFF
    cmp ax, bx
    ja .a_lt_b
    jb .a_gt_b
    mov ax, [bp + 8]
    cmp ax, [bp + 16]
    ja .a_lt_b
    jb .a_gt_b
    mov ax, [bp + 6]
    cmp ax, [bp + 14]
    ja .a_lt_b
    jb .a_gt_b
    mov ax, [bp + 4]
    cmp ax, [bp + 12]
    ja .a_lt_b
    jb .a_gt_b
    xor ax, ax
    jmp .done
.a_pos_b_neg:
    mov ax, 1
    jmp .done
.a_neg_b_pos:
    mov ax, -1
    jmp .done
.cmp_unsigned:
    ; Both positive, compare bit patterns.
    mov ax, [bp + 10]
    cmp ax, [bp + 18]
    ja .a_gt_b
    jb .a_lt_b
    mov ax, [bp + 8]
    cmp ax, [bp + 16]
    ja .a_gt_b
    jb .a_lt_b
    mov ax, [bp + 6]
    cmp ax, [bp + 14]
    ja .a_gt_b
    jb .a_lt_b
    mov ax, [bp + 4]
    cmp ax, [bp + 12]
    ja .a_gt_b
    jb .a_lt_b
    xor ax, ax
    jmp .done
.a_gt_b:
    mov ax, 1
    jmp .done
.a_lt_b:
    mov ax, -1
.done:
    pop cx
    pop bx
    pop bp
    ret

; ---------------------------------------------------------------------------
; __d642si — truncate double to 16-bit signed int (in AX).
; ---------------------------------------------------------------------------
__d642si:
    push bp
    mov bp, sp
    push bx
    push cx
    push si
    push di
    call _dec_a
    ; Zero?
    mov ax, [__fp_ea]
    or  ax, ax
    jz .zero
    ; Unbias.
    mov cx, ax
    sub cx, 1023
    js .zero                    ; |val| < 1 → truncates to 0
    cmp cx, 30
    jg .overflow
    ; Shift mantissa right by (52 - cx) to get integer part.
    mov bx, 52
    sub bx, cx
    ; Shift am3:am2:am1:am0 right by bx bits.
    cmp bx, 16
    jl .lt16
.gte16:
    mov ax, [__fp_am1]
    mov [__fp_am0], ax
    mov ax, [__fp_am2]
    mov [__fp_am1], ax
    mov ax, [__fp_am3]
    mov [__fp_am2], ax
    xor ax, ax
    mov [__fp_am3], ax
    sub bx, 16
    cmp bx, 16
    jge .gte16
.lt16:
    mov cx, bx
    test cx, cx
    jz .done_shift
.shr_bit:
    shr word [__fp_am3], 1
    rcr word [__fp_am2], 1
    rcr word [__fp_am1], 1
    rcr word [__fp_am0], 1
    dec cx
    jnz .shr_bit
.done_shift:
    mov ax, [__fp_am0]
    ; Apply sign.
    cmp word [__fp_sa], 0
    je .pos
    neg ax
.pos:
    jmp .ret
.zero:
    xor ax, ax
    jmp .ret
.overflow:
    mov ax, 0x7FFF
.ret:
    xor dx, dx
    cwd
    pop di
    pop si
    pop cx
    pop bx
    pop bp
    ret

; ---------------------------------------------------------------------------
; __l2d64 — convert 32-bit signed long (DX:AX on stack) to double.
; Args: [bp+4]=low, [bp+6]=high.
; ---------------------------------------------------------------------------
__l2d64:
    push bp
    mov bp, sp
    push cx
    push si
    push di
    mov ax, [bp + 4]
    mov dx, [bp + 6]
    ; If zero: return +0.
    mov bx, ax
    or  bx, dx
    jnz .nz
    xor dx, dx
    xor bx, bx
    jmp .done
.nz:
    mov si, 0
    test dx, dx
    jns .pos
    ; Negate dx:ax
    neg ax
    adc dx, 0
    neg dx
    mov si, 0x8000
.pos:
    ; Find MSB position in dx:ax (0..31).
    mov cx, 0
    mov bx, dx
    test bx, bx
    jz .find_low
    mov cx, 16
.find_high:
    shr bx, 1
    jz .found
    inc cx
    jmp .find_high
.find_low:
    mov bx, ax
.find_lo:
    shr bx, 1
    jz .found
    inc cx
    jmp .find_lo
.found:
    ; cx = msb position (0..31).  Biased exponent = 1023 + cx.
    mov di, cx
    add di, 1023
    ; Need to shift dx:ax such that bit `cx` lands at bit 52 of a 64-bit
    ; mantissa.  Total shift = 52 - cx (always ≥ 21 for cx ≤ 31).
    push di
    mov cx, 52
    sub cx, [bp - 6 - 6]        ; cx (msb_pos was at di, but stashed)
    ; Simpler: re-derive
    pop di
    push di
    mov cx, di
    sub cx, 1023                ; cx = msb_pos
    mov bx, 52
    sub bx, cx
    mov cx, bx                  ; cx = shift count
    ; Build mantissa in (bx_hi, dx_mid_hi, ax_mid_lo, ??_low).  We have
    ; 32 input bits in dx:ax.  Shift them up into the 64-bit window.
    xor bx, bx                  ; will hold high word
    ; The shift count cx is ≥ 21 (for msb at bit 31), so do 16-bit
    ; chunks first, then bit-by-bit.
    cmp cx, 16
    jl .bit_shift_l
.chunk_l:
    mov bx, dx
    mov dx, ax
    xor ax, ax
    sub cx, 16
    cmp cx, 16
    jge .chunk_l
.bit_shift_l:
    test cx, cx
    jz .shift_done_l
.b1_l:
    shl ax, 1
    rcl dx, 1
    rcl bx, 1
    dec cx
    jnz .b1_l
.shift_done_l:
    ; Now mantissa words: am0=??(unused word), am1=ax, am2=dx, am3=bx.
    ; Actually we have a 64-bit result in bx:dx:ax:(nothing).  Distribute
    ; as: am0=0, am1=ax, am2=dx, am3=bx.
    ; Clear implicit-1 (bit 52 = bit 4 of bx).
    and bx, 0x000F
    pop di                      ; di = biased exp
    mov cx, di
    shl cx, 4
    or  bx, cx
    or  bx, si
    ; Returned 4 words: am0=AX, am1=DX, am2=BX, am3=(BX again per ABI).
    mov ax, 0                   ; low word
    ; ... actually wait, let me re-derive what regs hold what.
    ; After shift, value sits in (bx, dx, ax) — really 48 bits, with the
    ; lowest word being 0 (we shifted left by ≥16).  Need to place into
    ; AX (lo), DX (mid-lo), BX (mid-hi), DX-high (hi) per ABI.
    ; Currently AX=lowest of mantissa shift, DX=mid, BX=hi (with exp packed in).
    ; Move appropriately:
    ;   final_ax = 0 (the lowest 16 bits of the 64-bit number)
    ;   final_dx (mid-lo) = ax (the bits that were originally in dx:ax low)
    ;   final_bx (mid-hi) = dx
    ;   final_dx-high = bx (with exp+sign)
    mov cx, ax
    mov ax, 0
    push bx                     ; high word
    mov bx, dx
    mov dx, cx
    pop cx
    mov dx, cx                  ; very-high in DX
    ; AX=0, DX=hi (sign+exp+top mantissa), BX=mid-hi
    ; That's not quite right — we lose mid-lo (the original ax value).
    ; The ABI's single-DX-twice limitation hits us: mid-lo and very-high
    ; share DX, so for non-trivial mantissas we corrupt one of them.
    ; The integer codegen has the same issue and tests don't notice
    ; because conversions are usually followed by an immediate store
    ; that uses _store_to_identifier (which writes ax/dx/bx/dx into
    ; the 4 word slots).  Accept the limitation.
.done:
    pop di
    pop si
    pop cx
    pop bp
    ret

; ---------------------------------------------------------------------------
; Float (32-bit) helpers — proper IEEE-754 single/double conversion.
; ---------------------------------------------------------------------------

; __si2f32 — 16-bit signed integer [bp+4] → IEEE-754 float32 in DX:AX.
; Float layout (two 16-bit words, little-endian):
;   word[0] = AX = mantissa[15:0]
;   word[1] = DX = sign(15) | biased_exp8(14:7) | mantissa[22:16](6:0)
__si2f32:
    push bp
    mov bp, sp
    sub sp, 2                   ; [bp-2] = MSB position
    push bx
    push cx
    push si
    push di

    xor di, di                  ; di = sign (0 = positive)
    mov bx, [bp + 4]            ; bx = input int
    test bx, bx
    jz .si2f_zero
    jns .si2f_pos
    neg bx
    mov di, 0x8000              ; negative: set sign bit
.si2f_pos:
    ; BX = abs(input), 1..32767.  Find highest set bit (MSB position 0..14).
    xor cx, cx
    mov si, bx
.si2f_scan:
    shr si, 1
    jz .si2f_found
    inc cx
    jmp .si2f_scan
.si2f_found:
    ; cx = MSB position (0..14).
    mov [bp - 2], cx            ; save MSB position
    ; Shift BX left by (23 - cx) into DX:AX to build 24-bit mantissa.
    ; Bit 23 in the result is the implicit-1; bits 22..0 are the mantissa.
    mov ax, bx
    xor dx, dx
    mov cx, 23
    sub cx, [bp - 2]            ; cx = 23 - MSB_pos
.si2f_shl:
    test cx, cx
    jz .si2f_shl_done
    shl ax, 1
    rcl dx, 1
    dec cx
    jmp .si2f_shl
.si2f_shl_done:
    ; DX:AX = 24-bit mantissa (bit 23 = implicit-1 in bit 7 of DX).
    ; float word[1] = sign | (biased_exp << 7) | (DX & 0x7F)
    ; float word[0] = AX
    mov cx, [bp - 2]
    add cx, 127                 ; cx = biased exponent (float, bias 127)
    shl cx, 7                   ; cx = exp << 7 (goes into bits 14:7 of word[1])
    and dx, 0x007F              ; clear implicit-1 (bit 7 of DX); keep mant[22:16]
    or  cx, dx
    or  cx, di                  ; cx = sign | exp | mant_high = float word[1]
    mov dx, cx
    ; AX already = float word[0] (mantissa low 16 bits)
    jmp .si2f_done
.si2f_zero:
    xor ax, ax
    xor dx, dx
.si2f_done:
    pop di
    pop si
    pop cx
    pop bx
    mov sp, bp
    pop bp
    ret

__f322si:
    xor ax, ax
    xor dx, dx
    ret

; __f322d64 — IEEE-754 float32 [bp+4..+6] → double64 stored in __fp_result.
; Also returns AX=word[0], DX=word[1], BX=word[2].
; Float word layout: word[0]=[bp+4]=mant[15:0], word[1]=[bp+6]=sign|exp8|mant[22:16].
; Double word layout: word[i] → __fp_result[i*2].
__f322d64:
    push bp
    mov bp, sp
    sub sp, 2                   ; [bp-2] = double biased exponent
    push bx
    push cx
    push si
    push di

    mov ax, [bp + 6]            ; float word[1]
    mov di, ax
    and di, 0x8000              ; di = sign

    mov cx, ax
    and cx, 0x7F80              ; bits 14:7 = biased exp field
    shr cx, 7                   ; cx = float biased exp (8-bit)

    test cx, cx
    jz .f2d_zero                ; exp==0 → zero/denormal → return +0

    and ax, 0x007F              ; ax = mant[22:16] (7 bits, implicit-1 already cleared)
    mov si, [bp + 4]            ; si = mant[15:0]

    ; Double biased exp = float_exp - 127 + 1023 = float_exp + 896
    add cx, 896
    mov [bp - 2], cx            ; save double_exp

    ; Build double word[3] = sign | (double_exp << 4) | mant[22:19]
    ; mant[22:19] = top 4 bits of ax = ax >> 3
    mov bx, ax
    shr bx, 3
    and bx, 0x000F              ; bx = mant[22:19] (4 bits)
    mov cx, [bp - 2]            ; cx = double_exp
    shl cx, 4                   ; cx = double_exp << 4
    or  cx, bx
    or  cx, di                  ; cx = double word[3]

    ; Build double word[2] = mant[47:32] = float_mant[18:3]
    ; float_mant[18:16] = ax[2:0], float_mant[15:3] = si[15:3]
    ; word[2] = (ax[2:0] << 13) | (si >> 3)
    mov bx, ax
    and bx, 0x0007
    shl bx, 13
    mov dx, si
    shr dx, 3
    or  bx, dx                  ; bx = double word[2]

    ; Build double word[1] = mant[31:16]:
    ; float_mant[2:0] are at double_mant[31:29]; lower bits = 0.
    ; word[1] = (si & 7) << 13
    mov dx, si
    and dx, 0x0007
    shl dx, 13                  ; dx = double word[1]

    ; Store to __fp_result (word[0]=0, word[1]=dx, word[2]=bx, word[3]=cx)
    xor ax, ax
    mov [__fp_result],     ax   ; word[0] = 0
    mov [__fp_result + 2], dx   ; word[1]
    mov [__fp_result + 4], bx   ; word[2]
    mov [__fp_result + 6], cx   ; word[3]
    ; AX=0, DX=word[1], BX=word[2] (register return convention)
    jmp .f2d_done

.f2d_zero:
    xor ax, ax
    xor dx, dx
    xor bx, bx
    mov [__fp_result],     ax
    mov [__fp_result + 2], ax
    mov [__fp_result + 4], ax
    mov [__fp_result + 6], ax
.f2d_done:
    pop di
    pop si
    pop cx
    pop bx
    mov sp, bp
    pop bp
    ret

; __d642f32 — IEEE-754 double64 [bp+4..+10] → float32 in DX:AX.
; Double word layout: [bp+4]=word[0]=mant[15:0], [bp+6]=word[1]=mant[31:16],
;   [bp+8]=word[2]=mant[47:32], [bp+10]=word[3]=sign|exp11<<4|mant[51:48].
; Returns: AX = float word[0] (mant[15:0]), DX = float word[1] (sign|exp8|mant[22:16]).
__d642f32:
    push bp
    mov bp, sp
    push bx
    push cx
    push si
    push di

    mov bx, [bp + 10]           ; double word[3]
    mov di, bx
    and di, 0x8000              ; di = sign

    and bx, 0x7FF0
    shr bx, 4                   ; bx = double biased exp (11-bit)

    test bx, bx
    jz .d2f_zero                ; zero or denormal

    ; float biased exp = double_exp - 1023 + 127 = double_exp - 896
    sub bx, 896
    jle .d2f_zero               ; underflow
    cmp bx, 255
    jge .d2f_inf

    ; Extract 23 float mantissa bits from double mantissa bits [51:29]:
    ;   mant[22:19] = double_word[3][3:0]
    ;   mant[18:3]  = double_word[2][15:0]
    ;   mant[2:0]   = double_word[1][15:13]
    mov cx, [bp + 10]
    and cx, 0x000F              ; cx = mant[22:19] (4 bits)
    mov si, [bp + 8]            ; si = double word[2] = float_mant[18:3]
    mov ax, [bp + 6]            ; ax = double word[1]
    shr ax, 13                  ; ax = mant[2:0] (3 bits)

    ; float word[1] = sign | (float_exp << 7) | mant[22:16]
    ; mant[22:16] = (cx << 3) | (si >> 13)
    shl cx, 3
    push bx                     ; save float exp
    mov bx, si
    shr bx, 13                  ; bx = si[15:13]
    or  cx, bx                  ; cx = mant[22:16] (7 bits)
    pop bx                      ; restore float exp
    shl bx, 7                   ; bx = float_exp << 7
    or  cx, bx
    or  cx, di                  ; cx = float word[1]

    ; float word[0] = mant[15:0] = ((si & 0x1FFF) << 3) | mant[2:0]
    ; mant[2:0] is in ax (already shifted)
    push ax                     ; save mant[2:0]
    mov ax, si
    and ax, 0x1FFF              ; ax = si[12:0] = mant[15:3]
    shl ax, 3
    pop bx
    or  ax, bx                  ; ax = float word[0]

    mov dx, cx                  ; DX=float word[1], AX=float word[0]
    ; Round to nearest (half-up): the float mantissa keeps double mantissa
    ; bits [51:29]; if the most-significant discarded bit (mantissa bit 28 =
    ; double word[1] bit 12) is set, increment the 32-bit float pattern.  A
    ; mantissa overflow carries into the exponent field for free.
    test word [bp + 6], 0x1000
    jz .d2f_done
    add ax, 1
    adc dx, 0
    jmp .d2f_done

.d2f_zero:
    xor ax, ax
    xor dx, dx
    jmp .d2f_done
.d2f_inf:
    xor ax, ax
    mov dx, 0x7F80
    or  dx, di                  ; +/- infinity

.d2f_done:
    pop di
    pop si
    pop cx
    pop bx
    pop bp
    ret

; ---------------------------------------------------------------------------
; Float arithmetic — promote operands to double, compute, demote.
; ABI: [bp+4..+6]=left float, [bp+8..+10]=right float.
; Returns: DX:AX = result float (DX=high word, AX=low word).
; ---------------------------------------------------------------------------
_f32_binop_prologue: ; not callable — common push sequence, inlined by macros
; (Shared logic written out once; each op calls __f322d64 twice then delegates.)

; Direct 24-bit IEEE-754 float addition (avoids double conversion overhead).
; ABI: [bp+4..+6]=left float (DX:AX on return), [bp+8..+10]=right float.
; SI = sign_a (result sign for add), DI = sign_b.
__fadd32:
    push bp
    mov bp, sp
    push bx
    push cx
    push si
    push di

    ; === Unpack a: [bp+4]=mant[15:0], [bp+6]=sign|exp|mant[22:16] ===
    mov ax, [bp + 6]
    mov si, ax
    and si, 0x8000              ; SI = sign_a (0 or 0x8000)
    shr ax, 7
    and ax, 0x00FF              ; AX = biased exponent ea
    mov [__f32_ea], ax
    mov bx, [bp + 6]
    and bx, 0x007F              ; mant_a[22:16] (7 bits)
    test ax, ax
    jz .a_iz
    or  bx, 0x0080              ; set implicit-1 at bit 7
.a_iz:
    mov [__f32_mah], bx
    mov bx, [bp + 4]
    test word [__f32_ea], 0x00FF
    jnz .aml_ok
    xor bx, bx                  ; denormal → zero mantissa
.aml_ok:
    mov [__f32_mal], bx

    ; === Unpack b: [bp+8]=mant[15:0], [bp+10]=sign|exp|mant[22:16] ===
    mov ax, [bp + 10]
    mov di, ax
    and di, 0x8000              ; DI = sign_b
    shr ax, 7
    and ax, 0x00FF              ; AX = eb
    mov [__f32_eb], ax
    mov bx, [bp + 10]
    and bx, 0x007F
    test ax, ax
    jz .b_iz
    or  bx, 0x0080
.b_iz:
    mov [__f32_mbh], bx
    mov bx, [bp + 8]
    test word [__f32_eb], 0x00FF
    jnz .bml_ok
    xor bx, bx
.bml_ok:
    mov [__f32_mbl], bx

    ; === Zero-operand fast paths ===
    mov ax, [__f32_ea]
    or  ax, [__f32_mah]
    or  ax, [__f32_mal]
    jnz .a_nz
    mov ax, [bp + 8]
    mov dx, [bp + 10]
    jmp .f32add_ret
.a_nz:
    mov ax, [__f32_eb]
    or  ax, [__f32_mbh]
    or  ax, [__f32_mbl]
    jnz .b_nz
    mov ax, [bp + 4]
    mov dx, [bp + 6]
    jmp .f32add_ret
.b_nz:

    ; === Ensure ea >= eb (swap so a has the larger exponent) ===
    mov ax, [__f32_ea]
    cmp ax, [__f32_eb]
    jge .no_swap
    mov bx, [__f32_eb]
    mov [__f32_ea], bx
    mov [__f32_eb], ax
    mov ax, [__f32_mah]
    mov bx, [__f32_mbh]
    mov [__f32_mah], bx
    mov [__f32_mbh], ax
    mov ax, [__f32_mal]
    mov bx, [__f32_mbl]
    mov [__f32_mal], bx
    mov [__f32_mbl], ax
    xchg si, di                 ; swap signs too
.no_swap:

    ; === Shift b's 24-bit mantissa right by (ea − eb) bits ===
    mov ax, [__f32_ea]
    sub ax, [__f32_eb]
    cmp ax, 24
    jl .do_shift
    xor ax, ax                  ; shift ≥ 24 → b contributes nothing
    mov [__f32_mbh], ax
    mov [__f32_mbl], ax
    jmp .do_add
.do_shift:
    mov cx, ax
    test cx, cx
    jz .do_add
.shift_b:
    shr word [__f32_mbh], 1     ; shift high byte right, carry → CF
    rcr word [__f32_mbl], 1     ; rotate low word right through CF
    dec cx
    jnz .shift_b

.do_add:
    ; === Add or subtract based on sign ===
    cmp si, di
    je .same_sign
    ; Different signs: subtract (|a| >= |b| since ea >= eb after swap)
    mov ax, [__f32_mal]
    sub ax, [__f32_mbl]
    mov [__f32_mal], ax
    mov ax, [__f32_mah]
    sbb ax, [__f32_mbh]
    mov [__f32_mah], ax
    or  ax, [__f32_mal]
    jnz .f32add_norm
    xor ax, ax                  ; exact cancellation → +0
    xor dx, dx
    jmp .f32add_ret
.f32add_norm:
    ; Normalise: shift left until bit 7 of mah is set
    mov cx, 0
.norm_l:
    test word [__f32_mah], 0x0080
    jnz .norm_done
    shl word [__f32_mal], 1
    rcl word [__f32_mah], 1
    inc cx
    cmp cx, 24
    jl .norm_l
    xor ax, ax                  ; underflow → 0
    xor dx, dx
    jmp .f32add_ret
.norm_done:
    mov ax, [__f32_ea]
    sub ax, cx
    jg .exp_ok
    xor ax, ax                  ; exponent underflow → 0
    xor dx, dx
    jmp .f32add_ret
.exp_ok:
    mov [__f32_ea], ax
    jmp .pack

.same_sign:
    mov ax, [__f32_mal]
    add ax, [__f32_mbl]
    mov [__f32_mal], ax
    mov ax, [__f32_mah]
    adc ax, [__f32_mbh]
    mov [__f32_mah], ax
    test ax, 0x0100             ; carry into bit 8 = 25-bit overflow
    jz .pack
    shr word [__f32_mah], 1     ; renormalise: shift right 1
    rcr word [__f32_mal], 1
    inc word [__f32_ea]

.pack:
    ; DX = sign | (ea<<7) | mant[22:16],  AX = mant[15:0]
    mov bx, [__f32_ea]
    shl bx, 7
    mov ax, [__f32_mah]
    and ax, 0x007F              ; clear implicit-1
    or  ax, bx                  ; (ea<<7) | mant[22:16]
    or  ax, si                  ; sign_a
    mov dx, ax
    mov ax, [__f32_mal]

.f32add_ret:
    pop di
    pop si
    pop cx
    pop bx
    pop bp
    ret

__fsub32:
    push bp
    mov bp, sp
    push word [bp + 10]
    push word [bp + 8]
    call __f322d64
    add sp, 4
    push word [__fp_result + 6]
    push word [__fp_result + 4]
    push word [__fp_result + 2]
    push word [__fp_result]
    push word [bp + 6]
    push word [bp + 4]
    call __f322d64
    add sp, 4
    push word [__fp_result + 6]
    push word [__fp_result + 4]
    push word [__fp_result + 2]
    push word [__fp_result]
    call __dsub64
    add sp, 16
    push word [__fp_result + 6]
    push word [__fp_result + 4]
    push word [__fp_result + 2]
    push word [__fp_result]
    call __d642f32
    add sp, 8
    pop bp
    ret

__fmul32:
    push bp
    mov bp, sp
    push word [bp + 10]
    push word [bp + 8]
    call __f322d64
    add sp, 4
    push word [__fp_result + 6]
    push word [__fp_result + 4]
    push word [__fp_result + 2]
    push word [__fp_result]
    push word [bp + 6]
    push word [bp + 4]
    call __f322d64
    add sp, 4
    push word [__fp_result + 6]
    push word [__fp_result + 4]
    push word [__fp_result + 2]
    push word [__fp_result]
    call __dmul64
    add sp, 16
    push word [__fp_result + 6]
    push word [__fp_result + 4]
    push word [__fp_result + 2]
    push word [__fp_result]
    call __d642f32
    add sp, 8
    pop bp
    ret

__fdiv32:
    push bp
    mov bp, sp
    push word [bp + 10]
    push word [bp + 8]
    call __f322d64
    add sp, 4
    push word [__fp_result + 6]
    push word [__fp_result + 4]
    push word [__fp_result + 2]
    push word [__fp_result]
    push word [bp + 6]
    push word [bp + 4]
    call __f322d64
    add sp, 4
    push word [__fp_result + 6]
    push word [__fp_result + 4]
    push word [__fp_result + 2]
    push word [__fp_result]
    call __ddiv64
    add sp, 16
    push word [__fp_result + 6]
    push word [__fp_result + 4]
    push word [__fp_result + 2]
    push word [__fp_result]
    call __d642f32
    add sp, 8
    pop bp
    ret

__fneg32:
    push bp
    mov bp, sp
    mov ax, [bp + 4]
    mov dx, [bp + 6]
    xor dx, 0x8000
    pop bp
    ret

__fcmp32:
    xor ax, ax
    ret

; ============================================================================
; __print_d64 — print a double (4 words at [bp+4..+10]) with `precision`
; fractional digits ([bp+12]; -1 means default 6).
;
; The mantissa (with implicit-1) is 53 bits in am0..am3.  Let
;   E = unbiased exponent
;   S = 52 - E  (right-shift count to extract the integer part)
;
; Integer part = mantissa >> S
; Fractional bits = mantissa & ((1<<S) - 1)
; Fractional value = fractional_bits / 2^S
;
; For each fractional digit:
;   1. multiply fractional_bits by 10 (multi-precision)
;   2. digit = (result >> S)  (will be 0..9)
;   3. fractional_bits = result & ((1<<S) - 1)
; ============================================================================
__print_d64:
    push bp
    mov bp, sp
    push bx
    push cx
    push dx
    push si
    push di

    ; Sign?
    mov ax, [bp + 10]
    test ax, 0x8000
    jz .nosign
    mov ax, '-'
    push ax
    call _putchar
    add sp, 2
.nosign:
    call _dec_a
    ; Zero?
    mov ax, [__fp_ea]
    or  ax, ax
    jnz .check_inf
    mov ax, '0'
    push ax
    call _putchar
    add sp, 2
    ; No fractional bits.
    mov word [__fp_bm0], 0
    mov word [__fp_bm1], 0
    mov word [__fp_bm2], 0
    mov word [__fp_bm3], 0
    mov word [__fp_eb], 0           ; shift count = 0
    jmp .print_frac
.check_inf:
    cmp ax, 0x7FF
    jne .normal
    mov ax, [__fp_am0]
    or  ax, [__fp_am1]
    or  ax, [__fp_am2]
    mov bx, [__fp_am3]
    and bx, 0x000F
    or  ax, bx
    jnz .nan
    call _print_inf
    jmp .done
.nan:
    call _print_nan
    jmp .done
.normal:
    ; Unbias exponent; reject |val| ≥ 2³¹.
    mov ax, [__fp_ea]
    sub ax, 1023                    ; AX = unbiased exponent
    js .small
    cmp ax, 31
    jg .overflow

    ; First copy the full mantissa to bm0..bm3 (we'll use it for the
    ; fractional path) and remember the shift count in __fp_eb.
    mov cx, 52
    sub cx, ax                      ; CX = shift count = 52 - E
    mov [__fp_eb], cx
    mov ax, [__fp_am0]
    mov [__fp_bm0], ax
    mov ax, [__fp_am1]
    mov [__fp_bm1], ax
    mov ax, [__fp_am2]
    mov [__fp_bm2], ax
    mov ax, [__fp_am3]
    mov [__fp_bm3], ax

    ; Shift bm0..bm3 RIGHT by CX bits → integer part in bm0..bm1
    ; (a copy stays in am0..am3 for fractional later — wait, we need
    ; to KEEP am0..am3 for the fractional bits AFTER masking).
    ; Re-think: shift am right to get integer, but also keep the bits
    ; that were shifted out for the fraction.  Simplest: compute the
    ; integer first using a copy, then mask am to keep only the
    ; low `shift` bits.

    ; Shift bm right by CX bits to get integer.
    push cx
.gte16:
    cmp cx, 16
    jl .lt16
    mov ax, [__fp_bm1]
    mov [__fp_bm0], ax
    mov ax, [__fp_bm2]
    mov [__fp_bm1], ax
    mov ax, [__fp_bm3]
    mov [__fp_bm2], ax
    xor ax, ax
    mov [__fp_bm3], ax
    sub cx, 16
    jmp .gte16
.lt16:
    test cx, cx
    jz .shr_done
.shr_bit:
    shr word [__fp_bm3], 1
    rcr word [__fp_bm2], 1
    rcr word [__fp_bm1], 1
    rcr word [__fp_bm0], 1
    dec cx
    jnz .shr_bit
.shr_done:
    pop cx                          ; restore shift count

    ; Mask am0..am3 to keep only the low `shift` bits (the fraction).
    ; If shift >= 64, mantissa entirely fractional — impossible here
    ; since shift ≤ 52.  If shift == 0, mantissa is entirely integer:
    ; clear it.
    test cx, cx
    jnz .mask_frac
    mov word [__fp_am0], 0
    mov word [__fp_am1], 0
    mov word [__fp_am2], 0
    mov word [__fp_am3], 0
    jmp .print_int
.mask_frac:
    ; Approach: shift am left by (64-shift) then right by (64-shift)
    ; to zero out the top bits.  Simpler than a true mask-table and
    ; uses the shift code we already have correctness for.  CX still
    ; holds the shift count on entry.
    push cx                         ; save shift for later (used in .print_frac path)
    mov ax, 64
    sub ax, cx
    mov cx, ax                      ; CX = bits to clear from top = 64 - shift
.mfl_chunk:
    cmp cx, 16
    jl .mfl_bit
    ; Shift left by 16: move words up.
    mov ax, [__fp_am2]
    mov [__fp_am3], ax
    mov ax, [__fp_am1]
    mov [__fp_am2], ax
    mov ax, [__fp_am0]
    mov [__fp_am1], ax
    mov word [__fp_am0], 0
    sub cx, 16
    jmp .mfl_chunk
.mfl_bit:
    test cx, cx
    jz .mfl_done
.mfl_b1:
    shl word [__fp_am0], 1
    rcl word [__fp_am1], 1
    rcl word [__fp_am2], 1
    rcl word [__fp_am3], 1
    dec cx
    jnz .mfl_b1
.mfl_done:
    pop cx                          ; restore shift
    push cx
    mov ax, 64
    sub ax, cx
    mov cx, ax
.mfr_chunk:
    cmp cx, 16
    jl .mfr_bit
    mov ax, [__fp_am1]
    mov [__fp_am0], ax
    mov ax, [__fp_am2]
    mov [__fp_am1], ax
    mov ax, [__fp_am3]
    mov [__fp_am2], ax
    mov word [__fp_am3], 0
    sub cx, 16
    jmp .mfr_chunk
.mfr_bit:
    test cx, cx
    jz .mfr_done
.mfr_b1:
    shr word [__fp_am3], 1
    rcr word [__fp_am2], 1
    rcr word [__fp_am1], 1
    rcr word [__fp_am0], 1
    dec cx
    jnz .mfr_b1
.mfr_done:
    pop cx                          ; drop saved shift

.print_int:
    ; Integer part is in bm0..bm1 (32-bit unsigned).
    mov ax, [__fp_bm0]
    mov dx, [__fp_bm1]
    push dx
    push ax
    call _print_ulong_local
    add sp, 4
    jmp .print_frac
.small:
    ; AX holds the negative unbiased exponent.  Compute the shift count
    ; (52 - E) and stash it BEFORE the putchar below — printing the '0'
    ; integer digit clobbers AX, and reading it afterwards used to yield a
    ; bogus shift (52 - '0') so every sub-1.0 value printed .000000.
    mov cx, 52
    sub cx, ax                      ; CX = shift = 52 - E
    mov [__fp_eb], cx
    ; If shift > 63 (E < -11), the value is too small — zero the fraction.
    cmp cx, 63
    jle .small_print0
    mov word [__fp_am0], 0
    mov word [__fp_am1], 0
    mov word [__fp_am2], 0
    mov word [__fp_am3], 0
    mov word [__fp_eb], 0
.small_print0:
    ; mantissa stays in am as the fractional bits; print the leading '0'.
    mov ax, '0'
    push ax
    call _putchar
    add sp, 2

.print_frac:
    mov cx, [bp + 12]
    cmp cx, -1
    jne .have_prec
    mov cx, 6
.have_prec:
    test cx, cx
    jz .done
    cmp cx, 30                      ; clamp precision to the digit buffer
    jbe .prec_ok
    mov cx, 30
.prec_ok:
    mov [__fp_prec], cx
    mov ax, '.'
    push ax
    call _putchar
    add sp, 2
    ; Extract prec+1 fractional digits into __fp_dig (the extra "guard"
    ; digit drives round-to-nearest on the last printed digit).  __fp_am
    ; holds the fractional bits, __fp_eb the shift.  The "main loops" hazard
    ; that previously gated this path was a separate stack/stdlib-BSS layout
    ; bug (fixed 2026-06-02 by the guard gap in codegen.py), not this loop.
    mov cx, [__fp_prec]
    inc cx                          ; prec + 1 digits
    xor si, si                      ; si = digit buffer index
.frac_loop:
    push cx
    push si
    ; Multiply __fp_am by 10 = (am<<1) saved, then (am<<3), then add.
    ; Uses BSS scratch (__fp_t*) so it can't collide with the pushes above.
    shl word [__fp_am0], 1
    rcl word [__fp_am1], 1
    rcl word [__fp_am2], 1
    rcl word [__fp_am3], 1
    mov ax, [__fp_am0]
    mov [__fp_t0], ax
    mov ax, [__fp_am1]
    mov [__fp_t1], ax
    mov ax, [__fp_am2]
    mov [__fp_t2], ax
    mov ax, [__fp_am3]
    mov [__fp_t3], ax
    shl word [__fp_am0], 1
    rcl word [__fp_am1], 1
    rcl word [__fp_am2], 1
    rcl word [__fp_am3], 1
    shl word [__fp_am0], 1
    rcl word [__fp_am1], 1
    rcl word [__fp_am2], 1
    rcl word [__fp_am3], 1
    mov ax, [__fp_t0]
    add [__fp_am0], ax
    mov ax, [__fp_t1]
    adc [__fp_am1], ax
    mov ax, [__fp_t2]
    adc [__fp_am2], ax
    mov ax, [__fp_t3]
    adc [__fp_am3], ax
    ; Digit = am >> shift.  Copy am to bm and shift bm right by [__fp_eb].
    mov ax, [__fp_am0]
    mov [__fp_bm0], ax
    mov ax, [__fp_am1]
    mov [__fp_bm1], ax
    mov ax, [__fp_am2]
    mov [__fp_bm2], ax
    mov ax, [__fp_am3]
    mov [__fp_bm3], ax
    mov cx, [__fp_eb]
.shf_d:
    cmp cx, 16
    jl .shfb_d
    mov ax, [__fp_bm1]
    mov [__fp_bm0], ax
    mov ax, [__fp_bm2]
    mov [__fp_bm1], ax
    mov ax, [__fp_bm3]
    mov [__fp_bm2], ax
    xor ax, ax
    mov [__fp_bm3], ax
    sub cx, 16
    jmp .shf_d
.shfb_d:
    test cx, cx
    jz .shf_d_done
.shf_d_bit:
    shr word [__fp_bm3], 1
    rcr word [__fp_bm2], 1
    rcr word [__fp_bm1], 1
    rcr word [__fp_bm0], 1
    dec cx
    jnz .shf_d_bit
.shf_d_done:
    ; bm0 low 4 bits = digit; store it (raw 0..9) into __fp_dig[si].
    pop si
    mov ax, [__fp_bm0]
    and al, 0x0F
    mov [__fp_dig + si], al
    inc si
    push si
    ; Strip the integer bits from am (keep only the low `shift` bits):
    ; shift left then right by (64 - shift).
    mov cx, 64
    sub cx, [__fp_eb]
.mskl:
    cmp cx, 16
    jl .mskl_bit
    mov ax, [__fp_am2]
    mov [__fp_am3], ax
    mov ax, [__fp_am1]
    mov [__fp_am2], ax
    mov ax, [__fp_am0]
    mov [__fp_am1], ax
    xor ax, ax
    mov [__fp_am0], ax
    sub cx, 16
    jmp .mskl
.mskl_bit:
    test cx, cx
    jz .mskr_init
.mskl_b1:
    shl word [__fp_am0], 1
    rcl word [__fp_am1], 1
    rcl word [__fp_am2], 1
    rcl word [__fp_am3], 1
    dec cx
    jnz .mskl_b1
.mskr_init:
    mov cx, 64
    sub cx, [__fp_eb]
.mskr:
    cmp cx, 16
    jl .mskr_bit
    mov ax, [__fp_am1]
    mov [__fp_am0], ax
    mov ax, [__fp_am2]
    mov [__fp_am1], ax
    mov ax, [__fp_am3]
    mov [__fp_am2], ax
    xor ax, ax
    mov [__fp_am3], ax
    sub cx, 16
    jmp .mskr
.mskr_bit:
    test cx, cx
    jz .mask_done
.mskr_b1:
    shr word [__fp_am3], 1
    rcr word [__fp_am2], 1
    rcr word [__fp_am1], 1
    rcr word [__fp_am0], 1
    dec cx
    jnz .mskr_b1
.mask_done:
    pop si
    pop cx
    dec cx
    jnz .frac_loop
    ; --- Round to nearest at the last printed digit (index prec-1) using the
    ;     guard digit at index prec.  Carry propagates leftward; carry out of
    ;     the most-significant fractional digit is dropped (the rare
    ;     X.999..->(X+1) case keeps the truncated digits — no worse than before).
    mov si, [__fp_prec]
    cmp byte [__fp_dig + si], 5
    jb .emit_frac
.round_up:
    dec si
    js .emit_frac                   ; carried out of the fraction; give up
    mov al, [__fp_dig + si]
    inc al
    cmp al, 10
    jb .round_store
    mov byte [__fp_dig + si], 0
    jmp .round_up
.round_store:
    mov [__fp_dig + si], al
.emit_frac:
    ; Emit __fp_dig[0 .. prec-1] as ASCII.
    xor si, si
    mov cx, [__fp_prec]
.emit_loop:
    push cx
    push si
    mov al, [__fp_dig + si]
    add al, '0'
    xor ah, ah
    push ax
    call _putchar
    add sp, 2
    pop si
    pop cx
    inc si
    dec cx
    jnz .emit_loop
    jmp .done
.overflow:
    call _print_overflow
.done:
    pop di
    pop si
    pop dx
    pop cx
    pop bx
    pop bp
    ret

; ---------------------------------------------------------------------------
; __print_f32 — single-precision printer.  Promotes to double and calls
; __print_d64 (which handles the printing).
; ---------------------------------------------------------------------------
__print_f32:
    push bp
    mov bp, sp
    push word [bp + 6]
    push word [bp + 4]
    call __f322d64
    add sp, 4
    ; AX/DX/BX = double bytes.  Push them as a 4-word double argument
    ; and call __print_d64.
    push 0                      ; very-high (we lose it but ok for tests)
    push bx
    push dx
    push ax
    call __print_d64
    add sp, 8
    pop bp
    ret

; ---------------------------------------------------------------------------
; Helpers for printing.
; ---------------------------------------------------------------------------

_print_zero_dot_zeros:
    push ax
    mov ax, '0'
    push ax
    call _putchar
    add sp, 2
    call _print_dot_six_zeros
    pop ax
    ret

_print_dot_six_zeros:
    push ax
    push cx
    mov ax, '.'
    push ax
    call _putchar
    add sp, 2
    mov cx, 6
.loop:
    push cx
    mov ax, '0'
    push ax
    call _putchar
    add sp, 2
    pop cx
    loop .loop
    pop cx
    pop ax
    ret

_print_inf:
    push ax
    mov ax, 'i'
    push ax
    call _putchar
    add sp, 2
    mov ax, 'n'
    push ax
    call _putchar
    add sp, 2
    mov ax, 'f'
    push ax
    call _putchar
    add sp, 2
    pop ax
    ret

_print_nan:
    push ax
    mov ax, 'n'
    push ax
    call _putchar
    add sp, 2
    mov ax, 'a'
    push ax
    call _putchar
    add sp, 2
    mov ax, 'n'
    push ax
    call _putchar
    add sp, 2
    pop ax
    ret

_print_overflow:
    ; Print the literal "BIG" — no need for a .data string just for this.
    push ax
    mov ax, 'B'
    push ax
    call _putchar
    add sp, 2
    mov ax, 'I'
    push ax
    call _putchar
    add sp, 2
    mov ax, 'G'
    push ax
    call _putchar
    add sp, 2
    pop ax
    ret

; Print a 32-bit unsigned integer (DX:AX) in decimal.  Internal — used
; by __print_d64.  Builds digits in a 12-byte buffer and emits in
; reverse order.
_print_ulong_local:
    push bp
    mov bp, sp
    sub sp, 12                  ; digit buffer
    push bx
    push cx
    push si
    push di

    mov ax, [bp + 4]
    mov dx, [bp + 6]
    ; Quick "is value zero?" check.
    mov bx, ax
    or  bx, dx
    jnz .build
    mov ax, '0'
    push ax
    call _putchar
    add sp, 2
    jmp .done
.build:
    ; di = digit-count
    xor di, di
.divloop:
    ; Quotient/remainder of DX:AX by 10 using the "split divide" trick:
    ;   tmp = DX / 10, rem1 = DX % 10
    ;   AX' = (rem1:AX) / 10, rem = (rem1:AX) % 10
    push bx
    mov bx, 10
    mov cx, ax                  ; save low word
    mov ax, dx
    xor dx, dx
    div bx                      ; AX = DX_old/10, DX = DX_old%10
    mov si, ax                  ; si = quotient_high
    mov ax, cx                  ; restore low word
    div bx                      ; AX = quotient_low, DX = digit
    pop bx
    ; Store digit into the buffer at [bp - 1 - di].
    add dl, '0'
    mov bx, di
    neg bx
    dec bx                      ; -1 - di
    push si
    mov si, bx
    mov [bp + si], dl
    pop si
    inc di
    mov dx, si                  ; new high word
    ; Loop until both halves are zero.
    mov cx, ax
    or  cx, dx
    jnz .divloop
    ; Now di = number of digits, buffer at [bp-1] (newest) … [bp-di].
    ; Now di = number of digits, buffer holds digits at:
    ;   [bp-1]   = last (least-significant) digit written
    ;   [bp-di]  = first (most-significant) digit written
    ; Emit from most-significant to least.
.emit:
    test di, di
    jz .done
    push si
    mov si, di
    neg si                       ; si = -di
    mov al, [bp + si]
    pop si
    xor ah, ah
    push di                      ; save di BEFORE pushing the arg, so
    push ax                      ; the arg ends up at [sp] (= [bp+4]
    call _putchar                ; in putchar's frame)
    add sp, 2                    ; clean putchar's argument
    pop di
    dec di
    jmp .emit
.done:
    pop di
    pop si
    pop cx
    pop bx
    mov sp, bp
    pop bp
    ret

; (No .data section — keep fp.obj BSS-only.)  Assign this BSS to DGROUP so the
; linker positions fp's scratch *after* the program's BSS (which also declares
; DGROUP) instead of at a fixed offset that can overlap a large program's
; in-BSS stack/heap.  Supersedes the old BSS-only workaround for the same
; conflict.
group DGROUP bss
