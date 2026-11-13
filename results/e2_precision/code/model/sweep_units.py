"""Unit-level experiment E1: for every method and output precision Fo, the smallest configuration whose maximum error
is at most 1 output LSB over the whole useful input range (n = 0 .. the first n whose exact value rounds to 0 at
Fo+2 bits). Roles: R1 timing kernel (c = dt/tau) and R2 weight dependence (c = beta / 2^8, 8-bit weights).
Writes results/units/sizing.csv and results/units/SIZING.md. Light: seconds on one core."""
import csv
import math
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from model.exp_units import (bitprod_exp, cordic_exp, error_stats, lut_exp, pow2_exp, ref_exp,  # noqa: E402
                             shift_decay_c_eff, shift_decay_trace)

CASES = {  # name: (role, c)
    "R1 tau=20 steps (dt 1 ms)": ("R1", 1 / 20),
    "R1 tau=40 steps (dt 0.5 ms)": ("R1", 1 / 40),
    "R2 beta=0.25, 8-bit w (Wu 2021)": ("R2", 0.25 / 256),
    "R2 beta=3, 8-bit w": ("R2", 3 / 256),
}
FOS = [4, 5, 6, 8, 10, 12, 16]


def domain(c, fo, role):
    nmax = math.ceil((fo + 2) * math.log(2) / c)
    if role == "R2":
        nmax = min(nmax, 255)          # an 8-bit weight code
    return np.arange(nmax + 1)


def main():
    out = os.path.join(ROOT, "results", "units")
    os.makedirs(out, exist_ok=True)
    rows = []
    for case, (role, c) in CASES.items():
        for fo in FOS:
            n = domain(c, fo, role)
            ref = ref_exp(n, c, fo)
            nz = int(np.argmax(ref == 0)) if (ref == 0).any() else len(n)
            rows.append(dict(case=case, fo=fo, method="B1 LUT", config=f"{nz} non-zero entries x {fo + 1} bit",
                             cost=nz * (fo + 1), max_err=0, mean_err=0.0))
            # C1: smallest iteration count m (then guard) with max error <= 1
            best = None
            for m in range(2, fo + 10):
                for g in range(0, 6):
                    s = error_stats(cordic_exp(n, c, fo, guard=g, iters=m), ref)
                    if s["max_abs"] <= 1:
                        best = (m, g, s)
                        break
                if best:
                    break
            if best:
                m, g, s = best
                rows.append(dict(case=case, fo=fo, method="C1 CORDIC", config=f"{m} iterations, W={fo + g}",
                                 cost=m, max_err=s["max_abs"], mean_err=s["mean_abs"]))
            for g in range(0, 6):
                s = error_stats(bitprod_exp(n, c, fo, guard=g), ref)
                if s["max_abs"] <= 1:
                    b = max(1, int(n.max()).bit_length())
                    rows.append(dict(case=case, fo=fo, method="B3 bit product",
                                     config=f"{b} constants, W={fo + g}", cost=b, max_err=s["max_abs"],
                                     mean_err=s["mean_abs"]))
                    break
            for mode in ("table", "linear"):
                found = None
                for F in range(1, fo + 4):
                    for g in range(0, 6):
                        s = error_stats(pow2_exp(n, c, fo, guard=g, frac_bits=F, mode=mode), ref)
                        if s["max_abs"] <= 1:
                            found = (F, g, s)
                            break
                    if found:
                        break
                if found:
                    F, g, s = found
                    rows.append(dict(case=case, fo=fo, method=f"B4 2^x {mode}",
                                     config=(f"{2 ** F} x {fo + g} bit table" if mode == "table" else f"F={F}")
                                     + f", W={fo + g}", cost=2 ** F if mode == "table" else F,
                                     max_err=s["max_abs"], mean_err=s["mean_abs"]))
                else:
                    rows.append(dict(case=case, fo=fo, method=f"B4 2^x {mode}", config="not reached (F <= Fo+3)",
                                     cost=None, max_err=None, mean_err=None))
    # B2: only meaningful for the timing role with tau = 2^k steps (its own c_eff)
    for k in (4, 5):
        ce = shift_decay_c_eff(k)
        for fo in FOS:
            steps = math.ceil((fo + 2) * math.log(2) / ce)
            ref = ref_exp(np.arange(steps + 1), ce, fo)
            for rd in ("floor", "round"):
                for g in range(0, 8):
                    s = error_stats(shift_decay_trace(k, steps, fo, guard=g, rounding=rd), ref)
                    if s["max_abs"] <= 1:
                        rows.append(dict(case=f"R1 B2 tau_eff={1 / ce:.2f} steps (k={k})", fo=fo,
                                         method=f"B2 shift decay ({rd})", config=f"register W={fo + g}",
                                         cost=fo + g, max_err=s["max_abs"], mean_err=s["mean_abs"]))
                        break
                else:
                    rows.append(dict(case=f"R1 B2 tau_eff={1 / ce:.2f} steps (k={k})", fo=fo,
                                     method=f"B2 shift decay ({rd})", config="not reached (W <= Fo+7)",
                                     cost=None, max_err=None, mean_err=None))
    with open(os.path.join(out, "sizing.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(out, "SIZING.md"), "w") as f:
        f.write("# Unit sizing for max |error| <= 1 output LSB (model/sweep_units.py)\n\n")
        for case in dict.fromkeys(r["case"] for r in rows):
            f.write(f"## {case}\n\n| Fo | method | smallest configuration | mean |err| (LSB) |\n|---|---|---|---|\n")
            for r in rows:
                if r["case"] == case:
                    me = "" if r["mean_err"] is None else f"{r['mean_err']:.3f}"
                    f.write(f"| {r['fo']} | {r['method']} | {r['config']} | {me} |\n")
            f.write("\n")
    print(open(os.path.join(out, "SIZING.md")).read())


if __name__ == "__main__":
    main()
