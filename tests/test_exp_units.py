"""Tests for model/exp_units.py against specs/exp_units.md (draft 3, 2026-11-13).

Written by the test agent from the spec text only; the implementation was not read.

The `spec_*` functions below are an independent re-implementation of the spec: deliberately simple
per-input loops on Python ints that follow the numbered steps literally.  The bit-exact tests require
the module to give identical codes; the property and accuracy tests check the promises of spec Section 3
(properties 1 and 6 at any setting, properties 2-5 at the default settings unless the spec states others).

Spec points the tests rely on (draft 3 settled the ambiguities A1-A7 and E1 of the draft-2 test report):
  * round(v) of a constant is floor(v + 1/2), in float64 (Section 1).  Exact ties can only occur for
    C = round(c 2^(W+P)); test_cordic_constant_round_half_up_on_tie probes it.
  * A rounding shift by 0 adds nothing: (v + 2^(s-1)) >> s with s = 0 is v (guard = 0, const_frac = 0).
  * C1 step 5: G is the product over the first m entries of the list (the iterations performed).
  * C1 shape (3.3): y(n2) <= y(n1) + 1 for all n1 < n2.
  * Accuracy range (3.5): n = 0 ... ceil((Fo+2) ln2 / c).
  * B2 (3.5): max|err| = max(1, 2^(k-1-g)); max|err| <= 1 is required for k = 1 ... 8 with guard = k - 1,
    and the formula itself is checked for (k, g) pairs where it is exact.  It is only an upper bound for
    g = 0, for g >= k, and when 2^(k-1-g) > 2^Fo (see the test report).
  * Section 3.6: n may have any shape (also 0-d and empty); the result has the same shape, dtype int64.
"""
import math
import sys

import numpy as np
import pytest

sys.path.insert(0, "/media/amir/CORDIC")
from model.exp_units import (  # noqa: E402
    bitprod_exp,
    cordic_exp,
    lut_exp,
    pow2_exp,
    ref_exp,
    shift_decay_trace,
)

LN2 = math.log(2.0)
LOG2E = math.log2(math.e)

# Section 3.5 grid
FO_GRID = list(range(4, 17))
C_SET = [1 / 40, 1 / 20, 1 / 16, 0.25 / 2 ** 4, 3 / 2 ** 8]
C_IDS = ["c=1/40", "c=1/20", "c=1/16", "c=0.25/2^4", "c=3/2^8"]
# extra constants for the bit-exact tests (not powers of two, small and large)
C_EXTRA = [0.0037, 0.0371, 0.2, 0.9, 1.7]
N_MAX = 2 ** 16 - 1  # largest input code used (b = 16)
INT_DTYPES = [np.int8, np.int16, np.int32, np.int64, np.uint8, np.uint16, np.uint32, np.uint64]


def n_top(fo, c):
    """Upper end of the Section 3.5 input range, ceil((Fo+2) ln2 / c)."""
    return math.ceil((fo + 2) * LN2 / c)


def bitexact_inputs(fo, c, seed, cap=2500, extra=150):
    """0 ... min(2 n_top + 20, cap) plus random codes up to 2^16 - 1 (sorted, unique)."""
    rng = np.random.default_rng(seed)
    top = min(2 * n_top(fo, c) + 20, cap)
    parts = [np.arange(0, top + 1), rng.integers(0, N_MAX + 1, size=extra), [N_MAX]]
    return np.unique(np.concatenate(parts)).astype(np.int64)


# ---------------------------------------------------------------------------------------------------
# Independent re-implementation of the spec
# ---------------------------------------------------------------------------------------------------

def rhu(v):
    """Spec round of a constant: round half up, floor(v + 1/2)."""
    return math.floor(v + 0.5)


def rhe(v):
    """Round half to even (Python round); only used to show that the tie test separates the two rules."""
    return round(v)


C1_GAIN_READING = "first_m"  # C1 step 5 (draft 3): G over the first m entries; "list" = the whole list
C_TIE_ROUND = rhu  # Section 1 (draft 3): constants are floor(v + 1/2)


def near_tie(v):
    """True if float v is so close to k + 1/2 that a float64 computed another way could round differently.

    An exact tie k + 1/2 with k odd is not flagged: half up, half even and half away from zero all give
    k + 1 (exact ties only occur for C = c 2^(W+P), which every implementation computes exactly).
    """
    gap = abs(v - math.floor(v) - 0.5)
    if gap == 0.0 and math.floor(v) % 2 == 1:
        return False
    return gap <= 256 * math.ulp(max(abs(v), 1.0))


def shr_round(v, s):
    """(v + 2^(s-1)) >> s; a rounding shift by 0 adds nothing (Section 1)."""
    return v if s == 0 else (v + (1 << (s - 1))) >> s


def clamp(y, fo):
    return min(max(y, 0), 1 << fo)


def my_ref(n, c, fo):
    """Spec Section 1 reference floor(2^Fo e^(-n c) + 1/2) in float64, own code (math.exp per input).

    Also returns a mask of numerically borderline inputs, where 2^Fo e^(-n c) is within 1e-9 of a
    half-integer, so that a float64 exp from another library (1-4 ulp apart) could round the other way.
    """
    v = np.array([(2.0 ** fo) * math.exp(-(float(k) * c)) for k in np.asarray(n).ravel().tolist()],
                 dtype=np.float64)
    if v.size == 0:
        return np.zeros(0, dtype=np.int64), np.zeros(0, dtype=bool)
    border = np.abs((v + 0.5) - np.round(v + 0.5)) < 1e-9
    return np.floor(v + 0.5).astype(np.int64), border


def cordic_indices(m):
    """C1 step 4: 1, 2, 3, 4, 4, 5, ..., 13, 13, 14, ..., 40, 40, ... (the first m entries)."""
    out, i = [], 1
    while len(out) < m:
        out.append(i)
        if i in (4, 13, 40):
            out.append(i)
        i += 1
    return out[:m]


def cordic_gain(m, reading):
    """C1 step 5, G = prod sqrt(1 - 2^(-2i)).

    reading="first_m" (draft 3): over the m entries actually used.  reading="list": over the whole list of
    step 4 (from i = 27 on the factor is exactly 1.0 in float64, so 80 entries is the whole list); kept only
    to name the other reading in a failure message.
    """
    g = 1.0
    for i in cordic_indices(80 if reading == "list" else m):
        g *= math.sqrt(1.0 - 2.0 ** (-2 * i))
    return g


