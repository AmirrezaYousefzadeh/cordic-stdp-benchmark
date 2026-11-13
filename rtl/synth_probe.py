#!/usr/bin/env python3
"""Early area probe of the batch-1 exponential units (specs/rtl_units.md section 5): Yosys synthesis only against
sky130_fd_sc_hd, tt corner (25 C, 1.8 V). INDICATIVE ONLY: untimed cell area without utilisation, not comparable
with hardened areas (flow notes, section 4).

For every module of rtl/gen/manifest.json, two cell sets:
  plain     the spec's recipe: synth -top X; dfflibmap -liberty LIB; abc -liberty LIB; stat -liberty LIB
  librelane the same commands with -dont_use for every cell that LibreLane 3.0.16 keeps out of synthesis on this
            PDK (no_synth.cells and drc_exclude.cells of sky130_fd_sc_hd): no lpflow isolation cells, no drive-0/1
            logic cells, no enable or scan flip-flops, no full/half adders
Also counts flip-flops and latches and compares the flip-flop count with what the RTL declares.

Writes results/rtl/synth_probe.md and results/rtl/synth_probe.json. Light: about a minute, one Yosys at a time.
Run: .venv/bin/python -I rtl/synth_probe.py
"""
import datetime
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
YOSYS = "/media/hardware_design_tools/oss-cad-suite-2026-10-24/bin/yosys"
PDK = "/media/pdk/sky130_8afc834"
PDK_PIN = "8afc8346a57fe1ab7934ba5a6056ea8b43078e71"
LIB = PDK + "/sky130A/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib"
EXCL = [PDK + "/sky130A/libs.tech/openlane/sky130_fd_sc_hd/no_synth.cells",
        PDK + "/sky130A/libs.tech/openlane/sky130_fd_sc_hd/drc_exclude.cells"]
FLOP = re.compile(r"sky130_fd_sc_hd__(df|edf|sdf|sedf)")
LATCH = re.compile(r"sky130_fd_sc_hd__(dl[xr]|dlclkp|sdlclkp|lpflow_inputisolatch)")
TIMEOUT_S = 600


def yosys_env():
    """One ABC process at a time (machine rule: at most 2 threads), and a short TMPDIR: this Yosys (0.70+219) talks
    to ABC through a pipe and waits for a 'YOSYS_ABC_DONE' marker at the end of its ABC script; when the script
    exceeds about 1 KiB, which a long temporary path (it appears six times) is enough for, the marker never comes
    and Yosys hangs forever (seen with TMPDIR = a 75-character path; /tmp works)."""
    env = dict(os.environ, YOSYS_MAX_THREADS="1")
    if len(env.get("TMPDIR", "/tmp")) > 32:
        env["TMPDIR"] = "/tmp"
    return env


def check_versions():
    with open(PDK + "/sky130A/SOURCES") as fh:
        src = fh.read()
    if PDK_PIN not in src:
        sys.exit("unexpected PDK version in %s/sky130A/SOURCES" % PDK)
    return subprocess.run([YOSYS, "-V"], capture_output=True, text=True).stdout.strip(), src.split()[1][:7]


def dont_use_list():
    cells = []
    for f in EXCL:
        with open(f) as fh:
            cells += [ln.strip() for ln in fh if ln.strip() and not ln.startswith("#")]
    return sorted(set(cells))


