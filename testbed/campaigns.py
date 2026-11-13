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

# E4 (2026-11-13; decisions D10: Wu's rule is the main rule, D11: N = 400 only for final points):
#  (a) 10 seeds at the key points of E2/E3; (b) the biased-table test: is the sign of a unit's mean error what costs
#  accuracy (the smallest CORDIC is biased by about +0.23 LSB over the first 2 tau at Fo = 3)? (c) nearest-spike
#  traces (trace set to 1 at each presynaptic spike): an event-driven engine then needs only a timestamp and the
#  exp unit, no multiplier.
E = ["--rule", "expw", "--set", "beta=0.25"]
E0 = ["--rule", "expw", "--set", "beta=0"]
P = ["--rule", "power"]
CMIN4 = ["--pre-unit", "cordic", "--unit-iters", "5", "--unit-guard", "2", "--pre-fo", "4"]
CMIN3 = ["--pre-unit", "cordic", "--unit-iters", "3", "--unit-guard", "1", "--pre-fo", "3"]
SET = ["--trace-set", "1"]
e4 = {
    "E_float": BASE + E,
    "E_beta0": BASE + E0,
    "E_wLUT_fo2": BASE + E + ["--w-unit", "lut", "--w-fo", "2"],
    "E_preLUT_fo4": BASE + E + ["--pre-unit", "lut", "--pre-fo", "4"],
    "E_preCORDICmin_fo4": BASE + E + CMIN4,
    "E_preBITPROD_fo4": BASE + E + ["--pre-unit", "bitprod", "--unit-guard", "1", "--pre-fo", "4"],
    "E_beta0_preLUT_fo4": BASE + E0 + ["--pre-unit", "lut", "--pre-fo", "4"],
    "P_float": BASE + P,
    "P_preLUT_fo3": BASE + P + ["--pre-unit", "lut", "--pre-fo", "3"],
    "P_preCORDICmin_fo3": BASE + P + CMIN3,
    "P_preLUTbias+0.25_fo3": BASE + P + ["--pre-unit", "lutbias", "--unit-bias", "0.25", "--pre-fo", "3"],
    "P_preLUTbias-0.25_fo3": BASE + P + ["--pre-unit", "lutbias", "--unit-bias", "-0.25", "--pre-fo", "3"],
    "E_preLUTbias+0.25_fo3": BASE + E + ["--pre-unit", "lutbias", "--unit-bias", "0.25", "--pre-fo", "3"],
    "E_preLUTbias-0.25_fo3": BASE + E + ["--pre-unit", "lutbias", "--unit-bias", "-0.25", "--pre-fo", "3"],
    "E_set_float": BASE + E + SET,
    "E_set_preLUT_fo4": BASE + E + SET + ["--pre-unit", "lut", "--pre-fo", "4"],
    "E_set_preLUT_fo3": BASE + E + SET + ["--pre-unit", "lut", "--pre-fo", "3"],
    "E_set_preCORDICmin_fo4": BASE + E + SET + CMIN4,
}
CAMPAIGNS["e4_confirm"] = e4

# E5 (2026-11-13; D11 profiling): forward Euler explodes at N = 400 (more than about 23 simultaneous inhibitory
#  spikes give dt/tau * g_i > 2). Backward Euler (--implicit 1) is unconditionally stable. Does it change N = 100, and
#  does N = 400 then reach D&C's 87.0 % (power-law rule, 3 epochs)?
IMP = ["--implicit", "1"]
N400 = ["--n", "400", "--train", "180000", "--label", "60000", "--test", "10000"]
CAMPAIGNS["e5_integrator"] = {
    "E_float_implicit": BASE + E + IMP,
    "P_float_implicit": BASE + P + IMP,
    "E_N400_implicit": N400 + E + IMP,
    "P_N400_implicit": N400 + P + IMP,
}
