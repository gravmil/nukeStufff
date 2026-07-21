"""Batch orchestration: discover inputs, name outputs, dispatch conversion
(optionally in parallel across processes), and report progress/results.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import convert, imaging, udim

DEFAULT_SEARCH_TOKENS = ("normal", "nrm", "nml")
DEFAULT_REPLACE_TOKEN = "height"
DEFAULT_OUTPUT_DIRNAME = "height_maps"


@dataclass
class JobResult:
    input_path: Path
    output_path: Optional[Path]
    ok: bool
    message: str = ""


def compute_output_path(input_path: Path, output_dir: Path, *,
                         search_tokens=DEFAULT_SEARCH_TOKENS,
                         replace_token: str = DEFAULT_REPLACE_TOKEN,
                         out_ext: Optional[str] = ".exr") -> Path:
    """``out_ext=None`` means "keep each input's own extension" (``--format same``)."""
    stem = input_path.stem
    lower = stem.lower()

    new_stem = None
    for tok in search_tokens:
        tok_lower = tok.lower()
        idx = lower.find(tok_lower)
        if idx != -1:
            new_stem = stem[:idx] + replace_token + stem[idx + len(tok):]
            break

    if new_stem is None:
        new_stem = f"{stem}_{replace_token}"

    ext = out_ext if out_ext is not None else input_path.suffix
    return output_dir / f"{new_stem}{ext}"


def process_one(input_path: Path, output_path: Path, options: Dict) -> JobResult:
    try:
        loaded = imaging.load_image(input_path, exr_layer=options.get("exr_layer"))
        z = convert.convert(
            loaded.data,
            source_is_float=loaded.was_float_source,
            method=options["method"],
            convention=options["convention"],
            flip_x=options["flip_x"],
            flip_y=options["flip_y"],
            invert_height=options["invert_height"],
            z_scale=options["z_scale"],
            max_slope=options.get("max_slope"),
            assume_signed=options.get("assume_signed"),
        )
        imaging.save_height_map(
            output_path, z,
            bit_depth=options["bit_depth"],
            normalize=options["normalize"],
            exr_channel_mode=options.get("exr_channel_mode", "y"),
        )
        return JobResult(input_path, output_path, True, "ok")
    except Exception as exc:  # noqa: BLE001 - one bad tile must not abort the whole batch
        return JobResult(input_path, None, False, f"{type(exc).__name__}: {exc}")


def resolve_output_dir(input_path: Path, output: Optional[Path]) -> Path:
    if output is not None:
        return output
    base_dir = input_path if input_path.is_dir() else input_path.parent
    return base_dir / DEFAULT_OUTPUT_DIRNAME


def list_input_files(input_path: Path, output_dir: Optional[Path], *,
                      recursive: bool = False) -> List[Path]:
    """Discover input images, excluding anything already inside the resolved
    output directory (so a previous run's own output never gets reprocessed
    as input on a later --recursive pass). This is the single source of
    truth for "what will actually be converted" - used by both run_batch and
    the CLI's upfront summary/--dry-run, so they can never disagree."""
    input_path = Path(input_path)
    files = list(udim.discover_images(input_path, recursive=recursive))

    resolved_output_dir_abs = resolve_output_dir(input_path, output_dir).resolve()
    kept = []
    for f in files:
        try:
            f.resolve().relative_to(resolved_output_dir_abs)
        except ValueError:
            kept.append(f)
    return kept


def run_batch(input_path: Path, output_dir: Optional[Path], options: Dict, *,
              recursive: bool = False, workers: int = 1,
              progress: Optional[Callable[[JobResult, int, int], None]] = None
              ) -> List[JobResult]:
    input_path = Path(input_path)
    files = list_input_files(input_path, output_dir, recursive=recursive)

    if not files:
        raise FileNotFoundError(f"No supported image files found under {input_path}")

    resolved_output_dir = resolve_output_dir(input_path, output_dir)

    jobs = [(f, compute_output_path(
        f, resolved_output_dir,
        search_tokens=options["search_tokens"],
        replace_token=options["replace_token"],
        out_ext=options["out_ext"],
    )) for f in files]

    results: List[JobResult] = []
    total = len(jobs)

    if workers <= 1:
        for i, (f, out) in enumerate(jobs, 1):
            r = process_one(f, out, options)
            results.append(r)
            if progress:
                progress(r, i, total)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            future_map = {executor.submit(process_one, f, out, options): (f, out) for f, out in jobs}
            i = 0
            for future in as_completed(future_map):
                i += 1
                r = future.result()
                results.append(r)
                if progress:
                    progress(r, i, total)

    return results
