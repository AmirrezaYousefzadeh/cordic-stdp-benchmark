"""Aggregate testbed JSON results: one row per configuration (seeds pooled), mean and standard deviation.
Usage: python -I testbed/summarize.py [results/testbed] > results/testbed/SUMMARY.md"""
import glob
import json
import os
import re
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
d = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "results", "testbed")
rows = {}
for f in sorted(glob.glob(os.path.join(d, "*.json"))):
    r = json.load(open(f))
    cfg = re.sub(r"_s\d+$", "", r["name"])
    rows.setdefault(cfg, []).append(r)


def ms(v):
    v = np.asarray(v, dtype=float) * 100
    return f"{v.mean():.2f} ± {v.std(ddof=1):.2f}" if len(v) > 1 else f"{v.mean():.2f}"


print("| configuration | seeds | test acc. % (labels: 60k frozen pass) | labels: first 10k of that pass | "
      "labels: last 10k of training | exc. spikes / test example | rate raises / test example | "
      "minutes per run |")
print("|---|---|---|---|---|---|---|---|")
for cfg, rs in rows.items():
    mins = np.mean([sum(r["seconds"].values()) for r in rs]) / 60
    sp = np.mean([r["mean_exc_spikes_per_test_example"] for r in rs])
    bumps = np.mean([r["stats_test"]["bumps"] / max(1, r["args"]["test"]) for r in rs])
    print(f"| {cfg} | {len(rs)} | {ms([r['acc_test'] for r in rs])} | {ms([r['acc_test_label10k'] for r in rs])} | "
          f"{ms([r['acc_test_label_lasttrain10k'] for r in rs])} | {sp:.1f} | {bumps:.2f} | {mins:.1f} |")
