; DOS directory operations for pyc, layered over INT 21h (see
; interrupts/dos_int_ref.md). Companion to posix_io.asm; shares its `errno`.
;
; C-visible (no leading underscore):
;   int mkdir(char *path)          ; INT 21h/AH=39h
;   int set_dta(void *dta)         ; INT 21h/AH=1Ah  (128-byte Disk Transfer Area)
;   int find_first(char *spec, int attr) ; INT 21h/AH=4Eh
;   int find_next(void)            ; INT 21h/AH=4Fh
;
; find_first/find_next fill the DTA: [21]=attr, [26..29]=size(dword LE),
; [30..]=filename ASCIIZ.  The C side sets a DTA via set_dta() and parses it.
;
; cdecl: args pushed right-to-left, caller cleans the stack, 16-bit return in AX.

[bits 16]

global mkdir
global set_dta
global find_first
global find_next
extern errno

section .text

; int mkdir(char *path) — [bp+4]=path.  Returns 0 on success OR if the
; directory already exists (DOS reports AX=5, "access denied"); -1 otherwise.
mkdir:
    push bp
    mov bp, sp
    mov dx, [bp + 4]
    mov ah, 0x39
    int 0x21
    jc .err
    xor ax, ax
    pop bp
    ret
.err:
    cmp ax, 5                       ; access denied ⇒ usually "already exists"
    je .exists
    mov [errno], ax
    mov ax, -1
    pop bp
    ret
.exists:
    xor ax, ax
    pop bp
    ret

; int set_dta(void *dta) — [bp+4]=dta (128-byte buffer).  Returns 0.
set_dta:
    push bp
    mov bp, sp
    mov dx, [bp + 4]
    mov ah, 0x1A
    int 0x21
    xor ax, ax
    pop bp
    ret

; int find_first(char *spec, int attr) — [bp+4]=spec, [bp+6]=attr.
; Returns 0 if a match was found, -1 otherwise (errno = DOS code).
find_first:
    push bp
    mov bp, sp
    push cx
    mov dx, [bp + 4]
    mov cx, [bp + 6]
    mov ah, 0x4E
    int 0x21
    jc .err
    xor ax, ax
    pop cx
    pop bp
    ret
.err:
    mov [errno], ax
    mov ax, -1
    pop cx
    pop bp
    ret

; int find_next(void) — continue the previous find.  0 if another match,
; -1 when no more files (errno = 18).
find_next:
    push bp
    mov bp, sp
    mov ah, 0x4F
    int 0x21
    jc .err
    xor ax, ax
    pop bp
    ret
.err:
    mov [errno], ax
    mov ax, -1
    pop bp
    ret