def spec_cordic(n, c, fo, guard=3, iters=None, const_frac=16, gain=None, round_c=None):
    """C1 steps 1-7 on a 1-D array.  Returns (codes, raw float constants used)."""
    gain = C1_GAIN_READING if gain is None else gain
    round_c = C_TIE_ROUND if round_c is None else round_c
    W = fo + guard
    P = const_frac
    m = W + 1 if iters is None else iters
    idx = cordic_indices(m)
    raw = {"C": c * 2.0 ** (W + P), "L": LN2 * 2.0 ** W, "Y": 2.0 ** W / cordic_gain(m, gain)}
    for i in set(idx):
        raw["A%d" % i] = math.atanh(2.0 ** -i) * 2.0 ** W
    C, L, Y0 = round_c(raw["C"]), rhu(raw["L"]), rhu(raw["Y"])
    A = {i: rhu(raw["A%d" % i]) for i in set(idx)}
    out = []
    for v in np.asarray(n).tolist():
        Z = shr_round(v * C, P)  # (n C + 2^(P-1)) >> P
        q = Z // L
        r = Z - q * L
        if q > fo + 1:
            out.append(0)
            continue
        Y, z = Y0, -r
        for i in idx:
            d = 1 if z >= 0 else -1
            Y = Y + d * (Y >> i)
            z = z - d * A[i]
        out.append(clamp(shr_round(Y, q + guard), fo))
    return np.array(out, dtype=np.int64), raw


def spec_bitprod(n, c, fo, guard=3):
    """B3 steps 1-3 on a 1-D array.  Returns (codes, raw float constants used)."""
    W = fo + guard
    vals = np.asarray(n).tolist()
    b = max(1, int(max(vals)).bit_length())
    raw = {"K%d" % k: math.exp(-(2 ** k) * c) * 2.0 ** W for k in range(b)}
    K = [rhu(raw["K%d" % k]) for k in range(b)]
    out = []
    for v in vals:
        Y = 1 << W
        for k in range(b):
            if (v >> k) & 1:
                Y = (Y * K[k]) >> W
        out.append(clamp(shr_round(Y, guard), fo))
    return np.array(out, dtype=np.int64), raw


def spec_pow2(n, c, fo, guard=3, frac_bits=4, mode="table", const_frac=16):
    """B4 steps 1-3 on a 1-D array.  Returns (codes, raw float constants used)."""
    W = fo + guard
    F = frac_bits
    P = const_frac
    raw = {"Cu": c * LOG2E * 2.0 ** (F + P)}
    Cu = rhu(raw["Cu"])
    out = []
    for v in np.asarray(n).tolist():
        U = shr_round(v * Cu, P)  # (n Cu + 2^(P-1)) >> P
        q, f = U >> F, U % (1 << F)
        if q + guard > W + 1:
            out.append(0)
            continue
        if mode == "table":
            raw["T%d" % f] = 2.0 ** (-f / 2 ** F) * 2.0 ** W
            T = rhu(raw["T%d" % f])
        elif mode == "linear":
            T = (1 << W) - ((f << W) >> (F + 1))
        else:
            raise ValueError(mode)
        out.append(clamp(shr_round(T, q + guard), fo))
    return np.array(out, dtype=np.int64), raw


def spec_trace(k, steps, fo, guard=3, rounding="floor"):
    """B2: Y_0 = 2^W, then Y = Y - (Y >> k) or Y = Y - ((Y + 2^(k-1)) >> k); y_t = (Y_t + 2^(g-1)) >> g."""
    W = fo + guard
    Y = 1 << W
    out = [shr_round(Y, guard)]
    for _ in range(steps):
        if rounding == "floor":
            Y = Y - (Y >> k)
        elif rounding == "round":
            Y = Y - shr_round(Y, k)
        else:
            raise ValueError(rounding)
        out.append(shr_round(Y, guard))
    return np.array(out, dtype=np.int64)


def b2_max_err(y, k, fo, steps):
    """max |y_t - ref(t)| with c = c_eff = -ln(1 - 2^-k), t = 0 ... steps, and where it occurs."""
    c_eff = -math.log(1.0 - 2.0 ** -k)
    ref, _ = my_ref(np.arange(steps + 1), c_eff, fo)
    err = np.abs(np.asarray(y) - ref)
    i = int(np.argmax(err))
    return int(err[i]), i, ref


def b2_steps(k, fo):
    """Section 3.5 B2 length, ceil((Fo+2) ln2 / c_eff)."""
    return math.ceil((fo + 2) * LN2 / -math.log(1.0 - 2.0 ** -k))


# ---------------------------------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------------------------------

def check_int64_array(got, shape, what):
    assert isinstance(got, np.ndarray), "%s: returned %s, spec 3.6 says a numpy int64 array" % (what, type(got))
    assert got.dtype == np.int64, "%s: dtype %s, spec 3.6 says int64" % (what, got.dtype)
    assert got.shape == shape, "%s: shape %s, expected %s" % (what, got.shape, shape)


def check_no_near_tie(raw, what, skip=()):
    ties = {k: v for k, v in raw.items() if k not in skip and near_tie(v)}
    assert not ties, "test setting %s has float constants at a rounding tie %s; choose another setting" % (what, ties)


def mismatch_report(n, got, want, limit=6):
    bad = np.flatnonzero(got != want)
    first = ", ".join("n=%d: got %d, spec %d" % (n[i], got[i], want[i]) for i in bad[:limit])
    return "%d of %d codes differ (%s)" % (bad.size, len(n), first)


def assert_bit_exact(got, want, n, what):
    check_int64_array(got, want.shape, what)  # the module's own return value, not converted
    assert np.array_equal(got, want), "%s: %s" % (what, mismatch_report(n, got, want))


# ---------------------------------------------------------------------------------------------------
# Reference and B1
# ---------------------------------------------------------------------------------------------------

REF_FO = [1, 2, 4, 8, 12, 16, 20]


