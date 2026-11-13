#!/usr/bin/env python3
"""Generator of the batch-1 exponential units (specs/rtl_units.md draft 1, arithmetic in specs/exp_units.md draft 3).

Writes
  rtl/gen/<unit>_<cfg>.v      one plain Verilog-2005 module per unit and configuration (module name = file name)
  tb/vec/<unit>_<cfg>.hex     test vectors computed by the golden model (model/exp_units.py)
  rtl/gen/manifest.json       one entry per module (interface, latency, widths, flip-flop count), read by
                              tb/run_sims.py and rtl/synth_probe.py

Every constant of a unit comes from a function of model/exp_units.py: cordic_constants, bitprod_constants,
pow2_table, lut_exp, shift_decay_trace, and the model's own rounding helper _rnd for B4's Cu, which pow2_exp computes
inline (there is no pow2 constants function). Default parameters (guard, const_frac) are read from the model's
function signatures. Each unit must be bit-exact on its input set (input_set): for R1 the whole bus n = 0 .. 2^NB - 1
(it contains the spec's domain 0 .. ceil((Fo+2) ln2 / c); a saturating time-difference counter can present any code),
for R2 the spec's domain 0 .. 256 (codes 257 .. 511 cannot occur and are left unspecified). Internal word widths are
the exact ranges of every intermediate value over that set, found by an exhaustive integer shadow of the model's
recurrence; each shadow is asserted equal to the model's output before its ranges are used. The vectors are
exhaustive over the same set.

Run (light, a few seconds): .venv/bin/python -I rtl/gen_units.py
"""
import csv
import re
import hashlib
import inspect
import json
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import numpy as np  # noqa: E402

from model import exp_units as M  # noqa: E402

GEN_DIR = os.path.join(ROOT, "rtl", "gen")
VEC_DIR = os.path.join(ROOT, "tb", "vec")
MODEL_FILE = os.path.join(ROOT, "model", "exp_units.py")
SIZING_CSV = os.path.join(ROOT, "results", "units", "sizing.csv")

# Batch-1 configurations (specs/rtl_units.md section 3)
ROLES = {
    "r1": dict(c=1 / 40, text="R1 timing kernel, c = dt/tau = 0.5 ms / 20 ms = 1/40",
               sizing_case="R1 tau=40 steps (dt 0.5 ms)"),
    "r2": dict(c=0.25 / 256, text="R2 weight dependence, c = beta/2^8 = 0.25/256 (Wu 2021)",
               sizing_case="R2 beta=0.25, 8-bit w (Wu 2021)"),
}
FOS = (4, 6, 8, 10, 12)
B2_K = 5                  # B2: k = 5, guard = k - 1 = 4, R1 only
B2_ROUNDING = "round"     # guard = k - 1 is the requirement for max |err| <= 1 with rounding="round" (exp_units.md 3.5)


def model_default(fn, name):
    return inspect.signature(fn).parameters[name].default


C1_GUARD_DEFAULT = model_default(M.cordic_exp, "guard")
C1_CONST_FRAC = model_default(M.cordic_exp, "const_frac")
B4_GUARD = model_default(M.pow2_exp, "guard")
B4_CONST_FRAC = model_default(M.pow2_exp, "const_frac")


# ----------------------------------------------------------------------------------------------------------------
# small helpers
# ----------------------------------------------------------------------------------------------------------------

def bl(x):
    """Bit length of a non-negative integer, at least 1."""
    return max(1, int(x).bit_length())


def sbits(lo, hi):
    """Width of a two's complement word that holds every value in [lo, hi]."""
    b = 1
    while not (-(1 << (b - 1)) <= lo and hi < (1 << (b - 1))):
        b += 1
    return b


def lit(w, v):
    """Sized unsigned decimal literal."""
    v = int(v)
    assert 0 <= v < (1 << w), (w, v)
    return "%d'd%d" % (w, v)


def lit2c(w, v):
    """Two's complement bit pattern of a signed value as a sized literal."""
    v = int(v)
    assert -(1 << (w - 1)) <= v < (1 << (w - 1)), (w, v)
    return "%d'd%d" % (w, v % (1 << w))


def zext(expr, w_from, w_to):
    assert w_to >= w_from, (expr, w_from, w_to)
    return expr if w_to == w_from else "{%d'd0, %s}" % (w_to - w_from, expr)


def sext(sig, w_from, w_to):
    """Sign extension of a plain signal name (its MSB is replicated)."""
    assert w_to >= w_from
    return sig if w_to == w_from else "{{%d{%s[%d]}}, %s}" % (w_to - w_from, sig, w_from - 1, sig)


def shr_fixed(sig, w, s):
    """sig >> s (logical) for a constant s, as a part select, result zero-extended to w bits."""
    if s == 0:
        return sig
    if s >= w:
        return lit(w, 0)
    return "{%d'd0, %s[%d:%d]}" % (s, sig, w - 1, s)


def domain_max(role, fo):
    """Largest input of the spec's input domain (specs/rtl_units.md 1)."""
    if role == "r1":
        return math.ceil((fo + 2) * math.log(2) / ROLES[role]["c"])
    return 256


def input_set(role, fo):
    """The inputs a unit must get right, bit-exact. R1: the whole bus 0 .. 2^NB - 1 (a saturating time-difference
    counter can present any code; the model gives 0 beyond the domain). R2: the spec's domain 0 .. 256 (weight codes w
    and w_max - w); codes 257 .. 2^NB - 1 cannot occur, so their outputs are unspecified and no unit spends logic on
    them. Returns (n array, NB, largest input of the spec's domain)."""
    nmax = domain_max(role, fo)
    NB = nmax.bit_length()
    top = (1 << NB) - 1 if role == "r1" else nmax
    return np.arange(top + 1, dtype=np.int64), NB, nmax


def scope_line(role, n, nmax):
    if role == "r1":
        return ("Bit-exact with the model for every n = 0 .. %d (the whole bus; the spec's domain is 0 .. %d, beyond it "
                "y = 0)." % (int(n.max()), nmax))
    return ("Bit-exact with the model for n = 0 .. %d (the spec's domain: weight codes); n = %d .. %d cannot occur "
            "and gives unspecified outputs." % (nmax, nmax + 1, (1 << nmax.bit_length()) - 1))


class V:
    """Collects Verilog lines."""

    def __init__(self):
        self.lines = []

    def __call__(self, s=""):
        self.lines.append(s)

    def text(self):
        return "\n".join(self.lines) + "\n"


def header(v, name, title, cfg_lines, iface_lines, const_lines):
    v("// %s.v: %s" % (name, title))
    v("// Generated by rtl/gen_units.py from model/exp_units.py (sha256 %s). Do not edit by hand." % MODEL_SHA[:16])
    v("// Plain Verilog-2005; no latches, no clock gating; reset rst_n is active low and synchronous.")
    v("//")
    for s in cfg_lines:
        v("// " + s)
    v("//")
    for s in iface_lines:
        v("// " + s)
    if const_lines:
        v("//")
        for s in const_lines:
            v("// " + s)
    v("")


