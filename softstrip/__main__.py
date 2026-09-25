import argparse
import os
import sys

from PIL import Image

from . import format, image


def num(s):
    return int(s, 0)


def encode(args):
    g = image.Geometry(args.nibbles, args.dpi, args.cell, args.row)
    files = []
    for path in args.files:
        with open(path, 'rb') as f:
            data = f.read()
        if args.text:  # Cauzin generic text: CR LF lines, $1A end of file (spec section 6)
            data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n') + b'\x1a'
        files.append(format.File(os.path.basename(path), data, args.ctype, args.ftype, args.exec))
    strip_id = args.id or os.path.splitext(files[0].name)[0].upper()
    max_length = args.max_length
    if args.page:  # strip + its white margin + label must fit between the page margins
        max_length = min(max_length, image.PAGES_MM[args.page][1] - 2 * image.PAGE_MARGIN_MM - image.LABEL_MM
                         - 2 * g.margin * 25.4 / g.dpi)
    payloads = format.build(files, strip_id, g.capacity(max_length), args.os)
    print(f'{len(payloads)} strip(s), {g.width_mm:.1f} mm wide, bit {g.cell_mm:.3f} x {g.row_mm:.3f} mm, '
          f'vsync code {g.code:#04x}', file=sys.stderr)
    for seq, p in enumerate(payloads, 1):
        print(f'strip {seq}: {len(p)} bytes, {g.length_mm(len(p)):.1f} mm long', file=sys.stderr)
    strips = [g.render(p) for p in payloads]
    if args.page:
        sid = payloads[0][6:12].decode('ascii').strip()
        labels = [f'{sid} {seq}/{len(payloads)}' for seq in range(1, len(payloads) + 1)]
        pages = image.sheets(strips, labels, g.dpi, args.page)
        out = f'{args.output}.pdf'
        pages[0].save(out, save_all=True, append_images=pages[1:], resolution=g.dpi)
        print(f'{out}: {len(pages)} page(s) {args.page}; print at 100% / actual size', file=sys.stderr)
        return
    for seq, img in enumerate(strips, 1):
        out = f'{args.output}-{seq}.png' if len(strips) > 1 else f'{args.output}.png'
        img.save(out, dpi=(g.dpi, g.dpi))
        print(f'{out}', file=sys.stderr)


def decode(args):
    groups = {}  # strip id -> {seq: payload}
    for path in args.images:
        crops = image.find_strips(Image.open(path)) or [Image.open(path)]
        for k, crop in enumerate(crops, 1):
            where = f'{path} #{k}' if len(crops) > 1 else path
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
                continue
            print(f'{where}: strip {s.strip_id!r} #{s.seq}, {info["nibbles"]} nibbles, '
                  f'{len(info["fixed_rows"])} row(s) corrected'
                  f'{", upside down" if turn else ""}',
                  file=sys.stderr)
            seen = groups.setdefault(s.strip_id, {})
            p = p[:5 + int.from_bytes(p[3:5], 'little')]  # drop rows past the strip's end
            if s.seq in seen and seen[s.seq] != p:
                print(f'{where}: a different strip {s.strip_id!r} #{s.seq} was read before, keeping that one; '
                      f'sequences sharing an id must be decoded separately', file=sys.stderr)
            seen.setdefault(s.seq, p)  # the same strip scanned twice counts once
    if not groups:
        raise ValueError('no readable strips')
    failed = False
    for sid, by_seq in groups.items():
        try:
            os_type, files, strips = format.parse(list(by_seq.values()))
        except ValueError as ex:
            print(f'strip id {sid!r}: {ex}', file=sys.stderr)
            failed = True
            continue
        print(f'strip id {sid!r}, os {os_type:#04x}, {len(strips)} strip(s)', file=sys.stderr)
        os.makedirs(args.dir, exist_ok=True)
        for f in files:
            name = os.path.basename(f.name.replace('\\', '/')) or 'unnamed'  # names come from the strip: no paths
            with open(os.path.join(args.dir, name), 'wb') as out:
                out.write(f.data)
            print(f'  {name}: {len(f.data)} bytes, cauzin type {f.cauzin_type:#04x}, os type {f.os_filetype:#04x}'
                  f'{", executable" if f.execute else ""}', file=sys.stderr)
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
e.add_argument('--max-length', type=float, default=240, help='max strip length, mm')
e.add_argument('--page', choices=sorted(image.PAGES_MM), help='lay strips out on pages, write OUTPUT.pdf')
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
