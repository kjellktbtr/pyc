# single/ Suite — Test Procedure

The `single/` directory contains 40 self-contained C programs, each paired with a
`*.reference_output` file recording the exact expected stdout (plus a trailing
`exit N` line from the reference compiler). They are the primary integration
test suite for the compiler.

## Directory layout

```
single/
  <name>.c                      # Source file
  <name>.reference_output       # Expected stdout (may have "exit 0" on last line)
  <name>.reference_output.AIX   # Alternate expected output on big-endian / AIX (optional)
```

Intermediate build artefacts (`.asm`, `.obj`) land next to the source unless
`-o` is used to redirect the output.

## Test files (40 total)

| # | File | Key feature under test |
|---|------|----------------------|
| t01 | 2003-05-14-initialize-string.c | Global string initializer |
| t02 | 2003-05-21-BitfieldHandling.c | Struct bitfields |
| t03 | 2003-05-21-UnionBitfields.c | Union bitfields |
| t04 | 2003-05-21-UnionTest.c | Designated initializers, union |
| t05 | 2003-05-22-LocalTypeTest.c | Nested-scope struct redefinition |
| t06 | 2003-05-22-VarSizeArray.c | Variable-length arrays (VLA) |
| t07 | 2003-05-23-TransparentUnion.c | `__attribute__((__transparent_union__))` |
| t08 | 2003-06-16-InvalidInitializer.c | Const-expr init `&((T*)0)->x` |
| t09 | 2003-06-16-VolatileError.c | `volatile` qualifier |
| t10 | 2003-10-12-GlobalVarInitializers.c | Global anonymous-union initializer |
| t11 | 2004-02-03-AggregateCopy.c | Struct assignment (`B = C = A`) |
| t12 | 2004-03-15-IndirectGoto.c | GNU `&&label` + computed `goto *p` |
| t13 | 2004-08-12-InlinerAndAllocas.c | `alloca`, inlining |
| t14 | 2005-05-06-LongLongSignedShift.c | 64-bit signed shift (`>>`) |
| t15 | 2008-01-07-LongDouble.c | `long double` type |
| t16 | badidx.c | Cast `(int *) calloc(...)` |
| t17 | bigstack.c | `double` arithmetic, large stack, K&R function header |
| t18 | callargs.c | Multi-member struct, `double` args |
| t19 | casts.c | `<inttypes.h>`, `%lld`/`%llx` |
| t20 | compare.c | `<stddef.h>`, `size_t` |
| t21 | ConstructorDestructorAttributes.c | `__attribute__((constructor))` |
| t22 | DuffsDevice.c | Duff's Device, K&R function definition |
| t23 | float16-smoke.c | Hex float literals (`0x1p+0` etc.) |
| t24 | globalrefs.c | `<inttypes.h>`, `PRId*` macros |
| t25 | matrixTranspose.c | `extern` array, `float` arithmetic |
| t26 | pointer_arithmetic.c | Struct field list with typedef'd type |
| t27 | PR10189.c | Multi-keyword integer specs (`int short`, `unsigned short`) |
| t28 | PR1386.c | Forward-declared `struct Foo*` in struct field |
| t29 | PR491.c | Bitfield inside union, `#` stringify |
| t30 | PR640.c | `va_arg` with `unsigned long` (4-byte) |
| t31 | sumarray2d.c | 2D array parameter `int Array[][N]` |
| t32 | sumarray.c | Cast `(int)` expression |
| t33 | sumarraymalloc.c | Cast `(int *)malloc(...)` |
| t34 | test_indvars.c | `double` loop induction, `%.0lf` |
| t35 | testtrace.c | Forward reference `struct Foo*` in parameter |
| t36 | uint64_to_float.c | `uint64_t` → `float`, `<fenv.h>` |
| t37 | posix_fileio.c | POSIX `open`/`write`/`lseek`/`read`/`close` round-trip (`<fcntl.h>`, `<unistd.h>`) |
| t38 | serial_smoke.c | Raw INT 14h serial layer `serial_init`/`serial_putc`/`serial_status` (`<serial.h>`) |
| t39 | multi_double_print.c | Regression: ≥2 distinct `double`s via `printf` (stack/stdlib-BSS guard-gap fix; loops without it) |
| t40 | double_muldiv.c | Regression: double `*` / `/` (`__dmul64`/`__ddiv64`; were stubs returning an operand) |

