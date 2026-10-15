"""Decode the local test corpus in experiments/ and print the Validation table of README.

The corpus is not tracked (see README, Repository layout); sets whose files are missing are
skipped. Manual pages are rendered from the PDFs with PyMuPDF (pip install pymupdf); without it
those sets are skipped too. Exit status 1 if any set reads fewer strips than README reports.

usage: python tools/run_corpus.py [set name substring ...]
"""
import glob
import os
import subprocess
import sys
import tempfile

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from softstrip import format, image  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), '..')
EXP = os.path.join(ROOT, 'experiments')
REF = os.path.join(EXP, 'references')


def read_strip(crop):
    """Payload of one strip crop, upright or turned by 180 degrees, or None."""
    for turn in (0, 180):
        try:
            p, _ = image.read(crop.rotate(turn) if turn else crop)
            format.parse_strip(p)
            return p[:5 + int.from_bytes(p[3:5], 'little')]  # drop rows past the strip's end
        except ValueError:
            pass
    return None


def read_page(img):
    """(strips found, payloads read) on one image, with the command line's whole-image fallback."""
    try:
        crops = image.find_strips(img)
    except ValueError:
        crops = []
    read = [p for p in map(read_strip, crops) if p]
    if not read and (len(crops) != 1 or crops[0].size != img.size):
        p = read_strip(img)
        return max(len(crops), 1), [p] if p else []
    return len(crops), read


def pdf_pages(name, pages):
    try:
        import pymupdf
    except ImportError:
        raise FileNotFoundError('PyMuPDF not installed (pip install pymupdf)')
    doc = pymupdf.open(os.path.join(REF, name))
    for pno in pages:
        pix = doc[pno - 1].get_pixmap(dpi=600, colorspace=pymupdf.csGRAY)
        yield f'p{pno}', Image.frombytes('L', (pix.width, pix.height), pix.samples)


def count(pages):
    """Strips read. There is no total: find_strips also returns page numbers, rules and pictures."""
    read = []
    for where, img in pages:
        before = len(read)
        read += read_page(img)[1]
        print(f'    {where}: {len(read) - before}')
    if len(set(read)) < len(read):
        print(f'    {len(set(read))} distinct')
    return len(read), None


def thesis():
    files = sorted(glob.glob(os.path.join(EXP, 'Cauzin-Softstrip-Decoder-master', 'Softstrips', '*', '*.png')))
    if not files:
        raise FileNotFoundError('no thesis strips')
    ok = 0
    for f in files:  # one strip per image, no margins: read it whole
        if read_strip(Image.open(f).convert('L')):
            ok += 1
        else:
            print(f'    {os.path.basename(f)}: failed')
    return ok, len(files)


def fx80():
    dump = os.path.join(EXP, 'CauzinStripperEpson', 'HELLO-softstrip.fx80')
    if not os.path.exists(dump):
        raise FileNotFoundError(dump)
    with tempfile.TemporaryDirectory() as tmp:
        png = os.path.join(tmp, 'hello.png')
        subprocess.run([sys.executable, os.path.join(ROOT, 'tools', 'fx80_render.py'), dump, png], check=True)
        return count([('HELLO', Image.open(png).convert('L'))])


def printtest():
    """Test sheet scans: files decoded byte-identical to originals/, over all strips on all scans."""
    scans = sorted(glob.glob(os.path.join(EXP, 'printtest', 'ScanImage*.png')))
    if not scans:
        raise FileNotFoundError('no printtest scans')
    originals = len(os.listdir(os.path.join(EXP, 'printtest', 'originals')))
    ok = total = 0
    for s in scans:
        _, read = read_page(Image.open(s).convert('L'))
        same = []
        for p in read:
            try:
                _, files, _ = format.parse([p])
            except ValueError:
                continue
            for f in files:
                with open(os.path.join(EXP, 'printtest', 'originals', f.name), 'rb') as o:
                    if o.read() == f.data:
                        same.append(f.name.split('.')[0])
        ok, total = ok + len(same), total + originals
        print(f'    {os.path.basename(s)}: {" ".join(sorted(same))}')
    return ok, total


# PDF page numbers, not the printed ones
HANDLING = [79, 80]  # printed pp. 77-78
APPNOTES = range(11, 148, 4)  # the strips are on every fourth page
STRIPPER = [3, 6, 9, 10, 11, 12, 13, 14]  # p. 3 (title) and 3 strips on p. 6 do not read

# (name, run, strips README reports as read)
SETS = [
    ('Thesis dataset (Distripitor renders)', thesis, 869),
    ('Data Handling Manual pp. 77-78', lambda: count(pdf_pages('SoftstripDataHandlingManual.pdf', HANDLING)), 4),
    ('Application Notes', lambda: count(pdf_pages('Softstrip System Application Notes.pdf', APPNOTES)), 58),
    ('StripWare Stripper Software Manual', lambda: count(pdf_pages(
        'Cauzin Softstrip StripWare Stripper Software Manual.pdf', STRIPPER)), 22),
    ('STRIPPER print dump (fx80)', fx80, 1),
    ('Print test scans (byte-identical files)', printtest, None),
]

if __name__ == '__main__':
    sys.stdout.reconfigure(line_buffering=True)  # progress shows up when piped too
    worse = False
    for name, run, expect in SETS:
        if sys.argv[1:] and not any(a.lower() in name.lower() for a in sys.argv[1:]):
            continue
        print(name)
        try:
            ok, total = run()
        except FileNotFoundError as ex:
            print(f'  skipped: {ex}')
            continue
        drop = expect is not None and ok < expect
        worse |= drop
        print(f'  {ok}' + (f' / {total}' if total else '') + (f'  (README: {expect})' if drop else ''))
    sys.exit(worse)