def ports_pipe(v, name, NB, fo):
    v("module %s (" % name)
    v("  input  wire        clk,")
    v("  input  wire        rst_n,")
    v("  input  wire        in_valid,")
    v("  input  wire [%d:0]  n," % (NB - 1))
    v("  output reg         out_valid,")
    v("  output reg  [%d:0]  y" % fo)
    v(");")


def ports_iter(v, name, NB, fo):
    v("module %s (" % name)
    v("  input  wire        clk,")
    v("  input  wire        rst_n,")
    v("  input  wire        start,")
    v("  input  wire [%d:0]  n," % (NB - 1))
    v("  output reg         busy,")
    v("  output reg         done,")
    v("  output wire [%d:0]  y" % fo)
    v(");")


def input_stage(v, NB):
    """Input register of the unrolled forms: n_r and v_r, then the output valid."""
    v("  // input register (loaded when in_valid) and the valid pipeline")
    v("  reg         v_r;")
    v("  reg  [%d:0]  n_r;" % (NB - 1))
    v("  always @(posedge clk) begin")
    v("    if (!rst_n) begin")
    v("      v_r       <= 1'b0;")
    v("      out_valid <= 1'b0;")
    v("    end else begin")
    v("      v_r       <= in_valid;")
    v("      out_valid <= v_r;")
    v("    end")
    v("  end")
    v("  always @(posedge clk) begin")
    v("    if (in_valid) n_r <= n;")
    v("  end")
    v("")


def output_reg(v, fo, en="v_r"):
    v("  // output register (loaded when a result is valid, held otherwise)")
    v("  always @(posedge clk) begin")
    v("    if (%s) y <= y_c;" % en)
    v("  end")


def iter_control(v, CNW, last_value):
    """busy/done control shared by the iterative forms. start is accepted only when busy = 0."""
    v("  // control: start is accepted when busy = 0; busy covers the iterations; done pulses for one cycle")
    v("  wire last = (cnt == %s);" % lit(CNW, last_value))
    v("  always @(posedge clk) begin")
    v("    if (!rst_n) begin")
    v("      busy <= 1'b0;")
    v("      done <= 1'b0;")
    v("    end else begin")
    v("      done <= busy & last;")
    v("      if (!busy) busy <= start;")
    v("      else if (last) busy <= 1'b0;")
    v("    end")
    v("  end")
    v("")


def select_chain(v, sel, SELW, out, OW, values):
    """out = values[sel] as a chain of conditional assignments (the last value also covers sel >= len(values))."""
    v("  assign %s =" % out)
    for j, val in enumerate(values[:-1]):
        v("    (%s == %s) ? %s :" % (sel, lit(SELW, j), lit(OW, val)))
    v("    %s;" % lit(OW, values[-1]))


def round_out(v, ysig, YW, qsig, QW, qcap, under, g, fo, clamp):
    """y_c = 0 on underflow, else min(2^fo, ((({Y,0} >> (q+g)) + 1) >> 1)), which equals the model's
    round shift (Y + 2^(q+g-1)) >> (q+g) (and Y itself for q+g = 0). qsig = None: q is always 0."""
    parts = ["round shift by %s (y = ((({Y,0} >> s) + 1) >> 1))" % ("q + g" if qsig else "g")] if (qsig or g) else \
        ["no shift (g = 0)"]
    if clamp:
        parts.append("clamp to 2^Fo")
    if under:
        parts.append("0 on underflow")
    v("  // output: " + ", ".join(parts))
    if qsig is None and g == 0:
        yr, TW = ysig, YW
    else:
        TW = YW + 1 - g
        v("  wire [%d:0] o_yx = {%s, 1'b0};" % (YW, ysig))
        if qsig is None:
            v("  wire [%d:0] o_t = o_yx[%d:%d];" % (TW - 1, YW, g))
        else:
            v("  reg  [%d:0] o_t;" % (TW - 1))
            v("  always @(*) begin")
            v("    case (%s)" % qsig)
            for qv in range(qcap + 1):
                s = qv + g
                if s > YW:
                    expr = lit(TW, 0)
                elif qv == 0:
                    expr = "o_yx[%d:%d]" % (YW, s)
                else:
                    expr = "{%d'd0, o_yx[%d:%d]}" % (qv, YW, s)
                v("      %s: o_t = %s;" % (lit(QW, qv), expr))
            v("      default: o_t = %s;" % lit(TW, 0))
            v("    endcase")
            v("  end")
        v("  wire [%d:0] o_tp1 = {1'b0, o_t} + %s;" % (TW, lit(TW + 1, 1)))
        v("  wire [%d:0] o_yr  = o_tp1[%d:1];" % (TW - 1, TW))
        yr = "o_yr"
    # bring the rounded value to fo+1 bits (clamp only where the exhaustive analysis says it is needed)
    if TW < fo + 1:
        yfit = zext(yr, TW, fo + 1)
    elif clamp:
        yfit = "((%s > %s) ? %s : %s[%d:0])" % (yr, lit(TW, 1 << fo), lit(fo + 1, 1 << fo), yr, fo)
    elif TW == fo + 1:
        yfit = yr
    else:
        yfit = "%s[%d:0]" % (yr, fo)
    if under is None:
        v("  wire [%d:0] y_c = %s;" % (fo, yfit))
    else:
        v("  wire [%d:0] y_c = %s ? %s : %s;" % (fo, under, lit(fo + 1, 0), yfit))
    v("")


# ----------------------------------------------------------------------------------------------------------------
# exhaustive shadows of the model (ranges of the intermediate values); each asserts equality with the model
# ----------------------------------------------------------------------------------------------------------------

def c1_shadow(c, fo, g, m, n):
    k = M.cordic_constants(c, fo, g, m, C1_CONST_FRAC)
    C, P, L = k["C"], k["P"], k["L"]
    Z = (n * C + (1 << (P - 1))) >> P
    q = Z // L
    r = Z - q * L
    ok = q <= fo + 1                       # not underflow
    Y = np.full(n.shape, k["Y0"], dtype=np.int64)
    z = -r
    Ys, zs = [Y.copy()], [z.copy()]
    for i, a in zip(k["idx"], k["A"]):
        d = np.where(z >= 0, 1, -1).astype(np.int64)
        Y = Y + d * np.right_shift(Y, i)
        z = z - d * a
        Ys.append(Y.copy())
        zs.append(z.copy())
    s = np.where(ok, q + g, 0)
    yr = (np.right_shift(np.left_shift(Y, 1), s) + 1) >> 1     # the RTL's rounding formula
    y = np.where(ok, np.minimum(yr, 1 << fo), 0)
    ym = M.cordic_exp(n, c, fo, guard=g, iters=m, const_frac=C1_CONST_FRAC)
    assert np.array_equal(y, ym), "C1 shadow differs from model"
    return dict(k=k, n=n, Z=Z, q=q, r=r, ok=ok, ym=ym,
                Y_rng=[(int(t[ok].min()), int(t[ok].max())) for t in Ys],
                z_rng=[(int(t[ok].min()), int(t[ok].max())) for t in zs],
                r_max=int(r[ok].max()), yr_max=int(yr[ok].max()))


