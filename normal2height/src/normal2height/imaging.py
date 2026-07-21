"""Image I/O: load any supported raster as a normalized float array, and write
reconstructed height maps back out at an appropriate bit depth / format.

Backends:
- EXR:  native ``OpenEXR`` python bindings (best precision; float32/float16,
  proper multi-layer support). Optional dependency - see README.
- TIFF: ``tifffile`` (robust 8/16-bit int and 32-bit float).
- Everything else (PNG, JPG, TGA, BMP, ...): ``imageio``.

Contract used by the rest of the package: ``LoadedImage.data`` is scaled to
[0, 1] for integer sources; float sources are passed through untouched
(a float normal map may already be signed in [-1, 1]).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

EXR_EXTS = {".exr"}
TIFF_EXTS = {".tif", ".tiff"}
DISALLOWED_OUTPUT_EXTS = {".jpg", ".jpeg"}  # lossy; unacceptable for a height map

_NORMAL_LAYER_TOKENS = ("normal", "nrm", "nml", "n")


class ImageIOError(Exception):
    """Raised for any image read/write failure, including missing optional backends."""


def warn(message: str) -> None:
    print(f"[normal2height][warn] {message}", file=sys.stderr)


@dataclass
class LoadedImage:
    data: np.ndarray          # float64, HxWxC (C>=3), see module docstring for scaling contract
    was_float_source: bool
    original_dtype: str
    width: int
    height: int


def _dtype_scale(dtype: np.dtype) -> float:
    if np.issubdtype(dtype, np.floating):
        return 1.0
    if dtype == np.uint8:
        return 255.0
    if dtype == np.uint16:
        return 65535.0
    if dtype == np.uint32:
        return float(2 ** 32 - 1)
    raise ImageIOError(f"Unsupported pixel dtype for a normal map: {dtype}")


def load_image(path: Path, exr_layer: Optional[str] = None) -> LoadedImage:
    path = Path(path)
    suffix = path.suffix.lower()
    if not path.exists():
        raise ImageIOError(f"No such file: {path}")

    if suffix in EXR_EXTS:
        arr, was_float = _load_exr(path, exr_layer)
    elif suffix in TIFF_EXTS:
        arr, was_float = _load_tiff(path)
    else:
        arr, was_float = _load_generic(path)

    if arr.ndim == 2:
        arr = np.stack([arr, arr, arr], axis=-1)
    if arr.ndim != 3 or arr.shape[-1] < 3:
        raise ImageIOError(f"{path}: expected an RGB(A) image, got array shape {arr.shape}")

    original_dtype = str(arr.dtype)
    scale = _dtype_scale(arr.dtype)
    data = arr.astype(np.float64)
    if not was_float:
        data = data / scale

    h, w = data.shape[0], data.shape[1]
    return LoadedImage(data=data, was_float_source=was_float, original_dtype=original_dtype,
                        width=w, height=h)


def _load_exr(path: Path, exr_layer: Optional[str]):
    try:
        import OpenEXR
    except ImportError as exc:
        raise ImageIOError(
            f"{path}: reading EXR requires the 'OpenEXR' python package. "
            f"Install it with `pip install OpenEXR`, or convert your normal maps "
            f"to 16-bit TIFF/PNG."
        ) from exc

    try:
        with OpenEXR.File(str(path)) as f:
            channels = {name: chan.pixels for name, chan in f.channels().items()}
    except Exception as exc:  # noqa: BLE001 - surface any OpenEXR-side failure clearly
        raise ImageIOError(f"{path}: failed to read EXR ({exc})") from exc

    if exr_layer is not None:
        if exr_layer not in channels:
            raise ImageIOError(
                f"{path}: --exr-layer {exr_layer!r} not found. "
                f"Channels in this file: {sorted(channels.keys())}"
            )
        px = channels[exr_layer]
        if px.ndim != 3 or px.shape[-1] < 3:
            raise ImageIOError(f"{path}: layer {exr_layer!r} is not an RGB layer (shape {px.shape})")
        return px, True

    rgb_candidates = [(name, px) for name, px in channels.items() if px.ndim == 3 and px.shape[-1] >= 3]

    if not rgb_candidates:
        single = {name: px for name, px in channels.items() if px.ndim == 2}
        for trio in (("R", "G", "B"), ("r", "g", "b"), ("X", "Y", "Z"), ("x", "y", "z")):
            if all(t in single for t in trio):
                arr = np.stack([single[trio[0]], single[trio[1]], single[trio[2]]], axis=-1)
                return arr, True
        raise ImageIOError(
            f"{path}: couldn't find an RGB normal-map layer in this EXR. "
            f"Channels found: {sorted(channels.keys())}. Use --exr-layer to pick one explicitly."
        )

    if len(rgb_candidates) == 1:
        return rgb_candidates[0][1], True

    for name, px in rgb_candidates:
        if name.lower() in _NORMAL_LAYER_TOKENS:
            return px, True
    for name, px in rgb_candidates:
        if any(tok in name.lower() for tok in _NORMAL_LAYER_TOKENS):
            return px, True

    names = [c[0] for c in rgb_candidates]
    raise ImageIOError(
        f"{path}: multiple candidate RGB layers found ({names}); pick one with --exr-layer."
    )


def _load_tiff(path: Path):
    import tifffile
    arr = tifffile.imread(str(path))
    was_float = np.issubdtype(arr.dtype, np.floating)
    return arr, was_float


def _peek_png_ihdr(path: Path):
    """Read (bit_depth, color_type) straight from a PNG's IHDR chunk, bypassing
    whatever a decoder library made of it. Returns None if not a PNG."""
    try:
        with open(path, "rb") as f:
            header = f.read(26)
    except OSError:
        return None
    if len(header) < 26 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        return None
    return header[24], header[25]


def _load_generic(path: Path):
    import imageio.v3 as iio
    try:
        arr = iio.imread(str(path))
    except Exception as exc:  # noqa: BLE001
        raise ImageIOError(f"{path}: failed to read image ({exc})") from exc

    if path.suffix.lower() == ".png":
        ihdr = _peek_png_ihdr(path)
        if ihdr is not None:
            bit_depth, color_type = ihdr
            # color_type 2 = RGB, 6 = RGBA. Pillow (imageio's PNG backend) has no
            # 16-bit-per-channel *color* mode - it silently decodes these as 8-bit,
            # quietly throwing away exactly the precision this tool exists to
            # preserve. (16-bit *grayscale*, color_type 0/4, is unaffected and used
            # correctly elsewhere for height-map output.) Fail loudly instead.
            if bit_depth == 16 and color_type in (2, 6) and arr.dtype == np.uint8:
                raise ImageIOError(
                    f"{path}: this is a 16-bit-per-channel RGB PNG, but the installed "
                    f"PNG backend (Pillow) can only decode 8-bit RGB and silently "
                    f"truncated it - reading it further would quietly corrupt your "
                    f"normal map's precision. Re-export as 16-bit/float TIFF or EXR "
                    f"instead (both are fully supported), or convert the PNG to 8-bit "
                    f"if that's an acceptable source precision."
                )

    was_float = np.issubdtype(arr.dtype, np.floating)
    return arr, was_float


# ---------------------------------------------------------------------------
# Writing height maps
# ---------------------------------------------------------------------------

def save_height_map(path: Path, z: np.ndarray, *, bit_depth: str = "float32",
                     normalize: str = "auto", exr_channel_mode: str = "y") -> None:
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in DISALLOWED_OUTPUT_EXTS:
        raise ImageIOError(
            f"{path}: refusing to write a height map as JPEG (lossy compression would "
            f"corrupt the displacement values). Use --format exr, tif, or png instead."
        )

    is_float_target = bit_depth in ("float32", "float16") or suffix in EXR_EXTS

    mode = normalize
    if mode == "auto":
        mode = "none" if is_float_target else "minmax"

    z = np.asarray(z, dtype=np.float64)
    if mode == "minmax":
        zmin, zmax = float(z.min()), float(z.max())
        span = zmax - zmin
        z01 = np.zeros_like(z) if span < 1e-12 else (z - zmin) / span
    elif mode == "signed":
        amax = float(np.max(np.abs(z))) or 1.0
        z01 = (z / amax) * 0.5 + 0.5
    elif mode == "none":
        z01 = z
        if not is_float_target:
            if z.min() < -1e-6 or z.max() > 1.0 + 1e-6:
                warn(f"{path}: writing un-normalized values to an integer format; "
                     f"they will be clipped to [0, 1]. Pass --normalize minmax or signed instead.")
    else:
        raise ImageIOError(f"Unknown normalize mode: {mode!r}")

    path.parent.mkdir(parents=True, exist_ok=True)

    if suffix in EXR_EXTS:
        _save_exr(path, z01, bit_depth, exr_channel_mode)
    elif suffix in TIFF_EXTS:
        _save_tiff(path, z01, bit_depth)
    else:
        _save_generic(path, z01, bit_depth)


def _cast_for_bit_depth(z01: np.ndarray, bit_depth: str) -> np.ndarray:
    if bit_depth == "uint8":
        return np.clip(np.round(z01 * 255.0), 0, 255).astype(np.uint8)
    if bit_depth == "uint16":
        return np.clip(np.round(z01 * 65535.0), 0, 65535).astype(np.uint16)
    if bit_depth == "float32":
        return z01.astype(np.float32)
    if bit_depth == "float16":
        return z01.astype(np.float16)
    raise ImageIOError(f"Unknown bit depth: {bit_depth!r}")


def _save_exr(path: Path, z01: np.ndarray, bit_depth: str, exr_channel_mode: str) -> None:
    try:
        import OpenEXR
    except ImportError as exc:
        raise ImageIOError(
            "Writing EXR requires the 'OpenEXR' python package. "
            "Install it with `pip install OpenEXR`, or pass --format tif."
        ) from exc

    dtype = np.float16 if bit_depth == "float16" else np.float32
    arr = np.ascontiguousarray(z01.astype(dtype))

    header = {"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage}
    if exr_channel_mode == "rgb":
        channels = {"R": arr, "G": arr, "B": arr}
    else:
        channels = {"Y": arr}

    with OpenEXR.File(header, channels) as outfile:
        outfile.write(str(path))


def _save_tiff(path: Path, z01: np.ndarray, bit_depth: str) -> None:
    import tifffile
    out = _cast_for_bit_depth(z01, bit_depth)
    tifffile.imwrite(str(path), out)


def _save_generic(path: Path, z01: np.ndarray, bit_depth: str) -> None:
    import imageio.v3 as iio
    if bit_depth in ("float32", "float16"):
        warn(f"{path}: {path.suffix} doesn't support float pixels; writing 16-bit integer instead. "
             f"Use --format exr or --format tif to keep float precision.")
        bit_depth = "uint16"
    out = _cast_for_bit_depth(z01, bit_depth)
    try:
        iio.imwrite(str(path), out)
    except Exception as exc:  # noqa: BLE001
        raise ImageIOError(f"{path}: failed to write image ({exc})") from exc