@pytest.mark.parametrize("c", C_SET + C_EXTRA)
def test_ref_exp_matches_independent_float64(c):
    """Section 1: ref(n) = floor(2^Fo e^(-n c) + 1/2) in float64, against my own float64 computation."""
    border_total = 0
    for fo in REF_FO:
        n = bitexact_inputs(fo, c, seed=fo, cap=6000, extra=300)
        want, border = my_ref(n, c, fo)
        got = ref_exp(n, c, fo)
        check_int64_array(got, n.shape, "ref_exp(Fo=%d, c=%g)" % (fo, c))
        hard = (got != want) & ~border
        assert not hard.any(), "ref_exp(Fo=%d, c=%g): %s" % (fo, c, mismatch_report(n[hard], got[hard], want[hard]))
        assert np.all(np.abs(got - want)[border] <= 1)
        assert got[0] == 2 ** fo  # n = 0
        border_total += int(border.sum())
    assert border_total <= 3, "too many borderline inputs (%d); the tolerance would hide errors" % border_total


@pytest.mark.parametrize("c", C_SET + C_EXTRA)
def test_lut_exp_equals_reference(c):
    """B1: y(n) = ref(n) for every n (exactly equal to the module's ref_exp, and to my own reference)."""
    for fo in REF_FO:
        n = bitexact_inputs(fo, c, seed=100 + fo, cap=6000, extra=300)
        got = lut_exp(n, c, fo)
        check_int64_array(got, n.shape, "lut_exp(Fo=%d, c=%g)" % (fo, c))
        mod_ref = ref_exp(n, c, fo)
        assert np.array_equal(got, mod_ref), "lut_exp != ref_exp (Fo=%d, c=%g): %s" % (
            fo, c, mismatch_report(n, got, mod_ref))
        want, border = my_ref(n, c, fo)
        hard = (got != want) & ~border
        assert not hard.any(), "lut_exp(Fo=%d, c=%g) vs own ref: %s" % (
            fo, c, mismatch_report(n[hard], got[hard], want[hard]))


# ---------------------------------------------------------------------------------------------------
# Section 3, properties 1-4.  Properties 2-4 at the default settings, over the Section 3.5 grid;
# property 1 also at non-default settings.
# ---------------------------------------------------------------------------------------------------

DEFAULT_UNITS = {
    "B1": lambda n, c, fo: lut_exp(n, c, fo),
    "C1": lambda n, c, fo: cordic_exp(n, c, fo),
    "B3": lambda n, c, fo: bitprod_exp(n, c, fo),
    "B4": lambda n, c, fo: pow2_exp(n, c, fo),
}
_OUT_CACHE = {}


def property_inputs(fo, c):
    """0 ... 2 n_top + 50 (covers the underflow region) and 200 random codes up to 2^16 - 1, sorted."""
    rng = np.random.default_rng(1000 * fo + int(1 / c))
    top = 2 * n_top(fo, c) + 50
    parts = [np.arange(0, top + 1), rng.integers(top, N_MAX + 1, size=200), [N_MAX]]
    return np.unique(np.concatenate(parts)).astype(np.int64)


def unit_out(unit, c, fo):
    key = (unit, c, fo)
    if key not in _OUT_CACHE:
        n = property_inputs(fo, c)
        y = DEFAULT_UNITS[unit](n, c, fo)
        check_int64_array(y, n.shape, "%s(Fo=%d, c=%g)" % (unit, fo, c))
        _OUT_CACHE[key] = (n, y)
    return _OUT_CACHE[key]


@pytest.mark.parametrize("c", C_SET, ids=C_IDS)
@pytest.mark.parametrize("unit", list(DEFAULT_UNITS))
def test_prop1_output_range(unit, c):
    """3.1: 0 <= y(n) <= 2^Fo for every input (default settings, Section 3.5 grid)."""
    bad = []
    for fo in FO_GRID:
        n, y = unit_out(unit, c, fo)
        if y.min() < 0 or y.max() > 2 ** fo:
            bad.append("Fo=%d: min %d max %d" % (fo, y.min(), y.max()))
    assert not bad, "%s %s outside [0, 2^Fo]: %s" % (unit, c, "; ".join(bad))


RANGE_SETTINGS = [
    # property 1 holds at any setting: non-default, small and edge settings (all parameters >= 0)
    ("B1", {}),
    ("C1", dict(guard=0)), ("C1", dict(guard=1, iters=1)), ("C1", dict(guard=2, iters=3)),
    ("C1", dict(iters=5, const_frac=0)), ("C1", dict(guard=5, iters=45, const_frac=20)), ("C1", dict(guard=1, const_frac=1)),
    ("B3", dict(guard=0)), ("B3", dict(guard=1)), ("B3", dict(guard=2)), ("B3", dict(guard=7)),
    ("B4", dict(guard=0, frac_bits=0)), ("B4", dict(guard=1, frac_bits=1, const_frac=0)), ("B4", dict(frac_bits=2, mode="linear")),
    ("B4", dict(guard=0, frac_bits=6, mode="linear", const_frac=1)), ("B4", dict(guard=5, frac_bits=12, const_frac=20)),
    ("B4", dict(frac_bits=17)), ("B4", dict(frac_bits=17, mode="linear")),
]
_RANGE_FN = {"B1": lut_exp, "C1": cordic_exp, "B3": bitprod_exp, "B4": pow2_exp}


@pytest.mark.parametrize("unit,kw", RANGE_SETTINGS)
def test_prop1_output_range_any_setting(unit, kw):
    """3.1 at non-default settings, Fo = 2, 4, 9, 16, every c, inputs up to 2^16 - 1."""
    for fo in (2, 4, 9, 16):
        for c in C_SET + C_EXTRA:
            n = property_inputs(fo, c)
            y = _RANGE_FN[unit](n, c, fo, **kw)
            what = "%s(Fo=%d, c=%g, %s)" % (unit, fo, c, kw)
            check_int64_array(y, n.shape, what)
            assert y.min() >= 0 and y.max() <= 2 ** fo, "%s: outputs from %d to %d" % (what, y.min(), y.max())


@pytest.mark.parametrize("c", C_SET, ids=C_IDS)
@pytest.mark.parametrize("unit", list(DEFAULT_UNITS))
def test_prop2_zero_input(unit, c):
    """3.2: y(0) = 2^Fo exactly for B1, B3, B4; within 1 LSB for C1 (default settings)."""
    tol = 1 if unit == "C1" else 0
    bad = []
    for fo in FO_GRID:
        y0 = int(DEFAULT_UNITS[unit](np.array([0], dtype=np.int64), c, fo)[0])
        if abs(y0 - 2 ** fo) > tol:
            bad.append("Fo=%d: y(0)=%d" % (fo, y0))
    assert not bad, "%s %s: %s" % (unit, c, "; ".join(bad))


