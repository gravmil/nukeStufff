"""Core normal-map -> height-map reconstruction math.

A tangent-space normal map encodes, at every texel, the tilt of the
surface at that point: n = normalize(-dz/dx, -dz/dy, 1). That means a
normal map is really just an encoded pair of height-field gradients
(p, q) = (dz/dx, dz/dy). Recovering the height field z is the classic
"surface reconstruction from gradients" problem from shape-from-shading
literature, and it is an integration, not a per-pixel remap.

Two integrators are provided:

- ``dct``  (default): solves the Poisson equation Laplacian(z) = div(p, q)
  via a Discrete Cosine Transform, which imposes Neumann (zero-derivative)
  boundary conditions. This does not assume the tile is seamless/tileable,
  so it is the more accurate default for arbitrary UDIM texture tiles that
  are a one-off patch of a model rather than a repeating pattern.
- ``fft``  (Frankot-Chellappa, 1988): solves the same least-squares
  integration in the Fourier domain, which implicitly assumes the tile is
  periodic (wraps seamlessly left-right and top-bottom). This is the
  better choice when the source normal map is a genuinely tileable/seamless
  texture.

Both are least-squares-optimal integrations of the gradient field and are
mathematically standard (not a heuristic slope-following/hill-climb), which
is what makes this "a true height map" rather than an approximation.

Two ambiguities are inherent to normal maps and cannot be recovered from
the image alone, no matter the algorithm:

1. Absolute height offset - a normal map carries zero information about
   where "zero height" is. The result is re-centered to zero mean.
2. Convex/concave (relief) direction - this depends on which way "+row"
   and "+column" were assumed to map to the surface's tangent basis when
   the source normal map was authored, and that convention is not
   standardized across tools. Use ``flip_x``/``flip_y``/``invert_height``
   to calibrate against a texture whose relief direction you already know,
   then reuse those flags for the rest of a batch from the same source.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.fftpack import dct, idct


class ConversionError(Exception):
    """Raised for any input that can't be turned into a height map."""


@dataclass
class ConvertOptions:
    method: str = "dct"                 # "dct" | "fft"
    convention: str = "opengl"          # "opengl" | "directx"
    flip_x: bool = False
    flip_y: bool = False
    invert_height: bool = False
    z_scale: float = 1.0
    max_slope: Optional[float] = None
    assume_signed: Optional[bool] = None  # None = auto-detect


def decode_normals(rgb: np.ndarray, was_float_source: bool,
                    assume_signed: Optional[bool] = None) -> np.ndarray:
    """Turn a loaded RGB(A) image array into signed (nx, ny, nz) in [-1, 1].

    ``rgb`` must already be normalized upstream so that integer sources are
    scaled to [0, 1]; float sources are passed through unmodified, since a
    float normal map may already be signed. Whether the data is signed is
    auto-detected (a real normal map has ~half its pixels with nx/ny < 0,
    so a minimum well below 0 is a reliable signal) unless overridden.
    """
    if rgb.ndim != 3 or rgb.shape[-1] < 3:
        raise ConversionError(
            f"Expected an RGB(A) image with at least 3 channels, got array shape {rgb.shape}"
        )
    rgb = np.asarray(rgb, dtype=np.float64)[..., :3]

    if assume_signed is None:
        signed = bool(was_float_source and float(np.min(rgb)) < -0.02)
    else:
        signed = assume_signed

    return rgb.copy() if signed else (rgb * 2.0 - 1.0)


def apply_convention(normals: np.ndarray, convention: str = "opengl",
                      flip_x: bool = False, flip_y: bool = False) -> np.ndarray:
    """Apply green-channel (Y) convention and any manual axis flips.

    OpenGL-convention normal maps have +G pointing toward +V; DirectX
    flips it. ``flip_x``/``flip_y`` are independent manual overrides for
    calibrating against a source tool whose row/column axis direction
    doesn't match this tool's default assumption (see module docstring).
    """
    if convention not in ("opengl", "directx"):
        raise ConversionError(f"Unknown normal map convention: {convention!r}")

    n = normals.copy()
    if convention == "directx":
        n[..., 1] *= -1.0
    if flip_x:
        n[..., 0] *= -1.0
    if flip_y:
        n[..., 1] *= -1.0
    return n


