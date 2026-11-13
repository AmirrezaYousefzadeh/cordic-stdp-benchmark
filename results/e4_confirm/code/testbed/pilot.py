"""P2 pilot: validate the float D&C reference against the published numbers and measure the effect of the planned
speed-ups (1 ms step, reset instead of rest, no delays). Runs every configuration x seed as its own process, using
$JOBQ_THREADS workers. Usage: python -I testbed/pilot.py [--only SUBSTRING] [--seeds 0,1,2]"""
import argparse
import multiprocessing as mp
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

# name -> run_dc arguments (seed added per run). N = 100, 40 000 training examples (D&C), labels from a frozen
# pass over the 60 000 training examples, 10 000 test examples.
CONFIGS = {
    "P_faithful":   ["--rule", "power"],
    "P_norm":       ["--rule", "power", "--norm", "1"],
    "P_dt1_reset":  ["--rule", "power", "--dt", "1.0", "--reset", "1"],
    "P_dt1_reset_nodelay": ["--rule", "power", "--dt", "1.0", "--reset", "1", "--delays", "0"],
    "E_beta3":      ["--rule", "expw", "--set", "beta=3"],
    "E_beta0.25":   ["--rule", "expw", "--set", "beta=0.25"],
    "T_code":       ["--rule", "triplet", "--norm", "1", "--trace-set", "1"],
    "PP_prepost":   ["--rule", "prepost"],
}
N400 = {"P_faithful_N400": ["--rule", "power", "--n", "400", "--train", "180000"]}


def run_one(job):
    name, argv = job
    import run_dc
    try:
        run_dc.main(["--name", name] + argv)
        return name, None
    except Exception:
        return name, traceback.format_exc()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--with-n400", type=int, default=1)
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(",")]
    jobs = []
    if a.with_n400:
        for name, argv in N400.items():          # longest first
            jobs.append((f"{name}_s0", argv + ["--seed", "0"]))
    for name, argv in CONFIGS.items():
        if a.only in name:
            for s in seeds:
                jobs.append((f"{name}_s{s}", argv + ["--seed", str(s)]))
    nproc = int(os.environ.get("JOBQ_THREADS", "2"))
    print(f"{len(jobs)} runs on {nproc} workers", flush=True)
    ctx = mp.get_context("fork")
    failed = []
    with ctx.Pool(nproc, maxtasksperchild=1) as pool:
        for name, err in pool.imap_unordered(run_one, jobs):
            if err:
                failed.append(name)
                print(f"FAILED {name}\n{err}", flush=True)
    print("failed:", failed, flush=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
