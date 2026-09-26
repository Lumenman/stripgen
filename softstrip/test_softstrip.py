"""Run: python -m softstrip.test_softstrip"""
import os
import random

import numpy as np
from PIL import Image, ImageFilter

from .format import File, build, checksum, crc16, parse, parse_strip
from .image import Geometry, find_strips, page_mm, read, sheets, with_marks

HERE = os.path.dirname(__file__)


def scanned(img, rnd):
    """Imitate a scan: grey, tilted, blurred, noisy."""
    img = img.convert('L').rotate(1.3, Image.BICUBIC, expand=True, fillcolor=255).filter(ImageFilter.GaussianBlur(1))
    a = np.asarray(img, float) * 0.8 + 30 + np.random.default_rng(rnd.randrange(1 << 30)).normal(0, 12, img.size[::-1])
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def roundtrip(files, geometry, max_length=240, scale=1.0, scan=False):
    payloads = build(files, 'TEST', geometry.capacity(max_length))
    got = []
    for p in payloads:
        img = geometry.render(p)
        if scale != 1.0:  # non-integer resampling, like a Distripitor PNG or a rescaled scan
            img = img.convert('L').resize((round(img.width * scale), round(img.height * scale)), Image.NEAREST)
        if scan:
            img = scanned(img, random.Random(len(p)))
        data, info = read(img)
        assert info['nibbles'] == geometry.n and info['vsync_code'] == geometry.code, info
        assert data[:len(p)] == p
        got.append(data)
    random.shuffle(got)  # decoder must reorder by sequence number
    _, out, strips = parse(got)
    assert [(f.name, f.data, f.execute) for f in out] == [(f.name, f.data, f.execute) for f in files]
    return len(strips)


def test():
    rnd = random.Random(1)
    blob = bytes(rnd.randrange(256) for _ in range(20000))

    assert checksum(b'') == 0 and checksum(b'\x01') == 0xff
    assert roundtrip([File('HELLO.TXT', b'Hello, Softstrip!\r\n\x1a')], Geometry()) == 1
    assert roundtrip([File('A.BIN', blob[:300]), File('B.BAS', blob[300:350], 0x04, 0x01, True)],
                     Geometry(nibbles=12, cell_px=3, row_px=5)) == 1
    assert roundtrip([File('BIG.BIN', blob)], Geometry(), max_length=120) > 1
    assert roundtrip([File('EMPTY', b'')], Geometry(nibbles=4)) == 1
    assert roundtrip([File('SCALED', blob[:2000])], Geometry(cell_px=4, row_px=6), scale=0.87) == 1
    assert roundtrip([File('ODD.COM', blob[:3000])], Geometry(nibbles=7)) == 1
    assert roundtrip([File('SCAN.BIN', blob[:9000])], Geometry(nibbles=9, cell_px=5, row_px=7), scan=True) > 1

    # a page of strips, scanned: find, read and reassemble them without cropping by hand
    g = Geometry(nibbles=8, dpi=400, cell_px=3, row_px=4)
    files = [File('PAGE.BIN', blob[:6000])]
    payloads = build(files, 'PAGE', g.capacity(100))
    page, = sheets([g.render(p) for p in payloads], [str(i) for i in range(len(payloads))], g.dpi, 'A4')
    crops = find_strips(scanned(page, rnd))
    assert len(crops) == len(payloads) > 2, len(crops)
    assert parse([read(c)[0] for c in crops])[1][0].data == files[0].data

    # the same with the reader's alignment marks: dots, bars and labels reach under the neighbouring strip
    rows = max(g.data_rows(len(p)) for p in payloads)
    page, = sheets([g.render(p, rows) for p in payloads], [f'PAGE {i}' for i in range(1, len(payloads) + 1)],
                   g.dpi, 'A4', marks=True)
    crops = find_strips(scanned(page, rnd))
    assert len(crops) == len(payloads), len(crops)
    assert parse([read(c)[0] for c in crops])[1][0].data == files[0].data
    assert parse([read(with_marks(g.render(payloads[0]), 'PAGE 1', g.dpi))[0]] + [read(c)[0] for c in crops[1:]])

    # file data repeating one byte outnumbers the vertical sync rows near the top
    for b in (b'A', b'\xff'):
        assert roundtrip([File('SAME', b * 1000)], Geometry()) == 1

    # a short strip next to a long one on a page (render fills it out to be found); a blank page has no strips
    g = Geometry()
    payloads = [build([File(n, d)], n, 10 ** 6)[0] for n, d in (('LONG', blob[:1000]), ('SHORT', b''))]
    page, = sheets([g.render(p) for p in payloads], ['1', '2'], g.dpi, 'A4')
    assert sorted(len(parse([read(c)[0]])[1][0].data) for c in find_strips(page)) == [0, 1000]
    assert find_strips(Image.new('L', (500, 700), 255)) == []
    assert page_mm('a4') == (210, 297) and page_mm('200x280') == (200, 280)

    # regular data looks the same a cell off; Letter's wider crop used to tip the column offsets over
    for data in (b'', b'abcd' * 250):
        p, = build([File('REG', data)], 'REG', 10 ** 6)
        page, = sheets([g.render(p)], ['1'], g.dpi, 'Letter')
        assert parse([read(g.render(p))[0]])[1][0].data == data
        assert parse([read(c)[0] for c in find_strips(page)])[1][0].data == data

    # malformed sequences and directories are ValueErrors, not crashes
    two = build([File('X', bytes(100))], 'X', 60)
    head = two[0][6:16]  # strip #1 cut to its header, checksum valid: no directory at all
    for bad in ([], two[1:], [bytes(3) + b'\x0b\x00' + bytes([checksum(head)]) + head]):
        try:
            parse(bad)
            assert False, bad
        except ValueError:
            pass

    # optional CRC (3.4.10): CRC-16/ARC's check value; a multi-strip round trip; a wrong CRC only reports
    assert crc16(b'123456789') == 0xbb3d
    ps = build([File('C.BIN', blob[:9000])], 'CRC', 4000, crc=True)
    assert all(p[14] == 0x80 for p in ps) and len(ps) == 3
    _, out, strips = parse(ps)
    assert out[0].data == blob[:9000] and all(s.crc_ok for s in strips)
    bad = bytearray(ps[0])
    bad[-1] ^= 1
    bad[5] = checksum(bytes(bad[6:5 + int.from_bytes(bad[3:5], 'little')]))
    assert parse_strip(bytes(bad)).crc_ok is False

    # sequence byte: bit 7 while more strips follow, as on Cauzin's strips ($81 $02, a lone strip $01)
    assert [p[12] for p in build([File('X', blob[:9000])], 'X', 4000)] == [0x81, 0x82, 0x03]
    assert build([File('X', b'x')], 'X', 4000)[0][12] == 0x01

    # Geometry 0.254 mm at 600 dpi -> 4 scans exactly: the patent's own example $40
    assert Geometry(row_px=6).code == 0x40

    # Strip made by Distripitor (the thesis dataset): third-party layout, fractional px per cell, no margins
    sample = os.path.join(HERE, '..', 'experiments', 'distripitor', 'glyphicons-328-sampler.png')  # untracked
    if os.path.exists(sample):
        data, info = read(Image.open(sample))
        _, files, _ = parse([data])
        assert info['nibbles'] == 8 and info['vsync_code'] == 0x80, info
        assert len(files) == 1 and files[0].data[:8] == b'\x89PNG\r\n\x1a\n', files[0].name
    print('ok')


if __name__ == '__main__':
    test()
