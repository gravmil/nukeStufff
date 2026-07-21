# normal2height

A batch, UDIM-aware **normal map → height map (displacement) converter**.

This does a real gradient integration (the same class of algorithm used in
shape-from-shading research), not a heuristic or a per-pixel brightness
remap — a normal map encodes the *slope* of a surface at every texel, and
recovering height means integrating those slopes back into a surface. Point
it at a single file or a folder full of UDIM tiles and it converts
everything it finds, in parallel, preserving as much precision as your
source files have.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .            # core: numpy, scipy, imageio, tifffile
pip install -e ".[exr]"     # + OpenEXR bindings (recommended, see "Formats" below)
```

This installs a `normal2height` command. You can also run it without
installing via `python -m normal2height` from inside `normal2height/src`
(with `PYTHONPATH=src`), or build a dependency-free standalone binary — see
[Standalone executable](#standalone-executable) below.

## Quickstart

```bash
# A single file, output written next to it in ./height_maps/
normal2height texture_normal.png

# A folder full of UDIM tiles (any naming convention, mixed conventions OK) -
# batches every tile it finds, in parallel across all CPU cores
normal2height /path/to/textures/

# Choose where output goes instead of the default <input>/height_maps/
normal2height /path/to/textures/ -o /path/to/displacement/

