"""Softstrip geometry: payload bytes <-> strip image.

Layout per US 4,782,221 / US 4,692,603 (FIG. 12, FIG. 38). One row, in bit cells:
  start bar(2 black) space(1) checkerboard(2) left parity(2) data(8n) right parity(2) space(2) rack(2-3 black)
n = nibbles per row. A dibit is black-white for 0, white-black for 1. Bytes go LSB first.
Left parity = sum of odd data dibits (0-based) mod 2, right parity = sum of even ones.
"""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

SCAN_MM = 0.0635       # reader scan step
HSYNC_MM = 28 * SCAN_MM
VSYNC_MM = 56 * SCAN_MM
PAGES_MM = {'A4': (210, 297), 'Letter': (215.9, 279.4)}
PAGE_MARGIN_MM, STRIP_GAP_MM, LABEL_MM = 12, 8, 6


def row_cells(n):
    return 8 * n + 14


def height_code(row_mm):
    """Vertical sync byte: high nibble whole scans, low nibble 1/16 scans, i.e. row height in 1/16 scans."""
    code = round(row_mm / SCAN_MM * 16)
    if not 0 < code <= 0xff:
        raise ValueError(f'row height {row_mm:.3f} mm out of vertical sync range')
    return code


def hsync_row(n):
    w = row_cells(n)
    r = np.zeros(w, bool)
    r[0:2] = r[4:10] = r[w - 12:w - 6] = r[w - 4:w - 2] = True  # start bar, wide bars, right guideline
    for i in range(n - 4):
        r[12 + 4 * i:14 + 4 * i] = r[w - 16 - 4 * i:w - 14 - 4 * i] = True
    return r


def data_row(bits, k, n):
    """Cells of row k (True = black). bits: 4n data bits."""
    w = row_cells(n)
    r = np.zeros(w, bool)
    r[0:2] = True
    r[3] = k % 2 == 0
    r[4] = not r[3]
    lp, rp = sum(bits[1::2]) % 2, sum(bits[0::2]) % 2
    for i, b in enumerate([lp, *bits, rp]):
        r[5 + 2 * i] = not b
        r[6 + 2 * i] = bool(b)
    r[w - 3:w - 1] = True
    r[w - 1] = r[4]  # rack is 2 or 3 cells, in step with the checkerboard
    return r


def to_bits(data):
    return [(b >> i) & 1 for b in data for i in range(8)]


def to_bytes(bits):
    return bytes(sum(bit << i for i, bit in enumerate(bits[j:j + 8])) for j in range(0, len(bits) - 7, 8))