def synth(ent, variant, excl, build):
    du = "".join(" -dont_use %s" % c for c in excl) if variant == "librelane" else ""
    js = os.path.join(build, "%s_%s.json" % (ent["name"], variant))
    net = os.path.join(build, "%s_%s_net.v" % (ent["name"], variant))
    script = os.path.join(build, "%s_%s.ys" % (ent["name"], variant))
    with open(script, "w") as fh:
        fh.write("read_verilog %s\n" % os.path.join(ROOT, ent["file"]))
        fh.write("synth -top %s\n" % ent["name"])
        fh.write("dfflibmap -liberty %s%s\n" % (LIB, du))
        fh.write("abc -liberty %s%s\n" % (LIB, du))
        fh.write("opt_clean\n")
        fh.write("write_verilog -noattr %s\n" % net)   # before -purge: register names stay the nets' names
        fh.write("opt_clean -purge\n")
        fh.write("tee -q -o %s stat -json -liberty %s\n" % (js, LIB))
    t0 = time.time()
    p = subprocess.Popen([YOSYS, "-q", "-l", os.path.join(build, "%s_%s.log" % (ent["name"], variant)), "-s", script],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=yosys_env(),
                         start_new_session=True)
    try:
        out, err = p.communicate(timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        os.killpg(p.pid, signal.SIGKILL)          # Yosys and its ABC child processes
        p.communicate()
        raise RuntimeError("yosys timed out after %d s on %s (%s)" % (TIMEOUT_S, ent["name"], variant))
    dt = time.time() - t0
    if p.returncode != 0:
        raise RuntimeError("yosys failed on %s (%s):\n%s%s" % (ent["name"], variant, out, err))
    d = json.load(open(js))["design"]
    types = d["num_cells_by_type"]
    flops = sum(v for k, v in types.items() if FLOP.match(k))
    latches = sum(v for k, v in types.items() if LATCH.match(k))
    if excl and variant == "librelane":
        used = [k for k in types if k in excl]
        assert not used, "excluded cells used: %s" % used
    unmapped = [k for k in types if not k.startswith("sky130_fd_sc_hd__")]
    present = flop_outputs(net)
    assert len(present) == flops, (ent["name"], variant, len(present), flops)
    declared = {("%s[%d]" % (r, b)) if w > 1 else r for r, w in ent["regs"].items() for b in range(w)}
    return dict(cells=d["num_cells"], area=d["area"], seq_area=d["sequential_area"], flops=flops, latches=latches,
                unmapped=unmapped, seconds=dt, lpflow=sum(v for k, v in types.items() if "lpflow" in k),
                extra=sorted(present - declared), removed=sorted(declared - present))


def flop_outputs(netlist):
    """Nets driven by the Q pins of the flip-flops of a Yosys netlist (register bit names such as n_r[3])."""
    with open(netlist) as fh:
        text = fh.read()
    out = set()
    for m in re.finditer(r"(sky130_fd_sc_hd__\w+)\s+\S+\s*\((.*?)\);", text, re.S):
        if FLOP.match(m.group(1)):
            q = re.search(r"\.Q\(\s*\\?([^\s)]+(?:\s*\[\d+\])?)\s*\)", m.group(2))
            out.add(re.sub(r"\s+", "", q.group(1)))
    return out


def bits_text(bits):
    """Compact list of register bits: n_r[0], n_r[1], n_r[2] -> n_r[2:0]."""
    groups = {}
    for b in bits:
        m = re.match(r"(.*)\[(\d+)\]$", b)
        name, idx = (m.group(1), int(m.group(2))) if m else (b, None)
        groups.setdefault(name, []).append(idx)
    parts = []
    for name, idx in sorted(groups.items()):
        if idx == [None]:
            parts.append(name)
            continue
        idx = sorted(idx)
        runs, start = [], idx[0]
        for a, b in zip(idx, idx[1:] + [None]):
            if b != a + 1:
                runs.append("%s[%d]" % (name, a) if a == start else "%s[%d:%d]" % (name, a, start))
                start = b
        parts += runs
    return ", ".join(parts)


def main():
    man = json.load(open(os.path.join(ROOT, "rtl", "gen", "manifest.json")))
    yosys_v, pdk_v = check_versions()
    excl = dont_use_list()
    build = os.environ.get("RTL_BUILD_DIR")
    tmp = None
    if not build:
        tmp = tempfile.mkdtemp(prefix="cordic_rtl_synth_")
        build = tmp
    os.makedirs(build, exist_ok=True)
    rows = []
    t0 = time.time()
    try:
        for ent in man["modules"]:
            res = {v: synth(ent, v, excl, build) for v in ("plain", "librelane")}
            rows.append(dict(ent=ent, res=res))
            print("%-34s plain %5d cells %9.1f um2 | librelane %5d cells %9.1f um2 | flops %d/%d (rtl %d)"
                  % (ent["name"], res["plain"]["cells"], res["plain"]["area"], res["librelane"]["cells"],
                     res["librelane"]["area"], res["plain"]["flops"], res["librelane"]["flops"], ent["flops"]))
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
    total = time.time() - t0
    write_report(man, rows, yosys_v, pdk_v, total, len(excl))
    bad = [r["ent"]["name"] for r in rows
           if any(x["latches"] or x["unmapped"] or x["extra"] for x in r["res"].values())]
    print("probe done in %.0f s; %s" % (total, "latches, unmapped cells or registers the RTL does not declare in: %s"
                                        % bad if bad else "no latches; every flip-flop is a declared register bit"))
    sys.exit(1 if bad else 0)


ORDER = {"B1": 0, "C1": 1, "B3": 2, "B4": 3, "B2": 4}
FORM = {"single-cycle": "ROM", "iterative": "iter", "unrolled": "unrolled", "trace update": "trace update"}


def label(e):
    p = e["params"]
    if e["method"] == "C1":
        return "C1 %s, m=%d g=%d%s" % (FORM[e["form"]], p["iters"], p["guard"],
                                      " (smallest)" if e["setting"].startswith("smallest") else " (default)")
    if e["method"] == "B3":
        return "B3 %s, g=%d" % (FORM[e["form"]], p["guard"])
    if e["method"] == "B4":
        return "B4 table, F=%d g=%d" % (p["frac_bits"], p["guard"])
    if e["method"] == "B2":
        return "B2 shift decay, k=%d g=%d" % (p["k"], p["guard"])
    return "B1 LUT"


def write_report(man, rows, yosys_v, pdk_v, total, n_excl):
    out = os.path.join(ROOT, "results", "rtl")
    os.makedirs(out, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    data = []
    for r in rows:
        e = r["ent"]
        data.append(dict(module=e["name"], method=e["method"], form=e["form"], role=e["role"], fo=e["fo"],
                         label=label(e), latency=e["latency"], rtl_flops=e["flops"], **{
                             "%s_%s" % (v, k): r["res"][v][k] for v in ("plain", "librelane")
                             for k in ("cells", "area", "seq_area", "flops", "latches", "lpflow")}))
    with open(os.path.join(out, "synth_probe.json"), "w") as fh:
        json.dump(dict(date=stamp, yosys=yosys_v, pdk="open_pdks " + pdk_v, liberty=os.path.basename(LIB),
                       model_sha256=man["model_sha256"], rows=data), fh, indent=1)
    L = ["# Early area probe of the batch-1 exponential units (INDICATIVE ONLY)", ""]
    L.append("**Untimed Yosys/ABC cell area, synthesis only, without utilisation, placement, clock tree or "
             "buffering. Not comparable with hardened areas (flow notes, section 4). It only shows early whether "
             "the expected ordering (LUT vs CORDIC vs bit product) holds.**")
    L.append("")
    L.append("Generated by `rtl/synth_probe.py` on %s (%.0f s). %s; liberty `%s` of open_pdks `%s` "
             "(sky130_fd_sc_hd, tt, 25 C, 1.8 V). RTL `rtl/gen/*.v` from model sha256 `%s`."
             % (stamp, total, yosys_v.split(" (")[0], os.path.basename(LIB), pdk_v, man["model_sha256"][:16]))
    L.append("")
    L.append("Two cell sets, same commands (`read_verilog; synth -top X; dfflibmap -liberty LIB; "
             "abc -liberty LIB; opt_clean -purge; stat -liberty LIB`):")
    L.append("- **plain**: the spec's recipe, every cell of the liberty. ABC then also uses `lpflow` isolation "
             "cells (`lpflow_isobufsrc`, which the PDK keeps out of synthesis and place-and-route; in %d of %d "
             "modules) and drive-0/1 cells." % (sum(1 for d in data if d["plain_lpflow"]), len(data)))
    L.append("- **LibreLane set**: `-dont_use` for the %d cells of the PDK's `no_synth.cells` and "
             "`drc_exclude.cells`, which LibreLane 3.0.16 excludes from synthesis: drive-2 and larger logic cells, "
             "no enable or scan flip-flops, no full/half adders. Closer to what a hardened run starts from; the "
             "flow notes' remedy A (drive-1 cells allowed) would land in between." % n_excl)
    L.append("")
    L.append("Columns: area in um^2 (sum of liberty cell areas), cells = standard cells, seq = flip-flop area. "
             "Flip-flops: the synthesised count (both sets) against what the RTL declares; no latches anywhere "
             "(checked). Latency in clock cycles (results/rtl/VERIFY.md).")
    L.append("")
    # summary at each Fo, LibreLane set, per role
    for role in ("r1", "r2"):
        L.append("## Summary, role %s, LibreLane cell set: area in um^2 (cells)" % role.upper())
        L.append("")
        fos = sorted({d["fo"] for d in data if d["role"] == role})
        labels = []
        for d in sorted((d for d in data if d["role"] == role),
                        key=lambda d: (ORDER[d["method"]], d["form"], "default" in d["label"])):
            key = re.sub(r", (m|g|F|k)=.*", "", d["label"]) + (
                " (smallest)" if "(smallest)" in d["label"] else " (default)" if "(default)" in d["label"] else "")
            if key not in labels:
                labels.append(key)
        L.append("| unit | " + " | ".join("Fo=%d" % f for f in fos) + " |")
        L.append("|---|" + "---|" * len(fos))
        for key in labels:
            cells = []
            for f in fos:
                m = [d for d in data if d["role"] == role and d["fo"] == f and
                     re.sub(r", (m|g|F|k)=.*", "", d["label"]) + (
                         " (smallest)" if "(smallest)" in d["label"] else " (default)" if "(default)" in d["label"]
                         else "") == key]
                cells.append("%.0f (%d)" % (m[0]["librelane_area"], m[0]["librelane_cells"]) if m else "-")
            L.append("| %s | %s |" % (key, " | ".join(cells)))
        L.append("")
    L.append("B2 is the datapath that updates one stored trace per cycle (the trace storage itself is not included; "
             "it needs W + 1 bits per trace). It is not an exponential unit and only compares at learning-engine "
             "level (planning.md 5.1, Level 2).")
    L.append("")
    L.append("## All modules")
    L.append("")
    L.append("| module | unit | role | Fo | latency | plain area | plain cells | LibreLane area | LibreLane cells "
             "| LibreLane seq | flip-flops synth/RTL |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for d in data:
        ff = "%d / %d" % (d["librelane_flops"], d["rtl_flops"])
        if d["plain_flops"] != d["librelane_flops"]:
            ff += " (plain %d)" % d["plain_flops"]
        L.append("| `%s` | %s | %s | %d | %d | %.1f | %d | %.1f | %d | %.1f | %s |"
                 % (d["module"], d["label"], d["role"].upper(), d["fo"], d["latency"], d["plain_area"],
                    d["plain_cells"], d["librelane_area"], d["librelane_cells"], d["librelane_seq_area"], ff))
    L.append("")
    same = [r for r in rows if not any(x["removed"] or x["extra"] for x in r["res"].values())]
    L.append("Flip-flops are checked by name in the synthesised netlists: every flip-flop drives a register bit the "
             "RTL declares (no duplicated or re-encoded registers; no latches). %d of %d modules keep all declared "
             "register bits. In the others Yosys removed register bits that are constant or never affect the "
             "output (low bits of `n_r` that vanish in a rounding or a multiplication by K = 2^W in R2, where "
             "c = 2^-10; the top bit of `y` where the result never reaches 2^Fo), or merged a bit of `y` that "
             "always equals another one (R2 at small Fo, whose outputs all lie in [2^Fo e^-0.25, 2^Fo] or are 0):"
             % (len(same), len(rows)))
    for r in rows:
        if r not in same:
            rm = {v: bits_text(x["removed"]) for v, x in r["res"].items()}
            L.append("- `%s`: %d declared, %d synthesised; removed or merged: %s%s" % (
                r["ent"]["name"], r["ent"]["flops"], r["res"]["librelane"]["flops"], rm["librelane"] or "none",
                "" if rm["plain"] == rm["librelane"] else " (plain set: %s)" % (rm["plain"] or "none")))
    bad = [r for r in rows if any(x["extra"] for x in r["res"].values())]
    if bad:
        L.append("")
        L.append("**Registers the RTL does not declare: %s.**" % "; ".join(
            "%s: %s" % (r["ent"]["name"], bits_text(r["res"]["librelane"]["extra"] + r["res"]["plain"]["extra"]))
            for r in bad))
    with open(os.path.join(out, "synth_probe.md"), "w") as fh:
        fh.write("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