## How to compile and run one test

### Step 1 — Compile to `.exe`

```bash
cd /home/ai/pyc
.venv/bin/python -m src.pyc single/<name>.c -o /tmp/pyc_single/<short>.exe
```

- `<short>` must be ≤ 8 alphanumeric characters (DOS 8.3 filename).
- Intermediate `.asm` and `.obj` files are written to `/tmp/pyc_single/` by
  virtue of the `-o` flag choosing that directory.
- Compile errors go to stderr; redirect with `2>&1 | tee /tmp/foo.log`.

### Step 2 — Run under DOSBox and capture stdout

```bash
mkdir -p /tmp/pyc_single
SDL_VIDEODRIVER=dummy timeout 12 dosbox \
    -c "mount c /tmp/pyc_single" \
    -c "c:" \
    -c "<short>.exe > <short>.out" \
    -c "exit" -exit \
    >/dev/null 2>&1
```

- `SDL_VIDEODRIVER=dummy` suppresses the video device requirement in headless
  environments (without it DOSBox exits immediately with
  `Can't init SDL No available video device`).
- `timeout 12` kills DOSBox if the program hangs (infinite loop, blocked
  `getchar`, etc.).
- DOSBox always writes redirect output with an **upper-case** 8.3 name, so
  `<short>.out` becomes `<SHORT>.OUT` on the mount. Check both casings:

```bash
for cand in /tmp/pyc_single/<SHORT>.OUT /tmp/pyc_single/<short>.out; do
    [ -f "$cand" ] && cat "$cand" && break
done
```

### Step 3 — Compare against the reference

```bash
ACTUAL=$(tr -d '\r' < /tmp/pyc_single/<SHORT>.OUT)
EXPECTED=$(cat single/<name>.reference_output)
diff <(echo "$EXPECTED" | grep -v '^exit [0-9]*$') <(echo "$ACTUAL")
```

The reference files end with `exit N` (the exit code printed by the reference
compiler). `pyc` cannot emit that line because it executes `INT 21/AH=4Ch`
after `main` returns without any stdio call. The harness strips lines matching
`^exit [0-9]+$` before comparing.

## Running the full suite with the harness

The script `/tmp/pyc_verify.sh` automates the above for one test at a time.
To run all 36:

```bash
cd /home/ai/pyc
mkdir -p /tmp/pyc_single
i=0
for f in single/*.c; do
    i=$((i + 1))
    short=$(printf "t%02d" "$i")
    /tmp/pyc_verify.sh "$f" "$short"
done
```

Each line prints one of:
- `PASS: <name>` — output matches reference (with or without the `exit N` line)
- `MISMATCH: <name>` — compiled and ran, but output differs (shows first 8 lines of each)
- `COMPILE_FAIL: <name>` — `pyc` or `alink`/`nasm` returned non-zero; last 5 lines of compile log shown
- `NO_OUTPUT: <name>` — DOSBox timed out or produced no file (often an infinite loop)
- `NO_EXE: <name>` — compile appeared to succeed but no `.exe` was produced

Compile logs are written to `/tmp/pyc_single/<short>.compilog`.

### Quick summary (count PASSes)

```bash
cd /home/ai/pyc
mkdir -p /tmp/pyc_single
i=0
pass=0; fail=0; miss=0
for f in single/*.c; do
    i=$((i + 1))
    short=$(printf "t%02d" "$i")
    result=$(/tmp/pyc_verify.sh "$f" "$short")
    echo "$result"
    case "$result" in
        PASS*) pass=$((pass + 1)) ;;
        MISMATCH*) miss=$((miss + 1)) ;;
        *) fail=$((fail + 1)) ;;
    esac
done
echo "---"
echo "PASS=$pass  MISMATCH=$miss  FAIL=$fail  TOTAL=$((pass+miss+fail))"
```

## Harness file location

The script is at `/tmp/pyc_verify.sh` (not in the repo; recreated below if lost):

