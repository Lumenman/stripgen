"""Softstrip byte layout (Cauzin Reader Interface Specification, July 1986, section 3).

A payload is everything the strip encodes after vertical sync: fields 3..20.
"""
from dataclasses import dataclass

HEADER_LEN = 16  # data sync(1) + expansion(2) + length(2) + checksum(1) + id(6) + seq(1) + type(1) + sw expansion(2)
MAX_STRIPS = 127  # sequence number is 7 bits


@dataclass
class File:
    name: str
    data: bytes
    cauzin_type: int = 0x00   # table 3.4.13; 0x00 on a generic strip means text
    os_filetype: int = 0x00   # table 3.4.14
    execute: bool = False     # filename terminator $FF


def checksum(data):
    """One-byte add with carry, then two's complement (3.4.6). Same arithmetic as Distripitor."""
    c = 0
    for b in data:
        c = ((c & 0xff) + b + (c >> 8)) & 0x1ff
    return (0x100 - ((c & 0xff) + (c >> 8))) & 0xff


def crc16(data):
    """CRC-16/ARC (reflected polynomial $A001, start 0). The spec (3.4.10) reserves a CRC but never defined
    its algorithm, so this is a guess: the common CRC-16 of the time, and the one cauzinTX uses."""
    c = 0
    for b in data:
        c ^= b
        for _ in range(8):
            c = c >> 1 ^ (0xa001 if c & 1 else 0)
    return c


def directory(files, os_type):
    d = bytearray([os_type, len(files)])
    for f in files:
        d += bytes([f.cauzin_type, f.os_filetype]) + len(f.data).to_bytes(3, 'little')
        d += f.name.encode('ascii') + bytes([0xff if f.execute else 0x00, 0x00])  # terminator, empty misc info
    return bytes(d)


def build(files, strip_id, capacity, os_type=0x00, crc=False):
    """Split files into strip payloads of at most `capacity` bytes each. With `crc`, each strip ends in a
    CRC-16 of all its bytes after the checksum, flagged in the first software expansion byte (3.4.10)."""
    if not 1 <= len(files) <= 255:
        raise ValueError('need 1..255 files')
    sid = strip_id.encode('ascii')[:6].ljust(6)
    dirent = directory(files, os_type)
    data = b''.join(f.data for f in files)
    room = capacity - HEADER_LEN - 2 * crc
    first = room - len(dirent)
    if first < 0:
        raise ValueError(f'file directory ({len(dirent)} bytes) does not fit on the first strip')
    chunks = [data[:first]] + [data[i:i + room] for i in range(first, len(data), room)]
    if len(chunks) > MAX_STRIPS:
        raise ValueError(f'{len(chunks)} strips needed, max {MAX_STRIPS}')
    payloads = []
    for seq, chunk in enumerate(chunks, 1):
        # bit 7: more strips follow. Not in the spec; seen on original Cauzin strips ($81, $02 and a lone $01).
        # ponytail: a middle strip ($82 vs $02) is a guess, no 3-strip original found yet
        more = 0x80 if seq < len(chunks) else 0x00
        tail = sid + bytes([seq | more, 0x00, 0x80 * crc, 0x00]) + (dirent if seq == 1 else b'') + chunk
        if crc:
            tail += crc16(tail).to_bytes(2, 'little')
        payloads.append(bytes(3) + (len(tail) + 1).to_bytes(2, 'little') + bytes([checksum(tail)]) + tail)
    return payloads


@dataclass
class Strip:
    strip_id: bytes
    seq: int
    strip_type: int
    body: bytes  # directory (first strip only) + file data
    crc_ok: bool = None  # None: no CRC on the strip


def parse_strip(p):
    if p[:3] != bytes(3):
        raise ValueError('data sync / expansion bytes are not zero')
    length = int.from_bytes(p[3:5], 'little')
    tail = p[6:5 + length]
    if len(tail) != length - 1:
        raise ValueError(f'strip truncated: length field {length}, have {len(tail) + 1}')
    if len(tail) < 10:
        raise ValueError(f'strip too short for its header: length field {length}')
    if checksum(tail) != p[5]:
        raise ValueError(f'checksum mismatch: strip {p[5]:#04x}, computed {checksum(tail):#04x}')
    body, crc_ok = tail[10:], None
    if tail[8] & 0x80:  # CRC flag. The algorithm was never defined: a mismatch may be another guess, not an error
        body, crc_ok = body[:-2], crc16(tail[:-2]) == int.from_bytes(tail[-2:], 'little')
    return Strip(tail[:6], tail[6] & 0x7f, tail[7], body, crc_ok)


def parse(payloads):
    """Return (os_type, [File], [Strip]) from the payloads of one strip sequence, any order."""
    strips = sorted(map(parse_strip, payloads), key=lambda s: s.seq)
    if not strips or strips[0].seq != 1:
        raise ValueError('strip #1 (the one with the directory) is missing')
    if any(s.strip_type for s in strips):  # $01 special key, $10 compressed: never defined publicly
        raise ValueError(f'strip type {max(s.strip_type for s in strips):#04x} is not supported')
    for a, b in zip(strips, strips[1:]):
        if b.strip_id != a.strip_id:
            raise ValueError(f'strip id mismatch: {a.strip_id!r} vs {b.strip_id!r}')
        if b.seq != a.seq + 1:
            raise ValueError(f'strip sequence gap: {a.seq} -> {b.seq}')
    d = strips[0].body
    try:
        os_type, pos, entries = d[0], 2, []
        for _ in range(d[1]):
            ctype, ftype, size = d[pos], d[pos + 1], int.from_bytes(d[pos + 2:pos + 5], 'little')
            end = pos + 5
            while d[end] not in (0x00, 0xff):
                end += 1
            entries.append((File(d[pos + 5:end].decode('latin-1'), b'', ctype, ftype, d[end] == 0xff), size))
            pos = end + 2 + d[end + 1]  # skip misc info block
    except IndexError:
        raise ValueError('directory runs past the end of strip #1') from None
    if pos > len(d):  # misc info block overran
        raise ValueError('directory runs past the end of strip #1')
    data = d[pos:] + b''.join(s.body for s in strips[1:])
    need = sum(size for _, size in entries)
    if len(data) < need:
        raise ValueError(f'data short by {need - len(data)} bytes (missing strips?)')
    files, pos = [], 0
    for f, size in entries:
        f.data = data[pos:pos + size]
        pos += size
        files.append(f)
    return os_type, files, strips