def b3_shadow(c, fo, g, n, NB):
    W = fo + g
    assert int(n.max()).bit_length() == NB      # the model's b, the bit length of the largest n of the call
    K = M.bitprod_constants(c, fo, g, NB)
    Y = np.full(n.shape, 1 << W, dtype=np.int64)
    Ys = [Y.copy()]
    for kk in range(NB):
        bit = np.right_shift(n, kk) & 1
        Y = np.where(bit == 1, np.right_shift(Y * K[kk], W), Y)
        Ys.append(Y.copy())
    yr = (np.right_shift(np.left_shift(Y, 1), g) + 1) >> 1
    ym = M.bitprod_exp(n, c, fo, guard=g)
    assert np.array_equal(np.minimum(yr, 1 << fo), ym), "B3 shadow differs from model"
    return dict(K=K, n=n, ym=ym, Y_max=[int(t.max()) for t in Ys], yr_max=int(yr.max()))


def b4_cu(c, F, P):
    # pow2_exp computes Cu inline; this is the same expression with the model's own rounding helper
    return M._rnd(c * math.log2(math.e) * 2 ** (F + P))


def b4_shadow(c, fo, g, F, n):
    P = B4_CONST_FRAC
    Cu = b4_cu(c, F, P)
    T = M.pow2_table(fo, g, F, "table")
    U = (n * Cu + (1 << (P - 1))) >> P
    q = U >> F
    f = U & ((1 << F) - 1)
    ok = q <= fo + 1                      # the model's underflow q + g > W + 1, with W = fo + g
    s = np.where(ok, q + g, 0)
    yr = (np.right_shift(np.left_shift(T[f], 1), s) + 1) >> 1
    y = np.where(ok, np.minimum(yr, 1 << fo), 0)
    ym = M.pow2_exp(n, c, fo, guard=g, frac_bits=F, mode="table", const_frac=P)
    assert np.array_equal(y, ym), "B4 shadow differs from model"
    return dict(Cu=Cu, P=P, T=T, n=n, U=U, q=q, ok=ok, ym=ym, yr_max=int(yr[ok].max()))


# ----------------------------------------------------------------------------------------------------------------
# C1 front end: angle Z, range reduction q = floor(Z / L), r = Z - q L, underflow q > fo + 1
# ----------------------------------------------------------------------------------------------------------------

def c1_front(v, nsig, NB, fo, k, nfmax):
    C, P, L = k["C"], k["P"], k["L"]
    half = 1 << (P - 1)
    PW = bl(nfmax * C + half)
    Zmax = (nfmax * C + half) >> P
    ZW = bl(Zmax)
    qmax = Zmax // L
    qcap = min(qmax, fo + 1)
    has_under = qmax >= fo + 2
    RW = bl(L - 1)
    v("  // angle: Z = (n*C + 2^(P-1)) >> P (constant multiplier)")
    v("  wire [%d:0] a_prod = %s * %s;" % (PW - 1, zext(nsig, NB, PW), lit(PW, C)))
    v("  wire [%d:0] a_sum  = a_prod + %s;" % (PW - 1, lit(PW, half)))
    v("  wire [%d:0] Z      = a_sum[%d:%d];" % (ZW - 1, PW - 1, P))
    if qcap == 0:
        assert not has_under and Zmax < L
        v("  // range reduction: Z < L = %d for every input, so q = 0 and r = Z" % L)
        v("  wire [%d:0] r_c = Z;" % (ZW - 1))
        v("")
        return dict(qsig=None, QW=0, qcap=0, under=None, RW=ZW, ZW=ZW, PW=PW, qmax=qmax)
    QW = bl(qcap)
    v("  // range reduction: q = floor(Z / L) by comparison with the multiples of L = %d (q <= %d used; "
      "q > %d is underflow)" % (L, qcap, fo + 1))
    v("  reg  [%d:0] q_c;" % (QW - 1))
    v("  reg  [%d:0] qL_c;" % (ZW - 1))
    v("  always @(*) begin")
    v("    q_c  = %s;" % lit(QW, 0))
    v("    qL_c = %s;" % lit(ZW, 0))
    for j in range(1, qcap + 1):
        v("    if (Z >= %s) begin q_c = %s; qL_c = %s; end" % (lit(ZW, j * L), lit(QW, j), lit(ZW, j * L)))
    v("  end")
    under = None
    if has_under:
        v("  wire under_c = (Z >= %s);   // q > Fo + 1: output 0" % lit(ZW, (fo + 2) * L))
        under = "under_c"
    v("  wire [%d:0] r_full = Z - qL_c;" % (ZW - 1))
    v("  wire [%d:0] r_c    = r_full[%d:0];" % (RW - 1, RW - 1))
    v("")
    return dict(qsig="q_c", QW=QW, qcap=qcap, under=under, RW=RW, ZW=ZW, PW=PW, qmax=qmax)


def c1_cfg_lines(role, fo, g, m, k, setting, n, nmax):
    return ["Unit C1: hyperbolic CORDIC, rotation mode, one datapath (x = y), range reduction by ln 2.",
            "Golden model: cordic_exp(n, c, fo=%d, guard=%d, iters=%d, const_frac=%d)" % (fo, g, m, k["P"]),
            "Role %s: %s" % (role.upper(), ROLES[role]["text"]),
            "Setting: %s; Fo = %d, guard g = %d, W = %d, iterations m = %d" % (setting, fo, g, k["W"], m),
            scope_line(role, n, nmax)]


def c1_const_lines(k):
    return ["Constants (cordic_constants): C = %d, P = %d, L = %d, Y0 = %d" % (k["C"], k["P"], k["L"], k["Y0"]),
            "  indices i = %s" % k["idx"],
            "  A_i       = %s" % k["A"]]


# ----------------------------------------------------------------------------------------------------------------
# unit generators; each returns (verilog text, manifest entry)
# ----------------------------------------------------------------------------------------------------------------

