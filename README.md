# stripgen

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
- **Tested** on original Cauzin strips scanned from three of Cauzin's own manuals (including two
  complete six-strip programs), on a strip printed by Cauzin's own STRIPPER program, and on the
  869-strip corpus made with Distripitor (see [Validation](#validation)).

## Usage

```sh
git clone https://github.com/Lumenman/stripgen && cd stripgen
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
- `--gap`: mm between strips on a `--page` (default 5, 8 strips on A4). The decoder keeps strips
  apart in a scan tilted up to 1° at 5 mm, 0.5° at 3 mm; at 8 mm, beyond 1.5°.

### Density

Four options set the density. Everything else follows from them.

| Option | Sets | Default |
|---|---|---|
| `--dpi` | resolution the strip is drawn at | 600 |
| `--cell` | bit width in pixels | 4 → 0.169 mm |
| `--row` | bit (row) height in pixels | 6 → 0.254 mm |
| `--nibbles` | data nibbles per row, n | 10 |

The encoder warns below the patent's minimum bit, 0.15 mm wide and 0.25 mm high: such strips
may not read back from print (see [Validation](#validation)). A strip is at least 15 mm long, so
that the decoder can find it on a page; a shorter one is filled out with random bits past its data.

From these:
- strip width = (8·n + 14) × bit width;
- bytes per row = n / 2;
- capacity = (n / 2) / row height × (strip length − about 5 mm of header);
- the vertical sync code is derived from the row height.

With the defaults the strip is 15.9 mm wide and holds about 4.6 KB in 240 mm, with 7 strips per
A4 page. Choose the bit size with `--cell` / `--row`, then pick `--nibbles` so the strip stays
about 16 mm wide, as Cauzin's strips are. The width is not checked.

A bit is always a whole number of pixels at one dpi on both axes, so that printing does not
distort it. Some historical sizes can therefore only be approximated.

**Cauzin STRIPPER's densities.** STRIPPER printed on an Epson FX-80: 5 nibbles per row, cells of
1/80 inch, rows of 4 / 5 / 6 paper-feed steps of 1/216 inch, strips about 8 inches long (finding 8).
Both grids fit whole pixels only at 2160 dpi. At other resolutions the bit is rounded:

| | 2160 dpi, exact | 1200 dpi | 600 dpi | STRIPPER |
|---|---|---|---|---|
| HIGH | `--cell 27 --row 40` | `--cell 15 --row 22` | `--cell 8 --row 11` | 0.318 × 0.470 mm, `$77`, 1034 bytes |
| NORMAL | `--cell 27 --row 50` | `--cell 15 --row 28` | `--cell 8 --row 14` | 0.318 × 0.588 mm, `$94`, 819 bytes |
| LOW | `--cell 27 --row 60` | `--cell 15 --row 33` | `--cell 8 --row 17` | 0.318 × 0.706 mm, `$B2`, 681 bytes |

All of them take `--nibbles 5 --max-length 203.2` together with the `--dpi` of their column, for
example:

```sh
python -m softstrip encode prog.bin -o prog --nibbles 5 --dpi 600 --cell 8 --row 14 --max-length 203.2
```

- At 2160 dpi the bit and the vertical sync code are STRIPPER's own.
- At 1200 dpi the bit width is exact, and the rows are within 0.007 mm of STRIPPER's. The codes
  are `$75` / `$95` / `$B0`.
- At 600 dpi the bits are 0.339 mm wide (7% wider) and 0.466 / 0.593 / 0.720 mm high. The codes
  are `$75` / `$95` / `$B5`.
- A strip holds 1–3% more than STRIPPER's, because this encoder's header is shorter. Capacity
  moves in steps of 2.5 bytes, so STRIPPER's exact figures cannot be hit.
- Render at your printer's own resolution. A 2160 dpi image gets resampled by any printer, and
  resampling hurts (see [Validation](#validation)). The 2160 dpi column is for exact renders, e.g.
  to compare with an original.

For reference:

| | Bit width | Row height | Bytes per strip |
|---|---|---|---|
| Cauzin STRIPPER on an Epson FX-80: HIGH / NORMAL / LOW | 0.318 mm | 0.470 / 0.588 / 0.706 mm | 1034 / 819 / 681 |
| Cauzin magazine strips (offset print) | ≈ 0.26 mm | 0.38–0.51 mm | up to ≈ 1400 |
| Cauzin's claim for laser printers | | | up to 3800 |
| US 4,754,127, high density, 16 × 254 mm strip | 0.15 mm | 0.25 mm | up to 5850 |
| this encoder, defaults, 240 mm strip | 0.169 mm | 0.254 mm | ≈ 4600 |

**Printing:** print at 100% / "actual size", never "fit to page", because scaling ruins the bit
height. [examples/print_test_sheet.py](examples/print_test_sheet.py) makes an A4 page with seven
bit sizes, from 0.127 × 0.169 mm to 0.296 × 0.423 mm, as PDF and as a 600 dpi PNG. Print it,
scan it at 600 dpi, decode it, and compare the output to see what a given printer and scanner
can manage.

The way to the printer matters as much as the bit size (see [Validation](#validation)):
- print the PNG from a viewer that honours its dpi (IrfanView: original size, DPI from image);
- the Windows photo viewer fits the page into the printable area, about 97%;
- a PDF viewer at "actual size" kept the scale but read ten times worse than IrfanView;
- driver extras such as edge smoothing or "enhanced quality" made the same sheet read worse.

Check the scale with a ruler: at the defaults a full strip is about 242 mm long.

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
decoded from scans of *Softstrip Data Handling Manual*, *Softstrip System Application Notes* and
*StripWare Stripper Software Manual*.

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
   - Single strips read `$01`.
   - Pairs read `$81`, then `$02`.
   - The two six-strip STRIPPER programs read `$81 $82 $83 $84 $85 $06`.
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
10. **From the STRIPPER manual** (*StripWare Stripper Software Manual*, 1986):
    - a line holds "from two bytes to six bytes in increments of half a byte", that is 4–12 nibbles;
    - a strip holds up to ten files;
    - the Epson version offers NORMAL (819 bytes) and HIGH (1034 bytes), matching the table in
      finding 8; the Imagewriter version has one density (914 bytes);
    - the alignment dot is 1/8 inch across, its centre 1¼ inch left of the strip's centre line and
      its bottom 3/32 inch above the strip; the alignment bar is 1/4 inch high, 1 9/32 inch left of
      the centre line, its top 1/32 inch below the strip.
11. **Printed layouts vary.** On facing pages Cauzin printed strips upside down. Two different
    programs (the Epson and the Imagewriter STRIPPER) share the strip id `STRIPP` and the numbers
    1–6, so the id alone does not identify a sequence.
12. **File names are untrusted input.** Names on strips can contain paths (the Distripitor corpus
    has `test-icons/…`), so the decoder keeps only the base name. It never overwrites a file:
    if a name already exists, or two strips carry the same name, it writes nothing and stops.
13. **From the strip generation patent** (US 4,754,127):
    - it confirms the row layout above: 2 + 1 + 2 cells on the left, 2 + 3 on the right, 4 parity
      cells, 14 in all;
    - rows are 0.25–1.0 mm high and bits 0.15–0.46 mm wide. The high density bit is 0.15 × 0.25 mm,
      and a 16 × 254 mm strip holds up to 5850 bytes;
    - a strip shorter than planned is filled out with random dibits, or its rows are made taller;
    - Cauzin printed strips on a dot matrix printer at full printer width and reduced them 6:1 to
      12:1 photographically (8:1 preferred). Direct laser print is named as the alternative;
    - dark bits are printed smaller by an "ink spread index" of −0.001" to +0.003", found by trial
      for the ink and paper. This encoder has no such correction: laser prints read without one.

## Decoder design

`softstrip/image.py`, `read()` for one strip and `find_strips()` for a page:

1. **Threshold:** Otsu's method on the grey image.
2. **Deskew and extent:** a robust line fit to the left edge of the start bar, then rotation. The
   strip runs over the longest stretch of rows where the start bar is present (gaps from label
   arrows bridged), so text or marks that happen to line up with it are ignored. The measured
   edge, median-smoothed, is followed where the strip is bent, as near a book's spine.
3. **Row width and cell pitch:** the white→black transitions of the horizontal sync, averaged
   over its scan lines, give the number of nibbles, and the two wide bars give the cell pitch.
4. **Rows:** the checkerboard signal (dark cell minus light cell) is periodic over two rows. Its
   spectrum over the whole strip gives the mean row pitch. Its phase against that reference,
   averaged over about six rows (a lock-in amplifier), gives the local offset, so smudges are
   bridged and drift is followed.
5. **Cells:** each cell is sampled as a box average. Each row gets a small horizontal shift and a
   width correction of up to ±1.2% that maximise dibit contrast, median-filtered along the strip.
   This follows paper that curls near a page edge and squeezes strips sideways. On top of that,
   each dibit column gets its own offset, the centroid of its contrast peak over all rows: a
   printer driver that resamples the page moves cell edges by a pixel here and there, the same in
   every row, and at 3 px per cell that is half a cell.
6. **Parity:** a row that fails parity is first resampled a little higher and lower; rows that
   pass stay put, so no row can slip onto its neighbour. If it still fails, the least certain
   dibit of the failing group is flipped. The patent's reader does the same.
7. **Checksum:** the strip checksum decides; nothing is guessed. An earlier search that tried
   other dibits in the corrected rows until the checksum matched accepted a wrong strip on a real
   scan: with 64 tries an 8-bit checksum passes a broken strip about one time in four.
8. **Trust:** unreadable rows do not stop the decoder, and anything that is not a strip is
   rejected with a ValueError. The command line also tries each strip turned by 180°.

## Validation

| Corpus | Result |
|---|---|
| Distripitor strips from the thesis dataset (clean renders, fractional scaling, no margins) | 869 / 869 |
| Original Cauzin strips, *Data Handling Manual* pp. 77–78 (whole pages, 600 dpi) | 4 / 4 |
| Original Cauzin strips, *Application Notes* (whole pages, 600 dpi, auto-cropped) | 58 / 58 |
| Original Cauzin strips, *StripWare Stripper Software Manual* (JPEG pages, 600 dpi) | 22 / 25 |
| Cauzin STRIPPER print dump `HELLO-softstrip.fx80`, rendered with `tools/fx80_render.py` | 1 / 1 |
| Own strips: A4 PDF → 600 dpi raster → page decode | byte-identical |
| Own strips: test sheet printed on a 600 dpi laser, scanned at 600 dpi (5 prints) | see below |

- "58 / 58" counts every strip `find_strips()` finds on those pages. An earlier count of "62 / 66"
  was wrong: it counted rescanned pages twice.
- The three failures in the STRIPPER manual are on p. 6 (a half-size reproduction of a
  dot-matrix printout, 5 of its 7 strips decode) and on the title page (p. 3).
- Both STRIPPER programs in that manual decode completely from their six strips each:
  `STRIPPER.E` (22,657 bytes) and `STRIPPER.I` (22,777 bytes), Applesoft for Apple DOS 3.3. The
  Epson one is about 90% identical to a different revision of the program in
  [CauzinStripperEpson](https://github.com/FozzTexx/CauzinStripperEpson), with the same strings.
- The original strips decode into working files. One is a MacBinary application `Convert`
  (type `APPL`, creator `CAUZ`). Six are MS-DOS utilities, including `cipher.bas`
  "(C) 1986 Cauzin Systems Inc.". The STRIPPER dump decodes into `HELLO`, an Applesoft program
  for Apple DOS 3.3.
- Print → scan, the test sheet on one 600 dpi laser printer and one flatbed scanner at 600 dpi.
  "OK" means the file is byte-identical to the original; the numbers are wrong bits before
  parity correction.

  | Print | Scale | T1 0.127×0.169 | T2 0.127×0.212 | T3 0.169×0.212 | T4–T7 ≥ 0.169×0.254 |
  |---|---|---|---|---|---|
  | PDF viewer, actual size | 100.0% | 1939 | 153 | OK (8) | OK |
  | Windows photo viewer | 97% | 2257 | 261 | fails (9) | OK |
  | IrfanView | 99.4% | 167 | 10 | OK (0) | OK |
  | IrfanView, driver "enhanced quality", no text sharpening | 100.2% | 1446 | 101 | OK (2) | OK |
  | the same, printed again | 100.2% | 1753 | 170 | fails (27) | OK |

  - The default bit, 0.169 × 0.254 mm (T4, 4.6 KB per strip), reads on every print.
  - T3 (5.5 KB per strip) reads when the print is not scaled.
  - 3 px cells (T1, T2) are past what parity and an 8-bit checksum can carry: T2 at 10 wrong
    bits still failed, on one row with two errors in one parity group.
  - T1–T3 are the only bits below the patent's minimum of 0.15 × 0.25 mm.
  - The per-column offsets took T2 on the PDF print from 1352 wrong bits to 153.
- The self-test covers the following, with synthetic tilt, blur and noise:
  - round trips;
  - odd nibble counts;
  - multi-strip and multi-file sequences;
  - a page of strips.

## Limitations and open questions

- Strips must be roughly upright, within a few degrees. A page scanned sideways has to be
  rotated first.
- The decoder takes images, not PDFs. Scan to PNG or TIFF.
- Sequences that share a strip id (as Cauzin's two STRIPPER programs do) must be decoded
  separately. The command line warns when it meets a different strip with an id and number it
  has already read.
- A strip in a half-size photocopy of dot-matrix print is at the limit: 5 of 7 decode.
- Special key strips (strip type `$01`), the expansion bytes and Cauzin's compression (type `$10`)
  are not supported: the decoder rejects them. They were never defined publicly.
- Print → scan results come from one printer and one scanner. Another pair may need a larger bit.
- The format's error detection is weak: parity per row and an 8-bit checksum per strip. A strip
  with several undetected errors could still pass the checksum 1 time in 256.

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
- Cauzin Systems, *StripWare Stripper Software Manual* (1986): STRIPPER's densities and capacities,
  the "Anatomy of a Data Strip" appendix, alignment mark dimensions, and the complete STRIPPER
  programs as strips.
  <http://mirrors.apple2.org.za/ftp.apple.asimov.net/documentation/hardware/io/cauzin_softstrip/Cauzin%20Softstrip%20StripWare%20Stripper%20Software%20Manual.pdf>
- US 4,782,221, *Printed data strip including bit-encoded information and scanner control* (1988):
  strip anatomy, header sizes, vertical sync code, bit size ranges.
  <https://patents.google.com/patent/US4782221A/en>
- US 4,692,603, *Optical reader for printed bit-encoded data and method of reading same* (1987): FIG. 12
  (header, vertical sync bytes), FIG. 38 (parity groups), the reader's parity correction.
  <https://patents.google.com/patent/US4692603A/en>
- US 4,754,127, *Method and apparatus for transforming digitally encoded data into printed data strips*
  (1988): strip generation. It confirms the row layout and gives bit size limits, fill-out and ink
  spread (finding 13).
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
drawings, which exist only as scanned images) and from decoding the strips in three Cauzin
manuals and the STRIPPER print dump. The tools used are this decoder,
`experiments/tools/scan_pages.py` and `tools/fx80_render.py`.

## License

The code in this repository is MIT-licensed, see [LICENSE](LICENSE). The third-party material in
`experiments/` (not part of this repository) keeps its own terms:
- Distripitor is GPL-2.0-or-later;
- Cauzin-Softstrip-Decoder is GPL-3.0;
- the thesis is CC BY-NC-ND 4.0;
- the Cauzin documents and the STRIPPER program are the property of their owners.

Softstrip is a trademark of Cauzin Systems; this project is not affiliated with Cauzin. The patents
cited above have long expired.