```bash
cat > /tmp/pyc_verify.sh << 'EOF'
#!/bin/bash
set -u
cd /home/ai/pyc
SRC="$1"
SHORT="$2"
NAME=$(basename "$SRC" .c)
REF="single/${NAME}.reference_output"
WORKDIR=/tmp/pyc_single
EXE="${WORKDIR}/${SHORT}.exe"
OUT_DOS_NAME="${SHORT}.out"
OUT="${WORKDIR}/${OUT_DOS_NAME^^}"
ALT_OUT="${WORKDIR}/${OUT_DOS_NAME}"
LOG="${WORKDIR}/${SHORT}.compilog"

rm -f "$EXE" "$OUT" "$ALT_OUT" "$LOG" "${WORKDIR}/${SHORT^^}.OUT" "${WORKDIR}/${SHORT}.out"

if ! .venv/bin/python -m src.pyc "$SRC" -o "$EXE" > "$LOG" 2>&1; then
    echo "COMPILE_FAIL: $NAME"; tail -5 "$LOG" | sed 's/^/  /'; exit 1
fi
if [ ! -f "$EXE" ]; then
    echo "NO_EXE: $NAME"; tail -5 "$LOG" | sed 's/^/  /'; exit 1
fi

SDL_VIDEODRIVER=dummy timeout 12 dosbox \
    -c "mount c ${WORKDIR}" -c "c:" \
    -c "${SHORT}.exe > ${SHORT}.out" \
    -c "exit" -exit >/dev/null 2>&1
RC=$?

FOUND=""
for cand in "${WORKDIR}/${SHORT}.OUT" "${WORKDIR}/${SHORT}.out" \
            "${WORKDIR}/${SHORT^^}.OUT" "${WORKDIR}/${SHORT^^}.out"; do
    [ -f "$cand" ] && FOUND="$cand" && break
done

if [ -z "$FOUND" ]; then
    echo "NO_OUTPUT: $NAME (dosbox rc=$RC)"; exit 1
fi

ACTUAL=$(tr -d '\r' < "$FOUND")
EXPECTED=$(cat "$REF")
EXPECTED_LINES_NX=$(grep -v '^exit [0-9]*$' "$REF" 2>/dev/null)
if [ "$ACTUAL" = "$EXPECTED" ] || [ "$ACTUAL" = "$EXPECTED_LINES_NX" ]; then
    echo "PASS: $NAME"; exit 0
fi
EXPECTED_NX2=$(sed -E 's/exit [0-9]+\s*$//' "$REF" | sed -E '/^$/d')
ACT_NORM=$(echo "$ACTUAL" | sed -E 's/exit [0-9]+$//')
EXP_NORM=$(echo "$EXPECTED" | sed -E 's/exit [0-9]+$//')
if [ "$ACTUAL" = "$EXPECTED_NX2" ] || [ "$ACT_NORM" = "$EXP_NORM" ]; then
    echo "PASS: $NAME (modulo exit-line)"; exit 0
fi
echo "MISMATCH: $NAME"
echo "  expected:"; echo "$EXPECTED_LINES_NX" | head -8 | sed 's/^/    /'
echo "  actual:";   echo "$ACTUAL"            | head -8 | sed 's/^/    /'
exit 2
EOF
chmod +x /tmp/pyc_verify.sh
```

## Important DOSBox notes

- **No video needed**: always export `SDL_VIDEODRIVER=dummy` or the `dosbox`
  process dies immediately in headless/SSH sessions.
- **Upper-case output names**: DOSBox forces 8.3 filenames to upper-case in its
  FAT layer. A redirect written as `t01.out` appears as `T01.OUT` on the host.
  Always check both cases (the harness does this automatically).
- **Timeout**: 12 seconds is generous for programs that run quickly. If a test
  hangs, check for infinite loops before extending the timeout.
- **Mount point**: the entire `/tmp/pyc_single/` directory is mounted as `C:\`.
  Only 8.3 filenames are accessible from inside DOSBox. The short name argument
  to the harness (`t01` … `t36`) satisfies this constraint.

## Adding a new reference output

If a C file is added to `single/` without a reference output, generate it with
GCC on the host and save it:

```bash
gcc -m32 single/<name>.c -o /tmp/<name>_ref && /tmp/<name>_ref > single/<name>.reference_output
echo "exit $?" >> single/<name>.reference_output
```

(Use `-m32` to match 32-bit int behaviour of the reference compiler; note that
`pyc` targets 16-bit int, so outputs that depend on int width will legitimately
differ.)
