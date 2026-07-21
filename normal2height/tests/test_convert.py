"""Accuracy tests for the core normal->height reconstruction math.

These are not just smoke tests: `test_dct_matches_bruteforce_lstsq` proves the
fast DCT solver is an exact (machine-precision) match for a brute-force dense
least-squares solve of the same discrete problem, and the synthetic-surface
tests prove the full pipeline recovers known ground-truth height fields to
tight, quantified tolerances.
"""
import numpy as np
import pytest
from scipy.sparse import coo_matrix
from scipy.sparse.linalg import lsqr

from normal2height import convert as cv


def rmse(a, b):
    return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))


def corr(a, b):
    return float(np.corrcoef(np.asarray(a).ravel(), np.asarray(b).ravel())[0, 1])


def height_to_normals(dzdx, dzdy):
    nx, ny, nz = -dzdx, -dzdy, np.ones_like(dzdx)
    n = np.sqrt(nx ** 2 + ny ** 2 + nz ** 2)
    return np.stack([nx / n, ny / n, nz / n], axis=-1)


def bruteforce_lstsq_reference(p, q):
    """Dense/sparse least-squares solve of the exact same discrete problem
    integrate_poisson_dct is meant to solve quickly, used as ground truth."""
    h, w = p.shape[0], p.shape[1] + 1  # p/q here are the (H,W-1)/(H-1,W) staggered form

    def idx(i, j):
        return i * w + j

    rows, cols, vals, b = [], [], [], []
    r = 0
    for i in range(h):
        for j in range(w - 1):
            rows += [r, r]
            cols += [idx(i, j + 1), idx(i, j)]
            vals += [1.0, -1.0]
            b.append(p[i, j])
            r += 1
    for i in range(h - 1):
        for j in range(w):
            rows += [r, r]
            cols += [idx(i + 1, j), idx(i, j)]
            vals += [1.0, -1.0]
            b.append(q[i, j])
            r += 1

    a_mat = coo_matrix((vals, (rows, cols)), shape=(r, h * w)).tocsr()
    sol = lsqr(a_mat, np.array(b), atol=1e-14, btol=1e-14, iter_lim=20000)[0]
    z = sol.reshape(h, w)
    return z - z.mean()


class TestDctSolverCorrectness:
    @pytest.mark.parametrize("trial", range(8))
    def test_dct_matches_bruteforce_lstsq(self, trial):
        rng = np.random.default_rng(trial)
        h = int(rng.integers(5, 30))
        w = int(rng.integers(5, 30))
        z_true = rng.standard_normal((h, w))

        p_staggered = z_true[:, 1:] - z_true[:, :-1]
        q_staggered = z_true[1:, :] - z_true[:-1, :]

        p_pointwise = np.zeros((h, w))
        p_pointwise[:, :-1] = p_staggered
        q_pointwise = np.zeros((h, w))
        q_pointwise[:-1, :] = q_staggered

        z_fast = cv.integrate_poisson_dct(p_pointwise, q_pointwise)
        z_fast0 = z_fast - z_fast.mean()

        z_ref = bruteforce_lstsq_reference(p_staggered, q_staggered)

        assert np.max(np.abs(z_fast0 - z_ref)) < 1e-9


class TestSyntheticSurfaceReconstruction:
    """Round-trip: known height field -> analytic normals -> reconstructed height."""

    def setup_grid(self, h=128, w=96):
        yy, xx = np.mgrid[0:h, 0:w]
        return h, w, xx.astype(np.float64), yy.astype(np.float64)

    def test_localized_bump_detail(self):
        h, w, x, y = self.setup_grid()
        bumps = [(w * 0.3, h * 0.65, 10.0, 1.4), (w * 0.7, h * 0.25, 6.0, -0.9),
                 (w * 0.5, h * 0.5, 16.0, 0.7), (w * 0.15, h * 0.2, 5.0, 1.1)]
        z = sum(amp * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * s ** 2))) for cx, cy, s, amp in bumps)
        dzdx = sum(amp * (-(x - cx) / s ** 2) * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * s ** 2)))
                   for cx, cy, s, amp in bumps)
        dzdy = sum(amp * (-(y - cy) / s ** 2) * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * s ** 2)))
                   for cx, cy, s, amp in bumps)

        normals = height_to_normals(dzdx, dzdy)
        p, q = cv.normals_to_gradients(normals)
        z0 = z - z.mean()

        for integrator in (cv.integrate_frankot_chellappa, cv.integrate_poisson_dct):
            rec = integrator(p, q)
            rec0 = rec - rec.mean()
            assert corr(z0, rec0) > 0.995
            assert rmse(z0, rec0) < 0.05

    def test_edge_clipped_bump_favors_dct(self):
        """Content whose value is nonzero right at the tile boundary (a cropped
        patch, not a seamless tile) is the realistic UDIM case: DCT/Neumann
        should stay accurate; FFT/periodic wraparound should degrade badly."""
        h, w, x, y = self.setup_grid()
        cx, cy, s, amp = 5.0, h * 0.5, 14.0, 1.2
        z = amp * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * s ** 2)))
        dzdx = amp * (-(x - cx) / s ** 2) * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * s ** 2)))
        dzdy = amp * (-(y - cy) / s ** 2) * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * s ** 2)))

        normals = height_to_normals(dzdx, dzdy)
        p, q = cv.normals_to_gradients(normals)
        z0 = z - z.mean()

        dct_rec = cv.integrate_poisson_dct(p, q)
        dct_rec0 = dct_rec - dct_rec.mean()
        fft_rec = cv.integrate_frankot_chellappa(p, q)
        fft_rec0 = fft_rec - fft_rec.mean()

        assert corr(z0, dct_rec0) > 0.999
        assert rmse(z0, dct_rec0) < 0.01
        assert rmse(z0, dct_rec0) < rmse(z0, fft_rec0)

    def test_full_pipeline_bit_depth_accuracy(self):
        """16-bit/float input should reconstruct a sharp feature almost exactly;
        8-bit input is expected to be measurably noisier for the same sharp
        feature (real quantization loss, not a bug) - this is why the README
        recommends >=16-bit or float source normal maps for best fidelity."""
        h, w, x, y = self.setup_grid()
        cx, cy, s, amp = w * 0.4, h * 0.6, 12.0, 1.0
        z = amp * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * s ** 2)))
        dzdx = amp * (-(x - cx) / s ** 2) * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * s ** 2)))
        dzdy = amp * (-(y - cy) / s ** 2) * np.exp(-(((x - cx) ** 2 + (y - cy) ** 2) / (2 * s ** 2)))
        normals = height_to_normals(dzdx, dzdy)
        img01 = normals * 0.5 + 0.5
        z0 = z - z.mean()

        img16 = np.clip(np.round(img01 * 65535), 0, 65535).astype(np.uint16).astype(np.float64) / 65535.0
        rec16 = cv.convert(img16, source_is_float=False, method="dct")
        rec16_0 = rec16 - rec16.mean()
        assert corr(z0, rec16_0) > 0.999
        assert rmse(z0, rec16_0) < 0.01

        img8 = np.clip(np.round(img01 * 255), 0, 255).astype(np.uint8).astype(np.float64) / 255.0
        rec8 = cv.convert(img8, source_is_float=False, method="dct")
        rec8_0 = rec8 - rec8.mean()
        assert corr(z0, rec8_0) > 0.9
        assert rmse(z0, rec8_0) < 0.1
        # the point of this test: quantify that 8-bit is meaningfully lossier than 16-bit
        assert rmse(z0, rec8_0) > rmse(z0, rec16_0)