# Recurse into subfolders, see exactly what would happen first
normal2height /path/to/project/ --recursive --dry-run
```

Nothing is asked interactively (this is a batch/scriptable tool): if you
don't pass `-o/--output`, results are written to a `height_maps/` folder
created next to the input, and the run always prints exactly where before
writing anything.

## What it recognizes

Any folder passed as input is scanned for `.exr .png .tif .tiff .jpg .jpeg
.tga .bmp .hdr` files. UDIM tiles are auto-detected in both common
conventions and reported in a summary before processing:

- **Mari/Mudbox/Substance numeric**: `name.1001.ext`, `name_1002.ext`
- **Explicit UV tile**: `name.u1_v1.ext`, `name_U2_V3.ext` (case-insensitive)

Every file is converted independently regardless of whether it's recognized
as part of a UDIM set — the grouping is only used to print a friendly
summary ("UDIM set 'wall': 4 tiles") before a batch run.

## Accuracy notes (read this)

**The algorithm.** Two well-established integration methods are available
via `--method`:

- `dct` (**default**) — solves the Poisson equation via a Discrete Cosine
  Transform (Neumann boundary). Makes no assumption that the tile wraps
  seamlessly, which is what you want for an arbitrary UDIM tile that's a
  one-off patch of a model. Verified in `tests/test_convert.py` to
  reproduce a brute-force dense least-squares solve of the same discrete
  problem to machine precision (~1e-14).
- `fft` — Frankot-Chellappa (1988), the classic Fourier-domain integrator.
  Assumes the tile is periodic/seamless. Use this for genuinely tileable,
  repeating textures (weave, brick, procedural patterns) — it outperforms
  `dct` there. For an ordinary cropped texture tile it does noticeably
  worse (in one of the test fixtures, correlation to ground truth drops
  from 0.9996 to 0.84) because periodic wraparound treats the tile edges as
  connected to their opposite edges, which they aren't.

**Bit depth matters, a lot.** An 8-bit normal map quantizes each axis to
256 steps; that quantization noise gets integrated (accumulated) into the
height result. In testing, a sharp feature reconstructed from a float/16-bit
source correlated at 0.999+ with ground truth, while the *same* feature from
an 8-bit source dropped to ~0.95 with visibly more noise. **Feed 16-bit or
float (EXR) normal maps whenever you have them.** 8-bit is fine for broad,
low-frequency detail and rough previews, not for fine sculpted/pore-level
detail.

**Two things a normal map genuinely cannot tell you**, regardless of
algorithm:
1. **Absolute height offset.** A normal map only encodes slope, never "how
   high off the ground." Output is re-centered to zero mean; there's no
   other principled choice.
2. **Convex vs. concave.** Whether a given slope pattern reads as a bump or
   a dent depends on which way "+row" and "+column" map to the tangent
   frame, and that convention is not standardized across authoring tools.
   Get it backwards and the whole result inverts (bumps become dents).
   **Calibrate once**: convert one texture whose relief you already know,
   and if it comes out inverted, add `--invert-height` (or `--flip-x`/
   `--flip-y` if only one axis is wrong). Reuse the same flags for the rest
   of that source's batches — it's a property of the tool/pipeline that
   made the normal maps, not of any individual file.

**One inherent limitation**: like all gradient-integration methods in this
family, a *global linear tilt spanning the whole tile* can't be recovered
(a periodic/Neumann-consistent function can't have a nonzero constant
gradient — the math rejects it, it isn't a bug). This essentially never
matters for real tangent-space *detail* normal maps (sculpted wrinkles,
pores, weave, brick) since those are zero-mean perturbations by
construction. It would matter if you fed in a world/object-space normal map
encoding a real average slope — this tool assumes **tangent-space** normal
maps, which is what any bump/detail workflow produces.

**Convention flags**, if your source doesn't match the defaults:
- `--convention directx` if your maps use the DirectX (flipped green
  channel) convention instead of OpenGL (default).
- `--assume-signed` / `--assume-unsigned` to override the automatic
  [0,1]-vs-signed-float detection for float source formats.
- `--max-slope` to clamp extreme per-texel slopes before integrating, so a
  handful of corrupted/extreme texels can't ring across the whole tile.

## Formats

| Format | Read | Write | Notes |
|---|---|---|---|
| EXR | yes | yes | Best precision (float32/float16). Needs the optional `OpenEXR` package; falls back to `tif` automatically (with a warning) if it isn't installed. |
| TIFF | yes | yes | Robust 8/16-bit int and float32. No extra dependency. |
| PNG | yes | yes (8/16-bit) | 8-bit is universal. 16-bit **grayscale** PNG works fine for height output; 16-bit **RGB** PNG input is refused with an explanation rather than silently read wrong — Pillow (the underlying library nearly everything uses for PNG) has no 16-bit RGB decode mode and silently truncates it to 8-bit, which would quietly corrupt precision. Re-export such sources as TIFF or EXR instead. |
| JPG/TGA/BMP/HDR | yes | JPG refused | JPEG is refused as an *output* format (lossy compression would corrupt displacement values); it's still fine as a rough-preview input. |

Multi-layer EXRs (e.g. a beauty+normal+position AOV stack) are handled: if
there's exactly one RGB-shaped layer it's used automatically; if there are
several, a layer literally or partially named `normal`/`nrm`/`nml` is
preferred; otherwise you'll get an error listing the candidates so you can
pick with `--exr-layer <name>`.

Default output is float32 EXR, single channel named `Y` (the standard
OpenEXR grayscale/luminance convention, read natively as grayscale by Nuke,
Houdini, etc.) — pass `--exr-channel-mode rgb` if your downstream tool
expects a triplicated R=G=B layer instead.

## Full option reference

```
normal2height --help
```

covers everything, including `-j/--jobs` (parallel workers, default = all
CPU cores), `--z-scale` (depth exaggeration), `--normalize` (how the result
is fit into the output range), and `--search-tokens`/`--replace-token`
(output filename rules — by default any of `normal`/`nrm`/`nml` in the
input filename is replaced with `height`; if none match, `_height` is
appended).

## Standalone executable

The commands above need Python + the packages in `requirements.txt`
installed. If you'd rather hand someone (or a render farm node) a single
binary with no Python setup required:

```bash
./scripts/build_executable.sh
./dist/normal2height --help
```

This uses PyInstaller to produce a self-contained `dist/normal2height`
binary. Build it **on the same OS/architecture** you intend to run it on
(a Linux build only runs on Linux) — PyInstaller bundles native
dependencies, it doesn't cross-compile.

## Running the tests

```bash
pip install -e ".[dev]"
pytest
```

The test suite (`tests/`) includes a brute-force dense-linear-algebra
verification of the DCT solver, synthetic-surface round-trip accuracy
checks with quantified tolerances, real image-format round trips against
the actual EXR/TIFF/PNG backends, and end-to-end CLI/batch tests — not just
smoke tests.
