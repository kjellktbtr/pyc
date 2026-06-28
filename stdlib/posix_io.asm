; POSIX-style low-level file I/O for pyc, layered over DOS INT 21h file-handle
; functions (see interrupts/dos_int_ref.md:202-208).
;
; C-visible (no leading underscore, per the stdlib convention):
;   int  open(char *path, int flags, int mode)
;   int  close(int fd)
;   int  read(int fd, void *buf, unsigned count)
;   int  write(int fd, void *buf, unsigned count)
;   long lseek(int fd, long offset, int whence)
;   int  errno          (data symbol)
;
; cdecl: args pushed right-to-left, caller cleans the stack. 16-bit return in
; AX, 32-bit return in DX:AX. The small-model bootstrap keeps SS=DS=ES=DGROUP,
; so a near pointer passed from C is a valid offset for DOS's DS:DX convention.
;
; O_* flag encoding (must match <fcntl.h>):
;   O_RDONLY 0x0000  O_WRONLY 0x0001  O_RDWR 0x0002
;   O_CREAT  0x0100  O_TRUNC  0x0200  O_APPEND 0x0400

[bits 16]

global open
global close
global read
global write
global lseek
global errno

section .text

; int open(char *path, int flags, int mode)
;   [bp+4]=path  [bp+6]=flags  [bp+8]=mode
open:
    push bp
    mov bp, sp
    push bx                         ; preserve callee-saved BX
    mov dx, [bp + 4]                ; DS:DX -> path
    mov bx, [bp + 6]                ; BX = flags (kept for O_APPEND test)
    test bx, 0x0100                 ; O_CREAT?
    jz .open_existing
    ; Create/truncate via AH=3Ch (normal attributes).
    xor cx, cx                      ; CX = 0 (normal file attributes)
    mov ah, 0x3C
    int 0x21
    jc .err
    jmp .opened
.open_existing:
    mov ax, bx
    and al, 0x03                    ; AL = access mode (low 2 bits)
    mov ah, 0x3D
    int 0x21
    jc .err
.opened:
    ; AX = handle. Honour O_APPEND by seeking to end.
    test bx, 0x0400                 ; O_APPEND?
    jz .done
    mov bx, ax                      ; BX = handle
    push ax                         ; save handle for return
    xor cx, cx
    xor dx, dx                      ; CX:DX = 0
    mov al, 0x02                    ; whence = SEEK_END
    mov ah, 0x42
    int 0x21                        ; (ignore seek result/error here)
    pop ax                          ; restore handle
.done:
    pop bx
    mov sp, bp
    pop bp
    ret
.err:
    mov [errno], ax
    mov ax, -1
    pop bx
    mov sp, bp
    pop bp
    ret

; int close(int fd)
;   [bp+4]=fd
close:
    push bp
    mov bp, sp
    push bx
    mov bx, [bp + 4]
    mov ah, 0x3E
    int 0x21
    jc .err
    xor ax, ax                      ; success -> 0
    pop bx
    mov sp, bp
    pop bp
    ret
.err:
    mov [errno], ax
    mov ax, -1
    pop bx
    mov sp, bp
    pop bp
    ret

; int read(int fd, void *buf, unsigned count)
;   [bp+4]=fd  [bp+6]=buf  [bp+8]=count
read:
    push bp
    mov bp, sp
    push bx
    mov bx, [bp + 4]                ; handle
    mov dx, [bp + 6]                ; DS:DX -> buf
    mov cx, [bp + 8]                ; byte count
    mov ah, 0x3F
    int 0x21
    jc .err
    ; AX = bytes read.
    pop bx
    mov sp, bp
    pop bp
    ret
.err:
    mov [errno], ax
    mov ax, -1
    pop bx
    mov sp, bp
    pop bp
    ret

; int write(int fd, void *buf, unsigned count)
;   [bp+4]=fd  [bp+6]=buf  [bp+8]=count
write:
    push bp
    mov bp, sp
    push bx
    mov bx, [bp + 4]                ; handle
    mov dx, [bp + 6]                ; DS:DX -> buf
    mov cx, [bp + 8]                ; byte count
    mov ah, 0x40
    int 0x21
    jc .err
    ; AX = bytes written.
    pop bx
    mov sp, bp
    pop bp
    ret
.err:
    mov [errno], ax
    mov ax, -1
    pop bx
    mov sp, bp
    pop bp
    ret

; long lseek(int fd, long offset, int whence)
;   [bp+4]=fd  [bp+6]=offset-low  [bp+8]=offset-high  [bp+10]=whence
; Returns DX:AX (new file position) or -1 (0xFFFFFFFF) on error.
lseek:
    push bp
    mov bp, sp
    push bx
    mov bx, [bp + 4]                ; handle
    mov dx, [bp + 6]                ; offset low
    mov cx, [bp + 8]                ; offset high  (CX:DX = offset)
    mov ax, [bp + 10]               ; AL = whence (origin); AH overwritten next
    mov ah, 0x42
    int 0x21
    jc .err
    ; DX:AX already = new position.
    pop bx
    mov sp, bp
    pop bp
    ret
.err:
    mov [errno], ax
    mov ax, -1
    mov dx, -1                      ; DX:AX = 0xFFFFFFFF
    pop bx
    mov sp, bp
    pop bp
    ret

section .data
errno: dw 0

; Assign data to DGROUP so the linker places it with the program's DGROUP
; rather than at a fixed offset (consistent with the other stdlib modules).
group DGROUP data