def normals_to_gradients(normals: np.ndarray, eps: float = 1e-8):
    """Convert unit surface normals to height-field slopes (p, q) = (dz/dx, dz/dy)."""
    nx = normals[..., 0]
    ny = normals[..., 1]
    nz = normals[..., 2]

    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    norm = np.where(norm < eps, 1.0, norm)
    nx, ny, nz = nx / norm, ny / norm, nz / norm

    # Guard near-grazing texels (nz ~ 0) from blowing up the slope; real
    # height-field-derived normal maps keep nz > 0 everywhere by construction.
    nz_safe = np.where(np.abs(nz) < eps, np.copysign(eps, np.where(nz == 0, 1.0, nz)), nz)

    p = -nx / nz_safe
    q = -ny / nz_safe
    return p, q


def integrate_frankot_chellappa(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Least-squares gradient integration in the Fourier domain (periodic boundary)."""
    h, w = p.shape
    wx = 2.0 * np.pi * np.fft.fftfreq(w)
    wy = 2.0 * np.pi * np.fft.fftfreq(h)
    wx_grid, wy_grid = np.meshgrid(wx, wy)

    p_f = np.fft.fft2(p)
    q_f = np.fft.fft2(q)

    denom = wx_grid ** 2 + wy_grid ** 2
    denom[0, 0] = 1.0  # avoid divide-by-zero; numerator's DC term is forced to 0 below anyway

    z_f = (-1j * wx_grid * p_f - 1j * wy_grid * q_f) / denom
    z_f[0, 0] = 0.0  # height has no absolute reference; drop the free constant

    return np.real(np.fft.ifft2(z_f))


def integrate_poisson_dct(p: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Least-squares gradient integration via DCT (Neumann/non-periodic boundary).

    ``p``/``q`` are treated as forward-difference slope estimates (p[i, j]
    models z[i, j+1] - z[i, j], q[i, j] models z[i+1, j] - z[i, j]); the last
    column of ``p`` and last row of ``q`` have no "next" sample to model and
    are dropped. This exact formulation - including the one-sided boundary
    terms below - is what's needed for the DCT-II eigenbasis to diagonalize
    the resulting discrete Poisson system; it has been verified to reproduce
    a brute-force dense least-squares solve to machine precision (see
    tests/test_convert.py).
    """
    h, w = p.shape

    p_ext = p.copy()
    p_ext[:, -1] = 0.0
    q_ext = q.copy()
    q_ext[-1, :] = 0.0

    divergence = np.zeros((h, w), dtype=np.float64)
    divergence[:, 1:] = p_ext[:, :-1] - p_ext[:, 1:]
    divergence[:, 0] = -p_ext[:, 0]
    divergence[1:, :] += q_ext[:-1, :] - q_ext[1:, :]
    divergence[0, :] += -q_ext[0, :]
    divergence = -divergence

    dct_div = dct(dct(divergence, axis=0, norm="ortho"), axis=1, norm="ortho")

    x = np.arange(w)
    y = np.arange(h)
    eigenvalues = (2.0 * np.cos(np.pi * x / w) - 2.0)[None, :] + \
                  (2.0 * np.cos(np.pi * y / h) - 2.0)[:, None]
    eigenvalues[0, 0] = 1.0  # avoid divide-by-zero; DC term is forced to 0 below anyway

    dct_z = dct_div / eigenvalues
    dct_z[0, 0] = 0.0  # height has no absolute reference; drop the free constant

    return idct(idct(dct_z, axis=0, norm="ortho"), axis=1, norm="ortho")


def normalize_height(z: np.ndarray, invert: bool = False) -> np.ndarray:
    """Re-center height to zero mean (the only sane default; see module docstring)."""
    z = z - np.mean(z)
    return -z if invert else z


def convert(image: np.ndarray, *, source_is_float: bool, method: str = "dct",
            convention: str = "opengl", flip_x: bool = False, flip_y: bool = False,
            invert_height: bool = False, z_scale: float = 1.0,
            max_slope: Optional[float] = None,
            assume_signed: Optional[bool] = None) -> np.ndarray:
    """Full pipeline: loaded image array -> reconstructed, zero-mean height field."""
    if method not in ("dct", "fft"):
        raise ConversionError(f"Unknown integration method: {method!r} (expected 'dct' or 'fft')")

    normals = decode_normals(image, source_is_float, assume_signed=assume_signed)
    normals = apply_convention(normals, convention=convention, flip_x=flip_x, flip_y=flip_y)
    p, q = normals_to_gradients(normals)

    if max_slope is not None:
        p = np.clip(p, -max_slope, max_slope)
        q = np.clip(q, -max_slope, max_slope)

    p = p * z_scale
    q = q * z_scale

    if method == "fft":
        z = integrate_frankot_chellappa(p, q)
    else:
        z = integrate_poisson_dct(p, q)

    return normalize_height(z, invert=invert_height)