@pytest.mark.parametrize("c", C_SET, ids=C_IDS)
@pytest.mark.parametrize("unit", list(DEFAULT_UNITS))
def test_prop3_non_increasing(unit, c):
    """3.3: y non-increasing in n for B1, B3, B4; for C1, y(n2) <= y(n1) + 1 for all n1 < n2 (default settings)."""
    allowed = 1 if unit == "C1" else 0
    bad = []
    for fo in FO_GRID:
        n, y = unit_out(unit, c, fo)
        runmin = np.minimum.accumulate(y)
        rise = y[1:] - runmin[:-1]
        if rise.max() > allowed:
            i = int(np.argmax(rise)) + 1
            bad.append("Fo=%d: y(%d)=%d is %d above an earlier output" % (fo, n[i], y[i], rise.max()))
    assert not bad, "%s %s: %s" % (unit, c, "; ".join(bad))


@pytest.mark.parametrize("c", C_SET, ids=C_IDS)
@pytest.mark.parametrize("unit", ["C1", "B3", "B4"])
def test_prop4_underflow_to_zero(unit, c):
    """3.4: y(n) = 0 whenever e^(-n c) < 2^-(Fo+2) for C1, B3, B4 (default settings)."""
    bad = []
    for fo in FO_GRID:
        n, y = unit_out(unit, c, fo)
        small = np.exp(-n.astype(np.float64) * c) < 2.0 ** -(fo + 2) * (1 - 1e-12)
        assert small.sum() > 100  # the input set reaches well into the underflow region
        nz = np.flatnonzero(small & (y != 0))
        if nz.size:
            bad.append("Fo=%d: %d nonzero, e.g. y(%d)=%d" % (fo, nz.size, n[nz[0]], y[nz[0]]))
    assert not bad, "%s %s: %s" % (unit, c, "; ".join(bad))


@pytest.mark.parametrize("rounding", ["floor", "round"])
def test_prop1_b2_range_any_setting(rounding):
    """3.1 for B2 at any setting: 0 <= y_t <= 2^Fo, for k = 1 ... 12 and guard 0 ... 8."""
    for k in (1, 2, 3, 4, 5, 6, 7, 9, 12):
        for fo in (2, 4, 8, 12, 16):
            for g in (0, 1, 3, 5, 8):
                steps = min(4 * 2 ** k * (fo + 2), 4000)
                y = shift_decay_trace(k, steps, fo, guard=g, rounding=rounding)
                what = "B2 k=%d Fo=%d guard=%d %s" % (k, fo, g, rounding)
                check_int64_array(y, (steps + 1,), what)
                assert y.min() >= 0 and y.max() <= 2 ** fo, what


def test_prop2_prop3_b2_default_settings():
    """3.2 and 3.3 for B2 at the default settings (guard 3, rounding "floor"): y_0 = 2^Fo, non-increasing in t."""
    for k in range(1, 13):
        for fo in FO_GRID:
            steps = min(4 * 2 ** k * (fo + 2), 4000)
            y = shift_decay_trace(k, steps, fo)
            what = "B2 k=%d Fo=%d" % (k, fo)
            check_int64_array(y, (steps + 1,), what)
            assert y[0] == 2 ** fo, what
            assert np.all(np.diff(y) <= 0), what


# ---------------------------------------------------------------------------------------------------
# Section 3.5, accuracy
# ---------------------------------------------------------------------------------------------------

ACC_UNITS = {
    "C1": (lambda n, c, fo: cordic_exp(n, c, fo), lambda n, c, fo: spec_cordic(n, c, fo)[0]),
    "B3": (lambda n, c, fo: bitprod_exp(n, c, fo), lambda n, c, fo: spec_bitprod(n, c, fo)[0]),
    "B4-table-F=Fo+1": (lambda n, c, fo: pow2_exp(n, c, fo, frac_bits=fo + 1),
                        lambda n, c, fo: spec_pow2(n, c, fo, frac_bits=fo + 1)[0]),
    "B4-table-F=Fo+2": (lambda n, c, fo: pow2_exp(n, c, fo, frac_bits=fo + 2),
                        lambda n, c, fo: spec_pow2(n, c, fo, frac_bits=fo + 2)[0]),
    "B4-table-F=Fo+3": (lambda n, c, fo: pow2_exp(n, c, fo, frac_bits=fo + 3),
                        lambda n, c, fo: spec_pow2(n, c, fo, frac_bits=fo + 3)[0]),
}


@pytest.mark.parametrize("c", C_SET, ids=C_IDS)
@pytest.mark.parametrize("unit", list(ACC_UNITS))
def test_accuracy_default_settings(unit, c):
    """3.5: max |err| <= 1 for C1, B3 and B4 table (frac_bits >= Fo + 1), n = 0 ... ceil((Fo+2) ln2 / c)."""
    module_fn, spec_fn = ACC_UNITS[unit]
    bad = []
    for fo in FO_GRID:
        n = np.arange(0, n_top(fo, c) + 1, dtype=np.int64)
        y = np.asarray(module_fn(n, c, fo))
        ref, _ = my_ref(n, c, fo)
        err = np.abs(y - ref)
        if err.max() > 1:
            i = int(np.argmax(err))
            spec_err = int(np.abs(spec_fn(n, c, fo) - ref).max())
            bad.append("Fo=%d: max|err|=%d at n=%d (y=%d, ref=%d); spec re-implementation max|err|=%d"
                       % (fo, err.max(), n[i], y[i], ref[i], spec_err))
    assert not bad, "%s %s: %s" % (unit, c, "; ".join(bad))


