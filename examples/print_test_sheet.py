"""A4 print test: seven strips from 0.127 x 0.169 mm to 0.296 x 0.423 mm bits.

Print at 100% / actual size, scan at 600 dpi, then
    python -m softstrip decode scan.png -d decoded
and compare decoded/ with originals/ to see which bit sizes a printer and scanner handle.

Run from the repository root: python examples/print_test_sheet.py [output_dir]
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from softstrip.format import File, build  # noqa: E402
from softstrip.image import Geometry, sheets  # noqa: E402

out = sys.argv[1] if len(sys.argv) > 1 else 'experiments/printtest'
os.makedirs(os.path.join(out, 'originals'), exist_ok=True)

# (cell_px, row_px, nibbles) at 600 dpi; widths kept near 16 mm like Cauzin's strips
variants = [(3, 4, 14), (3, 5, 14), (4, 5, 10), (4, 6, 10), (5, 7, 8), (6, 9, 6), (7, 10, 5)]
strips, labels = [], []
for i, (c, r, n) in enumerate(variants, 1):
    g = Geometry(nibbles=n, dpi=600, cell_px=c, row_px=r)
    name = f'T{i}.BIN'
    head = (f'Softstrip print test {i}/7: bit {g.cell_mm:.3f} x {g.row_mm:.3f} mm, {n} nibbles, '
            f'{g.width_mm:.1f} mm wide\r\n').encode()
    room = g.capacity(240) - 16 - (2 + 5 + len(name) + 2)  # strip header, one-file directory
    data = head + random.Random(i).randbytes(room - len(head))
    (payload,) = build([File(name, data)], f'TEST{i}', g.capacity(240))
    with open(os.path.join(out, 'originals', name), 'wb') as f:
        f.write(data)
    strips.append(g.render(payload))
    labels.append(f'T{i} {g.cell_mm:.2f}x{g.row_mm:.2f}')
    print(f'T{i}: bit {g.cell_mm:.3f} x {g.row_mm:.3f} mm, {n} nibbles, {len(data)} bytes')

pages = sheets(strips, labels, 600, 'A4')
pages[0].save(os.path.join(out, 'test_sheet_A4.pdf'), save_all=True, append_images=pages[1:], resolution=600)
