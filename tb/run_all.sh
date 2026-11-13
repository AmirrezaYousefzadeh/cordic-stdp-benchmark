#!/usr/bin/env bash
# tb/run_all.sh: regenerate the batch-1 exponential units and their vectors from the golden model, simulate every
# unit bit-exact against its vectors (Icarus Verilog), lint it (Verilator), and fail on any mismatch.
#
#   tb/run_all.sh            generate + simulate + lint; writes results/rtl/VERIFY.md and results/rtl/verify.json
#   tb/run_all.sh --synth    additionally runs the Yosys area probe (rtl/synth_probe.py, results/rtl/synth_probe.md)
#
# Light (about a minute, one process at a time; the area probe adds a few minutes). Tools pinned to the OSS CAD
# Suite 2026-10-24 (flow notes section 1). Exit status 0 only if everything passes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
export PATH="/media/hardware_design_tools/oss-cad-suite-2026-10-24/bin:$PATH"

"$PY" -I "$ROOT/rtl/gen_units.py"
"$PY" -I "$ROOT/tb/run_sims.py"
if [[ "${1:-}" == "--synth" ]]; then
    "$PY" -I "$ROOT/rtl/synth_probe.py"
fi
echo "run_all: all checks passed"