def gen_lut(role, fo):
    c = ROLES[role]["c"]
    n, NB, nmax = input_set(role, fo)
    name = "lut_%s_fo%d" % (role, fo)
    table = M.lut_exp(n, c, fo)
    nz = int(np.count_nonzero(table))
    nzero = int(np.argmax(table == 0)) if (table == 0).any() else len(table)
    v = V()
    header(v, name, "B1 lookup table (logic ROM)",
           ["Unit B1: y(n) = ref(n) = floor(2^Fo e^(-n c) + 1/2), a ROM indexed by n.",
            "Golden model: lut_exp(n, c, fo=%d)" % fo,
            "Role %s: %s" % (role.upper(), ROLES[role]["text"]),
            "Fo = %d; input n: %d bits; %d non-zero entries (n < %d), the rest is 0 (default branch)."
            % (fo, NB, nz, nzero), scope_line(role, n, nmax)],
           ["Interface (single-cycle form): in_valid, n -> out_valid, y; registered output, no input register.",
            "Latency 1: inputs presented in cycle t give out_valid = 1 and y in cycle t + 1.",
            "y holds its value while out_valid = 0."],
           ["Table: lut_exp over n = 0 .. %d." % int(n.max())])
    ports_pipe(v, name, NB, fo)
    v("  reg [%d:0] rom_y;" % fo)
    v("  always @(*) begin")
    v("    case (n)")
    for i, t in enumerate(table):
        if t != 0:
            v("      %s: rom_y = %s;" % (lit(NB, i), lit(fo + 1, t)))
    v("      default: rom_y = %s;" % lit(fo + 1, 0))
    v("    endcase")
    v("  end")
    v("")
    v("  always @(posedge clk) begin")
    v("    if (!rst_n) out_valid <= 1'b0;")
    v("    else        out_valid <= in_valid;")
    v("  end")
    v("  always @(posedge clk) begin")
    v("    if (in_valid) y <= rom_y;")
    v("  end")
    v("endmodule")
    ent = dict(name=name, unit="lut", method="B1", form="single-cycle", protocol="pipe", role=role, c=c, fo=fo,
               params=dict(), setting="", setting_short="-", NB=NB, latency=1, regs=dict(out_valid=1, y=fo + 1),
               y=[int(t) for t in table], n_domain=nmax + 1,
               notes="%d non-zero ROM entries of %d bits" % (nz, fo + 1))
    return v.text(), ent


def gen_cordic(role, fo, g, m, setting, form):
    c = ROLES[role]["c"]
    n, NB, nmax = input_set(role, fo)
    sh = c1_shadow(c, fo, g, m, n)
    k = sh["k"]
    W, idx, A = k["W"], k["idx"], k["A"]
    name = "cordic_%s_%s_fo%d_m%dg%d" % (form, role, fo, m, g)
    clamp = sh["yr_max"] > (1 << fo)
    YWs = [bl(hi) for (lo, hi) in sh["Y_rng"]]
    ZWs = [sbits(lo, hi) for (lo, hi) in sh["z_rng"]]
    v = V()
    if form == "iter":
        lat = m + 1
        YW = max(YWs)
        ZZW = max(ZWs + [sbits(-max(A), max(A))])
        SW = bl(max(idx))
        CNW = bl(m - 1)
        header(v, name, "C1 hyperbolic CORDIC, iterative form", c1_cfg_lines(role, fo, g, m, k, setting, n, nmax),
               ["Interface (iterative form): start, n -> busy, done, y.",
                "start is accepted only when busy = 0 (ignored while busy); n is sampled with start.",
                "Cycle 0 (start): Z, q, r are formed and loaded (z = -r, Y = Y0); cycles 1 .. %d: one rotation "
                "each;" % m,
                "Latency %d = %d iterations + 1: start in cycle t gives done = 1 (one cycle) and busy = 0 in cycle "
                "t + %d." % (lat, m, lat),
                "y is formed from the working registers (round shift by q + g); it is valid from done and held "
                "until the next start is accepted.",
                "Back to back: a new start may be given in the done cycle (one result every %d cycles)." % lat],
               c1_const_lines(k) + ["Widths: Y %d bits, z %d bits (two's complement), from the exhaustive "
                                    "ranges over n = 0 .. %d." % (YW, ZZW, int(n.max()))])
        ports_iter(v, name, NB, fo)
        fe = c1_front(v, "n", NB, fo, k, int(n.max()))
        v("  // working registers (no reset: they are loaded at start). fsm_encoding = \"none\" keeps Yosys from")
        v("  // re-encoding qr and cnt one-hot as state machines, so the netlist keeps the RTL's registers.")
        v("  reg  [%d:0] Yr;" % (YW - 1))
        v("  reg  [%d:0] zr;" % (ZZW - 1))
        if fe["qsig"]:
            v("  (* fsm_encoding = \"none\" *) reg [%d:0] qr;" % (fe["QW"] - 1))
        if fe["under"]:
            v("  reg         ur;")
        v("  (* fsm_encoding = \"none\" *) reg [%d:0] cnt;" % (CNW - 1))
        v("")
        v("  // iteration table: shift index i and angle constant A_i of iteration cnt (a selection chain, not a")
        v("  // case statement: Yosys turns a constant case behind a register into a ROM with a duplicated register)")
        v("  wire [%d:0] i_cur;" % (SW - 1))
        v("  wire [%d:0] a_cur;" % (ZZW - 1))
        select_chain(v, "cnt", CNW, "i_cur", SW, idx)
        select_chain(v, "cnt", CNW, "a_cur", ZZW, A)
        v("")
        v("  // one rotation: d = +1 if z >= 0; Y += d (Y >> i); z -= d A_i")
        v("  wire        d      = ~zr[%d];" % (ZZW - 1))
        v("  wire [%d:0] ysh    = Yr >> i_cur;" % (YW - 1))
        v("  wire [%d:0] y_next = Yr + (ysh ^ {%d{~d}}) + %s;" % (YW - 1, YW, zext("~d", 1, YW)))
        v("  wire [%d:0] z_next = zr + (a_cur ^ {%d{d}}) + %s;" % (ZZW - 1, ZZW, zext("d", 1, ZZW)))
        TZI = max(ZZW, fe["RW"] + 1)
        v("  wire [%d:0] z_ifull = %s - %s;   // -r" % (TZI - 1, lit(TZI, 0), zext("r_c", fe["RW"], TZI)))
        v("  wire [%d:0] z_init = z_ifull[%d:0];" % (ZZW - 1, ZZW - 1))
        v("")
        iter_control(v, CNW, m - 1)
        v("  always @(posedge clk) begin")
        v("    if (!busy) begin")
        v("      if (start) begin")
        v("        Yr  <= %s;" % lit(YW, k["Y0"]))
        v("        zr  <= z_init;")
        if fe["qsig"]:
            v("        qr  <= q_c;")
        if fe["under"]:
            v("        ur  <= under_c;")
        v("        cnt <= %s;" % lit(CNW, 0))
        v("      end")
        v("    end else begin")
        v("      Yr  <= y_next;")
        v("      zr  <= z_next;")
        v("      cnt <= cnt + %s;" % lit(CNW, 1))
        v("    end")
        v("  end")
        v("")
        round_out(v, "Yr", YW, "qr" if fe["qsig"] else None, fe["QW"], fe["qcap"], "ur" if fe["under"] else None,
                  g, fo, clamp)
        v("  assign y = y_c;")
        v("endmodule")
        regs = dict(busy=1, done=1, Yr=YW, zr=ZZW, cnt=CNW)
        if fe["qsig"]:
            regs["qr"] = fe["QW"]
        if fe["under"]:
            regs["ur"] = 1
        widths = dict(Y=YW, z=ZZW, cnt=CNW, Z=fe["ZW"], prod=fe["PW"], q_cap=fe["qcap"])
        protocol, form_txt = "iter", "iterative"
    else:
        lat = 2
        header(v, name, "C1 hyperbolic CORDIC, unrolled form", c1_cfg_lines(role, fo, g, m, k, setting, n, nmax),
               ["Interface (unrolled form): in_valid, n -> out_valid, y; one result per cycle.",
                "Registers at the input (n_r) and the output (y) only; the %d rotations are combinational." % m,
                "Latency 2: inputs presented in cycle t give out_valid = 1 and y in cycle t + 2.",
                "y holds its value while out_valid = 0."],
               c1_const_lines(k) + ["Per-stage widths (exhaustive ranges over n = 0 .. %d): Y %s, z %s"
                                    % (int(n.max()), YWs, ZWs[:m])])
        ports_pipe(v, name, NB, fo)
        input_stage(v, NB)
        fe = c1_front(v, "n_r", NB, fo, k, int(n.max()))
        v("  // rotations, stage j: d_j = (z_j >= 0); Y_(j+1) = Y_j + d_j (Y_j >> i_j); z_(j+1) = z_j - d_j A_j")
        v("  wire [%d:0] Ys0 = %s;" % (YWs[0] - 1, lit(YWs[0], k["Y0"])))
        TZ0 = max(fe["RW"] + 1, ZWs[0])
        v("  wire [%d:0] zf0 = %s - %s;" % (TZ0 - 1, lit(TZ0, 0), zext("r_c", fe["RW"], TZ0)))
        v("  wire [%d:0] zs0 = zf0[%d:0];" % (ZWs[0] - 1, ZWs[0] - 1))
        for j, (i, a) in enumerate(zip(idx, A)):
            yw0, yw1, zw0 = YWs[j], YWs[j + 1], ZWs[j]
            TW = max(yw0, yw1)
            v("  // stage %d: i = %d, A = %d" % (j, i, a))
            v("  wire         d%d   = ~zs%d[%d];" % (j, j, zw0 - 1))
            v("  wire [%d:0] ysh%d = %s;" % (TW - 1, j, zext(shr_fixed("Ys%d" % j, yw0, i), yw0, TW)))
            v("  wire [%d:0] yf%d  = %s + (ysh%d ^ {%d{~d%d}}) + %s;"
              % (TW - 1, j + 1, zext("Ys%d" % j, yw0, TW), j, TW, j, zext("~d%d" % j, 1, TW)))
            v("  wire [%d:0] Ys%d  = yf%d[%d:0];" % (yw1 - 1, j + 1, j + 1, yw1 - 1))
            if j < m - 1:                           # z after the last rotation is not needed
                zw1 = ZWs[j + 1]
                TZ = max(zw0, zw1, sbits(-a, a))
                v("  wire [%d:0] zf%d  = %s + (d%d ? %s : %s);"
                  % (TZ - 1, j + 1, sext("zs%d" % j, zw0, TZ), j, lit2c(TZ, -a), lit2c(TZ, a)))
                v("  wire [%d:0] zs%d  = zf%d[%d:0];" % (zw1 - 1, j + 1, j + 1, zw1 - 1))
        v("")
        round_out(v, "Ys%d" % m, YWs[m], fe["qsig"], fe["QW"], fe["qcap"], fe["under"], g, fo, clamp)
        output_reg(v, fo)
        v("endmodule")
        regs = dict(v_r=1, n_r=NB, out_valid=1, y=fo + 1)
        widths = dict(Y=YWs, z=ZWs[:m], Z=fe["ZW"], prod=fe["PW"], q_cap=fe["qcap"])
        protocol, form_txt = "pipe", "unrolled"
    ent = dict(name=name, unit="cordic_%s" % form, method="C1", form=form_txt, protocol=protocol, role=role, c=c,
               fo=fo, params=dict(guard=g, iters=m, const_frac=k["P"], W=W), setting=setting, NB=NB, latency=lat,
               regs=regs, y=[int(t) for t in sh["ym"]], n_domain=nmax + 1, widths=widths,
               setting_short="smallest (sizing.csv)" if setting.startswith("smallest") else "model default",
               notes="clamp %s; q <= %d over the inputs; underflow comparator %s"
                     % ("needed" if clamp else "not needed", fe["qmax"], "yes" if fe["under"] else "no"))
    return v.text(), ent


