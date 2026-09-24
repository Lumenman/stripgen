# softstrip

An encoder and decoder for the **Cauzin Softstrip**, the 2D barcode that 1980s computer magazines
used to print programs and data (1985–1989). It writes files as printable strips and reads them
back from scans. It needs only Python 3.9+, numpy and Pillow 10.1+. There is no machine learning and
no hardware reader involved.

- **Encoder:** one or more files become strip images (PNG) or a print-ready A4 / Letter PDF at true
  size. The byte layout follows Cauzin's 1986 reader specification and the geometry follows the
  patents. Long files are split over several strips.
- **Decoder:** reads clean renders, scans and photographs of single strips or whole pages. It finds
  the strips on a page, corrects tilt and paper distortion, repairs single-bit errors with the
  row parity, reassembles strip sequences and writes out the files.
- **Tested** on original Cauzin strips scanned from Cauzin's own manuals, on a strip printed by
  Cauzin's own STRIPPER program, and on the 869-strip corpus made with Distripitor (see
  [Validation](#validation)).

## Usage

```sh
pip install numpy "pillow>=10.1"

# files -> strips
python -m softstrip encode prog.com -o prog                  # prog.png, or prog-1.png, prog-2.png...
python -m softstrip encode a.bas b.txt -o disk --page A4     # disk.pdf: strips laid out on A4, numbered
python -m softstrip encode notes.txt -o notes --text --os 0x14 --id NOTES

# strips -> files: strip images or whole scanned pages, in any order
python -m softstrip decode page1.png page2.png -d out/

python -m softstrip encode -h                                # all options
python -m softstrip.test_softstrip                           # self-test
```

Useful encoder options:

- `--os` / `--ctype` / `--ftype`: operating system and file type codes from the specification.
- `--exec`: sets the "run after reading" flag.
- `--text`: converts a file to Cauzin generic text (CR LF line ends, `$1A` at the end).
- `--max-length`: longest strip in mm.

### Density

Four options set the density. Everything else follows from them.

| Option | Sets | Default |
|---|---|---|
| `--dpi` | resolution the strip is drawn at | 600 |
| `--cell` | bit width in pixels | 4 → 0.169 mm |
| `--row` | bit (row) height in pixels | 6 → 0.254 mm |
| `--nibbles` | data nibbles per row, n | 10 |

From these:
- strip width = (8·n + 14) × bit width;
- bytes per row = n / 2;
- capacity = (n / 2) / row height × (strip length − about 5 mm of header);
- the vertical sync code is derived from the row height.

With the defaults the strip is 15.9 mm wide and holds about 4.6 KB in 240 mm, with 7 strips per
A4 page. Choose the bit size with `--cell` / `--row`, then pick `--nibbles` so the strip stays
about 16 mm wide, as Cauzin's strips are. The width is not checked.

A bit is always a whole number of pixels at one dpi on both axes, so that printing does not
distort it. Some historical sizes can therefore only be approximated. STRIPPER's 0.318 × 0.588 mm
bit, for example, is `--cell 8 --row 14` (0.339 × 0.593 mm) at 600 dpi.

For reference:

| | Bit width | Row height | Bytes per strip |
|---|---|---|---|
| Cauzin STRIPPER on an Epson FX-80: HIGH / NORMAL / LOW | 0.318 mm | 0.470 / 0.588 / 0.706 mm | 1034 / 819 / 681 |
| Cauzin magazine strips (offset print) | ≈ 0.26 mm | 0.38–0.51 mm | up to ≈ 1400 |
| Cauzin's claim for laser printers | | | up to 3800 |
| this encoder, defaults, 240 mm strip | 0.169 mm | 0.254 mm | ≈ 4600 |

**Printing:** print at 100% / "actual size", never "fit to page", because scaling ruins the bit
height. [examples/print_test_sheet.py](examples/print_test_sheet.py) makes an A4 page with seven
bit sizes, from 0.127 × 0.169 mm to 0.296 × 0.423 mm. Print it, scan it at 600 dpi, decode it,
and compare the output to see what a given printer and scanner can manage.

## The format

The byte layout comes from Cauzin's *Reader Interface Specification* (1986, §3). The physical
layout comes from US 4,782,221 and US 4,692,603, whose FIG. 12 and FIG. 38 are the only
authoritative drawings. Everything below was checked against original strips.

**Strip**, top to bottom:

1. **Horizontal sync.** 28 scan steps of 0.0635 mm. It encodes the row width:
   nibbles = (white→black transitions + 4) / 2.
2. **Vertical sync.** Every row repeats one byte, the row height (see Findings). The patent gives
   56 scan steps, and this encoder uses that. Originals use 48–74 (see Findings).
3. **Data rows.**

**Row**, in bit cells:

| Cells | 2 | 1 | 2 | 2 | 8·n | 2 | 2 | 2–3 |
|---|---|---|---|---|---|---|---|---|
| | start bar | space | checkerboard | left parity | data dibits | right parity | space | rack |

- A dibit is black-white for 0 and white-black for 1.
- Bytes are stored least significant bit first, and they run on across rows.
- The checkerboard flips every row, and the rack is 2 or 3 cells wide in step with it.

**Bytes**, per the specification:

| Field | Size | Notes |
|---|---|---|
| data sync, expansion | 1 + 2 | `$00 $00 $00` |
| length | 2 | LSB first; the bytes from the checksum to the end of the strip |
| checksum | 1 | add-with-carry of all following bytes, then the two's complement |
| strip id | 6 | the same on every strip of a sequence |
| sequence | 1 | 1, 2, 3…; bit 7 is set while more strips follow (see Findings) |
| strip type | 1 | `$00` standard |
| software expansion | 2 | bit 7 of the first byte is the CRC flag; the CRC was never defined, so it stays 0 |
| OS type, number of files | 1 + 1 | first strip only |
| per file: Cauzin type, OS file type, length (3, LSB first), name, terminator (`$00` or `$FF` = executable), misc info (`$00`) | | the whole directory must fit on the first strip |
| file data | | all files back to back, running across strips |

## Findings

These are points the specification leaves open, or where existing tools differ from original
strips. Each one was checked against the patents' drawings and against original Cauzin strips
decoded from scans of *Softstrip Data Handling Manual* and *Softstrip System Application Notes*.

1. **The vertical sync byte is the row height in 1/16 scan steps** (0.0635 mm per step), LSB first.
   The patent says "40 hex means four scans per bit", and FIG. 12 draws exactly `$40`. On
   original strips we found `$60 $63 $66 $71 $80`, and the measured row heights match these
   values. Cauzin's STRIPPER writes `$94` (9.25 steps = 0.587 mm) and prints 0.588 mm rows.
   Distripitor always writes `$80` (0.51 mm) whatever the actual height is (≈0.20 mm).
2. **Parity (FIG. 38):**
   - the left bit covers the odd data dibits, counting from 0;
   - the right bit covers the even data dibits;
   - each parity bit is the sum of its dibits mod 2.
3. **Sequence byte:** bit 7 is set when more strips follow. This bit is not in the
   specification.
   - Single strips read `$01` (45 seen).
   - Pairs read `$81`, then `$02`.
   - No sequence of three or more strips was found, so `$82` for a middle strip is an inference.
4. **Odd row widths are real.** Originals use 5 and 7 nibbles. Vertical sync rows then repeat the
   code bits cut to the row length, the data starts on a new row, and bytes run across rows.
5. **Original densities** range from 4 to 7 nibbles per row. Bits are about 0.26 mm wide or more,
   and rows are 0.38–0.51 mm high (vertical sync codes `$60`–`$80`).
6. **Printed originals do not have a constant row pitch.** It drifts by up to half a row over the
   length of a strip, and the checkerboard is smudged in places. A reader that measures rows one
   by one, or fits a constant pitch, gains or loses rows (see the decoder design below).
7. **Other problems in Distripitor:**
   - its bits are 0.20 mm high, below the patents' 0.25 mm minimum;
   - its header sections are 2 and 4 mm high instead of 1.78 and 3.56 mm;
   - it has no support for multiple strips or files;
   - it hard-codes the file name, strip id and density.

   Its checksum, parity, row layout and horizontal sync are correct.
8. **Cauzin STRIPPER densities.** The Apple II STRIPPER for the Epson FX-80 keeps its LOW /
   NORMAL / HIGH settings in a table of three 9-byte records at `$6070` of the disassembly.
   - byte 0 is the row height in 1/216-inch paper-feed units (6 / 5 / 4);
   - bytes 2–3 are the strip capacity (681 / 819 / 1034 bytes);
   - bytes 4–5 are the vertical sync code (`$B2` / `$94` / `$77`).

   The capacities scale exactly with the inverse row height, so all three settings print the
   same row width, 5 nibbles of 3/240-inch cells, and the same strip length, about 8 inches.
   The NORMAL setting is confirmed by the program's own print dump. The other two are read from
   the table only. Bytes 1 and 6–8 are not decoded.
9. **The vertical sync section has no fixed height.** It is 6 to 12 rows, 48–74 scan steps, even
   for the same code (`$80` strips with 6 and with 9 rows). STRIPPER prints 8 rows (74 steps). The
   reader only needs enough of it to lock on.
10. **File names are untrusted input.** Names on strips can contain paths (the Distripitor corpus
   has `test-icons/…`), so the decoder keeps only the base name.

## Decoder design

`softstrip/image.py`, `read()` for one strip and `find_strips()` for a page:

1. **Threshold:** Otsu's method on the grey image.
2. **Deskew:** a robust line fit to the left edge of the start bar, then rotation.
3. **Row width and cell pitch:** the white→black transitions of the horizontal sync give the
   number of nibbles, and the two wide bars give the cell pitch.
4. **Rows:** the checkerboard signal (dark cell minus light cell) is periodic over two rows. Its
   spectrum over the whole strip gives the mean row pitch. Its phase against that reference,
   averaged over about six rows (a lock-in amplifier), gives the local offset, so smudges are
   bridged and drift is followed.
5. **Cells:** each cell is sampled as a box average. Each row gets a small horizontal shift that
   maximises dibit contrast, median-filtered along the strip to follow bends in the paper.
6. **Parity:** a group that fails parity has its least certain dibit flipped. The patent's reader
   does the same.
7. **Trust:** unreadable rows do not stop the decoder. The strip checksum decides whether the
   strip is accepted.

## Validation

| Corpus | Result |
|---|---|
| Distripitor strips from the thesis dataset (clean renders, fractional scaling, no margins) | 869 / 869 |
| Original Cauzin strips, *Data Handling Manual* pp. 77–78 (whole pages, 600 dpi) | 4 / 4 |
| Original Cauzin strips, *Application Notes* (whole pages, 600 dpi, auto-cropped) | 62 / 66 |
| Cauzin STRIPPER print dump `HELLO-softstrip.fx80`, rendered with `tools/fx80_render.py` | 1 / 1 |
| Own strips: A4 PDF → 600 dpi raster → page decode | byte-identical |

- The four failures are all copies of the same Macintosh program strips. The same data decodes
  from other pages, so these copies are probably damaged in print or in the scan.
- The original strips decode into working files. One is a MacBinary application `Convert`
  (type `APPL`, creator `CAUZ`). Six are MS-DOS utilities, including `cipher.bas`
  "(C) 1986 Cauzin Systems Inc.". The STRIPPER dump decodes into `HELLO`, an Applesoft program
  for Apple DOS 3.3.
- A real print → scan run has not been done yet.
- The self-test covers the following, with synthetic tilt, blur and noise:
  - round trips;
  - odd nibble counts;
  - multi-strip and multi-file sequences;
  - a page of strips.

## Limitations and open questions

- Strips must be roughly upright, within a few degrees. A page scanned sideways has to be
  rotated first.
- The decoder takes images, not PDFs. Scan to PNG or TIFF.
- The value of a middle strip's sequence byte (`$82` or `$02`) is unverified.
- Special key strips (strip type `$01`), the expansion bytes and Cauzin's compression (type `$10`)
  are not supported. They were never defined publicly.
- No print → scan results yet, so the default bit size is a guess.

## Repository layout

```
softstrip/          format.py  byte layout, checksum, multi-strip/multi-file build and parse
                    image.py   geometry, rendering, page layout, strip finding, decoding
                    __main__.py command line; test_softstrip.py self-test
examples/           print_test_sheet.py
tools/              fx80_render.py  renders an Epson FX-80 print dump to PNG (for STRIPPER output)
experiments/        not tracked (.gitignore): third-party code, reference PDFs, scans, test output
```

`experiments/` holds local copies of the sources below. It is not tracked, because the material
belongs to its authors and the PDFs are large:

- `distripitor/`: the original Distripitor sources and sample strips;
- `Cauzin-Softstrip-Decoder-master/`: the thesis decoder;
- `CauzinStripperEpson/`: the STRIPPER disassembly and print dump;
- `references/`: the patents, the Cauzin documents and the thesis;
- `tools/scan_pages.py`: the page scanner used for validation (needs PyMuPDF);
- `printtest/`: output of the print test sheet.

## Sources

### Primary documents

- Cauzin Systems, *Technical Specification for the Softstrip Reader Interface* (Reader Spec), July 1986:
  the byte layout, field meanings and generic text format. Published together with the *Softstrip System
  Application Notes*, *Softstrip Data Handling Manual* (1986), *The Art of Stripping* and other brochures
  in the Internet Archive collection <https://archive.org/details/CauzinSoftstrip>. The strips printed in
  the two manuals are this project's ground truth.
- US 4,782,221, *Printed data strip including bit-encoded information and scanner control* (1988):
  strip anatomy, header sizes, vertical sync code, bit size ranges.
  <https://patents.google.com/patent/US4782221A/en>
- US 4,692,603, *Optical reader for printed bit-encoded data and method of reading same* (1987): FIG. 12
  (header, vertical sync bytes), FIG. 38 (parity groups), the reader's parity correction.
  <https://patents.google.com/patent/US4692603A/en>
- US 4,754,127, *Method and apparatus for transforming digitally encoded data into printed data strips*
  (1988), which covers strip generation. Not consulted yet.
  <https://patents.google.com/patent/US4754127A/en>

### Code

- Chris Osborn (FozzTexx), **Distripitor** (2016). An Objective-C Softstrip generator, and the first
  modern one. Unfinished: one strip, fixed file name. <https://github.com/FozzTexx/Distripitor>
- Michael Reimsbach, **Cauzin-Softstrip-Decoder** (2018). A Python decoder with algorithmic and CNN
  row decoding (TensorFlow 1.x). <https://github.com/MR2011/Cauzin-Softstrip-Decoder>
- Chris Osborn, **CauzinStripperEpson**. A disassembly of Cauzin's own STRIPPER v1.1A (1986) for the
  Apple II and Epson FX-80, with a dump of its printer output. The program itself does not run
  there, but its density table and its print dump are the only first-hand evidence of how Cauzin
  generated strips. <https://github.com/FozzTexx/CauzinStripperEpson>

### Literature

- M. Reimsbach, *Reverse Engineering The Cauzin Softstrip*, Master's thesis, Technical Report
  STL-TR-2018-03, htw saar, 2018. <https://stl.htwsaar.de/tr/STL-TR-2018-03.pdf>. It summarises the
  format (ch. 3) and describes the decoder above and its corpus.
- *Decoding the Cauzin Softstrip: a case study in extracting information from old media*,
  Archival Science, 2021. Not consulted. <https://doi.org/10.1007/s10502-021-09358-z>
- C. Osborn, *Encoding Software in Barcodes, the Eight-Bit Magazine Way*, 2016.
  <http://www.insentricity.com/a.cl/265/encoding-software-in-barcodes-the-eight-bit-magazine-way>
- Softstrip magazine scans: <https://www.apple2scans.net/tag/cauzin-softstrip-reader/>
- Overview: <https://en.wikipedia.org/wiki/Cauzin_Softstrip>

### Own analysis

The [Findings](#findings) above come from reading the specification and patents (including the
drawings, which exist only as scanned images) and from decoding the strips in the two Cauzin
manuals and the STRIPPER print dump. The tools used are this decoder,
`experiments/tools/scan_pages.py` and `tools/fx80_render.py`.

## License

No license has been chosen for this code yet. The third-party material in `experiments/` keeps its
own terms:
- Distripitor is GPL-2.0-or-later;
- Cauzin-Softstrip-Decoder is GPL-3.0;
- the thesis is CC BY-NC-ND 4.0;
- the Cauzin documents and the STRIPPER program are the property of their owners.

Softstrip is a trademark of Cauzin Systems. The patents cited above have long expired.
