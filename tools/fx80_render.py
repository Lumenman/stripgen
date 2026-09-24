"""Render an Epson FX-80 print dump (ESC Z quad-density graphics, ESC J feeds) to a PNG.

Grid: x 1/240 in, y 1/216 in. A pin dot is ~1/72 in round: stamped as 3x3 grid units.
usage: python tools/fx80_render.py dump.fx80 out.png

Written to check the decoder against Cauzin STRIPPER output, e.g. HELLO-softstrip.fx80 from
https://github.com/FozzTexx/CauzinStripperEpson; then: python -m softstrip decode out.png
"""
import sys
import numpy as np
from PIL import Image

d = open(sys.argv[1], 'rb').read()
dots, x, y, i = [], 0, 0, 0
while i < len(d):
    c = d[i]
    if c == 0x1b:
        cmd = d[i + 1]
        if cmd == ord('Z'):
            n = d[i + 2] | d[i + 3] << 8
            for col, b in enumerate(d[i + 4:i + 4 + n]):
                for pin in range(8):
                    if b & (0x80 >> pin):
                        dots.append((x + col, y + 3 * pin))
            x += n
            i += 4 + n
            continue
        if cmd == ord('J'):
            y += d[i + 2]
            i += 3
            continue
        i += {ord('@'): 2, ord('2'): 2}.get(cmd, 3)  # ESC @, ESC 2; ESC ! n, ESC U n
        continue
    if c == 0x0d:
        x = 0
    elif c == 0x0a:
        y += 36
    elif c >= 0x20:
        x += 24  # a 10 cpi text character is 24 dots wide at 240 dpi; text itself is not drawn
    i += 1

dots = np.array(dots)
w, h = dots[:, 0].max() + 4, dots[:, 1].max() + 4
a = np.zeros((h, w), bool)
for dx in range(3):
    for dy in range(3):
        a[dots[:, 1] + dy, dots[:, 0] + dx] = True
img = Image.fromarray(~a).convert('L').resize((w, round(h * 240 / 216)), Image.NEAREST)  # square 240 dpi pixels
img.save(sys.argv[2], dpi=(240, 240))
print(len(dots), 'dots,', img.size, 'px at 240 dpi =', round(img.size[0] / 240 * 25.4, 1), 'x',
      round(img.size[1] / 240 * 25.4, 1), 'mm')
