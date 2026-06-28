; Raw BIOS serial-port layer for pyc, using INT 14h. This bypasses DOS and
; talks to the UART through the BIOS for polled access and baud configuration.
;
; C-visible (no leading underscore, per the stdlib convention):
;   int serial_init(int port, int params)   ; INT 14h/AH=00h
;   int serial_putc(int port, int ch)        ; INT 14h/AH=01h
;   int serial_getc(int port)                ; INT 14h/AH=02h
;   int serial_status(int port)              ; INT 14h/AH=03h
;
; `port` is 0-based (0 = COM1). `params` is the INT 14h line-control byte
; (see <serial.h> for the bit layout / convenience macros).
;
; cdecl: args pushed right-to-left, caller cleans the stack, return in AX.

[bits 16]

global serial_init
global serial_putc
global serial_getc
global serial_status
; Direct 8250/16550 UART access by I/O base (e.g. 0x3F8 = COM1).  Polled, no
; BIOS — reliable enough for an ack/nak framed protocol.  See <serial.h>.
global uart_init
global uart_rx_ready
global uart_getc
global uart_putc

section .text

; int uart_init(int base) — [bp+4]=I/O base.  8N1, 9600 baud (divisor 12),
; FIFOs on, interrupts off (we poll).  Returns 0.
uart_init:
    push bp
    mov bp, sp
    push dx
    mov dx, [bp + 4]
    inc dx                      ; base+1 = IER
    xor al, al
    out dx, al                  ; disable UART interrupts (polled mode)
    mov dx, [bp + 4]
    add dx, 3                   ; base+3 = LCR
    mov al, 0x80
    out dx, al                  ; DLAB = 1
    mov dx, [bp + 4]            ; base+0 = DLL
    mov al, 12                  ; 115200 / 9600
    out dx, al
    mov dx, [bp + 4]
    inc dx                      ; base+1 = DLM
    xor al, al
    out dx, al
    mov dx, [bp + 4]
    add dx, 3                   ; LCR
    mov al, 0x03                ; 8 data bits, no parity, 1 stop, DLAB=0
    out dx, al
    mov dx, [bp + 4]
    add dx, 2                   ; base+2 = FCR
    mov al, 0xC7                ; enable + clear RX/TX FIFOs
    out dx, al
    mov dx, [bp + 4]
    add dx, 4                   ; base+4 = MCR
    mov al, 0x0B                ; DTR, RTS, OUT2
    out dx, al
    xor ax, ax
    pop dx
    pop bp
    ret

; int uart_rx_ready(int base) — nonzero if a received byte is waiting.
uart_rx_ready:
    push bp
    mov bp, sp
    push dx
    mov dx, [bp + 4]
    add dx, 5                   ; base+5 = LSR
    in al, dx
    xor ah, ah
    and al, 0x01                ; data-ready bit
    pop dx
    pop bp
    ret

; int uart_getc(int base) — block until a byte arrives; return it (0..255).
uart_getc:
    push bp
    mov bp, sp
    push dx
.ug_wait:
    mov dx, [bp + 4]
    add dx, 5                   ; LSR
    in al, dx
    test al, 0x01               ; data ready?
    jz .ug_wait
    mov dx, [bp + 4]            ; RBR = base
    in al, dx
    xor ah, ah
    pop dx
    pop bp
    ret

; int uart_putc(int base, int c) — block until the transmit holding register
; is empty, then send the byte.  Returns 0.
uart_putc:
    push bp
    mov bp, sp
    push dx
.up_wait:
    mov dx, [bp + 4]
    add dx, 5                   ; LSR
    in al, dx
    test al, 0x20               ; THR empty?
    jz .up_wait
    mov dx, [bp + 4]            ; THR = base
    mov ax, [bp + 6]
    out dx, al
    xor ax, ax
    pop dx
    pop bp
    ret

; int serial_init(int port, int params)
;   [bp+4]=port  [bp+6]=params
; Returns the 16-bit status word (AH=line status, AL=modem status).
serial_init:
    push bp
    mov bp, sp
    mov dx, [bp + 4]                ; DX = port number
    mov ax, [bp + 6]
    mov ah, 0x00                    ; AL = params, AH = init function
    int 0x14
    mov sp, bp
    pop bp
    ret

; int serial_putc(int port, int ch)
;   [bp+4]=port  [bp+6]=ch
; Returns the line-status byte (AH on return, bit 7 = timeout).
serial_putc:
    push bp
    mov bp, sp
    mov dx, [bp + 4]                ; DX = port
    mov ax, [bp + 6]                ; AL = char
    mov ah, 0x01
    int 0x14
    mov al, ah                      ; return line status in AX
    xor ah, ah
    mov sp, bp
    pop bp
    ret

; int serial_getc(int port)
;   [bp+4]=port
; Returns the received byte (0-255), or -1 if AH bit 7 (error/timeout) is set.
serial_getc:
    push bp
    mov bp, sp
    mov dx, [bp + 4]                ; DX = port
    mov ah, 0x02
    int 0x14
    test ah, 0x80                   ; error/timeout?
    jnz .err
    xor ah, ah                      ; AX = received byte
    mov sp, bp
    pop bp
    ret
.err:
    mov ax, -1
    mov sp, bp
    pop bp
    ret

; int serial_status(int port)
;   [bp+4]=port
; Returns the 16-bit status word (AH=line status, AL=modem status).
serial_status:
    push bp
    mov bp, sp
    mov dx, [bp + 4]                ; DX = port
    mov ah, 0x03
    int 0x14
    mov sp, bp
    pop bp
    ret
