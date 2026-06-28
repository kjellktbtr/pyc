# Debugging pyc-generated DOS programs (bochs / qemu)

How to run a compiled `.exe` under a full PC emulator with a real DOS, and
inspect it at runtime. Built to chase the layout-dependent FP corruption bug
(see `docs/progress-log.md`), but reusable for any runtime debugging that the
`single/` DOSBox harness can't reach.

## What's installed (Manjaro, this machine)

| Tool | Use |
|------|-----|
| `qemu-system-i386` | **Fast** boot (~2 s). Best for iteration. Non-invasive introspection via `-monitor stdio` and `-serial file:`. gdb stub via `-s -S`. |
| `bochs` (debugger build: `-debugger`, `-rc cmds`, `-dbglog`) | Scriptable debugger + magic breakpoints, but **slow** (~10⁵ ticks/s under xvfb) and needs `display_library: x` under `xvfb-run` (no `nogui` in this build). |
| `dosbox` 0.74-3 | The `single/` suite reference env. The FP corruption reproduces here AND under qemu (it is **not** a DOSBox quirk). |
| `tools/fat12img.py` | Pure-Python FAT12 reader/writer — inject the `.exe` + `AUTOEXEC.BAT` into a boot floppy. No mtools/root/loop-mount needed. |

A bootable FreeDOS floppy (`fdboot.img`, boots to a prompt) was fetched from
`https://raw.githubusercontent.com/codercowboy/freedosbootdisks/master/bootdisks/freedos.boot.disk.1.4MB.img`
(the ibiblio `FD12FLOPPY.zip` is the *setup* floppy — usable but launches the
installer). Keep a copy; the disk just needs `KERNEL.SYS`/`COMMAND.COM` + space.

## Recipe — run an exe under qemu and capture output

```bash
cp fdboot.img run.img
printf 'MYPROG.EXE\r\n' > ae.bat          # or 'MYPROG.EXE > OUT.TXT' to capture
python3 tools/fat12img.py write run.img MYPROG.EXE /path/to/MYPROG.EXE
python3 tools/fat12img.py write run.img AUTOEXEC.BAT ae.bat
timeout 20 qemu-system-i386 -fda run.img -boot a -display none -no-reboot
python3 tools/fat12img.py read run.img OUT.TXT   # read results back out
```

Notes:
- `printf` in pyc's runtime uses INT 21/AH=02 (console). DOS `> OUT.TXT`
  **does** redirect it (it routes through handle 1), so file capture works.
- For looping programs, DOS flushes the 512-byte file buffer periodically, so
  `OUT.TXT` still fills even without a clean exit.

## Recipe — serial round-trip (feed input + log output)

QEMU can both feed a file into the guest's serial port and log what the guest
sends — no live interaction, fully scriptable:

```bash
printf 'HELLO\n' > /tmp/ser_in.dat
qemu-system-i386 -fda run.img -boot a -display none \
  -chardev file,id=s0,path=/tmp/ser_out.log,input-path=/tmp/ser_in.dat \
  -serial chardev:s0
cat /tmp/ser_out.log     # whatever the guest wrote to COM1
```
- `input-path` → bytes delivered to the guest UART (read via the INT 14h serial
  layer `serial_getc`, or DOS `open("COM1")`/`read`).
- `path` → the guest's serial TX (`serial_putc`) is appended here.
- Verified with an echo program (`serial_getc`→`serial_putc`): `HELLO-FROM-HOST`
  fed in came back out in the log. This is how to do *real* serial RX/TX testing
  (the `single/serial_smoke.c` suite test only checks link+run under DOSBox,
  whose 0.74 serial backends are nullmodem/directserial only — no file I/O).
- Needs QEMU ≥ 7.0 for `input-path` (here 10.2.1).

## Recipe — non-invasive runtime introspection (qemu monitor)

Freeze the running program and dump CPU state **without modifying the binary**
(critical: the FP bug is layout-sensitive, so any instrumentation perturbs it):

