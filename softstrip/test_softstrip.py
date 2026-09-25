"""Run: python -m softstrip.test_softstrip"""
import os
import random

import numpy as np
from PIL import Image, ImageFilter

from .format import File, build, checksum, parse
from .image import Geometry, find_strips, read, sheets

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

    # file data repeating one byte outnumbers the vertical sync rows near the top
    for b in (b'A', b'\xff'):
        assert roundtrip([File('SAME', b * 1000)], Geometry()) == 1

    # a short strip next to a long one on a page (render pads it to be found); a blank page has no strips
    g = Geometry()
    payloads = [build([File(n, d)], n, 10 ** 6)[0] for n, d in (('LONG', blob[:1000]), ('SHORT', b''))]
    page, = sheets([g.render(p) for p in payloads], ['1', '2'], g.dpi, 'A4')
    assert sorted(len(parse([read(c)[0]])[1][0].data) for c in find_strips(page)) == [0, 1000]
    assert find_strips(Image.new('L', (500, 700), 255)) == []

    # malformed sequences and directories are ValueErrors, not crashes
    two = build([File('X', bytes(100))], 'X', 60)
    head = two[0][6:16]  # strip #1 cut to its header, checksum valid: no directory at all
    for bad in ([], two[1:], [bytes(3) + b'\x0b\x00' + bytes([checksum(head)]) + head]):
        try:
            parse(bad)
            assert False, bad
        except ValueError:
            pass

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
