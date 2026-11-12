"""Experiment campaigns: config name -> run_dc.py arguments (campaign.py adds --seed and --out).

All campaigns use the validated float-reference settings (pilot, 2026-11-13): dt 0.5 ms, 150 ms rest, input delays,
D&C parameters, N = 100 excitatory neurons, 40 000 training examples, labels from a frozen pass over 60 000 training
examples, 10 000 test examples.
"""

BASE = ["--n", "100", "--train", "40000", "--label", "60000", "--test", "10000"]


def cost(argv):
    """Relative run time, for scheduling the longest runs first."""
    def get(flag, default):
        return float(argv[argv.index(flag) + 1]) if flag in argv else default
    n = get("--n", 100)
    return n * (get("--train", 40000) + 0.5 * get("--label", 60000) + 0.5 * get("--test", 10000))


CAMPAIGNS = {}

# E2: where is the accuracy knee? Ideal units (LUT = exact rounding) at decreasing output precision.
#  R1: the presynaptic trace of the power-law rule (D&C's main rule) through an event-driven unit of Fo bits.
#  R2: both weight-dependence factors of the exponential rule (beta = 3) through a unit of Fo bits.
e2 = {"P_float": BASE + ["--rule", "power"],
      "E3_float": BASE + ["--rule", "expw", "--set", "beta=3"]}
for fo in (2, 3, 4, 5, 6, 8):
    e2[f"P_preLUT_fo{fo}"] = BASE + ["--rule", "power", "--pre-unit", "lut", "--pre-fo", str(fo)]
for fo in (2, 3, 4, 6, 8):
    e2[f"E3_wLUT_fo{fo}"] = BASE + ["--rule", "expw", "--set", "beta=3", "--w-unit", "lut", "--w-fo", str(fo)]
CAMPAIGNS["e2_precision"] = e2