class TestDecodeAndConvention:
    def test_unsigned_roundtrip(self):
        rng = np.random.default_rng(0)
        signed = rng.uniform(-1, 1, (4, 4, 3))
        encoded = signed * 0.5 + 0.5
        decoded = cv.decode_normals(encoded, was_float_source=False)
        assert np.allclose(decoded, signed, atol=1e-10)

    def test_signed_float_autodetect(self):
        rng = np.random.default_rng(0)
        signed = rng.uniform(-1, 1, (4, 4, 3))
        decoded = cv.decode_normals(signed, was_float_source=True)
        assert np.allclose(decoded, signed, atol=1e-10)

    def test_assume_signed_override(self):
        rng = np.random.default_rng(0)
        # values happen to look unsigned (all positive) but caller insists they're signed
        data = rng.uniform(0.1, 0.9, (4, 4, 3))
        decoded = cv.decode_normals(data, was_float_source=True, assume_signed=True)
        assert np.allclose(decoded, data)

    def test_directx_flips_green_only(self):
        n = np.zeros((1, 1, 3))
        n[..., 0] = 0.5
        n[..., 1] = -0.3
        n[..., 2] = 1.0
        flipped = cv.apply_convention(n, convention="directx")
        assert np.isclose(flipped[0, 0, 0], 0.5)
        assert np.isclose(flipped[0, 0, 1], 0.3)
        assert np.isclose(flipped[0, 0, 2], 1.0)

    def test_manual_flip_x_y(self):
        n = np.zeros((1, 1, 3))
        n[..., 0] = 0.5
        n[..., 1] = -0.3
        n[..., 2] = 1.0
        flipped = cv.apply_convention(n, convention="opengl", flip_x=True, flip_y=True)
        assert np.isclose(flipped[0, 0, 0], -0.5)
        assert np.isclose(flipped[0, 0, 1], 0.3)

    def test_rejects_bad_shape(self):
        with pytest.raises(cv.ConversionError):
            cv.decode_normals(np.zeros((4, 4)), was_float_source=False)


class TestOptions:
    def test_z_scale_is_linear(self):
        rng = np.random.default_rng(1)
        img = rng.uniform(0.3, 0.7, (16, 16, 3))
        img[..., 2] = 0.9  # keep nz safely positive
        base = cv.convert(img, source_is_float=True, method="dct", z_scale=1.0)
        scaled = cv.convert(img, source_is_float=True, method="dct", z_scale=2.0)
        ratio = np.std(scaled) / np.std(base)
        assert np.isclose(ratio, 2.0, atol=1e-6)

    def test_invert_height_negates(self):
        rng = np.random.default_rng(1)
        img = rng.uniform(0.3, 0.7, (16, 16, 3))
        img[..., 2] = 0.9
        z = cv.convert(img, source_is_float=True, method="dct", invert_height=False)
        z_inv = cv.convert(img, source_is_float=True, method="dct", invert_height=True)
        assert np.allclose(z, -z_inv, atol=1e-10)

    def test_max_slope_clamps(self):
        rng = np.random.default_rng(1)
        img = rng.uniform(0.0, 1.0, (16, 16, 3))
        img[..., 2] = 0.9
        unclamped = cv.convert(img, source_is_float=True, method="dct")
        clamped = cv.convert(img, source_is_float=True, method="dct", max_slope=0.05)
        assert not np.allclose(unclamped, clamped)

    def test_unknown_method_raises(self):
        img = np.zeros((4, 4, 3))
        img[..., 2] = 1.0
        with pytest.raises(cv.ConversionError):
            cv.convert(img, source_is_float=True, method="bogus")
