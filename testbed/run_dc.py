"""Train, label and test one Diehl & Cook float-reference configuration; write a JSON result (and the trained
weights). Usage: python -I testbed/run_dc.py --name NAME [options]; see --help. Many configurations at once:
testbed/pilot.py."""
import argparse
import json
import os
import platform
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import dc_sim as S  # noqa: E402
from model import exp_units as U  # noqa: E402

UNITS = {"lut": U.lut_exp, "cordic": U.cordic_exp, "bitprod": U.bitprod_exp, "pow2": U.pow2_exp, "rect": None,
         "lutbias": None}


def unit_table(unit, c, fo, guard, iters, frac, nmax, bias=0.0):
    """Output codes of an exp unit for inputs 0..nmax-1 (the whole useful domain)."""
    if unit == "float":
        return np.zeros(0, dtype=np.int64)
    n = np.arange(nmax, dtype=np.int64)
    if unit == "lut":
        return U.lut_exp(n, c, fo)
    if unit == "cordic":
        return U.cordic_exp(n, c, fo, guard=guard, iters=iters)
    if unit == "bitprod":
        return U.bitprod_exp(n, c, fo, guard=guard)
    if unit == "pow2":
        return U.pow2_exp(n, c, fo, guard=guard, frac_bits=frac)
    if unit == "lutbias":
        # a table rounded with a deliberate offset of `bias` LSB: floor(2^fo e^(-n c) + 1/2 + bias), clamped;
        # tests whether the sign of a unit's mean error matters (E4)
        v = np.floor(np.exp(-n * c) * (1 << fo) + 0.5 + bias)
        return np.clip(v, 0, 1 << fo).astype(np.int64)
    if unit == "rect":
        # B5 ablation, no exponential at all: a box kernel of width tau (1/c steps)
        return np.where(n < int(round(1.0 / c)), 1 << fo, 0).astype(np.int64)
    raise ValueError(unit)