def gen_bitprod(role, fo, g, form):
    c = ROLES[role]["c"]
    n, NB, nmax = input_set(role, fo)
    W = fo + g
    sh = b3_shadow(c, fo, g, n, NB)
    K = sh["K"]
    YW = bl(max(sh["Y_max"]))
    assert YW == W + 1
    clamp = sh["yr_max"] > (1 << fo)
    name = "bitprod_%s_%s_fo%d_g%d" % (form, role, fo, g)
    cfg = ["Unit B3: product of constants selected by the bits of n, least significant bit first.",
           "Golden model: bitprod_exp(n, c, fo=%d, guard=%d) with b = %d input bits" % (fo, g, NB),
           "Role %s: %s" % (role.upper(), ROLES[role]["text"]),
           "Fo = %d, guard g = %d (smallest with max |err| <= 1), W = %d" % (fo, g, W), scope_line(role, n, nmax)]
    consts = ["Constants (bitprod_constants): K_k = %s" % K]
    v = V()
    if form == "iter":
        lat = NB + 1
        CNW = bl(NB - 1)
        KW = bl(max(K))
        assert KW >= W, "K_0 < 2^(W-1): the product slice below would be out of range"
        header(v, name, "B3 bit-product exponential, iterative form", cfg,
               ["Interface (iterative form): start, n -> busy, done, y.",
                "start is accepted only when busy = 0 (ignored while busy); n is sampled with start.",
                "Cycle 0 (start): Y = 2^W and n are loaded; cycles 1 .. %d: one input bit each "
                "(Y = (Y K_k) >> W if bit k is 1), one multiplier and a table of the K_k." % NB,
                "Latency %d = %d bits + 1: start in cycle t gives done = 1 (one cycle) and busy = 0 in cycle "
                "t + %d." % (lat, NB, lat),
                "y is formed from the working register (round shift by g); it is valid from done and held until "
                "the next start is accepted.",
                "Back to back: a new start may be given in the done cycle (one result every %d cycles)." % lat],
               consts)
        ports_iter(v, name, NB, fo)
        PW = YW + KW
        v("  // working registers (no reset: they are loaded at start). fsm_encoding = \"none\" keeps Yosys from")
        v("  // re-encoding cnt one-hot as a state machine, so the netlist keeps the RTL's registers.")
        v("  reg  [%d:0] Yr;" % (YW - 1))
        v("  reg  [%d:0] nr;" % (NB - 1))
        v("  (* fsm_encoding = \"none\" *) reg [%d:0] cnt;" % (CNW - 1))
        v("")
        v("  // constant table K_cnt (a selection chain, not a case statement: Yosys turns a constant case behind a")
        v("  // register into a ROM with a duplicated register)")
        v("  wire [%d:0] k_cur;" % (KW - 1))
        select_chain(v, "cnt", CNW, "k_cur", KW, K)
        v("  wire [%d:0] prod  = %s * %s;" % (PW - 1, zext("Yr", YW, PW), zext("k_cur", KW, PW)))
        v("  wire [%d:0] y_mul = prod[%d:%d];   // (Y K) >> W" % (YW - 1, W + YW - 1, W))
        v("")
        iter_control(v, CNW, NB - 1)
        v("  always @(posedge clk) begin")
        v("    if (!busy) begin")
        v("      if (start) begin")
        v("        Yr  <= %s;" % lit(YW, 1 << W))
        v("        nr  <= n;")
        v("        cnt <= %s;" % lit(CNW, 0))
        v("      end")
        v("    end else begin")
        v("      if (nr[0]) Yr <= y_mul;")
        v("      nr  <= %s;" % ("{1'b0, nr[%d:1]}" % (NB - 1) if NB > 1 else "1'b0"))
        v("      cnt <= cnt + %s;" % lit(CNW, 1))
        v("    end")
        v("  end")
        v("")
        round_out(v, "Yr", YW, None, 0, 0, None, g, fo, clamp)
        v("  assign y = y_c;")
        v("endmodule")
        regs = dict(busy=1, done=1, Yr=YW, nr=NB, cnt=CNW)
        protocol, form_txt = "iter", "iterative"
        widths = dict(Y=YW, K=KW, prod=PW, cnt=CNW)
    else:
        lat = 2
        header(v, name, "B3 bit-product exponential, unrolled form", cfg,
               ["Interface (unrolled form): in_valid, n -> out_valid, y; one result per cycle.",
                "Registers at the input (n_r) and the output (y) only; %d constant-multiplier stages in between."
                % NB,
                "Latency 2: inputs presented in cycle t give out_valid = 1 and y in cycle t + 2.",
                "y holds its value while out_valid = 0."],
               consts)
        ports_pipe(v, name, NB, fo)
        input_stage(v, NB)
        PW = YW + W                      # Y <= 2^W and K_k <= 2^W: the product fits 2W + 1 bits
        v("  // stage k: Y_(k+1) = bit k of n ? (Y_k K_k) >> W : Y_k")
        v("  wire [%d:0] Yb0 = %s;" % (YW - 1, lit(YW, 1 << W)))
        for kk, Kk in enumerate(K):
            if Kk == (1 << W):
                v("  wire [%d:0] Yb%d = Yb%d;   // K_%d = 2^W: no change" % (YW - 1, kk + 1, kk, kk))
            elif Kk == 0:
                v("  wire [%d:0] Yb%d = n_r[%d] ? %s : Yb%d;   // K_%d = 0"
                  % (YW - 1, kk + 1, kk, lit(YW, 0), kk, kk))
            else:
                v("  wire [%d:0] p%d  = %s * %s;" % (PW - 1, kk, zext("Yb%d" % kk, YW, PW), lit(PW, Kk)))
                v("  wire [%d:0] Yb%d = n_r[%d] ? p%d[%d:%d] : Yb%d;" % (YW - 1, kk + 1, kk, kk, PW - 1, W, kk))
        v("")
        round_out(v, "Yb%d" % NB, YW, None, 0, 0, None, g, fo, clamp)
        output_reg(v, fo)
        v("endmodule")
        regs = dict(v_r=1, n_r=NB, out_valid=1, y=fo + 1)
        protocol, form_txt = "pipe", "unrolled"
        widths = dict(Y=YW, prod=PW)
    ent = dict(name=name, unit="bitprod_%s" % form, method="B3", form=form_txt, protocol=protocol, role=role, c=c,
               fo=fo, params=dict(guard=g, W=W, b=NB), setting="smallest guard", setting_short="smallest guard", NB=NB,
               latency=lat, regs=regs,
               y=[int(t) for t in sh["ym"]], n_domain=nmax + 1, widths=widths,
               notes="%d constants; clamp %s" % (NB, "needed" if clamp else "not needed"))
    return v.text(), ent


