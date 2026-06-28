#!/bin/bash
# Verifies one C file: compile -> .exe in 8.3 short name -> dosbox run with stdout redirect -> diff vs reference
set -u
cd /home/ai/pyc
SRC="$1"
SHORT="$2"   # 1..8 chars, [a-z0-9]
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
    echo "COMPILE_FAIL: $NAME"
    tail -5 "$LOG" | sed 's/^/  /'
    exit 1
fi
if [ ! -f "$EXE" ]; then
    echo "NO_EXE: $NAME"
    tail -5 "$LOG" | sed 's/^/  /'
    exit 1
fi

SDL_VIDEODRIVER=dummy timeout 12 dosbox \
    -c "mount c ${WORKDIR}" -c "c:" \
    -c "${SHORT}.exe > ${SHORT}.out" \
    -c "exit" -exit >/dev/null 2>&1
RC=$?

FOUND=""
for cand in "${WORKDIR}/${SHORT}.OUT" "${WORKDIR}/${SHORT}.out" "${WORKDIR}/${SHORT^^}.OUT" "${WORKDIR}/${SHORT^^}.out"; do
    if [ -f "$cand" ]; then FOUND="$cand"; break; fi
done

if [ -z "$FOUND" ]; then
    echo "NO_OUTPUT: $NAME (dosbox rc=$RC, timeout likely)"
    exit 1
fi

ACTUAL=$(tr -d '\r' < "$FOUND")
if [ ! -f "$REF" ]; then
    echo "NO_REFERENCE: $NAME"
    exit 1
fi
EXPECTED=$(cat "$REF")
# Strip "exit N" anywhere in expected (some references have it on its own
# line, others append it to the prior line without a newline).
EXPECTED_NX=$(sed -E 's/exit [0-9]+$//' "$REF" | sed -E '/^$/d' | tr -d '\n')
ACTUAL_NN=$(echo -n "$ACTUAL" | tr -d '\n')

if [ "$ACTUAL" = "$EXPECTED" ]; then
    echo "PASS: $NAME"
    exit 0
fi
# Try stripping the trailing "exit N" line
EXPECTED_LINES_NX=$(grep -v '^exit [0-9]*$' "$REF" 2>/dev/null)
if [ "$ACTUAL" = "$EXPECTED_LINES_NX" ]; then
    echo "PASS: $NAME (modulo exit-line)"
    exit 0
fi
# Strip "exit N" appearing in the middle/end without a preceding newline
EXPECTED_NX2=$(sed -E 's/exit [0-9]+\s*$//' "$REF" | sed -E '/^$/d')
if [ "$ACTUAL" = "$EXPECTED_NX2" ]; then
    echo "PASS: $NAME (modulo exit-line)"
    exit 0
fi
# Last resort: compare ignoring trailing "exit N" with no newline before it
ACT_NORM=$(echo "$ACTUAL" | sed -E 's/exit [0-9]+$//')
EXP_NORM=$(echo "$EXPECTED" | sed -E 's/exit [0-9]+$//')
if [ "$ACT_NORM" = "$EXP_NORM" ]; then
    echo "PASS: $NAME (modulo exit-line)"
    exit 0
fi

echo "MISMATCH: $NAME"
echo "  expected:"
echo "$EXPECTED_LINES_NX" | head -8 | sed 's/^/    /'
echo "  actual:"
echo "$ACTUAL" | head -8 | sed 's/^/    /'
exit 2