@pytest.mark.parametrize("k", range(1, 9))
def test_accuracy_b2_round_guard_k_minus_1(k):
    """3.5: B2, rounding="round", guard = k - 1: max |err| <= 1 against ref(t) with c_eff = -ln(1 - 2^-k),
    t = 0 ... ceil((Fo+2) ln2 / c_eff), Fo = 4 ... 16."""
    g = k - 1
    bad = []
    for fo in FO_GRID:
        steps = b2_steps(k, fo)
        y = shift_decay_trace(k, steps, fo, guard=g, rounding="round")
        check_int64_array(y, (steps + 1,), "B2 k=%d guard=%d Fo=%d" % (k, g, fo))
        e, t, ref = b2_max_err(y, k, fo, steps)
        if e > 1:
            spec_e = b2_max_err(spec_trace(k, steps, fo, g, "round"), k, fo, steps)[0]
            bad.append("Fo=%d: max|err|=%d at t=%d (y=%d, ref=%d); spec re-implementation max|err|=%d"
                       % (fo, e, t, y[t], ref[t], spec_e))
    assert not bad, "B2 k=%d guard=%d: %s" % (k, g, "; ".join(bad))


# (k, g) pairs with 1 <= g <= k - 1 and 2^(k-1-g) <= 2^4, where max|err| = max(1, 2^(k-1-g)) holds exactly
# at every Fo = 4 ... 16; they include the default guard 3 for k = 4 ... 8
B2_FORMULA_PAIRS = [(3, 1), (4, 2), (4, 3), (5, 3), (6, 2), (6, 3), (6, 5), (7, 3), (8, 3), (8, 5)]


@pytest.mark.parametrize("k,g", B2_FORMULA_PAIRS)
def test_b2_error_formula(k, g):
    """3.5: B2, rounding="round": max |err| = max(1, 2^(k-1-g)) exactly, for each Fo = 4 ... 16."""
    want = max(1, 2 ** (k - 1 - g))
    bad = []
    for fo in FO_GRID:
        steps = b2_steps(k, fo)
        y = shift_decay_trace(k, steps, fo, guard=g, rounding="round")
        e, t, _ = b2_max_err(y, k, fo, steps)
        if e != want:
            spec_e = b2_max_err(spec_trace(k, steps, fo, g, "round"), k, fo, steps)[0]
            bad.append("Fo=%d: max|err|=%d (t=%d); spec re-implementation max|err|=%d" % (fo, e, t, spec_e))
    assert not bad, "B2 k=%d guard=%d, formula %d: %s" % (k, g, want, "; ".join(bad))


# ---------------------------------------------------------------------------------------------------
# Bit-exactness against the spec re-implementation
# ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("c", C_SET + C_EXTRA)
def test_cordic_bit_exact_defaults(c):
    """C1 at default guard / iters / const_frac (call without keywords), Fo = 4 ... 16."""
    for fo in FO_GRID:
        n = bitexact_inputs(fo, c, seed=fo)
        want, raw = spec_cordic(n, c, fo)
        check_no_near_tie(raw, "C1 Fo=%d c=%g" % (fo, c))
        assert_bit_exact(cordic_exp(n, c, fo), want, n, "cordic_exp(Fo=%d, c=%g)" % (fo, c))


CORDIC_SETTINGS = [
    # (fo, guard, c, iters, const_frac); includes the repeats of 4 and 13 (m = 14, 15, 16) and of 40 (m = 45)
    (4, 1, 1 / 40, None, 16), (4, 2, 3 / 2 ** 8, 15, 8), (5, 4, 0.2, None, 4), (6, 3, 0.9, 20, 16),
    (7, 6, 1 / 16, None, 20), (8, 2, 0.0371, 16, 12), (9, 3, 1 / 20, 45, 16), (10, 1, 0.0037, None, 16),
    (11, 5, 1.7, 18, 8), (12, 3, 0.25 / 2 ** 4, 24, 4), (12, 3, 1 / 40, 14, 16), (12, 3, 1 / 40, 15, 16),
    (13, 4, 1 / 40, None, 12), (14, 2, 0.2, 30, 20), (15, 3, 0.0371, 22, 16), (16, 3, 1 / 16, 17, 16),
    (16, 6, 3 / 2 ** 8, None, 8), (16, 1, 0.9, 22, 20), (16, 5, 0.0037, 21, 1), (6, 2, 1 / 20, 15, 2),
]


@pytest.mark.parametrize("fo,guard,c,iters,const_frac", CORDIC_SETTINGS)
def test_cordic_bit_exact_settings(fo, guard, c, iters, const_frac):
    """C1 at non-default guard / iters / const_frac (keywords)."""
    n = bitexact_inputs(fo, c, seed=fo * 31 + guard)
    want, raw = spec_cordic(n, c, fo, guard, iters, const_frac)
    what = "cordic_exp(Fo=%d, guard=%d, c=%g, iters=%s, const_frac=%d)" % (fo, guard, c, iters, const_frac)
    check_no_near_tie(raw, what)
    got = cordic_exp(n, c, fo, guard=guard, iters=iters, const_frac=const_frac)
    assert_bit_exact(got, want, n, what)


CORDIC_SMALL_ITERS = [
    (4, 3, 1 / 20, 4, 16), (4, 3, 1 / 20, 5, 16), (8, 3, 1 / 40, 3, 16), (8, 3, 0.2, 6, 16),
    (10, 3, 0.0371, 8, 16), (13, 3, 3 / 2 ** 8, 9, 16), (16, 3, 1 / 16, 9, 16), (16, 2, 0.9, 10, 8),
    (12, 4, 1 / 40, 1, 16), (12, 4, 1 / 40, 2, 16), (9, 3, 1 / 16, 12, 16),
]


@pytest.mark.parametrize("fo,guard,c,iters,const_frac", CORDIC_SMALL_ITERS)
def test_cordic_bit_exact_small_iters(fo, guard, c, iters, const_frac):
    """C1 with few iterations, where G over the first m entries (step 5, draft 3) differs from G over the whole
    list.  The failure message says whether the module follows the other reading instead."""
    other = "first_m" if C1_GAIN_READING == "list" else "list"
    n = bitexact_inputs(fo, c, seed=fo * 7 + iters)
    want, raw = spec_cordic(n, c, fo, guard, iters, const_frac, gain=C1_GAIN_READING)
    alt, _ = spec_cordic(n, c, fo, guard, iters, const_frac, gain=other)
    what = "cordic_exp(Fo=%d, guard=%d, c=%g, iters=%d, const_frac=%d)" % (fo, guard, c, iters, const_frac)
    check_no_near_tie(raw, what)
    got = cordic_exp(n, c, fo, guard=guard, iters=iters, const_frac=const_frac)
    check_int64_array(got, n.shape, what)
    assert np.array_equal(got, want), "%s, G reading %r: %s [matches reading %r: %s]" % (
        what, C1_GAIN_READING, mismatch_report(n, got, want), other, np.array_equal(got, alt))


