"""Command-line interface for normal2height."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional

from . import __version__, batch, udim
from .imaging import warn

FORMAT_EXTENSIONS = {"exr": ".exr", "tif": ".tif", "tiff": ".tiff", "png": ".png"}
OUTPUT_LOOKING_EXTS = {".exr", ".png", ".tif", ".tiff", ".jpg", ".jpeg", ".tga", ".bmp", ".hdr"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="normal2height",
        description="Convert tangent-space normal maps into true, integrated height/displacement "
                     "maps. Point it at a single file or a folder of UDIM tiles and it batches "
                     "everything it finds.",
    )
    p.add_argument("input", type=Path,
                    help="A normal map file, or a directory containing normal maps / UDIM tiles.")
    p.add_argument("-o", "--output", type=Path, default=None,
                    help="Output file (single input, exact name) or directory (batch). "
                         "Default: <input>/height_maps/ next to the input.")
    p.add_argument("-r", "--recursive", action="store_true",
                    help="Recurse into subdirectories when INPUT is a directory.")
    p.add_argument("-j", "--jobs", type=int, default=None,
                    help="Parallel worker processes. Default: all CPU cores.")

    math_group = p.add_argument_group("reconstruction")
    math_group.add_argument(
        "--method", choices=["dct", "fft"], default="dct",
        help="Integration algorithm. 'dct' (default) makes no assumption about tile edges and is "
             "the better choice for ordinary UDIM/texture tiles that are a one-off patch of a "
             "model. 'fft' (Frankot-Chellappa) assumes the tile is seamless/tileable and is the "
             "better choice for genuinely repeating patterns.")
    math_group.add_argument(
        "--convention", choices=["opengl", "directx"], default="opengl",
        help="Green-channel convention of the source normal maps. Default: opengl.")
    math_group.add_argument("--flip-x", action="store_true", help="Flip the horizontal gradient sign.")
    math_group.add_argument("--flip-y", action="store_true", help="Flip the vertical gradient sign.")
    math_group.add_argument(
        "--invert-height", action="store_true",
        help="Flip convex/concave in the reconstructed height. A normal map alone can't tell "
             "which way is 'out' - calibrate once on a known texture with --flip-x/--flip-y/"
             "--invert-height, then reuse the same flags for the rest of that source's batches.")
    math_group.add_argument(
        "--z-scale", type=float, default=1.0,
        help="Slope multiplier / depth exaggeration applied before integration. Default: 1.0.")
    math_group.add_argument(
        "--max-slope", type=float, default=None,
        help="Clamp |dz/dx|,|dz/dy| to this value before integrating, so a few corrupted/extreme "
             "texels can't ring across the whole tile. Default: unclamped.")
    signed_group = math_group.add_mutually_exclusive_group()
    signed_group.add_argument(
        "--assume-signed", dest="assume_signed", action="store_true", default=None,
        help="Force float source pixels to be treated as already signed in [-1,1] "
             "(skips auto-detection).")
    signed_group.add_argument(
        "--assume-unsigned", dest="assume_signed", action="store_false",
        help="Force source pixels to be treated as [0,1]-encoded (skips auto-detection).")

    out_group = p.add_argument_group("output")
    out_group.add_argument(
        "--format", choices=["exr", "tif", "tiff", "png", "same"], default="exr",
        help="Output image format. 'same' keeps each input's own extension. Default: exr "
             "(automatically falls back to tif if the optional OpenEXR package isn't installed).")
    out_group.add_argument(
        "--bit-depth", choices=["float32", "float16", "uint16", "uint8"], default="float32",
        help="Output pixel precision. Default: float32. 8-bit is not recommended for anything "
             "beyond quick previews - see the README's accuracy notes.")
    out_group.add_argument(
        "--exr-half", action="store_true", help="Shorthand for --bit-depth float16.")
    out_group.add_argument(
        "--normalize", choices=["auto", "minmax", "signed", "none"], default="auto",
        help="How the reconstructed height is fit into the output range. 'auto' (default) = raw "
             "float for float formats, full-range 0..1 minmax for integer formats. 'signed' puts "
             "zero height at the format's midpoint. 'none' writes raw values as-is.")
    out_group.add_argument(
        "--exr-channel-mode", choices=["y", "rgb"], default="y",
        help="Write EXR height as a single 'Y' luminance channel (default) or triplicated R=G=B "
             "(for tools that expect an RGB layer).")

    naming_group = p.add_argument_group("naming")
    naming_group.add_argument(
        "--search-tokens", default=",".join(batch.DEFAULT_SEARCH_TOKENS),
        help="Comma-separated, case-insensitive tokens to look for in each filename and replace "
             f"with --replace-token. Default: {','.join(batch.DEFAULT_SEARCH_TOKENS)}")
    naming_group.add_argument(
        "--replace-token", default=batch.DEFAULT_REPLACE_TOKEN,
        help=f"Replacement token (or suffix, if no search token matches this file). "
             f"Default: {batch.DEFAULT_REPLACE_TOKEN}")

    p.add_argument("--exr-layer", default=None,
                    help="Which EXR layer/channel-group to read when a file has more than one "
                         "candidate RGB layer.")
    p.add_argument("--dry-run", action="store_true",
                    help="List what would be processed and where, without writing anything.")
    p.add_argument("-v", "--verbose", action="store_true", help="Print extra detail per file.")
    p.add_argument("--version", action="version", version=f"normal2height {__version__}")
    return p


def _resolve_format(requested: str, verbose: bool) -> str:
    if requested != "exr":
        return requested
    try:
        import OpenEXR  # noqa: F401
    except ImportError:
        warn("--format exr requested but the OpenEXR package isn't installed; "
             "falling back to --format tif. Run `pip install OpenEXR` for EXR support.")
        return "tif"
    return "exr"


def _looks_like_output_file(path: Path) -> bool:
    return path.suffix.lower() in OUTPUT_LOOKING_EXTS and not path.is_dir()


def _print_group_summary(paths, verbose: bool) -> None:
    groups = udim.group_tiles(paths)
    named = {(dir_, base): tiles for (dir_, base), tiles in groups.items() if tiles[0].style != "none"}
    loose_count = sum(len(tiles) for tiles in groups.values() if tiles[0].style == "none")

    for (_, base), tiles in sorted(named.items(), key=lambda kv: kv[0][1]):
        if verbose:
            labels = ", ".join(t.tile_label for t in tiles)
            print(f"  UDIM set '{base}': {len(tiles)} tile(s) [{labels}]")
        else:
            print(f"  UDIM set '{base}': {len(tiles)} tile(s)")
    if loose_count:
        print(f"  {loose_count} file(s) with no recognized UDIM/tile token (processed individually)")


def main(argv: Optional[list] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.exr_half:
        args.bit_depth = "float16"

    if not args.input.exists():
        print(f"error: no such file or directory: {args.input}", file=sys.stderr)
        return 2

    out_format = _resolve_format(args.format, args.verbose)
    out_ext = None if out_format == "same" else FORMAT_EXTENSIONS[out_format]

    search_tokens = [t.strip() for t in args.search_tokens.split(",") if t.strip()]

    options = dict(
        method=args.method, convention=args.convention, flip_x=args.flip_x, flip_y=args.flip_y,
        invert_height=args.invert_height, z_scale=args.z_scale, max_slope=args.max_slope,
        assume_signed=args.assume_signed, bit_depth=args.bit_depth, normalize=args.normalize,
        exr_channel_mode=args.exr_channel_mode, exr_layer=args.exr_layer,
        search_tokens=search_tokens, replace_token=args.replace_token, out_ext=out_ext,
    )

    workers = args.jobs if args.jobs is not None else (os.cpu_count() or 1)

    # --- Single file with an explicit, exact output filename -> one-shot mode ---
    if args.input.is_file() and args.output is not None and _looks_like_output_file(args.output):
        if args.dry_run:
            print(f"{args.input}  ->  {args.output}")
            return 0
        print(f"normal2height: 1 file -> {args.output}")
        result = batch.process_one(args.input, args.output, options)
        if result.ok:
            print(f"OK  {args.input.name} -> {result.output_path}")
            return 0
        print(f"FAIL  {args.input.name}: {result.message}", file=sys.stderr)
        return 1

    # --- Directory (or single-file-into-a-directory) batch mode ---
    if args.output is not None and args.output.exists() and args.output.is_file():
        print(f"error: --output {args.output} already exists as a file; "
              f"batch mode needs a directory to write into.", file=sys.stderr)
        return 2

    try:
        files = batch.list_input_files(args.input, args.output, recursive=args.recursive)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if not files:
        print(f"error: no supported image files found under {args.input}", file=sys.stderr)
        return 2

    resolved_output_dir = batch.resolve_output_dir(args.input, args.output)
    print(f"normal2height: {len(files)} file(s) found under {args.input}")
    _print_group_summary(files, args.verbose)
    print(f"  method={args.method}  convention={args.convention}  format={out_format}  "
          f"bit-depth={args.bit_depth}")
    print(f"  writing output to: {resolved_output_dir}"
          + ("" if args.output is not None else "  (default; pass -o/--output to choose a different place)"))

    if args.dry_run:
        print("\n--dry-run: listing planned conversions, nothing will be written\n")
        for f in files:
            out = batch.compute_output_path(
                f, resolved_output_dir, search_tokens=search_tokens,
                replace_token=args.replace_token, out_ext=out_ext,
            )
            print(f"  {f}  ->  {out}")
        return 0

    def progress(result: batch.JobResult, i: int, total: int) -> None:
        if result.ok:
            print(f"[{i}/{total}] OK    {result.input_path.name} -> {result.output_path}")
        else:
            print(f"[{i}/{total}] FAIL  {result.input_path.name}: {result.message}", file=sys.stderr)

    try:
        results = batch.run_batch(
            args.input, args.output, options,
            recursive=args.recursive, workers=workers, progress=progress,
        )
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    ok_count = sum(1 for r in results if r.ok)
    fail_count = len(results) - ok_count
    print(f"\ndone: {ok_count} succeeded, {fail_count} failed")
    if fail_count:
        print("failed files:", file=sys.stderr)
        for r in results:
            if not r.ok:
                print(f"  {r.input_path}: {r.message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
