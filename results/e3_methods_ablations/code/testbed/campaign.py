"""Run one experiment campaign from a frozen copy of the code.

    python -I testbed/campaign.py prepare <campaign>     # copy model/ and testbed/ into results/<campaign>/code,
                                                         # record git commit and diff (do this before jobq add)
    python -I results/<campaign>/code/testbed/campaign.py run <campaign> [--seeds 0,1,2]

The configurations of every campaign are in testbed/campaigns.py. Each configuration x seed runs as its own process
($JOBQ_THREADS workers); results go to results/<campaign>/<config>_s<seed>.json. Running from the frozen copy means
later edits of the working tree cannot change a running campaign, and the code that produced every number is kept
next to it.
"""
import argparse
import multiprocessing as mp
import os
import shutil
import subprocess
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = "/media/amir/CORDIC"


def prepare(name):
    dst = os.path.join(REPO, "results", name)
    code = os.path.join(dst, "code")
    if os.path.exists(code):
        sys.exit(f"{code} exists; choose a new campaign name")
    os.makedirs(dst, exist_ok=True)
    for sub in ("model", "testbed"):
        shutil.copytree(os.path.join(REPO, sub), os.path.join(code, sub),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    commit = subprocess.run(["git", "-C", REPO, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    diff = subprocess.run(["git", "-C", REPO, "diff", "HEAD", "--", "model", "testbed"], capture_output=True,
                          text=True).stdout
    with open(os.path.join(dst, "CODE_VERSION.txt"), "w") as f:
        f.write(f"git commit {commit}\nuncommitted diff of model/ and testbed/ below ({len(diff)} chars)\n{diff}")
    print(code)


def run_one(job):
    name, argv = job
    sys.path.insert(0, HERE)
    import run_dc
    try:
        run_dc.main(["--name", name] + argv)
        return name, None
    except Exception:
        return name, traceback.format_exc()


def run(name, seeds, only):
    sys.path.insert(0, HERE)
    import campaigns
    cfgs = campaigns.CAMPAIGNS[name]
    out = os.path.join(REPO, "results", name)
    jobs = []
    for cfg, argv in cfgs.items():
        if only and only not in cfg:
            continue
        for s in seeds:
            if os.path.exists(os.path.join(out, f"{cfg}_s{s}.json")):
                continue                                    # resumable
            jobs.append((f"{cfg}_s{s}", argv + ["--seed", str(s), "--out", out]))
    jobs.sort(key=lambda j: -campaigns.cost(j[1]))          # longest first
    nproc = int(os.environ.get("JOBQ_THREADS", "2"))
    print(f"{len(jobs)} runs on {nproc} workers", flush=True)
    failed = []
    with mp.get_context("fork").Pool(nproc, maxtasksperchild=1) as pool:
        for nm, err in pool.imap_unordered(run_one, jobs):
            if err:
                failed.append(nm)
                print(f"FAILED {nm}\n{err}", flush=True)
    print("failed:", failed, flush=True)
    sys.exit(1 if failed else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["prepare", "run"])
    ap.add_argument("campaign")
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    if a.action == "prepare":
        prepare(a.campaign)
    else:
        run(a.campaign, [int(s) for s in a.seeds.split(",")], a.only)


if __name__ == "__main__":
    main()
