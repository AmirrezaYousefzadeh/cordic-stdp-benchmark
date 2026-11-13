#!/usr/bin/env python3
"""Runs every generated unit (rtl/gen/manifest.json) against its golden-model vectors with Icarus Verilog, lints it
with Verilator, checks that the testbenches can fail (mutation self-test), and writes results/rtl/VERIFY.md and
results/rtl/verify.json. Exit status 1 on any mismatch, compile error, lint warning or self-test failure.

Called by tb/run_all.sh after rtl/gen_units.py. Light: about a minute on one core, one process at a time.
Build products (compiled simulations, logs) go to $RTL_BUILD_DIR, or to a temporary directory that is removed.
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OSS_BIN = "/media/hardware_design_tools/oss-cad-suite-2026-10-24/bin"
IVERILOG = os.path.join(OSS_BIN, "iverilog")
VVP = os.path.join(OSS_BIN, "vvp")
VERILATOR = os.path.join(OSS_BIN, "verilator")
PINNED_ICARUS = "s20260301-664"          # Icarus 14.0 devel of the OSS CAD Suite 2026-10-24 (flow notes 1)
TB = {"pipe": "tb_pipe", "iter": "tb_iter", "trace": "tb_trace"}


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def tool_versions():
    iv = run([IVERILOG, "-V"]).stdout.splitlines()[0].strip()
    vl = run([VERILATOR, "--version"]).stdout.strip()
    if PINNED_ICARUS not in iv:
        sys.exit("unexpected Icarus version: %s (pinned %s)" % (iv, PINNED_ICARUS))
    return dict(icarus=iv, verilator=vl)


def defines(ent, vec):
    d = ["-DDUT=%s" % ent["name"], "-DFO=%d" % ent["fo"], '-DVEC="%s"' % vec]
    if ent["protocol"] == "trace":
        d += ["-DW=%d" % ent["W"], "-DNV=%d" % ent["n_vec"]]
    else:
        d += ["-DNB=%d" % ent["NB"], "-DLAT=%d" % ent["latency"], "-DNV=%d" % ent["n_vec"]]
    return d


def simulate(ent, build, vec):
    """Compile and run one module; returns (passed, summary line, full log)."""
    tb = TB[ent["protocol"]]
    out = os.path.join(build, ent["name"] + ".vvp")
    comp = run([IVERILOG, "-g2005", "-Wall", "-Wno-timescale", "-s", tb, "-o", out] + defines(ent, vec)
               + [os.path.join(ROOT, "tb", tb + ".v"), os.path.join(ROOT, ent["file"])])
    log = "$ iverilog ...\n" + comp.stdout + comp.stderr
    if comp.returncode != 0:
        return False, "compile error", log
    warn = [ln for ln in (comp.stdout + comp.stderr).splitlines() if "warning" in ln.lower()]
    sim = run([VVP, "-n", out])
    log += "$ vvp ...\n" + sim.stdout + sim.stderr
    lines = [ln for ln in sim.stdout.splitlines() if ln.startswith(("PASS", "FAIL"))]
    summary = lines[-1] if lines else "no PASS/FAIL line"
    passed = sim.returncode == 0 and summary.startswith("PASS") and not warn
    if warn:
        summary += " (compiler warnings: %d)" % len(warn)
    return passed, summary, log


def lint(ent):
    """Verilator -Wall. Allowed: 'Bits of signal are not used' (low product bits below the binary point and
    rounding LSBs are discarded on purpose). Anything else (a wholly unused signal, width, latch, case, ...)
    fails. Returns (ok, number of discarded-bit notes, other messages)."""
    r = run([VERILATOR, "--lint-only", "-Wall", "-Wno-fatal", "--top-module", ent["name"],
             os.path.join(ROOT, ent["file"])])
    msgs = [ln for ln in (r.stdout + r.stderr).splitlines() if ln.startswith("%")]
    notes = [ln for ln in msgs if ln.startswith("%Warning-UNUSEDSIGNAL") and "Bits of signal are not used" in ln]
    other = [ln for ln in msgs if ln not in notes]
    return (r.returncode == 0 and not other), len(notes), other


def mutate(ent, build):
    """Flip the least significant bit of one expected value; the testbench must then fail."""
    with open(os.path.join(ROOT, ent["vec"])) as fh:
        lines = fh.read().split()
    k = len(lines) // 3
    width = len(lines[k])
    lines[k] = "%0*x" % (width, int(lines[k], 16) ^ 1)
    path = os.path.join(build, ent["name"] + "_mutant.hex")
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    passed, summary, _ = simulate(ent, build, path)
    return not passed, summary


def params_text(ent):
    p = ent["params"]
    if ent["method"] == "C1":
        return "m=%d, g=%d, W=%d" % (p["iters"], p["guard"], p["W"])
    if ent["method"] == "B3":
        return "g=%d, W=%d, b=%d" % (p["guard"], p["W"], p["b"])
    if ent["method"] == "B4":
        return "F=%d, g=%d, W=%d" % (p["frac_bits"], p["guard"], p["W"])
    if ent["method"] == "B2":
        return "k=%d, g=%d, W=%d, %s" % (p["k"], p["guard"], p["W"], p["rounding"])
    return "-"


def main():
    man = json.load(open(os.path.join(ROOT, "rtl", "gen", "manifest.json")))
    versions = tool_versions()
    build = os.environ.get("RTL_BUILD_DIR")
    tmp = None
    if not build:
        tmp = tempfile.mkdtemp(prefix="cordic_rtl_sim_")
        build = tmp
    os.makedirs(build, exist_ok=True)
    rows, fails = [], 0
    try:
        for ent in man["modules"]:
            ok, summary, log = simulate(ent, build, os.path.join(ROOT, ent["vec"]))
            lok, lnotes, lmsgs = lint(ent)
            status = "pass" if ok else "FAIL"
            print("%-36s %-4s %s%s" % (ent["name"], status, summary, "" if lok else "  LINT: %d messages" % len(lmsgs)))
            if not ok:
                print(log)
            if not lok:
                print("\n".join(lmsgs))
            fails += (not ok) + (not lok)
            rows.append(dict(name=ent["name"], method=ent["method"], form=ent["form"], role=ent["role"],
                             fo=ent["fo"], params=params_text(ent), setting=ent["setting_short"], sim=status,
                             summary=summary, lint=("clean (%d)" % lnotes) if lok else "FAIL (%d)" % len(lmsgs),
                             n_vec=ent["n_vec"], n_domain=ent["n_domain"], latency=ent["latency"],
                             max_err=ent["max_err_domain"], protocol=ent["protocol"]))
        # mutation self-test: one module per testbench must fail on a corrupted vector
        mut = []
        for proto in ("pipe", "iter", "trace"):
            ent = next(e for e in man["modules"] if e["protocol"] == proto)
            caught, summary = mutate(ent, build)
            mut.append(dict(tb=TB[proto], module=ent["name"], caught=caught, summary=summary))
            print("self-test %-8s on %-32s %s (%s)" % (TB[proto], ent["name"], "caught" if caught else "MISSED",
                                                       summary))
            fails += not caught
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    write_report(man, rows, mut, versions, fails)
    print("%d modules, %d failures" % (len(rows), fails))
    sys.exit(1 if fails else 0)


def write_report(man, rows, mut, versions, fails):
    out = os.path.join(ROOT, "results", "rtl")
    os.makedirs(out, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(os.path.join(out, "verify.json"), "w") as fh:
        json.dump(dict(date=stamp, tools=versions, model_sha256=man["model_sha256"], modules=rows, self_test=mut,
                       failures=fails), fh, indent=1)
    L = []
    L.append("# RTL verification of the batch-1 exponential units")
    L.append("")
    L.append("Generated by `tb/run_all.sh` (`tb/run_sims.py`) on %s. Overall: **%s** (%d modules, %d failures)."
             % (stamp, "PASS" if fails == 0 else "FAIL", len(rows), fails))
    L.append("")
    L.append("- RTL: `rtl/gen/*.v` from `rtl/gen_units.py`; golden model `model/exp_units.py` (sha256 `%s`)."
             % man["model_sha256"])
    L.append("- Tools: %s; %s (lint `--lint-only -Wall`)." % (versions["icarus"], versions["verilator"]))
    L.append("- Lint: 'clean (n)' means no Verilator message except n notes 'Bits of signal are not used' "
             "(product bits below the binary point and rounding LSBs, discarded on purpose); any other message "
             "(a wholly unused signal, width, latch, case, ...) fails the run.")
    L.append("- Every module is simulated through its real handshake against vectors computed by the golden model "
             "(`tb/vec/<module>.hex`), bit-exact (4-state compare) on every result, every cycle checked:")
    L.append("  - single-cycle and unrolled units (`tb/tb_pipe.v`): out_valid exactly `latency` cycles after "
             "in_valid, y on every valid output, y held while out_valid = 0; all vectors back to back, then all "
             "again in a permuted order with random idle cycles (random n while in_valid = 0); no output from "
             "inputs given during reset;")
    L.append("  - iterative units (`tb/tb_iter.v`): busy = 1 and done = 0 for cycles 1 .. latency-1 after start, "
             "done = 1 for exactly one cycle at `latency` with busy = 0 and the right y, y held until the next "
             "start; back to back (start in the done cycle), then permuted with 0-3 idle cycles and random start "
             "pulses and random n while busy (ignored); start during reset ignored;")
    L.append("  - shift-decay trace (`tb/tb_trace.v`): the testbench holds the trace and writes y_new back every "
             "cycle: set, then decay along the whole trajectory to its fixed point and beyond, then random "
             "set/decay/hold cycles; y_new (W+1 bits) and y_out checked every cycle.")
    L.append("- Vectors: R1, the whole input bus n = 0 .. 2^NB - 1 (it contains the spec's domain 0 .. "
             "ceil((Fo+2) ln2 / c), whose size is the column 'domain'; a saturating time-difference counter can "
             "present any code, and beyond the domain the model gives 0). R2, the spec's domain n = 0 .. 256 "
             "(weight codes; 257 .. 511 cannot occur, their outputs are unspecified and no unit spends logic on "
             "them). Each vector is applied twice (two phases), so 'results' = 2 x vectors.")
    L.append("- Latency in clock cycles: inputs (or start) given in cycle t give the result (out_valid, or done) "
             "in cycle t + latency. Iterative units: one result every `latency` cycles; the others: one result "
             "per cycle.")
    L.append("- max |err|: the model's error against `ref_exp` over the spec domain (for information; the RTL "
             "equals the model, so it has the same error).")
    L.append("- Mutation self-test (a testbench must fail when one expected bit is flipped): " +
             "; ".join("%s on `%s`: %s" % (m["tb"], m["module"], "caught" if m["caught"] else "**missed**")
                       for m in mut) + ".")
    L.append("")
    L.append("| module | method, form | role | Fo | parameters | setting | sim | vectors (domain) | results "
             "| latency (cycles) | lint | max \\|err\\| |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        res = r["summary"].split("results_checked=")[1].split()[0] if "results_checked=" in r["summary"] else "-"
        L.append("| `%s` | %s %s | %s | %d | %s | %s | %s | %d (%d) | %s | %d | %s | %d |"
                 % (r["name"], r["method"], r["form"], r["role"].upper(), r["fo"], r["params"], r["setting"],
                    r["sim"], r["n_vec"], r["n_domain"], res, r["latency"], r["lint"], r["max_err"]))
    L.append("")
    L.append("For `shiftdecay` the vectors are cycles of the trace (set/decay/hold), 'domain' is the number of "
             "steps t = 0 .. ceil((Fo+2) ln2 / c_eff) (the R1 domain with the unit's own c_eff), and the latency "
             "is that of one trace update.")
    if man.get("warnings"):
        L.append("")
        L.append("Generator warnings: " + "; ".join(man["warnings"]))
    with open(os.path.join(out, "VERIFY.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
