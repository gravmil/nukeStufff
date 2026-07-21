"""UDIM / tile-sequence discovery and filename parsing.

Every image found is processed independently regardless of whether it's
recognized as part of a UDIM set - tile-set grouping here exists only to
print a friendly summary before a batch run ("found UDIM set 'wall' with
4 tiles"). A file that doesn't match any known convention is still
converted; it just isn't grouped with anything.

Two UDIM naming conventions are recognized:
- Mari/Mudbox/Substance numeric: ``name.1001.ext`` (also ``name_1001.ext``).
- Explicit UV tile: ``name.u1_v1.ext`` (also ``name_u1_v1.ext``,
  case-insensitive, negative indices allowed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

IMAGE_EXTENSIONS = {
    ".exr", ".png", ".tif", ".tiff", ".jpg", ".jpeg", ".tga", ".bmp", ".hdr",
}

_MARI_UDIM_RE = re.compile(r"^(?P<base>.+)[._](?P<udim>\d{4,5})$")
_UV_TILE_RE = re.compile(r"^(?P<base>.+)[._][uU](?P<u>-?\d+)_[vV](?P<v>-?\d+)$")


@dataclass
class TileInfo:
    path: Path
    base: str
    style: str            # "mari" | "uv" | "none"
    tile_label: str        # human-readable tile token, e.g. "1001" or "u2_v1"
    udim: Optional[int] = None


def is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS


def parse_tile(path: Path) -> TileInfo:
    stem = path.stem

    m = _MARI_UDIM_RE.match(stem)
    if m:
        udim = int(m.group("udim"))
        return TileInfo(path=path, base=m.group("base"), style="mari",
                         tile_label=m.group("udim"), udim=udim)

    m = _UV_TILE_RE.match(stem)
    if m:
        u, v = int(m.group("u")), int(m.group("v"))
        udim = 1001 + u + v * 10 if 0 <= u <= 9 else None
        return TileInfo(path=path, base=m.group("base"), style="uv",
                         tile_label=f"u{u}_v{v}", udim=udim)

    return TileInfo(path=path, base=stem, style="none", tile_label="")


def discover_images(input_path: Path, recursive: bool = False) -> Iterator[Path]:
    input_path = Path(input_path)
    if input_path.is_file():
        if not is_image_file(input_path):
            raise ValueError(f"{input_path} doesn't look like a supported image file "
                              f"({', '.join(sorted(IMAGE_EXTENSIONS))})")
        yield input_path
        return

    if not input_path.is_dir():
        raise FileNotFoundError(f"No such file or directory: {input_path}")

    pattern = "**/*" if recursive else "*"
    for p in sorted(input_path.glob(pattern)):
        if is_image_file(p):
            yield p


def group_tiles(paths: List[Path]) -> Dict[Tuple[Path, str], List[TileInfo]]:
    """Group discovered files by (parent directory, base name) for reporting."""
    groups: Dict[Tuple[Path, str], List[TileInfo]] = {}
    for p in paths:
        info = parse_tile(p)
        key = (p.parent, info.base)
        groups.setdefault(key, []).append(info)
    for key in groups:
        groups[key].sort(key=lambda t: (t.udim if t.udim is not None else -1, t.tile_label))
    return groups
