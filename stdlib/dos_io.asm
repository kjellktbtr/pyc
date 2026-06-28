; Minimal DOS I/O routines for pyc
; Provides: _putchar, _getchar, _exit

[bits 16]

global _putchar
global _getchar
global _exit

section .text

_putchar:
    push bp
    mov bp, sp
    mov dl, [bp + 4]
    cmp dl, 0x0A                ; LF? DOS text-mode newline is CR+LF, so a bare
    jne .pc_emit               ; '\n' must be preceded by a CR or the cursor
    mov dl, 0x0D               ; stays in the same column (staircase output).
    mov ah, 0x02
    int 0x21
    mov dl, 0x0A
.pc_emit:
    mov ah, 0x02
    int 0x21
    mov sp, bp
    pop bp
    ret

_getchar:
    push bp
    mov bp, sp
    mov ah, 0x01
    int 0x21
    mov ah, 0
    mov sp, bp
    pop bp
    ret

_exit:
    push bp
    mov bp, sp
    mov al, [bp + 4]
    mov ah, 0x4C
    int 0x21