def git_commit():
    try:
        return subprocess.run(["git", "-C", ROOT, "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, timeout=10).stdout.strip() or None
    except Exception:
        return None


def build(args):
    prm = S.default_params()
    opt = S.default_opts()
    prm[S.DT] = args.dt
    opt[S.O_RULE] = S.RULES[args.rule]
    opt[S.O_TRACE_SET] = int(args.trace_set)
    opt[S.O_NORM] = int(args.norm)
    opt[S.O_DELAYS] = int(args.delays)
    opt[S.O_RESET] = int(args.reset)
    for kv in args.set or []:
        k, v = kv.split("=")
        prm[S.PARAM_NAMES.index(k)] = float(v)
    return prm, opt


def accuracy(counts_label, y_label, counts_test, y_test):
    assign = S.assign_labels(counts_label, y_label)
    pred = S.predict(counts_test, assign)
    return float((pred == y_test).mean()), assign


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--out", default=os.path.join(ROOT, "results", "testbed"))
    ap.add_argument("--n", type=int, default=100, help="excitatory neurons")
    ap.add_argument("--rule", default="power", choices=list(S.RULES))
    ap.add_argument("--dt", type=float, default=0.5)
    ap.add_argument("--delays", type=int, default=1)
    ap.add_argument("--reset", type=int, default=0, help="1: reset instead of the 150 ms rest")
    ap.add_argument("--norm", type=int, default=0)
    ap.add_argument("--trace-set", type=int, default=0)
    ap.add_argument("--train", type=int, default=40000, help="training examples (D&C: 40000 for N=100)")
    ap.add_argument("--label", type=int, default=60000, help="examples of the frozen labelling pass")
    ap.add_argument("--test", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--set", action="append", help="override a parameter, e.g. --set theta_plus=0.05")
    ap.add_argument("--pre-unit", default="float", choices=["float"] + list(UNITS),
                    help="exp unit of the presynaptic trace (role R1)")
    ap.add_argument("--pre-fo", type=int, default=8, help="output fraction bits of the R1 unit")
    ap.add_argument("--w-unit", default="float", choices=["float"] + list(UNITS),
                    help="exp unit of the weight dependence of the exponential rule (role R2)")
    ap.add_argument("--w-fo", type=int, default=8, help="output fraction bits of the R2 unit")
    ap.add_argument("--unit-guard", type=int, default=3)
    ap.add_argument("--unit-iters", type=int, default=None, help="CORDIC iterations (default Fo+guard+1)")
    ap.add_argument("--unit-frac", type=int, default=None, help="2^x fraction bits (default Fo+1)")
    ap.add_argument("--unit-bias", type=float, default=0.0, help="lutbias: rounding offset in LSB")
    args = ap.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    d = np.load(os.environ.get("CORDIC_DATA", "/media/amir/CORDIC/data/mnist.npz"))
    xtr, ytr, xte, yte = d["x_train"], d["y_train"], d["x_test"], d["y_test"]
    prm, opt = build(args)
    c_pre = prm[S.DT] / prm[S.TAU_PRE]
    n_pre = int(np.ceil((args.pre_fo + 2) * np.log(2) / c_pre)) + 1
    tab_pre = unit_table(args.pre_unit, c_pre, args.pre_fo, args.unit_guard, args.unit_iters,
                         args.unit_frac if args.unit_frac else args.pre_fo + 1, n_pre, args.unit_bias)
    tab_w = unit_table(args.w_unit, prm[S.BETA] / 256.0, args.w_fo, args.unit_guard, args.unit_iters,
                       args.unit_frac if args.unit_frac else args.w_fo + 1, 257, args.unit_bias)
    hist_d = np.zeros(S.HIST_D, dtype=np.int64)
    hist_w = np.zeros(257, dtype=np.int64)
    S.seed_rng(args.seed)
    W, delays, theta = S.init_network(784, args.n, prm, 1000 + args.seed)
    stats_tr = np.zeros(S.NSTAT, dtype=np.int64)
    stats_lb = np.zeros(S.NSTAT, dtype=np.int64)
    stats_te = np.zeros(S.NSTAT, dtype=np.int64)

    t0 = time.time()
    order_tr = np.arange(args.train) % 60000           # MNIST order, as the public code (j % 60000)
    counts_tr = np.zeros((args.train, args.n), dtype=np.int64)
    S.run_phase(xtr, order_tr, True, prm, opt, W, theta, delays, counts_tr, stats_tr, 2000 + args.seed,
                tab_pre, args.pre_fo, tab_w, args.w_fo, hist_d, hist_w)
    t1 = time.time()
    order_lb = np.arange(args.label) % 60000
    counts_lb = np.zeros((args.label, args.n), dtype=np.int64)
    S.run_phase(xtr, order_lb, False, prm, opt, W, theta, delays, counts_lb, stats_lb, 3000 + args.seed,
                tab_pre, args.pre_fo, tab_w, args.w_fo, np.zeros(S.HIST_D, dtype=np.int64),
                np.zeros(257, dtype=np.int64))
    t2 = time.time()
    order_te = np.arange(args.test)
    counts_te = np.zeros((args.test, args.n), dtype=np.int64)
    S.run_phase(xte, order_te, False, prm, opt, W, theta, delays, counts_te, stats_te, 4000 + args.seed,
                tab_pre, args.pre_fo, tab_w, args.w_fo, np.zeros(S.HIST_D, dtype=np.int64),
                np.zeros(257, dtype=np.int64))
    t3 = time.time()

    yl = ytr[order_lb]
    acc_full, assign = accuracy(counts_lb, yl, counts_te, yte[:args.test])
    acc_l10k, _ = accuracy(counts_lb[:10000], yl[:10000], counts_te, yte[:args.test])
    k = min(10000, args.train)
    acc_lasttrain, _ = accuracy(counts_tr[-k:], ytr[order_tr[-k:]], counts_te, yte[:args.test])
    # running training accuracy in blocks of 10000 (D&C Fig. 2C style: labels from the previous block)
    blocks = []
    for b in range(1, args.train // 10000):
        a = S.assign_labels(counts_tr[(b - 1) * 10000:b * 10000], ytr[order_tr[(b - 1) * 10000:b * 10000]])
        p = S.predict(counts_tr[b * 10000:(b + 1) * 10000], a)
        blocks.append(float((p == ytr[order_tr[b * 10000:(b + 1) * 10000]]).mean()))

    res = {
        "name": args.name, "args": vars(args),
        "params": {k_: float(prm[i]) for i, k_ in enumerate(S.PARAM_NAMES)},
        "opts": {k_: int(opt[i]) for i, k_ in enumerate(S.OPT_NAMES)},
        "acc_test": acc_full, "acc_test_label10k": acc_l10k, "acc_test_label_lasttrain10k": acc_lasttrain,
        "train_block_acc": blocks,
        "assigned_neurons": int((assign >= 0).sum()), "class_histogram": np.bincount(assign[assign >= 0],
                                                                                       minlength=10).tolist(),
        "stats_train": {k_: int(stats_tr[i]) for i, k_ in enumerate(S.STAT_NAMES)},
        "stats_label": {k_: int(stats_lb[i]) for i, k_ in enumerate(S.STAT_NAMES)},
        "stats_test": {k_: int(stats_te[i]) for i, k_ in enumerate(S.STAT_NAMES)},
        "mean_exc_spikes_per_test_example": float(counts_te.sum(1).mean()),
        "theta_mean": float(theta.mean()), "w_colsum_mean": float(W.sum(0).mean()),
        "pre_table": tab_pre.tolist(), "w_table_len": int(tab_w.shape[0]),
        # operand histograms of the training phase (trailing zeros trimmed): dt in steps at R1 evaluations,
        # weight code round(256 w) at R2 evaluations
        "hist_dt_train": np.trim_zeros(hist_d, "b").tolist(),
        "hist_wcode_train": np.trim_zeros(hist_w, "b").tolist(),
        "seconds": {"train": t1 - t0, "label": t2 - t1, "test": t3 - t2},
        "env": {"python": platform.python_version(), "numpy": np.__version__,
                "numba": __import__("numba").__version__, "host": platform.node(), "git": git_commit()},
    }
    with open(os.path.join(args.out, args.name + ".json"), "w") as f:
        json.dump(res, f, indent=1)
    np.savez_compressed(os.path.join(args.out, args.name + "_net.npz"), W=W, theta=theta)
    print(f"{args.name}: acc {acc_full:.4f} (label10k {acc_l10k:.4f}, lasttrain {acc_lasttrain:.4f}) "
          f"time {t3 - t0:.0f}s", flush=True)
    return res


if __name__ == "__main__":
    main()
