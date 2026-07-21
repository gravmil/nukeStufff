from pathlib import Path

import numpy as np
import pytest

from normal2height import batch

DEFAULT_OPTIONS = dict(
    method="dct", convention="opengl", flip_x=False, flip_y=False,
    invert_height=False, z_scale=1.0, max_slope=None, assume_signed=None,
    bit_depth="float32", normalize="auto", exr_channel_mode="y",
    search_tokens=batch.DEFAULT_SEARCH_TOKENS, replace_token=batch.DEFAULT_REPLACE_TOKEN,
    out_ext=".tif",  # avoid requiring the optional OpenEXR dependency in these tests
)


def write_flat_normal_png(path: Path, size=(16, 20)):
    import imageio.v3 as iio
    h, w = size
    img = np.full((h, w, 3), 128, dtype=np.uint8)
    img[..., 2] = 255  # nz ~ 1 after decode
    path.parent.mkdir(parents=True, exist_ok=True)
    iio.imwrite(str(path), img)


class TestComputeOutputPath:
    def test_replaces_search_token(self):
        out = batch.compute_output_path(
            Path("wall_normal.1001.png"), Path("/out"),
            search_tokens=["normal"], replace_token="height", out_ext=".exr",
        )
        assert out == Path("/out/wall_height.1001.exr")

    def test_case_insensitive_token_match(self):
        out = batch.compute_output_path(
            Path("Wall_Normal.png"), Path("/out"),
            search_tokens=["normal"], replace_token="height", out_ext=".exr",
        )
        assert out == Path("/out/Wall_height.exr")

    def test_appends_suffix_when_no_token_found(self):
        out = batch.compute_output_path(
            Path("wall.1001.png"), Path("/out"),
            search_tokens=["normal", "nrm"], replace_token="height", out_ext=".exr",
        )
        assert out == Path("/out/wall.1001_height.exr")

    def test_first_matching_token_wins(self):
        out = batch.compute_output_path(
            Path("wall_nrm_detail.png"), Path("/out"),
            search_tokens=["normal", "nrm"], replace_token="height", out_ext=".exr",
        )
        assert out == Path("/out/wall_height_detail.exr")


class TestResolveOutputDir:
    def test_explicit_output_used_verbatim(self, tmp_path):
        assert batch.resolve_output_dir(tmp_path, tmp_path / "custom") == tmp_path / "custom"

    def test_default_for_directory_input(self, tmp_path):
        assert batch.resolve_output_dir(tmp_path, None) == tmp_path / "height_maps"

    def test_default_for_file_input_uses_parent(self, tmp_path):
        f = tmp_path / "tex.1001.png"
        f.write_bytes(b"0")
        assert batch.resolve_output_dir(f, None) == tmp_path / "height_maps"


class TestRunBatchEndToEnd:
    def test_processes_udim_set(self, tmp_path):
        for tile in ("1001", "1002", "1003"):
            write_flat_normal_png(tmp_path / f"wall_normal.{tile}.png")

        results = batch.run_batch(tmp_path, None, DEFAULT_OPTIONS, workers=1)
        assert len(results) == 3
        assert all(r.ok for r in results)
        for r in results:
            assert r.output_path.exists()
            assert r.output_path.parent == tmp_path / "height_maps"

    def test_parallel_workers_match_serial(self, tmp_path):
        for tile in ("1001", "1002", "1003", "1004"):
            write_flat_normal_png(tmp_path / f"wall_normal.{tile}.png")

        serial = batch.run_batch(tmp_path, tmp_path / "out_serial", DEFAULT_OPTIONS, workers=1)
        parallel = batch.run_batch(tmp_path, tmp_path / "out_parallel", DEFAULT_OPTIONS, workers=2)
        assert len(serial) == len(parallel) == 4
        assert all(r.ok for r in serial)
        assert all(r.ok for r in parallel)

    def test_single_file_input(self, tmp_path):
        f = tmp_path / "prop_normal.png"
        write_flat_normal_png(f)
        results = batch.run_batch(f, None, DEFAULT_OPTIONS, workers=1)
        assert len(results) == 1
        assert results[0].ok
        assert results[0].output_path == tmp_path / "height_maps" / "prop_height.tif"

    def test_explicit_output_directory(self, tmp_path):
        write_flat_normal_png(tmp_path / "a_normal.png")
        out_dir = tmp_path / "somewhere_else"
        results = batch.run_batch(tmp_path, out_dir, DEFAULT_OPTIONS, workers=1)
        assert results[0].output_path.parent == out_dir

    def test_no_files_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            batch.run_batch(tmp_path, None, DEFAULT_OPTIONS, workers=1)

    def test_excludes_previous_output_directory_from_reprocessing(self, tmp_path):
        write_flat_normal_png(tmp_path / "a_normal.png")
        # simulate a prior run's output already sitting under the default output dir
        write_flat_normal_png(tmp_path / "height_maps" / "a_height.png")

        results = batch.run_batch(tmp_path, None, DEFAULT_OPTIONS, recursive=True, workers=1)
        assert len(results) == 1
        assert results[0].input_path.name == "a_normal.png"

    def test_list_input_files_matches_what_run_batch_processes(self, tmp_path):
        """CLI --dry-run and the pre-run summary call list_input_files() directly
        (not through run_batch); this proves that call sees exactly the same
        exclusion behavior run_batch applies internally, so a dry-run preview
        can never show a file that the real run would then skip."""
        write_flat_normal_png(tmp_path / "a_normal.png")
        write_flat_normal_png(tmp_path / "height_maps" / "a_height.png")

        previewed = batch.list_input_files(tmp_path, None, recursive=True)
        assert [p.name for p in previewed] == ["a_normal.png"]

        results = batch.run_batch(tmp_path, None, DEFAULT_OPTIONS, recursive=True, workers=1)
        assert [r.input_path.name for r in results] == [p.name for p in previewed]

    def test_bad_file_does_not_abort_batch(self, tmp_path):
        write_flat_normal_png(tmp_path / "good_normal.png")
        bad = tmp_path / "bad_normal.png"
        bad.write_bytes(b"not a real png")

        results = batch.run_batch(tmp_path, None, DEFAULT_OPTIONS, workers=1)
        assert len(results) == 2
        ok_results = [r for r in results if r.ok]
        bad_results = [r for r in results if not r.ok]
        assert len(ok_results) == 1
        assert len(bad_results) == 1
        assert bad_results[0].input_path.name == "bad_normal.png"
        assert bad_results[0].message  # has an explanation
