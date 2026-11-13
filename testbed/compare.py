"""Paired comparison of campaign configurations against a reference configuration, seed by seed.

Runs with the same seed share the initial weights, delays and the first random numbers, so the per-seed difference
removes much of the network-to-network spread. Reports mean, standard deviation, the paired mean difference with a
95 % confidence interval (t distribution) and the two-sided paired t-test p-value.

Usage: python -I testbed/compare.py results/<campaign> REF=config[,config...] [REF2=...]
Example: python -I testbed/compare.py results/e4_confirm E_float=E_ P_float=P_
  (each configuration whose name starts with the given prefix is compared with that reference)
"""
import glob
import json
import os
import re
import sys

import numpy as np
from scipy import stats


def load(d):
    runs = {}
    for f in glob.glob(os.path.join(d, "*.json")):
        r = json.load(open(f))
        m = re.match(r"(.+)_s(\d+)$", r["name"])
        runs.setdefault(m.group(1), {})[int(m.group(2))] = r["acc_test"] * 100
    return runs


def main():
    d = sys.argv[1]
    pairs = [a.split("=") for a in sys.argv[2:]]
    runs = load(d)
    print(f"| configuration | reference | n | accuracy % (mean ± sd) | paired difference (pp) | 95 % CI | p |")
    print("|---|---|---|---|---|---|---|")
    for ref, prefix in pairs:
        r = runs[ref]
        for cfg in sorted(runs):
            if not cfg.startswith(prefix):
                continue
            c = runs[cfg]
            seeds = sorted(set(c) & set(r))
            a = np.array([c[s] for s in seeds])
            if cfg == ref:
                print(f"| **{cfg}** | – | {len(a)} | {a.mean():.2f} ± {a.std(ddof=1):.2f} | – | – | – |")
                continue
            b = np.array([r[s] for s in seeds])
            diff = a - b
            n = len(diff)
            md = diff.mean()
            se = diff.std(ddof=1) / np.sqrt(n)
            h = stats.t.ppf(0.975, n - 1) * se
            p = stats.ttest_rel(a, b).pvalue
            print(f"| {cfg} | {ref} | {n} | {a.mean():.2f} ± {a.std(ddof=1):.2f} | {md:+.2f} | "
                  f"[{md - h:+.2f}, {md + h:+.2f}] | {p:.3f} |")


if __name__ == "__main__":
    main()
