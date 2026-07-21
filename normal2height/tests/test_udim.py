from pathlib import Path

import pytest

from normal2height import udim


class TestParseTile:
    @pytest.mark.parametrize("filename,expected_base,expected_style,expected_udim", [
        ("wallTexture.1001.png", "wallTexture", "mari", 1001),
        ("wallTexture_1001.exr", "wallTexture", "mari", 1001),
        ("wallTexture.normal.1002.tif", "wallTexture.normal", "mari", 1002),
        ("props.1023.png", "props", "mari", 1023),
        ("plain_no_tile.png", "plain_no_tile", "none", None),
        ("render.0001.exr", "render", "mari", 1),  # ambiguous w/ frame numbers by design; see module docstring
    ])
    def test_mari_and_plain(self, filename, expected_base, expected_style, expected_udim):
        info = udim.parse_tile(Path(filename))
        assert info.base == expected_base
        assert info.style == expected_style
        assert info.udim == expected_udim

    @pytest.mark.parametrize("filename,expected_base,expected_u,expected_v,expected_udim", [
        # canonical UDIM numbering: udim = 1001 + u + v*10
        ("wallTexture.u1_v1.png", "wallTexture", 1, 1, 1012),
        ("wallTexture_u0_v0.exr", "wallTexture", 0, 0, 1001),
        ("wallTexture.U2_V3.tif", "wallTexture", 2, 3, 1033),
        ("wallTexture.u-1_v0.png", "wallTexture", -1, 0, None),  # out of canonical UDIM range
    ])
    def test_uv_tile_style(self, filename, expected_base, expected_u, expected_v, expected_udim):
        info = udim.parse_tile(Path(filename))
        assert info.style == "uv"
        assert info.base == expected_base
        assert info.tile_label == f"u{expected_u}_v{expected_v}"
        assert info.udim == expected_udim

    def test_multi_dot_basename_grabs_trailing_token_only(self):
        info = udim.parse_tile(Path("hero.body.diffuse.1001.exr"))
        assert info.base == "hero.body.diffuse"
        assert info.udim == 1001


class TestIsImageFile:
    def test_known_extensions(self, tmp_path):
        for ext in (".png", ".exr", ".tif", ".tiff", ".jpg", ".jpeg", ".tga", ".bmp", ".hdr"):
            f = tmp_path / f"x{ext}"
            f.write_bytes(b"0")
            assert udim.is_image_file(f)

    def test_unknown_extension_rejected(self, tmp_path):
        f = tmp_path / "readme.txt"
        f.write_text("hi")
        assert not udim.is_image_file(f)

    def test_directory_rejected(self, tmp_path):
        d = tmp_path / "subdir.png"
        d.mkdir()
        assert not udim.is_image_file(d)


class TestDiscoverImages:
    def _touch(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"0")

    def test_single_file_input(self, tmp_path):
        f = tmp_path / "tex.1001.png"
        self._touch(f)
        found = list(udim.discover_images(f))
        assert found == [f]

    def test_single_file_input_rejects_non_image(self, tmp_path):
        f = tmp_path / "notes.txt"
        self._touch(f)
        with pytest.raises(ValueError):
            list(udim.discover_images(f))

    def test_directory_non_recursive(self, tmp_path):
        self._touch(tmp_path / "a.1001.png")
        self._touch(tmp_path / "b.1002.png")
        self._touch(tmp_path / "ignore.txt")
        self._touch(tmp_path / "sub" / "c.1003.png")

        found = sorted(p.name for p in udim.discover_images(tmp_path, recursive=False))
        assert found == ["a.1001.png", "b.1002.png"]

    def test_directory_recursive(self, tmp_path):
        self._touch(tmp_path / "a.1001.png")
        self._touch(tmp_path / "sub" / "c.1003.png")

        found = sorted(p.name for p in udim.discover_images(tmp_path, recursive=True))
        assert found == ["a.1001.png", "c.1003.png"]

    def test_missing_path_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            list(udim.discover_images(tmp_path / "nope"))


class TestGroupTiles:
    def _touch(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"0")

    def test_groups_by_base_and_directory(self, tmp_path):
        paths = []
        for name in ["wall.1001.png", "wall.1002.png", "wall.1011.png", "floor.1001.png"]:
            p = tmp_path / name
            self._touch(p)
            paths.append(p)

        groups = udim.group_tiles(paths)
        assert (tmp_path, "wall") in groups
        assert (tmp_path, "floor") in groups
        wall_tiles = groups[(tmp_path, "wall")]
        assert [t.udim for t in wall_tiles] == [1001, 1002, 1011]
        assert len(groups[(tmp_path, "floor")]) == 1

    def test_mixed_styles_and_ungrouped(self, tmp_path):
        paths = []
        for name in ["a.1001.png", "a.u1_v0.png", "loose_file.png"]:
            p = tmp_path / name
            self._touch(p)
            paths.append(p)
        groups = udim.group_tiles(paths)
        # "a.u1_v0" parses to base "a" too (udim-equivalent 1002), grouping with "a.1001"
        assert len(groups[(tmp_path, "a")]) == 2
        assert (tmp_path, "loose_file") in groups