@pytest.mark.parametrize("c", C_SET + C_EXTRA)
def test_bitprod_bit_exact(c):
    """B3 at default guard (call without keyword) over Fo = 4 ... 16, and at guard 1, 2, 5, 8."""
    for fo in FO_GRID:
        n = bitexact_inputs(fo, c, seed=fo + 50, cap=2000, extra=100)
        want, raw = spec_bitprod(n, c, fo)
        check_no_near_tie(raw, "B3 Fo=%d c=%g" % (fo, c))
        assert_bit_exact(bitprod_exp(n, c, fo), want, n, "bitprod_exp(Fo=%d, c=%g)" % (fo, c))
    for fo, guard in [(4, 1), (6, 2), (9, 5), (12, 8), (16, 1), (16, 5)]:
        n = bitexact_inputs(fo, c, seed=fo + guard, cap=2000, extra=100)
        want, raw = spec_bitprod(n, c, fo, guard)
        check_no_near_tie(raw, "B3 Fo=%d guard=%d c=%g" % (fo, guard, c))
        assert_bit_exact(bitprod_exp(n, c, fo, guard=guard), want, n,
                         "bitprod_exp(Fo=%d, guard=%d, c=%g)" % (fo, guard, c))


@pytest.mark.parametrize("c", C_SET + C_EXTRA)
def test_pow2_bit_exact_defaults(c):
    """B4 at default guard / frac_bits / mode / const_frac (call without keywords), Fo = 4 ... 16."""
    for fo in FO_GRID:
        n = bitexact_inputs(fo, c, seed=fo + 70)
        want, raw = spec_pow2(n, c, fo)
        check_no_near_tie(raw, "B4 Fo=%d c=%g" % (fo, c))
        assert_bit_exact(pow2_exp(n, c, fo), want, n, "pow2_exp(Fo=%d, c=%g)" % (fo, c))


POW2_SETTINGS = [
    # (fo, guard, frac_bits, const_frac)
    (4, 3, 5, 16), (4, 1, 1, 16), (5, 2, 3, 8), (6, 3, 7, 12), (8, 3, 9, 16), (8, 5, 2, 20),
    (10, 1, 11, 16), (10, 3, 6, 4), (12, 3, 13, 16), (12, 2, 8, 1), (14, 4, 15, 20), (16, 3, 17, 16),
    (16, 3, 19, 16), (16, 6, 10, 8), (16, 1, 5, 2),
]


@pytest.mark.parametrize("mode", ["table", "linear"])
@pytest.mark.parametrize("fo,guard,frac_bits,const_frac", POW2_SETTINGS)
def test_pow2_bit_exact_settings(fo, guard, frac_bits, const_frac, mode):
    """B4 at non-default guard / frac_bits / const_frac, both modes (keywords), all c."""
    for c in C_SET + C_EXTRA:
        n = bitexact_inputs(fo, c, seed=fo * 13 + frac_bits, cap=2000, extra=100)
        want, raw = spec_pow2(n, c, fo, guard, frac_bits, mode, const_frac)
        what = "pow2_exp(Fo=%d, c=%g, guard=%d, frac_bits=%d, mode=%s, const_frac=%d)" % (
            fo, c, guard, frac_bits, mode, const_frac)
        check_no_near_tie(raw, what)
        got = pow2_exp(n, c, fo, guard=guard, frac_bits=frac_bits, mode=mode, const_frac=const_frac)
        assert_bit_exact(got, want, n, what)


@pytest.mark.parametrize("rounding", ["floor", "round"])
def test_shift_decay_trace_bit_exact(rounding):
    """B2 recurrence and output rounding, against my own loop, several k / Fo / guard."""
    for k in (1, 2, 3, 4, 5, 6, 7, 9, 12):
        for fo in (4, 7, 10, 13, 16):
            for g in (1, 2, 3, 6):
                steps = min(b2_steps(k, fo) + 50, 3000)
                want = spec_trace(k, steps, fo, g, rounding)
                got = shift_decay_trace(k=k, steps=steps, fo=fo, guard=g, rounding=rounding)
                assert_bit_exact(got, want, np.arange(steps + 1),
                                 "shift_decay_trace(k=%d, steps=%d, Fo=%d, guard=%d, %s)" % (k, steps, fo, g, rounding))


def test_shift_decay_trace_defaults():
    """B2 defaults guard=3, rounding="floor"; steps=0 returns only y_0."""
    for k in (2, 4, 6):
        for fo in (4, 8, 16):
            want = spec_trace(k, 500, fo, 3, "floor")
            assert_bit_exact(shift_decay_trace(k, 500, fo), want, np.arange(501),
                             "shift_decay_trace(%d, 500, %d)" % (k, fo))
            y = shift_decay_trace(k, 0, fo)
            check_int64_array(y, (1,), "shift_decay_trace(steps=0)")
            assert y[0] == 2 ** fo


EDGE_SETTINGS = [
    # guard = 0, const_frac = 0, frac_bits = 0 (Section 1: parameters >= 0, a rounding shift by 0 adds nothing)
    ("C1", dict(guard=0)), ("C1", dict(const_frac=0)), ("C1", dict(guard=0, const_frac=0, iters=20)),
    ("B3", dict(guard=0)),
    ("B4", dict(guard=0)), ("B4", dict(const_frac=0, frac_bits=8)), ("B4", dict(guard=0, mode="linear", frac_bits=6)),
    ("B4", dict(frac_bits=0)), ("B4", dict(frac_bits=0, mode="linear")), ("B4", dict(const_frac=0, mode="linear")),
]