```bash
( sleep 10; echo stop; echo "info registers"; echo "x/8i $eip"; echo quit ) | \
  timeout 25 qemu-system-i386 -fda run.img -boot a -display none -monitor stdio
```
`info registers` gives CS/SS/DS (the DOS load segment) and ESP/EBP; `x/...`
examines code/memory at the current segment. This is how the "stack marches
~14 KB downward (runaway re-entry)" signature was found.

## Recipe — instrument with a serial trace (when perturbing layout is OK)

Emit values over COM1 by writing the UART THR directly (`out 0x3F8, al`), which
qemu captures with `-serial file:OUT`:

```asm
_dbg_hex:            ; print AX as 4 hex + CRLF to COM1, preserves regs
    pushf
    push ax / push cx / push dx / push si
    mov si, ax
    mov cx, 4
.lp: rol si, 4
    mov ax, si
    and al, 0x0F
    add al, '0'
    cmp al, '9'
    jbe .e
    add al, 7
.e: mov dx, 0x3F8
    out dx, al
    loop .lp
    mov dx,0x3F8 / mov al,13 / out dx,al / mov al,10 / out dx,al
    pop si / pop dx / pop cx / pop ax / popf / ret
```
Insert `mov ax, sp` + `call _dbg_hex` at checkpoints. ⚠️ Adding code shifts the
layout and can move a buggy binary out of the trigger window — use the monitor
(above) when you must observe the *unmodified* binary.

## bochs (scriptable debugger, slow)

```bash
cat > bochsrc <<EOF
megs: 32
romimage: file=/usr/share/bochs/BIOS-bochs-latest
vgaromimage: file=/usr/share/bochs/VGABIOS-lgpl-latest.bin
floppya: 1_44=run.img, status=inserted
boot: floppy
display_library: x
magic_break: enabled=1
EOF
{ echo c; for i in $(seq 8); do echo sreg; echo r; echo c; done; echo q; } > cmds.txt
xvfb-run -a bochs -q -f bochsrc -rc cmds.txt
```
`magic_break` stops on `xchg bx, bx` (opcode `87 DB`) inserted in the code —
position-independent breakpoints. Debugger output goes to stdout (under the `x`
GUI it can be swallowed; prefer qemu for capture). Slow: budget minutes per run.

## qemu + gdb (hardware watchpoint — next step for the FP bug)

`qemu-system-i386 -fda run.img -boot a -display none -s -S` exposes a gdb stub
on `:1234`; `gdb -batch -ex 'target remote :1234' ...`. gdb breakpoints and
watchpoints are written into live memory, so they're **non-invasive to the
on-disk layout** (essential for the layout-sensitive FP bug). Attach without
`-S` and the CPU halts wherever it is on connect (use a delay to land mid-run).

**Gotchas (learned the hard way):**
- This gdb disassembles the guest's 16-bit code as **32-bit** even after
  `set architecture i8086`. Don't trust `x/i`; dump bytes with `x/NXb <lin>` and
  pipe through `ndisasm -b16`.
- Segment arithmetic: `x/... ((int)$cs*16)+((int)$eip & 0xffff)` (cast to int).
- gdb examines by **linear address** (= physical in real mode, no paging):
  `linear = (seg<<4) + off`.

**Deterministic procedure to catch the first corrupting write:**
1. Get the target's layout from its link map (`alink ... -m`): e.g. for the FP
   repro, `main` at `text:0`, header `CS=0x0806` (relative).
2. qemu `-S` (frozen at reset); `target remote :1234`.
3. Learn `LOADSEG`: break at `_entry` (its first insn is `mov ax, imm16` where the
   relocated `imm16` = DGROUP segment = `DS`=`SS`); read it. Then runtime
   `main` linear = `(LOADSEG + 0x806) << 4`.
4. `hbreak *<main_linear>`, `continue`; at the hit read `SS:SP` — `[SS:SP]` is
   `main`'s return address slot.
5. `watch` (hardware) the return slot `(SS<<4)+SP`; `continue`. The watchpoint
   fires on the write that clobbers it — `CS:IP` then names the culprit. (Near
   `ret`s can't change `CS`; the observed `CS`-escape into DGROUP/BIOS is a
   downstream `IRET` from an `INT 21h` reading an already-corrupted stack.)
```
