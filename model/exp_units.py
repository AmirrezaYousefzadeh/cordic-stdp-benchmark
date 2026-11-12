"""Bit-accurate integer models of the exponential units, batch 1 (specs/exp_units.md).

Every function computes y = e^(-n*c) for an integer input code n, with an output code y in [0, 2^fo] (value y/2^fo).
All arithmetic after the constants are formed is integer (numpy int64); right shifts are floor shifts unless the spec
says "round". These models are the golden reference for the RTL: the Verilog must match them bit for bit.
"""
import math

import numpy as np

_REPEATS = (4, 13, 40)


def _as_int(n):
    return np.asarray(n, dtype=np.int64)


def _rnd(v):
    """round(v) of a constant as the spec defines it: floor(v + 1/2), half up."""
    return int(math.floor(v + 0.5))


def _round_shift(Y, sh):
    """(Y + 2^(sh-1)) >> sh elementwise; sh may be an array; sh == 0 means no shift and no rounding."""
    Y = np.asarray(Y, dtype=np.int64)
    sh = np.broadcast_to(np.asarray(sh, dtype=np.int64), Y.shape)
    half = np.where(sh > 0, np.left_shift(np.int64(1), np.maximum(sh - 1, 0)), 0)
    return np.right_shift(Y + half, sh)


def _clamp(y, fo):
    return np.clip(y, 0, 1 << fo).astype(np.int64)


def _out(y, shape):
    """Always an int64 ndarray of the input's shape (also for 0-d input)."""
    return np.asarray(y, dtype=np.int64).reshape(shape)


def ref_exp(n, c, fo):
    """floor(2^fo * e^(-n c) + 1/2) in float64."""
    n = _as_int(n)
    return _out(np.floor(np.exp(-n.astype(np.float64) * c) * float(1 << fo) + 0.5), n.shape)


def lut_exp(n, c, fo):
    """B1: a table of ref values indexed by n."""
    n = _as_int(n)
    if n.size == 0:
        return n.copy()
    table = ref_exp(np.arange(int(n.max()) + 1), c, fo)
    return _out(table[n], n.shape)


def cordic_indices(m):
    """First m iteration indices of hyperbolic CORDIC: 1, 2, 3, 4, 4, 5, ..., 13, 13, ..., 40, 40, ..."""
    out = []
    i = 1
    while len(out) < m:
        out.append(i)
        if i in _REPEATS and len(out) < m:
            out.append(i)
        i += 1
    return out


def cordic_constants(c, fo, guard=3, iters=None, const_frac=16):
    W = fo + guard
    m = fo + guard + 1 if iters is None else iters
    idx = cordic_indices(m)
    G = 1.0
    for i in idx:
        G *= math.sqrt(1.0 - 2.0 ** (-2 * i))
    return {
        "W": W, "m": m, "idx": idx,
        "P": const_frac, "C": _rnd(c * 2 ** (W + const_frac)), "L": _rnd(math.log(2.0) * 2 ** W),
        "Y0": _rnd(2 ** W / G), "A": [_rnd(math.atanh(2.0 ** -i) * 2 ** W) for i in idx],
    }


def cordic_exp(n, c, fo, guard=3, iters=None, const_frac=16):
    """C1: hyperbolic CORDIC in rotation mode, one datapath (x = y), with range reduction by ln 2."""
    n = _as_int(n)
    k = cordic_constants(c, fo, guard, iters, const_frac)
    Z = _round_shift(n * k["C"], const_frac)
    q = Z // k["L"]
    r = Z - q * k["L"]
    Y = np.full(n.shape, k["Y0"], dtype=np.int64)
    z = -r
    for i, a in zip(k["idx"], k["A"]):
        d = np.where(z >= 0, 1, -1).astype(np.int64)
        Y = Y + d * np.right_shift(Y, i)
        z = z - d * a
    under = q > fo + 1
    sh = np.where(under, 0, q + guard)
    y = _round_shift(Y, sh)
    y = np.where(under, 0, y)
    return _out(_clamp(y, fo), n.shape)


def bitprod_constants(c, fo, guard, b):
    W = fo + guard
    return [_rnd(math.exp(-(2.0 ** kk) * c) * 2 ** W) for kk in range(b)]


def bitprod_exp(n, c, fo, guard=3):
    """B3: Y = 2^W, then Y = (Y*K_k) >> W for every set bit k of n (LSB first), K_k = round(e^(-2^k c) 2^W)."""
    n = _as_int(n)
    if n.size == 0:
        return n.copy()
    W = fo + guard
    b = max(1, int(n.max()).bit_length())
    K = bitprod_constants(c, fo, guard, b)
    Y = np.full(n.shape, 1 << W, dtype=np.int64)
    for kk in range(b):
        bit = np.right_shift(n, kk) & 1
        Y = np.where(bit == 1, np.right_shift(Y * K[kk], W), Y)
    return _out(_clamp(_round_shift(Y, guard), fo), n.shape)


def pow2_table(fo, guard, frac_bits, mode):
    W = fo + guard
    F = frac_bits
    f = np.arange(1 << F, dtype=np.int64)
    if mode == "table":
        return np.array([_rnd(2.0 ** (-j / 2 ** F) * 2 ** W) for j in range(1 << F)], dtype=np.int64)
    if mode == "linear":
        return (1 << W) - np.right_shift(np.left_shift(f, W), F + 1)
    raise ValueError(mode)


def pow2_exp(n, c, fo, guard=3, frac_bits=4, mode="table", const_frac=16):
    """B4: e^(-x) = 2^(-x log2 e): U = n*Cu (F fraction bits), shift by the integer part, table (or linear
    approximation) for the fraction."""
    n = _as_int(n)
    W = fo + guard
    F = frac_bits
    Cu = _rnd(c * math.log2(math.e) * 2 ** (F + const_frac))
    U = _round_shift(n * Cu, const_frac)
    q = np.right_shift(U, F)
    f = U & ((1 << F) - 1)
    T = pow2_table(fo, guard, F, mode)[f]
    sh = q + guard
    under = sh > W + 1
    y = _round_shift(T, np.where(under, 0, sh))
    y = np.where(under, 0, y)
    return _out(_clamp(y, fo), n.shape)


def shift_decay_trace(k, steps, fo, guard=3, rounding="floor"):
    """B2: trace set to 2^W at a spike, Y -= Y >> k every step (or rounded). Returns output codes for t=0..steps."""
    k, steps, fo, guard = int(k), int(steps), int(fo), int(guard)
    W = fo + guard
    Y = 1 << W
    out = np.empty(steps + 1, dtype=np.int64)
    for t in range(steps + 1):
        out[t] = (Y + (1 << (guard - 1))) >> guard if guard > 0 else Y
        if rounding == "floor":
            Y = Y - (Y >> k)
        elif rounding == "round":
            Y = Y - ((Y + (1 << (k - 1))) >> k)
        else:
            raise ValueError(rounding)
    return _clamp(out, fo)


def shift_decay_c_eff(k):
    """The exact decay constant per step that the shift-decay trace approximates: -ln(1 - 2^-k)."""
    return -math.log(1.0 - 2.0 ** (-k))


def error_stats(y, ref):
    e = np.asarray(y, dtype=np.int64) - np.asarray(ref, dtype=np.int64)
    a = np.abs(e)
    return {"max_abs": int(a.max()) if a.size else 0, "mean_abs": float(a.mean()) if a.size else 0.0,
            "exact_frac": float((e == 0).mean()) if e.size else 1.0}
