"""Round-trip and error-handling tests for the image I/O layer.

These exercise the real backends (OpenEXR / tifffile / imageio) rather than
mocking them, since the whole point is to prove bytes survive the pipeline
at the precision the format promises.
"""
from pathlib import Path

import numpy as np
import pytest

from normal2height import imaging

pytest.importorskip("OpenEXR", reason="OpenEXR bindings not installed")
import OpenEXR  # noqa: E402


@pytest.fixture
def tmp_out(tmp_path):
    return tmp_path


class TestPngRoundTrip:
    def test_8bit_normal_map(self, tmp_out):
        rng = np.random.default_rng(0)
        img = rng.integers(0, 256, (16, 20, 3), dtype=np.uint8)
        p = tmp_out / "normal.png"
        import imageio.v3 as iio
        iio.imwrite(str(p), img)

        loaded = imaging.load_image(p)
        assert loaded.was_float_source is False
        assert loaded.data.shape == (16, 20, 3)
        assert np.allclose(loaded.data, img.astype(np.float64) / 255.0)

    def test_16bit_rgb_png_raises_instead_of_silently_truncating(self, tmp_out):
        pytest.importorskip("png", reason="pypng not installed")
        import png as pypng

        rng = np.random.default_rng(0)
        h, w = 8, 10
        img16 = rng.integers(0, 65536, (h, w, 3), dtype=np.uint16)
        p = tmp_out / "sixteen_bit_rgb.png"
        writer = pypng.Writer(width=w, height=h, bitdepth=16, greyscale=False)
        with open(p, "wb") as f:
            writer.write(f, img16.reshape(h, w * 3).tolist())

        with pytest.raises(imaging.ImageIOError, match="16-bit"):
            imaging.load_image(p)

    def test_height_output_minmax_normalize(self, tmp_out):
        z = np.linspace(-3.0, 5.0, 32 * 24).reshape(32, 24)
        out = tmp_out / "height.png"
        imaging.save_height_map(out, z, bit_depth="uint16", normalize="minmax")

        import imageio.v3 as iio
        back = iio.imread(str(out))
        assert back.dtype == np.uint16
        # min->0, max->65535
        assert back.min() == 0
        assert back.max() == 65535
        # monotonic relationship preserved
        assert np.corrcoef(z.ravel(), back.astype(np.float64).ravel())[0, 1] > 0.9999

    def test_refuses_jpeg_output(self, tmp_out):
        z = np.zeros((8, 8))
        with pytest.raises(imaging.ImageIOError, match="lossy"):
            imaging.save_height_map(tmp_out / "height.jpg", z)


class TestTiffRoundTrip:
    def test_float32_height_exact(self, tmp_out):
        rng = np.random.default_rng(1)
        z = rng.uniform(-2, 2, (12, 18)).astype(np.float64)
        out = tmp_out / "height.tif"
        imaging.save_height_map(out, z, bit_depth="float32", normalize="none")

        import tifffile
        back = tifffile.imread(str(out))
        assert back.dtype == np.float32
        assert np.allclose(back, z, atol=1e-6)

    def test_uint16_normal_map_roundtrip(self, tmp_out):
        rng = np.random.default_rng(2)
        img = rng.integers(0, 65536, (10, 14, 3), dtype=np.uint16)
        p = tmp_out / "normal16.tif"
        import tifffile
        tifffile.imwrite(str(p), img)

        loaded = imaging.load_image(p)
        assert loaded.was_float_source is False
        assert np.allclose(loaded.data, img.astype(np.float64) / 65535.0)


class TestExrRoundTrip:
    def test_float32_height_single_channel(self, tmp_out):
        rng = np.random.default_rng(3)
        z = rng.uniform(-1, 1, (10, 16)).astype(np.float64)
        out = tmp_out / "height.exr"
        imaging.save_height_map(out, z, bit_depth="float32", normalize="none", exr_channel_mode="y")

        with OpenEXR.File(str(out)) as f:
            px = f.channels()["Y"].pixels
        assert np.allclose(px, z, atol=1e-6)

    def test_rgb_channel_mode(self, tmp_out):
        z = np.linspace(0, 1, 6 * 6).reshape(6, 6)
        out = tmp_out / "height_rgb.exr"
        imaging.save_height_map(out, z, bit_depth="float32", normalize="none", exr_channel_mode="rgb")
        with OpenEXR.File(str(out)) as f:
            px = f.channels()["RGB"].pixels
        assert px.shape == (6, 6, 3)
        assert np.allclose(px[..., 0], px[..., 1]) and np.allclose(px[..., 1], px[..., 2])

    def test_load_simple_rgb_exr(self, tmp_out):
        rng = np.random.default_rng(4)
        rgb = rng.uniform(-1, 1, (8, 10, 3)).astype(np.float32)
        p = tmp_out / "normal.exr"
        header = {"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage}
        # OpenEXR needs contiguous per-channel buffers; rgb[..., k] is a strided view.
        channels = {c: np.ascontiguousarray(rgb[..., i]) for i, c in enumerate("RGB")}
        with OpenEXR.File(header, channels) as f:
            f.write(str(p))

        loaded = imaging.load_image(p)
        assert loaded.was_float_source is True
        assert np.allclose(loaded.data, rgb, atol=1e-6)

    def test_multi_layer_prefers_normal_named_layer(self, tmp_out):
        rng = np.random.default_rng(5)
        beauty = rng.uniform(0, 1, (6, 6, 3)).astype(np.float32)
        normal = rng.uniform(-1, 1, (6, 6, 3)).astype(np.float32)
        p = tmp_out / "multi.exr"
        header = {"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage}
        c = np.ascontiguousarray
        channels = {
            "beauty.R": c(beauty[..., 0]), "beauty.G": c(beauty[..., 1]), "beauty.B": c(beauty[..., 2]),
            "normal.R": c(normal[..., 0]), "normal.G": c(normal[..., 1]), "normal.B": c(normal[..., 2]),
        }
        with OpenEXR.File(header, channels) as f:
            f.write(str(p))

        loaded = imaging.load_image(p)
        assert np.allclose(loaded.data, normal, atol=1e-6)

    def test_multi_layer_ambiguous_without_hint_raises(self, tmp_out):
        rng = np.random.default_rng(6)
        a = rng.uniform(-1, 1, (6, 6, 3)).astype(np.float32)
        b = rng.uniform(-1, 1, (6, 6, 3)).astype(np.float32)
        p = tmp_out / "ambiguous.exr"
        header = {"compression": OpenEXR.ZIP_COMPRESSION, "type": OpenEXR.scanlineimage}
        c = np.ascontiguousarray
        channels = {
            "foo.R": c(a[..., 0]), "foo.G": c(a[..., 1]), "foo.B": c(a[..., 2]),
            "bar.R": c(b[..., 0]), "bar.G": c(b[..., 1]), "bar.B": c(b[..., 2]),
        }
        with OpenEXR.File(header, channels) as f:
            f.write(str(p))

        with pytest.raises(imaging.ImageIOError, match="multiple candidate"):
            imaging.load_image(p)

        loaded = imaging.load_image(p, exr_layer="bar")
        assert np.allclose(loaded.data, b, atol=1e-6)

    def test_missing_file_raises(self, tmp_out):
        with pytest.raises(imaging.ImageIOError):
            imaging.load_image(tmp_out / "nope.exr")