@pytest.mark.parametrize("unit,kw", EDGE_SETTINGS)
def test_edge_parameters_bit_exact(unit, kw):
    """guard = 0, const_frac = 0 and frac_bits = 0."""
    fn, spec = {"C1": (cordic_exp, spec_cordic), "B3": (bitprod_exp, spec_bitprod), "B4": (pow2_exp, spec_pow2)}[unit]
    for fo in (4, 8, 12, 16):
        for c in C_SET + [0.2, 0.9]:
            n = bitexact_inputs(fo, c, seed=fo, cap=1500, extra=100)
            want, raw = spec(n, c, fo, **kw)
            what = "%s Fo=%d c=%g %s" % (unit, fo, c, kw)
            check_no_near_tie(raw, what)
            assert_bit_exact(fn(n, c, fo, **kw), want, n, what)


def test_shift_decay_trace_guard0():
    for rounding in ("floor", "round"):
        for k in (1, 3, 5):
            want = spec_trace(k, 300, 8, 0, rounding)
            assert_bit_exact(shift_decay_trace(k, 300, 8, guard=0, rounding=rounding), want, np.arange(301),
                             "shift_decay_trace(k=%d, guard=0, %s)" % (k, rounding))


def test_cordic_constant_round_half_up_on_tie():
    """C = round(c 2^(W+P)) when c 2^(W+P) is exactly k + 1/2 (k even): Section 1 (draft 3) says floor(v + 1/2).

    Exact ties are only possible for C (c with exactly W+P+1 fraction bits).
    """
    other_rule = rhe if C_TIE_ROUND is rhu else rhu
    cases = []
    for fo, guard, P in [(8, 3, 4), (6, 3, 2), (10, 2, 6)]:
        W = fo + guard
        k = int(0.03 * 2 ** (W + P)) // 2 * 2  # even
        c = (k + 0.5) / 2 ** (W + P)
        assert c * 2.0 ** (W + P) == k + 0.5
        cases.append((fo, guard, P, c))
    for fo, guard, P, c in cases:
        n = np.arange(0, 2 * n_top(fo, c) + 1, dtype=np.int64)
        want, raw = spec_cordic(n, c, fo, guard, None, P)
        check_no_near_tie(raw, "tie case", skip=("C",))
        other, _ = spec_cordic(n, c, fo, guard, None, P, round_c=other_rule)
        assert not np.array_equal(want, other)  # the case does tell the two rounding rules apart
        got = cordic_exp(n, c, fo, guard=guard, const_frac=P)
        check_int64_array(got, n.shape, "cordic_exp tie case")
        assert np.array_equal(got, want), "Fo=%d guard=%d P=%d c=%r, C rounded %s: %s [matches %s: %s]" % (
            fo, guard, P, c, C_TIE_ROUND.__name__, mismatch_report(n, got, want), other_rule.__name__,
            np.array_equal(got, other))


# ---------------------------------------------------------------------------------------------------
# Section 3.6, arguments (any setting)
# ---------------------------------------------------------------------------------------------------

def test_signature_ref_and_lut():
    n = np.arange(0, 300, dtype=np.int64)
    for f in (ref_exp, lut_exp):
        a = f(n=n, c=1 / 20, fo=8)
        b = f(n, 1 / 20, 8)
        check_int64_array(a, n.shape, f.__name__)
        assert np.array_equal(a, b)


def test_signature_cordic_exp():
    n = np.arange(0, 400, dtype=np.int64)
    kw = cordic_exp(n=n, c=1 / 20, fo=8, guard=3, iters=None, const_frac=16)
    pos = cordic_exp(n, 1 / 20, 8, 3, None, 16)
    dflt = cordic_exp(n, 1 / 20, 8)
    explicit_m = cordic_exp(n, 1 / 20, 8, iters=8 + 3 + 1)  # default m = Fo + g + 1
    for y in (kw, pos, dflt, explicit_m):
        check_int64_array(y, n.shape, "cordic_exp")
        assert np.array_equal(y, kw)
    kw2 = cordic_exp(n=n, c=1 / 20, fo=8, guard=2, iters=9, const_frac=8)
    pos2 = cordic_exp(n, 1 / 20, 8, 2, 9, 8)
    assert np.array_equal(kw2, pos2)


def test_signature_bitprod_exp():
    n = np.arange(0, 400, dtype=np.int64)
    kw = bitprod_exp(n=n, c=1 / 20, fo=8, guard=3)
    for y in (kw, bitprod_exp(n, 1 / 20, 8, 3), bitprod_exp(n, 1 / 20, 8)):
        check_int64_array(y, n.shape, "bitprod_exp")
        assert np.array_equal(y, kw)
    assert np.array_equal(bitprod_exp(n=n, c=1 / 20, fo=8, guard=5), bitprod_exp(n, 1 / 20, 8, 5))


def test_signature_pow2_exp():
    n = np.arange(0, 400, dtype=np.int64)
    kw = pow2_exp(n=n, c=1 / 20, fo=8, guard=3, frac_bits=4, mode="table", const_frac=16)
    for y in (kw, pow2_exp(n, 1 / 20, 8, 3, 4, "table", 16), pow2_exp(n, 1 / 20, 8)):
        check_int64_array(y, n.shape, "pow2_exp")
        assert np.array_equal(y, kw)
    kw2 = pow2_exp(n=n, c=1 / 20, fo=8, guard=2, frac_bits=7, mode="linear", const_frac=10)
    assert np.array_equal(kw2, pow2_exp(n, 1 / 20, 8, 2, 7, "linear", 10))


def test_signature_shift_decay_trace():
    kw = shift_decay_trace(k=5, steps=200, fo=8, guard=3, rounding="floor")
    for y in (kw, shift_decay_trace(5, 200, 8, 3, "floor"), shift_decay_trace(5, 200, 8)):
        check_int64_array(y, (201,), "shift_decay_trace")
        assert np.array_equal(y, kw)
    kw2 = shift_decay_trace(k=5, steps=200, fo=8, guard=2, rounding="round")
    assert np.array_equal(kw2, shift_decay_trace(5, 200, 8, 2, "round"))


