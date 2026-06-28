#!/usr/bin/env python3
"""Minimal FAT12 floppy-image tool: list / read / write files in the root dir.

No external deps, no mount, no root. Enough to inject a test .exe and an
AUTOEXEC.BAT into a FreeDOS boot floppy for debugging under bochs/qemu.
"""
from __future__ import annotations
import struct, sys
from pathlib import Path


class Fat12:
    def __init__(self, path: Path):
        self.path = path
        self.data = bytearray(path.read_bytes())
        bpb = self.data
        self.bytes_per_sec = struct.unpack_from("<H", bpb, 11)[0]
        self.sec_per_clus = bpb[13]
        self.reserved = struct.unpack_from("<H", bpb, 14)[0]
        self.num_fats = bpb[16]
        self.root_entries = struct.unpack_from("<H", bpb, 17)[0]
        self.sec_per_fat = struct.unpack_from("<H", bpb, 22)[0]
        self.fat_start = self.reserved * self.bytes_per_sec
        self.root_start = (self.reserved + self.num_fats * self.sec_per_fat) * self.bytes_per_sec
        self.root_bytes = self.root_entries * 32
        self.data_start = self.root_start + self.root_bytes
        self.clus_bytes = self.sec_per_clus * self.bytes_per_sec

    # --- FAT12 entry get/set ---
    def _fat_get(self, n: int) -> int:
        off = self.fat_start + (n * 3) // 2
        pair = self.data[off] | (self.data[off + 1] << 8)
        return (pair >> 4) if (n & 1) else (pair & 0x0FFF)

    def _fat_set(self, n: int, val: int) -> None:
        off = self.fat_start + (n * 3) // 2
        pair = self.data[off] | (self.data[off + 1] << 8)
        if n & 1:
            pair = (pair & 0x000F) | (val << 4)
        else:
            pair = (pair & 0xF000) | (val & 0x0FFF)
        self.data[off] = pair & 0xFF
        self.data[off + 1] = (pair >> 8) & 0xFF
        # mirror into all FAT copies
        for i in range(1, self.num_fats):
            base = self.fat_start + i * self.sec_per_fat * self.bytes_per_sec
            self.data[base + (n * 3) // 2] = self.data[off]
            self.data[base + (n * 3) // 2 + 1] = self.data[off + 1]

    def _clus_off(self, n: int) -> int:
        return self.data_start + (n - 2) * self.clus_bytes

    def _free_clusters(self):
        total = (len(self.data) - self.data_start) // self.clus_bytes
        return [n for n in range(2, total + 2) if self._fat_get(n) == 0]

    @staticmethod
    def _name83(name: str) -> bytes:
        name = name.upper()
        if "." in name:
            base, ext = name.split(".", 1)
        else:
            base, ext = name, ""
        return (base[:8].ljust(8) + ext[:3].ljust(3)).encode("ascii")

    def list(self):
        out = []
        for i in range(self.root_entries):
            e = self.data[self.root_start + i * 32: self.root_start + i * 32 + 32]
            if e[0] in (0x00, 0xE5):
                continue
            if e[11] & 0x08:  # volume label / lfn
                continue
            nm = e[0:8].decode("ascii", "replace").rstrip()
            ex = e[8:11].decode("ascii", "replace").rstrip()
            sz = struct.unpack_from("<I", e, 28)[0]
            out.append((f"{nm}.{ex}" if ex else nm, sz))
        return out

    def _find_entry(self, name: str):
        tgt = self._name83(name)
        for i in range(self.root_entries):
            o = self.root_start + i * 32
            if bytes(self.data[o:o + 11]) == tgt:
                return i
        return None

    def read(self, name: str) -> bytes:
        i = self._find_entry(name)
        if i is None:
            raise FileNotFoundError(name)
        o = self.root_start + i * 32
        clus = struct.unpack_from("<H", self.data, o + 26)[0]
        size = struct.unpack_from("<I", self.data, o + 28)[0]
        buf = bytearray()
        while 2 <= clus < 0xFF8:
            co = self._clus_off(clus)
            buf += self.data[co:co + self.clus_bytes]
            clus = self._fat_get(clus)
        return bytes(buf[:size])

    def write(self, name: str, content: bytes) -> None:
        # free any existing chain + dir slot
        idx = self._find_entry(name)
        if idx is not None:
            o = self.root_start + idx * 32
            c = struct.unpack_from("<H", self.data, o + 26)[0]
            while 2 <= c < 0xFF8:
                nxt = self._fat_get(c)
                self._fat_set(c, 0)
                c = nxt
            self.data[o] = 0xE5  # mark deleted
        n_clus = max(1, (len(content) + self.clus_bytes - 1) // self.clus_bytes)
        free = self._free_clusters()
        if len(free) < n_clus:
            raise RuntimeError(f"not enough free clusters ({len(free)} < {n_clus})")
        chain = free[:n_clus]
        for k, cl in enumerate(chain):
            co = self._clus_off(cl)
            chunk = content[k * self.clus_bytes:(k + 1) * self.clus_bytes]
            self.data[co:co + len(chunk)] = chunk
            if len(chunk) < self.clus_bytes:
                self.data[co + len(chunk):co + self.clus_bytes] = b"\x00" * (self.clus_bytes - len(chunk))
            self._fat_set(cl, chain[k + 1] if k + 1 < n_clus else 0xFFF)
        # find a free dir slot
        slot = None
        for i in range(self.root_entries):
            o = self.root_start + i * 32
            if self.data[o] in (0x00, 0xE5):
                slot = o
                break
        if slot is None:
            raise RuntimeError("root directory full")
        ent = bytearray(32)
        ent[0:11] = self._name83(name)
        ent[11] = 0x20  # archive
        struct.pack_into("<H", ent, 26, chain[0])
        struct.pack_into("<I", ent, 28, len(content))
        self.data[slot:slot + 32] = ent

    def save(self, path: Path | None = None) -> None:
        (path or self.path).write_bytes(self.data)


if __name__ == "__main__":
    cmd = sys.argv[1]
    img = Fat12(Path(sys.argv[2]))
    if cmd == "list":
        for n, s in img.list():
            print(f"{n:14} {s}")
    elif cmd == "read":
        sys.stdout.buffer.write(img.read(sys.argv[3]))
    elif cmd == "write":
        content = Path(sys.argv[4]).read_bytes() if len(sys.argv) > 4 else sys.stdin.buffer.read()
        img.write(sys.argv[3], content)
        img.save()
        print(f"wrote {sys.argv[3]} ({len(content)} bytes)")
    else:
        sys.exit(f"unknown cmd {cmd}")
