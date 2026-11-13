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
#  Rule P: D&C's power-law rule (their main rule); its exponential is the presynaptic trace (R1).
#  Rule E: D&C's exponential weight-dependence rule with beta = 0.25, as Wu et al. 2021 (TCAS-I) use it; it has both
#          roles: the presynaptic trace (R1) and the weight-dependence factors e^(-beta w), e^(-beta (1-w)) (R2).
e2 = {"P_float": BASE + ["--rule", "power"],
      "E_float": BASE + ["--rule", "expw", "--set", "beta=0.25"]}
for fo in (2, 3, 4, 5, 6, 8):
    e2[f"P_preLUT_fo{fo}"] = BASE + ["--rule", "power", "--pre-unit", "lut", "--pre-fo", str(fo)]
    e2[f"E_preLUT_fo{fo}"] = BASE + ["--rule", "expw", "--set", "beta=0.25", "--pre-unit", "lut", "--pre-fo", str(fo)]
for fo in (2, 3, 4, 6, 8):
    e2[f"E_wLUT_fo{fo}"] = BASE + ["--rule", "expw", "--set", "beta=0.25", "--w-unit", "lut", "--w-fo", str(fo)]
CAMPAIGNS["e2_precision"] = e2

# E3: (a) do the methods differ at the accuracy knee (trace unit, Fo = 3 and 4)? Every unit is configured to its
#     smallest setting with max |error| <= 1 LSB (model/exp_units.py, c = 1/40) or to its default.
#     (b) ablations: is an exponential needed at all? beta = 0 removes the weight dependence of rule E (Wu's two
#     CORDICs per synapse); Fo = 1 trace; a box kernel of width tau instead of the exponential trace.
CORDIC_MIN = {3: (3, 1), 4: (5, 2)}            # (iterations, guard), smallest with max |err| <= 1 at c = 1/40
BITPROD_MIN_GUARD = {3: 0, 4: 1}
e3 = {}
for rule, rargs in (("E", ["--rule", "expw", "--set", "beta=0.25"]), ("P", ["--rule", "power"])):
    for fo in (3, 4):
        pre = ["--pre-fo", str(fo)]
        it, g = CORDIC_MIN[fo]
        e3[f"{rule}_preCORDIC_fo{fo}"] = BASE + rargs + ["--pre-unit", "cordic"] + pre
        e3[f"{rule}_preCORDICmin_fo{fo}"] = BASE + rargs + ["--pre-unit", "cordic", "--unit-iters", str(it),
                                                           "--unit-guard", str(g)] + pre
        e3[f"{rule}_preBITPROD_fo{fo}"] = BASE + rargs + ["--pre-unit", "bitprod", "--unit-guard",
                                                          str(BITPROD_MIN_GUARD[fo])] + pre
        e3[f"{rule}_prePOW2_fo{fo}"] = BASE + rargs + ["--pre-unit", "pow2"] + pre
    e3[f"{rule}_preLUT_fo1"] = BASE + rargs + ["--pre-unit", "lut", "--pre-fo", "1"]
    e3[f"{rule}_preRECT"] = BASE + rargs + ["--pre-unit", "rect", "--pre-fo", "1"]
e3["E_beta0"] = BASE + ["--rule", "expw", "--set", "beta=0"]
e3["E_beta0_preLUT_fo3"] = BASE + ["--rule", "expw", "--set", "beta=0", "--pre-unit", "lut", "--pre-fo", "3"]
CAMPAIGNS["e3_methods_ablations"] = e3
