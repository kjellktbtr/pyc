// stdlib.c - Standard library for pyc
#include <stdlib.h>

/* DOS I/O helper */
void _exit(int code);

/* --- exit --- */
void exit(int code) {
    _exit(code);
}

/* --- atoi --- */
int atoi(char *nptr) {
    int result = 0;
    int negative = 0;

    while (*nptr == ' ' || *nptr == '\t') {
        nptr = nptr + 1;
    }

    if (*nptr == '-') {
        negative = 1;
        nptr = nptr + 1;
    } else if (*nptr == '+') {
        nptr = nptr + 1;
    }

    while (*nptr >= '0' && *nptr <= '9') {
        result = result * 10 + (*nptr - '0');
        nptr = nptr + 1;
    }

    if (negative) {
        result = -result;
    }
    return result;
}

/* --- atol --- */
long atol(char *nptr) {
    return atoi(nptr);
}

/* --- malloc: bump-pointer allocator over a fixed BSS heap. --- */
/* Heap layout: `_heap` is a 16 KB byte array in BSS; `_heap_pos`
   is the index of the next free byte.  Allocations align up to 2
   bytes (matching the natural word alignment for the 16-bit target).
   This is intentionally simple — no coalescing, no reuse — but lets
   programs that allocate-and-forget run correctly. */
#define _HEAP_SIZE 16384
static char _heap[_HEAP_SIZE];
static int _heap_pos = 0;

void *malloc(int size) {
    /* Align request up to 2 bytes. */
    int need = (size + 1) & ~1;
    if (need <= 0) {
        return 0;
    }
    if (_heap_pos + need > _HEAP_SIZE) {
        return 0;
    }
    char *p = &_heap[_heap_pos];
    _heap_pos = _heap_pos + need;
    return p;
}

/* --- free (no-op for bump allocator) --- */
void free(void *ptr) {
}

/* --- calloc: malloc + zero-fill --- */
void *calloc(int nmemb, int size) {
    int n = nmemb * size;
    char *p = malloc(n);
    if (p == 0) {
        return 0;
    }
    int i;
    for (i = 0; i < n; i = i + 1) {
        p[i] = 0;
    }
    return p;
}

/* --- realloc: allocate fresh, copy bytes, leak old (bump alloc) --- */
void *realloc(void *ptr, int size) {
    char *new_p = malloc(size);
    if (ptr == 0 || new_p == 0) {
        return new_p;
    }
    /* We don't know the old size; copy `size` bytes which is the
       caller's promise that's at least the old size. */
    char *src = ptr;
    int i;
    for (i = 0; i < size; i = i + 1) {
        new_p[i] = src[i];
    }
    return new_p;
}

/* --- atof (stub - returns 0.0) --- */
/* No FPU emulation; declared so source compiles and links. */
double atof(char *nptr) {
    return 0;
}

/* `abs` collides with a NASM reserved word; it is provided as a macro in
   <stdlib.h>: #define abs(x) ((x)<0?-(x):(x)) */

/* --- rand / srand: LCG, C stdlib-compatible parameters ---
   Seed must be 32-bit so that (seed >> 16) produces a non-zero result.
   unsigned int is 16-bit in pyc; use unsigned long (32-bit) for the seed. */
static unsigned long _rand_seed = 1;

void srand(unsigned int seed) {
    _rand_seed = (unsigned long)seed;
}

int rand(void) {
    _rand_seed = _rand_seed * 1103515245UL + 12345UL;
    return (int)((_rand_seed >> 16) & 0x7FFF);
}