class Geometry:
    def __init__(self, nibbles=10, dpi=600, cell_px=4, row_px=6, margin_px=16):
        if nibbles < 4:
            raise ValueError('nibbles must be >= 4')
        self.n, self.dpi, self.cell_px, self.row_px, self.margin = nibbles, dpi, cell_px, row_px, margin_px
        mm = 25.4 / dpi
        self.cell_mm, self.row_mm = cell_px * mm, row_px * mm
        self.hsync_px = math.ceil(HSYNC_MM / mm)
        self.vsync_rows = math.ceil(VSYNC_MM / self.row_mm)
        self.code = height_code(self.row_mm)

    @property
    def width_mm(self):
        return row_cells(self.n) * self.cell_mm

    def length_mm(self, payload_len):
        rows = self.vsync_rows + math.ceil(payload_len * 8 / (4 * self.n))
        return self.hsync_px * 25.4 / self.dpi + rows * self.row_mm

    def capacity(self, max_length_mm):
        """Payload bytes that fit in a strip of the given length."""
        rows = int((max_length_mm - self.hsync_px * 25.4 / self.dpi) / self.row_mm) - self.vsync_rows
        return rows * self.n // 2

    def render(self, payload):
        bpr = 4 * self.n
        bits = to_bits(payload)
        bits += [0] * (-len(bits) % bpr)
        # vsync rows repeat the code bits, cut to the row (odd n ends on half a byte, as on Cauzin's own strips)
        rows = [to_bits([self.code] * ((self.n + 1) // 2))[:bpr]] * self.vsync_rows
        rows += [bits[i:i + bpr] for i in range(0, len(bits), bpr)]
        cells = np.array([data_row(b, k, self.n) for k, b in enumerate(rows)])
        px = np.vstack([np.repeat(hsync_row(self.n)[None], self.hsync_px, 0),
                        np.repeat(cells, self.row_px, 0)])
        px = np.repeat(px, self.cell_px, 1)
        px = np.pad(px, self.margin)
        return Image.fromarray(~px)  # PIL mode '1': True = white




def otsu(g):
    p = np.bincount(g.ravel(), minlength=256) / g.size
    w, mu = np.cumsum(p), np.cumsum(p * np.arange(256))
    with np.errstate(divide='ignore', invalid='ignore'):
        between = (mu[-1] * w - mu) ** 2 / (w * (1 - w))
    return int(np.nanargmax(between))


def robust_line(y, x):
    """Fit x = a*y + b ignoring outliers. Returns a, b, inlier mask."""
    keep = np.ones(len(x), bool)
    for _ in range(5):
        a, b = np.polyfit(y[keep], x[keep], 1)
        r = np.abs(x - (a * y + b))
        keep = r <= max(2.0, 3 * np.median(r[keep]))
    return a, b, keep


def runs(line):
    """(start, end) of black runs in a boolean row."""
    d = np.diff(np.concatenate([[0], line.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def row_centres(sig, y0):
    """Row centres from the checkerboard signal sig (dark minus light cell, sampled from y = y0 on).

    The checkerboard flips every row, so sig ~ cos(pi * (y - c(y)) / p): periodic over two rows, with an
    offset c(y) that wanders as print and paper stretch. p comes from the spectrum of the whole strip;
    c(y) from the phase of sig against that reference, averaged over a few rows (a lock-in amplifier),
    so smudged or noisy stretches of checkerboard are bridged instead of adding or dropping rows.
    """
    y = np.arange(len(sig))
    edges = np.flatnonzero((sig[1:] > 0) != (sig[:-1] > 0))
    if len(edges) < 4:
        raise ValueError('no data rows found')
    p = np.median(np.diff(edges))
    for span in (0.25, 0.01):  # coarse, then fine search of the period
        ps = p * np.linspace(1 - span, 1 + span, 400)
        p = ps[np.abs(np.exp(-1j * np.pi * np.outer(1 / ps, y)) @ sig).argmax()]
    win = int(6 * p) | 1
    z = np.convolve(sig * np.exp(-1j * np.pi * y / p), np.ones(win), 'same')
    u = np.maximum.accumulate(y / p + np.unwrap(np.angle(z)) / np.pi)  # row number, integer at row centres
    return y0 + np.interp(np.arange(np.ceil(u[0]), np.floor(u[-1]) + 1), u, y), p


def read(img):
    """Decode one strip from a scan or render: grey or b/w, tilt up to a few degrees, some margin around.

    Returns (payload, info). Bad rows do not raise; the strip checksum decides.
    """
    g = np.asarray(img.convert('L'))
    t = otsu(g)
    ink = g <= t
    ys = np.flatnonzero(ink.any(1))
    if len(ys) < 10:
        raise ValueError('blank image')

    # deskew on the start bar: first ink in every row
    a, b, _ = robust_line(ys, ink[ys].argmax(1).astype(float))
    tilt = math.degrees(math.atan(a))
    if abs(a) > 1e-3:
        g = np.asarray(Image.fromarray(g).rotate(-math.degrees(math.atan(a)), Image.BICUBIC,
                                                 expand=True, fillcolor=255))
        ink = g <= t
        ys = np.flatnonzero(ink.any(1))
    left = ink[ys].argmax(1).astype(float)
    a, b, keep = robust_line(ys, left)
    top, bot = ys[keep].min(), ys[keep].max()
    right = np.median(ink.shape[1] - 1 - ink[ys[keep], ::-1].argmax(1))
    width = right - np.median(left[keep])

    # hsync: nibbles from white->black transitions, cell pitch from the two wide bars
    hs = [ink[y, int(a * y + b):int(right) + 1] for y in range(top + int(0.02 * width), top + int(0.08 * width))]
    counts = [len(runs(r)) for r in hs]
    n = (max(set(counts), key=counts.count) + 4) // 2
    if n < 4:
        raise ValueError('no horizontal sync found')
    w = row_cells(n)
    fits = []
    for y, r in zip(range(top + int(0.02 * width), top + int(0.08 * width)), hs):
        rr = runs(r)
        if len(rr) == 2 * n - 4:
            pitch = (rr[-2][1] - rr[1][0]) / (w - 10)  # wide bars span cells 4 .. w-6
            fits.append((pitch, int(a * y + b) + rr[1][0] - 4 * pitch - (a * y + b)))
    if not fits:
        raise ValueError('horizontal sync unreadable')
    pitch, off = np.median(fits, 0)

    # darkness 0..1 and its integral image for box sampling
    strip = g[top:bot + 1, int(b + off):int(right) + 1]
    black, white = np.percentile(strip, 2), np.percentile(strip, 98)
    d = np.clip((white - g.astype(float)) / max(white - black, 1), 0, 1)
    S = np.pad(d, ((1, 0), (1, 0))).cumsum(0).cumsum(1)

    def box(x, y, hw, hh):
        x0 = np.clip(np.floor(x - hw).astype(int), 0, d.shape[1] - 1)
        x1 = np.clip(np.floor(x + hw).astype(int) + 1, x0 + 1, d.shape[1])
        y0 = np.clip(np.floor(y - hh).astype(int), 0, d.shape[0] - 1)
        y1 = np.clip(np.floor(y + hh).astype(int) + 1, y0 + 1, d.shape[0])
        return (S[y1, x1] - S[y0, x1] - S[y1, x0] + S[y0, x0]) / ((x1 - x0) * (y1 - y0))

    def cx(i, y):  # cell centre, following any drift of the start bar
        return a * y + b + off + (i + 0.5) * pitch

    yy = np.arange(top, bot + 1)
    hw = max(pitch * 0.3, 0.5)
    in_hsync = np.minimum(box(cx(5, yy), yy, hw, 0), box(cx(6, yy), yy, hw, 0)) > 0.5
    y_rows = top + int(np.argmin(in_hsync))
    # run a little past the start bar: its end can be shorter than the last row; extra rows are ignored by length
    yy = np.arange(y_rows, min(bot + int(0.15 * width), g.shape[0] - 1) + 1)
    sig = np.convolve(box(cx(3, yy), yy, hw, 0) - box(cx(4, yy), yy, hw, 0), np.ones(3) / 3, 'same')
    yc, row_h = row_centres(sig, y_rows)
    yc = yc[:, None]
    hh = max(row_h * 0.25, 0.5)
    ci = np.arange(w)[None, :]

    def dibits(dx):
        c = box(cx(ci, yc) + dx, yc, hw, hh)
        return c[:, 6:10 + 8 * n:2] - c[:, 5:9 + 8 * n:2]  # >0: white-black = 1

    # paper and print are never quite straight: per row, take the horizontal offset with the sharpest
    # dibits, median-filtered over neighbouring rows since the drift is smooth. (Not vertically: the
    # centre of the next row is just as sharp, so that search slips rows.)
    dxs = np.linspace(-0.4, 0.4, 9) * pitch
    best = dxs[np.array([np.abs(dibits(x)).sum(1) for x in dxs]).argmax(0)]
    dx = np.array([np.median(best[max(k - 7, 0):k + 8]) for k in range(len(best))])[:, None]
    v = dibits(dx)
    bits, conf = v > 0, np.abs(v)

    # parity (US 4,692,603 FIG. 38): left bit covers odd data dibits, right bit the even ones.
    # A failing group gets its least certain dibit flipped, as the patent's reader does.
    fixed = []
    groups = [np.r_[0, 2:4 * n + 1:2], np.r_[1:4 * n + 1:2, 4 * n + 1]]
    for k in range(len(bits)):
        for grp in groups:
            if bits[k, grp].sum() % 2:
                j = grp[np.argmin(conf[k, grp])]
                bits[k, j] ^= True
                fixed.append(k)
    rows = bits[:, 1:-1].astype(int).tolist()

    # vertical sync rows repeat a nonzero byte; data sync is the first zero byte
    first = [to_bytes(r[:8])[0] for r in rows]
    v_rows = next((k for k, x in enumerate(first) if x == 0), len(rows))
    code = max(set(first[:v_rows]), key=first[:v_rows].count) if v_rows else 0
    payload = to_bytes([x for r in rows[v_rows:] for x in r])
    if len(payload) >= 5:  # rows past the strip's length field are paper, labels, the next strip...
        used = v_rows + math.ceil((5 + int.from_bytes(payload[3:5], 'little')) * 8 / (4 * n))
        fixed = [k for k in fixed if k < used]
    return payload, {'nibbles': n, 'rows': len(rows), 'vsync_rows': v_rows, 'vsync_code': code,
                     'fixed_rows': sorted(set(fixed)), 'px_per_cell': round(float(pitch), 2),
                     'px_per_row': round(float(row_h), 2), 'tilt_deg': round(tilt, 3)}


def sheets(strips, labels, dpi, page='A4'):
    """Lay strip images side by side on pages at true size, a label under each."""
    px = lambda mm: round(mm / 25.4 * dpi)
    pw, ph = map(px, PAGES_MM[page])
    margin, gap = px(PAGE_MARGIN_MM), px(STRIP_GAP_MM)
    sw = max(s.width for s in strips)
    if sw > pw - 2 * margin or max(s.height for s in strips) > ph - 2 * margin - px(LABEL_MM):
        raise ValueError(f'strips do not fit on {page}')
    per_page = (pw - 2 * margin + gap) // (sw + gap)
    font = ImageFont.load_default(size=px(3))
    pages = []
    for i in range(0, len(strips), per_page):
        pg = Image.new('1', (pw, ph), 1)
        draw = ImageDraw.Draw(pg)
        for j, (s, text) in enumerate(zip(strips[i:i + per_page], labels[i:i + per_page])):
            x = margin + j * (sw + gap)
            pg.paste(s, (x, margin))
            draw.text((x + s.width // 2, margin + s.height + px(1)), text, fill=0, font=font, anchor='mt')
        pages.append(pg)
    return pages


def find_strips(img):
    """Crop every strip out of a page image (or return the one strip of an already cropped image).

    A strip is a tall block of dense ink: ~1 mm blocks at >30% ink, in vertical runs of 10+ blocks.
    Text is too sparse or too short to qualify; anything that still slips through fails in read().
    """
    g = np.asarray(img.convert('L'))
    ink = g <= otsu(g)
    h, w = ink.shape
    b = max(1, round(max(h, w) / 300))
    H, W = h // b, w // b
    dense = ink[:H * b, :W * b].reshape(H, b, W, b).mean((1, 3)) > 0.3
    dense[1:-1] |= dense[:-2] & dense[2:]  # bridge one-block gaps
    tall = np.zeros_like(dense)
    for x in range(W):
        for s, e in runs(dense[:, x]):
            if e - s >= 10:
                tall[s:e, x] = True
    cols = [(x0, x1) for x0, x1 in runs(tall.any(0)) if x1 - x0 >= 3]
    boxes = []
    for k, (x0, x1) in enumerate(cols):
        # pad by a quarter strip width, but only halfway to a neighbour (the image edge is no neighbour)
        left = (x0 - cols[k - 1][1]) // 2 if k else x0
        right = (cols[k + 1][0] - x1) // 2 if k + 1 < len(cols) else W - x1
        pad_l, pad_r = min((x1 - x0) // 4, left), min((x1 - x0) // 4, right)
        ys = tall[:, x0:x1].any(1)
        ys[1:-1] |= ys[:-2] & ys[2:]
        for y0, y1 in runs(ys):  # strips stacked in one column
            if y1 - y0 >= 10:
                pad = (x1 - x0) // 4
                boxes.append(((x0 - pad_l) * b, max(y0 - pad, 0) * b, min((x1 + pad_r) * b, w),
                              min((y1 + pad) * b, h)))
    return [img.crop(box) for box in boxes]