def gen_pow2(role, fo, g=None, F=None):
    c = ROLES[role]["c"]
    n, NB, nmax = input_set(role, fo)
    g = B4_GUARD if g is None else g             # batch 1: the model's default guard
    F = fo + 1 if F is None else F               # batch 1: frac_bits = Fo + 1
    W = fo + g
    sh = b4_shadow(c, fo, g, F, n)
    Cu, P, T = sh["Cu"], sh["P"], sh["T"]
    clamp = sh["yr_max"] > (1 << fo)
    name = "pow2_%s_fo%d_f%dg%d" % (role, fo, F, g)
    nfmax = int(n.max())
    half = 1 << (P - 1)
    PW = bl(nfmax * Cu + half)
    Umax = (nfmax * Cu + half) >> P
    UW = bl(Umax)
    qmax = Umax >> F
    qcap = min(qmax, fo + 1)
    has_under = qmax >= fo + 2
    TW = bl(int(T.max()))
    v = V()
    header(v, name, "B4 2^x exponential (shift plus fraction table), single-pass form",
           ["Unit B4: e^(-x) = 2^(-x log2 e): U = n Cu (F fraction bits), shift by q = U >> F, table T[U mod 2^F].",
            "Golden model: pow2_exp(n, c, fo=%d, guard=%d, frac_bits=%d, mode='table', const_frac=%d)"
            % (fo, g, F, P),
            "Role %s: %s" % (role.upper(), ROLES[role]["text"]),
            "Fo = %d, guard g = %d%s, frac_bits F = %d%s, W = %d; table of %d x %d bits"
            % (fo, g, " (the model's default)" if g == B4_GUARD else "", F, " (= Fo + 1)" if F == fo + 1 else "",
               W, 1 << F, TW), scope_line(role, n, nmax)],
           ["Interface (unrolled form): in_valid, n -> out_valid, y; one result per cycle.",
            "Registers at the input (n_r) and the output (y) only; multiplier, table and shifter in between.",
            "Latency 2: inputs presented in cycle t give out_valid = 1 and y in cycle t + 2.",
            "y holds its value while out_valid = 0."],
           ["Constants: Cu = round(c log2(e) 2^(F+P)) = %d (P = %d, the model's _rnd; pow2_exp has no constants "
            "function), T = pow2_table(fo, g, F, 'table')." % (Cu, P),
            "q <= %d over n = 0 .. %d%s." % (qmax, nfmax, "" if has_under else " (no underflow possible)")])
    ports_pipe(v, name, NB, fo)
    input_stage(v, NB)
    v("  // exponent: U = (n*Cu + 2^(P-1)) >> P; q = U >> F; f = U mod 2^F")
    v("  wire [%d:0] u_prod = %s * %s;" % (PW - 1, zext("n_r", NB, PW), lit(PW, Cu)))
    v("  wire [%d:0] u_sum  = u_prod + %s;" % (PW - 1, lit(PW, half)))
    v("  wire [%d:0] U      = u_sum[%d:%d];" % (UW - 1, PW - 1, P))
    fW = min(F, UW)
    v("  wire [%d:0] f      = %s;" % (F - 1, zext("U[%d:0]" % (fW - 1), fW, F)))
    QW = 0
    under = None
    if qmax > 0:
        QW = UW - F
        v("  wire [%d:0] q      = U[%d:%d];" % (QW - 1, UW - 1, F))
        if has_under:
            v("  wire        under  = (q >= %s);   // q + g > W + 1: output 0" % lit(QW, fo + 2))
            under = "under"
    v("")
    v("  // fraction table T[f] = round(2^(-f/2^F) 2^W)")
    v("  reg  [%d:0] T;" % (TW - 1))
    v("  always @(*) begin")
    v("    case (f)")
    for j, t in enumerate(T):
        v("      %s: T = %s;" % (lit(F, j), lit(TW, t)))
    v("      default: T = %s;" % lit(TW, 0))
    v("    endcase")
    v("  end")
    v("")
    round_out(v, "T", TW, "q" if qmax > 0 else None, QW, qcap, under, g, fo, clamp)
    output_reg(v, fo)
    v("endmodule")
    ent = dict(name=name, unit="pow2", method="B4", form="unrolled", protocol="pipe", role=role, c=c, fo=fo,
               params=dict(guard=g, frac_bits=F, const_frac=P, W=W),
               setting=("frac_bits = Fo + 1" if F == fo + 1 else "frac_bits = %d" % F) + ", guard = %d" % g,
               setting_short=("F = Fo + 1" if F == fo + 1 else "F = %d" % F) + ", g = %d" % g,
               NB=NB, latency=2, regs=dict(v_r=1, n_r=NB, out_valid=1, y=fo + 1), y=[int(t) for t in sh["ym"]],
               n_domain=nmax + 1,
               widths=dict(U=UW, prod=PW, T=TW, q=QW),
               notes="table %d x %d bit; q <= %d; clamp %s" % (1 << F, TW, qmax, "needed" if clamp else "not needed"))
    return v.text(), ent


