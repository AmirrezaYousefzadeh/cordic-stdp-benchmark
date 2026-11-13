# Spec: RTL of the exponential units, batch 1

Status: draft 2, 2026-11-13. Draft 2 resolves the RTL agent's findings (B2 width and rounding, B4 settings,
R2 domain). Golden model: `model/exp_units.py` (spec `specs/exp_units.md`, draft 3); the RTL must
match it bit for bit. Flow rules: `/media/amir/flow_notes/skywater130_flow_notes.md` section 3.

## 1. Generation

- One Python generator, `rtl/gen_units.py`, writes one plain Verilog-2005 file per unit and configuration,
  `rtl/gen/<unit>_<cfg>.v`.
- Every constant is computed by calling the functions of `model/exp_units.py` (`cordic_constants`,
  `bitprod_constants`, `pow2_table`, `lut_exp`, ...). No constant is retyped by hand, and there are no
  `$`-functions or `real` in the RTL.
- The generator also writes test vectors from the golden model, `tb/vec/<unit>_<cfg>.hex`. They are exhaustive over
  the input domain: n = 0 … ⌈(Fo+2)·ln2/c⌉ for R1, and 0 … 256 for R2.

## 2. Interfaces (all synchronous to `clk`, active-low synchronous reset `rst_n`)

| form | ports | timing |
|---|---|---|
| single-cycle (`lut`) | `in_valid`, `n[NB-1:0]` → `out_valid`, `y[FO:0]` | registered output, latency 1 |
| iterative (`cordic_iter`, `bitprod_iter`) | `start`, `n` → `busy`, `done` (1-cycle pulse), `y` (held until the next `start`) | one iteration (C1) or one input bit (B3) per cycle; latency = iterations + fixed overhead, stated in the module header |
| unrolled (`cordic_unrolled`, `bitprod_unrolled`, `pow2`) | `in_valid`, `n` → `out_valid`, `y` | one result per cycle, registers at input and output only (combinational in between); the latency is stated in the module header |
| trace update (`shiftdecay`) | `y_old[W:0]`, `set`, `decay` → `y_new[W:0]` (registered; W+1 bits because the set value is 2^W), `y_out[FO:0]` (registered, rounded output of y_old) | latency 1; one trace update per cycle. In a learning engine the trace lives in memory, and this is the datapath that updates one trace. |

General rules:
- `n` is unsigned with NB = the bit length of the largest input.
- `y` is the Fo+1-bit output code.
- No latches, no clock gating inside the units (gating is a learning-engine decision).

## 3. Configurations for batch 1

- Roles:
  - R1: c = 1/40 (τ = 20 ms at dt = 0.5 ms, the testbed setting).
  - R2: c = 0.25/256 (β = 0.25, 8-bit weight, Wu 2021).
- Precisions: Fo ∈ {4, 6, 8, 10, 12}.
- Unit parameters per Fo:
  - C1: the smallest (iterations, guard) with max |err| ≤ 1 from `results/units/sizing.csv`, and also the default
    settings.
  - B3: the smallest guard with max |err| ≤ 1.
  - B4: table mode, at its smallest (frac_bits, guard) with max |err| ≤ 1 from `sizing.csv`, and also
    frac_bits = Fo + 1 with the model's default guard 3.
  - B2: k = 5, guard = k − 1 = 4, rounding "round" (R1 only).
- **Input domains:**
  - R1: every unit is exact on the whole input bus. A saturating Δt counter can present any code; the model gives
    0 above the useful range.
  - R2: exact on 0 … 256 (the weight code round(256·w)). Codes 257 … 511 never occur, and the LUT returns 0 for
    them.

## 4. Verification

- Icarus Verilog from the OSS CAD Suite 2026-10-24.
- Every module is checked against its vectors, bit-exact on every input, through its real handshake.
- `tb/run_all.sh` runs everything and fails on any mismatch.
- Only light runs (under a few minutes and 2 threads); anything heavier goes through `jobq`.

## 5. Early area probe (indicative only)

Yosys synthesis-only against sky130_fd_sc_hd (tt, 1.8 V): cell count and cell area per module, in
`results/rtl/synth_probe.md`. Per the flow notes this is untimed cell area without utilisation, not comparable with
hardened areas. It only shows early whether the expected ordering (LUT vs CORDIC vs bit product) holds.
