import argparse
import os
import sys

from PIL import Image

from . import format, image


def num(s):
    return int(s, 0)


def encode(args):
    g = image.Geometry(args.nibbles, args.dpi, args.cell, args.row)
    if g.cell_mm < image.MIN_BIT_MM or g.row_mm < image.MIN_ROW_MM:
        print(f'warning: bit {g.cell_mm:.3f} x {g.row_mm:.3f} mm is below the patent minimum '
              f'{image.MIN_BIT_MM} x {image.MIN_ROW_MM} mm; a printed strip may not read back', file=sys.stderr)
    if args.marks and (g.n > image.MAX_NIBBLES or g.cell_mm > image.MAX_BIT_MM or g.row_mm > image.MAX_ROW_MM):
        print(f"warning: Cauzin's reader takes up to {image.MAX_NIBBLES} nibbles and bits up to "
              f'{image.MAX_BIT_MM} x {image.MAX_ROW_MM} mm', file=sys.stderr)
    if args.marks and not image.MIN_WIDTH_MM <= g.width_mm <= image.MAX_WIDTH_MM:
        print(f"warning: strip {g.width_mm:.1f} mm wide; Cauzin's strips are {image.MIN_WIDTH_MM:.1f}-"
              f'{image.MAX_WIDTH_MM:.1f} mm (change --nibbles or --cell)', file=sys.stderr)
    if args.max_length is None:  # the reader's window is 9 inches long
        args.max_length = image.READER_MAX_MM if args.marks else 240
    elif args.marks and args.max_length > image.READER_MAX_MM:
        print(f"warning: strips up to {args.max_length} mm; Cauzin's reader takes {image.READER_MAX_MM} mm "
              f'(9 inches) at most', file=sys.stderr)
    files = []
    for path in args.files:
        with open(path, 'rb') as f:
            data = f.read()
        if args.text:  # Cauzin generic text: CR LF lines, $1A end of file (spec section 6)
            data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n') + b'\x1a'
        files.append(format.File(os.path.basename(path), data, args.ctype, args.ftype, args.exec))
    strip_id = args.id or os.path.splitext(files[0].name)[0].upper()
    max_length = args.max_length
    if args.page:  # strip + its white margin + label (or marks) must fit between the page margins
        extra = image.MARKS_TOP_MM + image.MARKS_BOTTOM_MM + 2 * 25.4 / g.dpi if args.marks else image.LABEL_MM
        max_length = min(max_length, image.page_mm(args.page)[1] - 2 * args.margin - extra
                         - 2 * g.margin * 25.4 / g.dpi)
    payloads = format.build(files, strip_id, g.capacity(max_length), args.os, args.crc)
    print(f'{len(payloads)} strip(s), {g.width_mm:.1f} mm wide, bit {g.cell_mm:.3f} x {g.row_mm:.3f} mm, '
          f'vsync code {g.code:#04x}', file=sys.stderr)
    for seq, p in enumerate(payloads, 1):
        print(f'strip {seq}: {len(p)} bytes, {g.length_mm(len(p)):.1f} mm long', file=sys.stderr)
    # a bar below a short strip would sit on its longer neighbour's data: fill strips out to one length
    rows = max(g.data_rows(len(p)) for p in payloads) if args.marks and args.page else 0
    strips = [g.render(p, rows) for p in payloads]
    sid = payloads[0][6:12].decode('ascii').strip()
    if args.marks:  # as in Cauzin's magazines: program, then strip number, beside the bar ("C 2"; "A" alone)
        labels = [f'{sid} {seq}' if len(payloads) > 1 else sid for seq in range(1, len(payloads) + 1)]
    else:
        labels = [f'{sid} {seq}/{len(payloads)}' for seq in range(1, len(payloads) + 1)]
    if args.page:
        pages = image.sheets(strips, labels, g.dpi, args.page, args.gap, args.margin, args.marks)
        out = f'{args.output}.pdf'
        pages[0].save(out, save_all=True, append_images=pages[1:], resolution=g.dpi)
        print(f'{out}: {len(pages)} page(s) {args.page}; print at 100% / actual size', file=sys.stderr)
        return
    for seq, (img, label) in enumerate(zip(strips, labels), 1):
        if args.marks:
            img = image.with_marks(img, label, g.dpi)
        out = f'{args.output}-{seq}.png' if len(strips) > 1 else f'{args.output}.png'
        img.save(out, dpi=(g.dpi, g.dpi))
        print(f'{out}', file=sys.stderr)