def gen_shiftdecay(fo):
    k, g = B2_K, B2_K - 1
    W = fo + g
    rnd = B2_ROUNDING
    ce = M.shift_decay_c_eff(k)
    steps_dom = math.ceil((fo + 2) * math.log(2) / ce)
    # trajectory long enough to reach the fixed point (the decrement becomes 0) and a few steps beyond
    long_traj = M.shift_decay_trace(k, 8 * steps_dom, W, guard=0, rounding=rnd)
    stuck = int(np.argmax(long_traj[1:] == long_traj[:-1]))
    assert long_traj[stuck + 1] == long_traj[stuck] and long_traj[-1] == long_traj[stuck]
    S = max(steps_dom, stuck + 4)
    Ytr = M.shift_decay_trace(k, S, W, guard=0, rounding=rnd)    # the internal register Y_t (W+1 bits)
    ytr = M.shift_decay_trace(k, S, fo, guard=g, rounding=rnd)   # the output codes y_t
    assert Ytr[S] == Ytr[S - 1]
    name = "shiftdecay_r1_fo%d_k%dg%d" % (fo, k, g)
    v = V()
    header(v, name, "B2 shift-decay trace update datapath",
           ["Unit B2: clock-driven trace; set: Y = 2^W; decay: Y = Y - ((Y + 2^(k-1)) >> k) (rounding '%s')." % rnd,
            "Golden model: shift_decay_trace(k=%d, steps, fo=%d, guard=%d, rounding='%s')" % (k, fo, g, rnd),
            "Role R1: tau_eff = 1/c_eff = %.2f steps (c_eff = -ln(1 - 2^-k))" % (1 / ce),
            "Fo = %d, k = %d, guard g = k - 1 = %d, W = %d; the stored trace has W + 1 = %d bits because the set "
            "value 2^W needs bit W." % (fo, k, g, W, W + 1)],
           ["Interface (trace update): y_old, set, decay -> y_new (registered), y_out (registered).",
            "y_new = set ? 2^W : decay ? y_old - ((y_old + 2^(k-1)) >> k) : y_old  (set has priority).",
            "y_out = (y_old + 2^(g-1)) >> g, the output code of the trace before this update.",
            "Latency 1: y_old, set, decay in cycle t give y_new and y_out in cycle t + 1; one update per cycle.",
            "y_old must be a trace value (<= 2^W). rst_n is part of the common interface; the unit has no "
            "control state, so it is unused."],
           [])
    v("module %s (" % name)
    v("  input  wire        clk,")
    v("  /* verilator lint_off UNUSEDSIGNAL */")
    v("  input  wire        rst_n,")
    v("  /* verilator lint_on UNUSEDSIGNAL */")
    v("  input  wire [%d:0] y_old," % W)
    v("  input  wire        set,")
    v("  input  wire        decay,")
    v("  output reg  [%d:0] y_new," % W)
    v("  output reg  [%d:0]  y_out" % fo)
    v(");")
    v("  wire [%d:0] dsum    = y_old + %s;" % (W, lit(W + 1, 1 << (k - 1))))
    v("  wire [%d:0] decr    = %s;   // (y_old + 2^(k-1)) >> k" % (W, shr_fixed("dsum", W + 1, k)))
    v("  wire [%d:0] decayed = y_old - decr;" % W)
    v("  wire [%d:0] nxt     = set ? %s : (decay ? decayed : y_old);" % (W, lit(W + 1, 1 << W)))
    if g > 0:
        v("  wire [%d:0] osum    = y_old + %s;" % (W, lit(W + 1, 1 << (g - 1))))
        v("  wire [%d:0]  yo      = osum[%d:%d];   // (y_old + 2^(g-1)) >> g" % (fo, W, g))
    else:
        v("  wire [%d:0]  yo      = y_old;" % fo)
    v("  always @(posedge clk) begin")
    v("    y_new <= nxt;")
    v("    y_out <= yo;")
    v("  end")
    v("endmodule")
    # control sequence: phase A = set then decay along the whole trajectory; phase B = random set/decay/hold
    rng = random.Random(20261113 + fo)
    ctrl = [(1, 0)] + [(0, 1)] * S
    for _ in range(2 * S):
        u = rng.random()
        ctrl.append((1, 0) if u < 0.03 else (1, 1) if u < 0.05 else (0, 1) if u < 0.80 else (0, 0))
    vec = []
    s = 0                       # decays since the last set; the testbench's trace starts at Y_0 = 2^W
    for st, dc in ctrl:
        s_next = 0 if st else min(s + 1, S) if dc else s
        vec.append((st, dc, int(Ytr[s_next]), int(ytr[s])))
        s = s_next
    ent = dict(name=name, unit="shiftdecay", method="B2", form="trace update", protocol="trace", role="r1",
               c=ce, fo=fo, params=dict(k=k, guard=g, rounding=rnd, W=W), setting="k = 5, guard = k - 1",
               setting_short="k = 5, g = k - 1",
               NB=0, W=W, latency=1, regs=dict(y_new=W + 1, y_out=fo + 1), trace_vec=vec, n_domain=steps_dom + 1,
               stuck=stuck, S=S,
               notes="trajectory t = 0 .. %d (spec-like domain 0 .. %d; fixed point from t = %d) plus %d random "
                     "set/decay/hold cycles" % (S, steps_dom, stuck, 2 * S))
    return v.text(), ent


# ----------------------------------------------------------------------------------------------------------------
# configurations
# ----------------------------------------------------------------------------------------------------------------