@pytest.mark.parametrize("dtype", INT_DTYPES, ids=lambda d: np.dtype(d).name)
def test_integer_dtypes_in_int64_out(dtype):
    """3.6: every numpy integer dtype is accepted for n; the result is int64 and equals the spec result."""
    hi = min(int(np.iinfo(dtype).max), 500)
    n64 = np.arange(0, hi + 1, dtype=np.int64)
    n = n64.astype(dtype)
    c, fo = 1 / 16, 10
    calls = {
        "ref_exp": lambda v: ref_exp(v, c, fo),
        "lut_exp": lambda v: lut_exp(v, c, fo),
        "cordic_exp": lambda v: cordic_exp(v, c, fo),
        "bitprod_exp": lambda v: bitprod_exp(v, c, fo),
        "pow2_exp table": lambda v: pow2_exp(v, c, fo, frac_bits=11),
        "pow2_exp linear": lambda v: pow2_exp(v, c, fo, frac_bits=6, mode="linear"),
    }
    spec = {
        "cordic_exp": spec_cordic(n64, c, fo)[0],
        "bitprod_exp": spec_bitprod(n64, c, fo)[0],
        "pow2_exp table": spec_pow2(n64, c, fo, frac_bits=11)[0],
        "pow2_exp linear": spec_pow2(n64, c, fo, frac_bits=6, mode="linear")[0],
    }
    for name, f in calls.items():
        got = f(n)
        check_int64_array(got, n.shape, "%s(%s input)" % (name, np.dtype(dtype).name))
        want = spec[name] if name in spec else f(n64)
        assert np.array_equal(got, want), "%s with %s input: %s" % (
            name, np.dtype(dtype).name, mismatch_report(n64, got, want))


# functions at a mix of default and non-default settings, and the spec result for a flat int64 input
SHAPE_FUNCS = {
    "ref_exp": (lambda v: ref_exp(v, 1 / 20, 9), None),
    "lut_exp": (lambda v: lut_exp(v, 1 / 20, 9), None),
    "cordic_exp": (lambda v: cordic_exp(v, 1 / 20, 9, guard=2, iters=9, const_frac=8),
                   lambda v: spec_cordic(v, 1 / 20, 9, 2, 9, 8)[0]),
    "bitprod_exp": (lambda v: bitprod_exp(v, 1 / 20, 9), lambda v: spec_bitprod(v, 1 / 20, 9)[0]),
    "pow2_exp table": (lambda v: pow2_exp(v, 1 / 20, 9, frac_bits=10), lambda v: spec_pow2(v, 1 / 20, 9, frac_bits=10)[0]),
    "pow2_exp linear": (lambda v: pow2_exp(v, 1 / 20, 9, guard=2, frac_bits=6, mode="linear", const_frac=12),
                        lambda v: spec_pow2(v, 1 / 20, 9, 2, 6, "linear", 12)[0]),
}


@pytest.mark.parametrize("name", list(SHAPE_FUNCS))
def test_any_shape_same_shape_out(name):
    """3.6: n of any shape (also transposed and strided views) gives an int64 array of the same shape,
    element by element equal to the result for the flattened input."""
    f, spec = SHAPE_FUNCS[name]
    rng = np.random.default_rng(5)
    base = rng.integers(0, 500, size=(4, 6))
    cases = {
        "(1,)": base[0, :1], "(7,)": rng.integers(0, 500, size=7), "(3,4)": base[:3, :4],
        "(2,3,4)": rng.integers(0, 500, size=(2, 3, 4)), "(4,1)": base[:, :1], "(1,1,5)": rng.integers(0, 500, size=(1, 1, 5)),
        "transposed (6,4)": base.T, "strided (4,3)": base[:, ::2], "reversed (4,6)": base[::-1],
    }
    for label, n in cases.items():
        got = f(n)
        check_int64_array(got, n.shape, "%s(%s)" % (name, label))
        flat = np.ascontiguousarray(n).ravel()
        want = spec(flat) if spec is not None else f(flat)
        assert np.array_equal(got.ravel(), want), "%s(%s): %s" % (name, label, mismatch_report(flat, got.ravel(), want))


@pytest.mark.parametrize("name", list(SHAPE_FUNCS))
def test_empty_input_gives_empty_array(name):
    """3.6: an empty n returns an empty int64 array of the same shape (B3 included, where n.max() is undefined)."""
    f, _ = SHAPE_FUNCS[name]
    for n in (np.array([], dtype=np.int64), np.zeros((0, 3), dtype=np.int64), np.array([], dtype=np.uint16)):
        check_int64_array(f(n), n.shape, "%s(empty, shape %s, %s)" % (name, n.shape, n.dtype))


@pytest.mark.parametrize("name", list(SHAPE_FUNCS))
def test_zero_dim_input(name):
    """3.6, any shape includes the 0-d array (shape ()): the result is a 0-d int64 array (not a numpy scalar)."""
    f, _ = SHAPE_FUNCS[name]
    for v in (0, 37, 450):
        got = f(np.array(v, dtype=np.int64))
        check_int64_array(got, (), "%s(0-d array %d)" % (name, v))
        assert int(got) == int(f(np.array([v], dtype=np.int64))[0])


@pytest.mark.parametrize("dtype", INT_DTYPES, ids=lambda d: np.dtype(d).name)
def test_shift_decay_trace_numpy_scalars(dtype):
    """3.6: B2 takes Python or numpy integer scalars (k, steps, fo, guard of any integer type)."""
    for k, steps, fo, g in [(1, 30, 4, 0), (4, 100, 8, 3), (6, 120, 16, 5)]:
        for rounding in ("floor", "round"):
            got = shift_decay_trace(dtype(k), dtype(steps), dtype(fo), guard=dtype(g), rounding=rounding)
            assert_bit_exact(got, spec_trace(k, steps, fo, g, rounding), np.arange(steps + 1),
                             "shift_decay_trace(%s scalars k=%d steps=%d fo=%d guard=%d, %s)"
                             % (np.dtype(dtype).name, k, steps, fo, g, rounding))


def test_bitprod_batch_independent_and_all_zero():
    """B3: b comes from the largest n of the call, but bits above it are 0, so a code's output must not
    depend on the other codes in the call; an all-zero call (b = max(1, 0) = 1) gives 2^Fo."""
    c, fo = 1 / 40, 10
    n = np.array([0, 1, 2, 3, 5, 77, 255, 256, 1000, 4095, 65535], dtype=np.int64)
    batch = bitprod_exp(n, c, fo)
    single = np.array([bitprod_exp(np.array([v], dtype=np.int64), c, fo)[0] for v in n])
    assert np.array_equal(batch, single)
    z = bitprod_exp(np.zeros(5, dtype=np.int64), c, fo)
    check_int64_array(z, (5,), "bitprod_exp(zeros)")
    assert np.all(z == 2 ** fo)
