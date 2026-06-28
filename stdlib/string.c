// string.c - String functions for pyc
#include <string.h>

/* --- strlen --- */
int strlen(char *s) {
    int len = 0;
    while (*s) {
        len = len + 1;
        s = s + 1;
    }
    return len;
}

/* --- strcpy --- */
char *strcpy(char *dest, char *src) {
    char *d = dest;
    while (*src) {
        *d = *src;
        d = d + 1;
        src = src + 1;
    }
    *d = '\0';
    return dest;
}

/* --- strcmp --- */
int strcmp(char *s1, char *s2) {
    while (*s1 && *s2) {
        if (*s1 != *s2) {
            return *s1 - *s2;
        }
        s1 = s1 + 1;
        s2 = s2 + 1;
    }
    return *s1 - *s2;
}

/* --- memcpy --- */
void *memcpy(void *dest, void *src, int n) {
    char *d = dest;
    char *s = src;
    while (n > 0) {
        *d = *s;
        d = d + 1;
        s = s + 1;
        n = n - 1;
    }
    return dest;
}

/* --- memset --- */
void *memset(void *s, int c, int n) {
    char *p = s;
    while (n > 0) {
        *p = c;
        p = p + 1;
        n = n - 1;
    }
    return s;
}

/* --- strncpy: copy at most n bytes, zero-pad remainder --- */
char *strncpy(char *dest, char *src, int n) {
    char *d = dest;
    while (n > 0 && *src) {
        *d = *src;
        d = d + 1;
        src = src + 1;
        n = n - 1;
    }
    while (n > 0) {
        *d = '\0';
        d = d + 1;
        n = n - 1;
    }
    return dest;
}

/* --- strcat: append src to dest --- */
char *strcat(char *dest, char *src) {
    char *d = dest;
    while (*d) {
        d = d + 1;
    }
    while (*src) {
        *d = *src;
        d = d + 1;
        src = src + 1;
    }
    *d = '\0';
    return dest;
}

/* --- strncmp: compare at most n chars --- */
int strncmp(char *s1, char *s2, int n) {
    while (n > 0 && *s1 && *s2) {
        if (*s1 != *s2) {
            return *s1 - *s2;
        }
        s1 = s1 + 1;
        s2 = s2 + 1;
        n = n - 1;
    }
    if (n == 0) {
        return 0;
    }
    return *s1 - *s2;
}