def c1_smallest(role, fo):
    with open(SIZING_CSV) as fh:
        for r in csv.DictReader(fh):
            if r["case"] == ROLES[role]["sizing_case"] and int(r["fo"]) == fo and r["method"] == "C1 CORDIC":
                m = int(r["config"].split()[0])
                W = int(r["config"].split("W=")[1])
                return m, W - fo
    raise KeyError((role, fo))


def b3_smallest(role, fo):
    c = ROLES[role]["c"]
    n = np.arange(domain_max(role, fo) + 1)
    ref = M.ref_exp(n, c, fo)
    for g in range(0, 9):
        if M.error_stats(M.bitprod_exp(n, c, fo, guard=g), ref)["max_abs"] <= 1:
            return g
    raise RuntimeError("B3 does not reach max |err| <= 1")


def b4_smallest(role, fo):
    """Smallest (frac_bits, guard) of B4 (table mode) with max |err| <= 1, from sizing.csv
    ("<2^F> x <W> bit table, W=<W>")."""
    with open(SIZING_CSV) as fh:
        for r in csv.DictReader(fh):
            if r["case"] == ROLES[role]["sizing_case"] and int(r["fo"]) == fo and r["method"] == "B4 2^x table":
                m = re.match(r"(\d+) x (\d+) bit table, W=(\d+)", r["config"])
                if m:
                    F = int(m.group(1)).bit_length() - 1
                    return F, int(m.group(3)) - fo
    return None


def b3_sizing_guard(role, fo):
    with open(SIZING_CSV) as fh:
        for r in csv.DictReader(fh):
            if r["case"] == ROLES[role]["sizing_case"] and int(r["fo"]) == fo and r["method"] == "B3 bit product":
                return int(r["config"].split("W=")[1]) - fo
    return None


def error_over_domain(ent):
    """max |err| of the configuration over the spec's input domain (model output vs ref_exp)."""
    if ent["protocol"] == "trace":
        k, g, rnd = ent["params"]["k"], ent["params"]["guard"], ent["params"]["rounding"]
        steps = ent["n_domain"] - 1
        y = M.shift_decay_trace(k, steps, ent["fo"], guard=g, rounding=rnd)
        return M.error_stats(y, M.ref_exp(np.arange(steps + 1), ent["c"], ent["fo"]))["max_abs"]
    n = np.arange(ent["n_domain"])
    return M.error_stats(np.asarray(ent["y"])[: ent["n_domain"]], M.ref_exp(n, ent["c"], ent["fo"]))["max_abs"]


def write_vectors(ent):
    path = os.path.join(VEC_DIR, ent["name"] + ".hex")
    lines = []
    if ent["protocol"] == "trace":
        W, fo = ent["W"], ent["fo"]
        width = 2 + (W + 1) + (fo + 1)
        nd = (width + 3) // 4
        for st, dc, yn, yo in ent["trace_vec"]:
            word = (st << (W + 1 + fo + 1 + 1)) | (dc << (W + 1 + fo + 1)) | (yn << (fo + 1)) | yo
            lines.append("%0*x" % (nd, word))
    else:
        NB, fo = ent["NB"], ent["fo"]
        width = NB + fo + 1
        nd = (width + 3) // 4
        for i, yv in enumerate(ent["y"]):
            lines.append("%0*x" % (nd, (i << (fo + 1)) | yv))
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return os.path.relpath(path, ROOT), len(lines)


def main():
    global MODEL_SHA
    with open(MODEL_FILE, "rb") as fh:
        MODEL_SHA = hashlib.sha256(fh.read()).hexdigest()
    os.makedirs(GEN_DIR, exist_ok=True)
    os.makedirs(VEC_DIR, exist_ok=True)
    for d, ext in ((GEN_DIR, ".v"), (VEC_DIR, ".hex")):
        for f in os.listdir(d):
            if f.endswith(ext):
                os.remove(os.path.join(d, f))
    jobs = []
    warnings = []
    for role in ROLES:
        for fo in FOS:
            jobs.append(gen_lut(role, fo))
            m_s, g_s = c1_smallest(role, fo)
            k_def = M.cordic_constants(ROLES[role]["c"], fo, C1_GUARD_DEFAULT, None, C1_CONST_FRAC)
            c1_sets = [(m_s, g_s, "smallest (iterations, guard) with max error <= 1 LSB, from sizing.csv")]
            if (k_def["m"], C1_GUARD_DEFAULT) != (m_s, g_s):
                c1_sets.append((k_def["m"], C1_GUARD_DEFAULT, "model default (guard %d, iterations Fo + g + 1)"
                                % C1_GUARD_DEFAULT))
            else:
                warnings.append("C1 %s Fo=%d: the smallest setting equals the default" % (role, fo))
            for (m, g, setting) in c1_sets:
                for form in ("iter", "unrolled"):
                    jobs.append(gen_cordic(role, fo, g, m, setting, form))
            g3 = b3_smallest(role, fo)
            gs = b3_sizing_guard(role, fo)
            if gs != g3:
                warnings.append("B3 %s Fo=%d: smallest guard over the RTL domain is %d, sizing.csv says %s"
                                % (role, fo, g3, gs))
            for form in ("iter", "unrolled"):
                jobs.append(gen_bitprod(role, fo, g3, form))
            jobs.append(gen_pow2(role, fo))
            sm = b4_smallest(role, fo)
            if sm and sm != (fo + 1, B4_GUARD):
                jobs.append(gen_pow2(role, fo, g=sm[1], F=sm[0]))
    for fo in FOS:
        jobs.append(gen_shiftdecay(fo))
    manifest = []
    for text, ent in jobs:
        with open(os.path.join(GEN_DIR, ent["name"] + ".v"), "w") as fh:
            fh.write(text)
        ent["vec"], ent["n_vec"] = write_vectors(ent)
        ent["flops"] = sum(ent["regs"].values())
        # the testbenches permute the vectors with i -> (37 i + 11) mod NV, a bijection only if gcd(37, NV) = 1
        assert math.gcd(37, ent["n_vec"]) == 1, ent["name"]
        ent["max_err_domain"] = int(error_over_domain(ent))
        if ent["max_err_domain"] > 1:
            warnings.append("%s: max |err| over the spec domain is %d" % (ent["name"], ent["max_err_domain"]))
        ent["file"] = os.path.relpath(os.path.join(GEN_DIR, ent["name"] + ".v"), ROOT)
        ent.pop("y", None)
        ent.pop("trace_vec", None)
        manifest.append(ent)
    with open(os.path.join(GEN_DIR, "manifest.json"), "w") as fh:
        json.dump(dict(model_sha256=MODEL_SHA, modules=manifest, warnings=warnings), fh, indent=1)
    print("generated %d modules in %s, vectors in %s" % (len(manifest), os.path.relpath(GEN_DIR, ROOT),
                                                         os.path.relpath(VEC_DIR, ROOT)))
    for w in warnings:
        print("WARNING:", w)


MODEL_SHA = ""

if __name__ == "__main__":
    main()