def decode(args):
    groups = {}  # strip id -> {seq: payload}

    def take(where, crop):
        for turn in (0, 180):  # strips are sometimes printed upside down (e.g. on facing pages)
            try:
                p, info = image.read(crop.rotate(turn) if turn else crop)
                s = format.parse_strip(p)
                break
            except ValueError as ex:
                if not turn:  # the upright error says more than the turned one
                    error = ex
        else:
            print(f'{where}: skipped, {error}', file=sys.stderr)
            return False
        print(f'{where}: strip {s.strip_id!r} #{s.seq}, {info["nibbles"]} nibbles, '
              f'{len(info["fixed_rows"])} row(s) corrected'
              f'{", upside down" if turn else ""}'
              f'{"" if s.crc_ok is None else ", CRC ok" if s.crc_ok else ", CRC differs (not CRC-16/ARC?)"}',
              file=sys.stderr)
        seen = groups.setdefault(s.strip_id, {})
        p = p[:5 + int.from_bytes(p[3:5], 'little')]  # drop rows past the strip's end
        if s.seq in seen and seen[s.seq] != p:
            print(f'{where}: a different strip {s.strip_id!r} #{s.seq} was read before, keeping that one; '
                  f'sequences sharing an id must be decoded separately', file=sys.stderr)
        seen.setdefault(s.seq, p)  # the same strip scanned twice counts once
        return True

    for path in args.images:
        try:
            img = Image.open(path)
            crops = image.find_strips(img)
        except (OSError, ValueError) as ex:
            print(f'{path}: skipped, {ex}', file=sys.stderr)
            continue
        read = [take(f'{path} #{k}' if len(crops) > 1 else path, crop) for k, crop in enumerate(crops, 1)]
        # nothing read: the image may be one strip whose cells are as big as find_strips' blocks
        # (a short strip, or a high-dpi render), which splits it apart
        if not any(read) and (len(crops) != 1 or crops[0].size != img.size):
            take(f'{path} (whole image)', img)
    if not groups:
        raise ValueError('no readable strips')
    failed, out = False, {}  # output name -> File
    for sid, by_seq in groups.items():
        try:
            os_type, files, strips = format.parse(list(by_seq.values()))
        except ValueError as ex:
            print(f'strip id {sid!r}: {ex}', file=sys.stderr)
            failed = True
            continue
        print(f'strip id {sid!r}, os {os_type:#04x}, {len(strips)} strip(s)', file=sys.stderr)
        for f in files:
            name = os.path.basename(f.name.replace('\\', '/')) or 'unnamed'  # names come from the strip: no paths
            if name in out:
                raise ValueError(f'two files would be written as {name}; decode their strips separately')
            out[name] = f
            print(f'  {name}: {len(f.data)} bytes, cauzin type {f.cauzin_type:#04x}, os type {f.os_filetype:#04x}'
                  f'{", executable" if f.execute else ""}', file=sys.stderr)
    exist = [n for n in out if os.path.exists(os.path.join(args.dir, n))]
    if exist:
        raise ValueError(f'already in {args.dir}: {", ".join(exist)}; nothing written')
    os.makedirs(args.dir, exist_ok=True)
    for name, f in out.items():
        with open(os.path.join(args.dir, name), 'xb') as o:
            o.write(f.data)
    if failed:
        sys.exit(1)


p = argparse.ArgumentParser(prog='softstrip', description='Cauzin Softstrip encoder/decoder')
sub = p.add_subparsers(required=True)

e = sub.add_parser('encode', help='files -> strip PNG(s)')
e.add_argument('files', nargs='+')
e.add_argument('-o', '--output', required=True, help='output name prefix')
e.add_argument('--id', help='6-char strip id (default: first file name)')
e.add_argument('--os', type=num, default=0x00, help='operating system type (0=generic, 0x14=MS-DOS...)')
e.add_argument('--ctype', type=num, default=0x00, help='Cauzin file type')
e.add_argument('--ftype', type=num, default=0x00, help='OS file type')
e.add_argument('--exec', action='store_true', help='mark files executable (terminator $FF)')
e.add_argument('--text', action='store_true', help='convert to Cauzin generic text (CR LF, $1A)')
e.add_argument('--nibbles', type=int, default=10, help='data nibbles per row (>= 4)')
e.add_argument('--dpi', type=int, default=600)
e.add_argument('--cell', type=int, default=4, help='bit width in pixels')
e.add_argument('--row', type=int, default=6, help='bit height in pixels')
e.add_argument('--max-length', type=float, help='max strip length, mm (default 240; 228.6 with --marks)')
e.add_argument('--page', help=f'lay strips out on pages, write OUTPUT.pdf: {", ".join(image.PAGES_MM)} '
               'or WxH in mm, e.g. 200x280')
e.add_argument('--margin', type=float, default=image.PAGE_MARGIN_MM,
               help='page margin, mm (default %(default)s; most printers cannot print the outer 3-5 mm)')
e.add_argument('--gap', type=float, default=image.STRIP_GAP_MM,
               help='mm between strips on a page (default %(default)s: reads from a scan tilted up to 1 degree)')
e.add_argument('--marks', action='store_true',
               help="print alignment marks for Cauzin's reader (dot and bar) and a magazine-style label")
e.add_argument('--crc', action='store_true',
               help='end each strip in a CRC-16 of its bytes. Off by default: the spec reserves a CRC flag but '
                    "never defined the algorithm, so CRC-16/ARC here is a guess, and Cauzin's own software may "
                    'not expect the two extra bytes')
e.set_defaults(func=encode)

d = sub.add_parser('decode', help='strip image(s) -> files')
d.add_argument('images', nargs='+', help='strip images or whole scanned pages, any order')
d.add_argument('-d', '--dir', default='.', help='output directory')
d.set_defaults(func=decode)

args = p.parse_args()
try:
    args.func(args)
except ValueError as ex:
    sys.exit(f'error: {ex}')
