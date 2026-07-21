from pathlib import Path

import numpy as np
import pytest

from normal2height import cli


def write_flat_normal_png(path: Path, size=(16, 20)):
    import imageio.v3 as iio
    h, w = size
    img = np.full((h, w, 3), 128, dtype=np.uint8)
    img[..., 2] = 255
    path.parent.mkdir(parents=True, exist_ok=True)
    iio.imwrite(str(path), img)


class TestCliBasics:
    def test_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--help"])
        assert exc.value.code == 0

    def test_version_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc:
            cli.main(["--version"])
        assert exc.value.code == 0

    def test_missing_input_returns_error_code(self, tmp_path, capsys):
        code = cli.main([str(tmp_path / "nope")])
        assert code == 2
        assert "no such file" in capsys.readouterr().err.lower()


class TestBatchRun:
    def test_directory_batch_default_output(self, tmp_path, capsys):
        write_flat_normal_png(tmp_path / "a_normal.1001.png")
        write_flat_normal_png(tmp_path / "a_normal.1002.png")

        code = cli.main([str(tmp_path), "--format", "tif"])
        out = capsys.readouterr().out
        assert code == 0
        assert "2 succeeded, 0 failed" in out
        assert (tmp_path / "height_maps" / "a_height.1001.tif").exists()
        assert (tmp_path / "height_maps" / "a_height.1002.tif").exists()

    def test_dry_run_writes_nothing(self, tmp_path, capsys):
        write_flat_normal_png(tmp_path / "a_normal.png")
        code = cli.main([str(tmp_path), "--dry-run", "--format", "tif"])
        assert code == 0
        assert not (tmp_path / "height_maps").exists()
        out = capsys.readouterr().out
        assert "a_normal.png" in out and "a_height.tif" in out

    def test_dry_run_excludes_prior_output_from_recursive_rerun(self, tmp_path, capsys):
        write_flat_normal_png(tmp_path / "a_normal.png")
        write_flat_normal_png(tmp_path / "height_maps" / "a_height.png")

        code = cli.main([str(tmp_path), "--recursive", "--dry-run", "--format", "tif"])
        assert code == 0
        out = capsys.readouterr().out
        assert "1 file(s) found" in out
        assert "height_maps/a_height.png  ->" not in out

    def test_explicit_output_directory(self, tmp_path, capsys):
        write_flat_normal_png(tmp_path / "in" / "a_normal.png")
        out_dir = tmp_path / "out"
        code = cli.main([str(tmp_path / "in"), "-o", str(out_dir), "--format", "tif"])
        assert code == 0
        assert (out_dir / "a_height.tif").exists()

    def test_single_file_exact_output_path(self, tmp_path, capsys):
        src = tmp_path / "a_normal.png"
        write_flat_normal_png(src)
        dest = tmp_path / "custom_name.tif"
        code = cli.main([str(src), "-o", str(dest)])
        assert code == 0
        assert dest.exists()

    def test_no_images_found_returns_error(self, tmp_path, capsys):
        (tmp_path / "notes.txt").write_text("hi")
        code = cli.main([str(tmp_path)])
        assert code == 2
        assert "no supported image files" in capsys.readouterr().err.lower()

    def test_output_is_existing_file_for_directory_input_errors(self, tmp_path, capsys):
        write_flat_normal_png(tmp_path / "in" / "a_normal.png")
        clashing_file = tmp_path / "clash"
        clashing_file.write_bytes(b"0")
        code = cli.main([str(tmp_path / "in"), "-o", str(clashing_file)])
        assert code == 2
        assert "already exists as a file" in capsys.readouterr().err

    def test_partial_failure_returns_exit_code_1(self, tmp_path, capsys):
        write_flat_normal_png(tmp_path / "good_normal.png")
        (tmp_path / "bad_normal.png").write_bytes(b"not a real image")
        code = cli.main([str(tmp_path), "--format", "tif"])
        assert code == 1
        combined = capsys.readouterr()
        assert "1 succeeded, 1 failed" in combined.out


class TestFormatFallback:
    def test_exr_falls_back_to_tif_when_openexr_missing(self, tmp_path, monkeypatch, capsys):
        import builtins
        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "OpenEXR":
                raise ImportError("simulated: OpenEXR not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        write_flat_normal_png(tmp_path / "a_normal.png")
        code = cli.main([str(tmp_path)])
        assert code == 0
        err = capsys.readouterr().err
        assert "falling back to --format tif" in err
        assert (tmp_path / "height_maps" / "a_height.tif").exists()
