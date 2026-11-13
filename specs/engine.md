# Spec (proposal): the STDP learning engine (Level 2) for the energy comparison

Status: draft 1, 2026-11-13, **for Amir's D5 check**. Decisions are marked **[E-Dn]**, each with my recommendation.
Nothing of this is built yet.

## 1. Why a Level-2 engine

The exponential unit alone (Level 1) does not decide the comparison, for three reasons:

1. The trace can be kept in two forms, and they cost different things:
   - **Event-driven:** store the time of the last update and compute e^(−Δt/τ) on demand with an exp unit.
   - **Clock-driven:** store the trace and decay it every time step by a shift (B2). This needs no exp unit, but
     every trace is touched every step.
2. Accumulating traces (X = X·e(Δt) + 1, D&C's rule) need a multiplier; nearest-spike traces (X = 1 at a spike)
   need only the exp unit.
3. Every update also reads and writes state memory. Its energy can dwarf the unit's.

So the comparison is made on **energy per training example of the whole learning engine**, on one template. Only
two things change between variants: the exp unit and the trace form. This follows Amir's rule from the delay study:
one design, the slowest real-time clock, clock gating, and energy per example split into dynamic and static.

## 2. What the engine computes (D10: Wu's rule, β = 0.25, N = 100)

- **Pre spike of input i** (about 2 200 per training example, measured by the testbed counters):
  - accumulating traces: X_i ← X_i·e(t − t_i) + 1, t_i ← t;
  - nearest-spike traces: only t_i ← t.
- **Post spike of excitatory neuron j** (about 20 per training example): a sweep over i = 0 … 783:
  - x = X_i·e(t − t_i) (nearest-spike: x = e(t − t_i));
  - w = W[i][j];
  - w ← clip(w + η·(x·f(w) − x_tar·f(1 − w))), with f(w) = e^(−βw) (role R2) or f = 1 when β = 0;
  - W[i][j] ← w.
- **Event counts and operand histograms (Δt, weight code)** come from the testbed (`stats_train`,
  `hist_dt_train`, `hist_wcode_train` in every result file). They are used as the GLS stimulus and to scale the
  energy to a full example.

## 3. The template

- **Inputs from the network:** a FIFO of events (pre index; post index) and a global time-step counter. Δt is a
  saturating subtraction of NB-bit timestamps (NB = 8 covers Δt ≤ 255 steps = 127 ms at dt = 0.5 ms; the trace
  is 0 beyond about 140 steps at Fo = 4).
- **Datapath:**
  - time-multiplexed: **one synapse per clock cycle in a sweep, one trace per cycle for pre events**;
  - one exp unit (R1), one multiplier (accumulating traces only), the weight-update arithmetic, and the R2
    unit(s) if β ≠ 0.
- **Real-time clock:**
  - A sweep must finish within one time step (0.5 ms) to stay equivalent to the testbed: 784 cycles per 0.5 ms
    means ≥ 1.57 MHz.
  - The clock-driven form must decay 784 traces per step: also 1.57 MHz.
  - **[E-D1] Proposal:** one clock of 2 MHz for every variant, gated off whenever the engine has nothing to do. An
    iterative unit (m+1 cycles per evaluation) runs in a faster local clock domain, or the unrolled form is used;
    both forms are measured.
- **State memory (traces / timestamps), 784 words of 8–16 bits:**
  - **[E-D2]** a latch array with one `dlclkp` per row (flow notes 9.2); recommended, as in Amir's other cores;
  - or SRAM22;
  - or flip-flops.
- **Weight memory, 784 × N × 8 bit (N = 100: 627 kbit):** it is the same for every variant.
  - **[E-D3]** Recommended: do not harden it. Take its energy per read and write from the SRAM22 characterisation
    (flow notes 9.1), and report it separately, so that the share of the exp unit in the total is visible.
  - Alternative: a hardened latch array (large, slow to harden).

## 4. Variants

**[E-D4]** At the iso-accuracy precision from E2/E4 (Fo = 4 for R1) and at a common 8 bits (D4):

| # | trace form | R1 unit | multiplier | R2 |
|---|---|---|---|---|
| 1–5 | event-driven, accumulating | LUT, CORDIC iterative, CORDIC unrolled, bit product, 2^x | yes | LUT (Fo = 2) |
| 6–10 | event-driven, nearest-spike | same five | no | LUT (Fo = 2) |
| 11 | clock-driven, shift decay (B2) in the trace memory (read-modify-write of all 784 traces every step) | none | yes (accumulating) | LUT (Fo = 2) |
| 12–14 | best of 1–11 | – | – | CORDIC (as Wu 2021), LUT, none (β = 0) |

- About 14 hardening runs of a small core.
- Only the generated unit and a few muxes change between them; the template RTL is shared.

## 5. Measurement (P5/P6)

- Hardening with LibreLane 3.0.16 through `harden_ladder.sh`, sign-off at all 9 corners, the flow notes' checklist
  (section 10).
- SDF-annotated gate-level simulation of each variant on the same recorded event stream: K = 20 training examples
  from the steady state of a testbed run (the events plus Δt and weight operands, recorded once and replayed
  bit-exactly; the GLS output must match the integer model).
- OpenSTA per-pin power with measured activities; root-clock correction because the clock is gated most of the
  time (flow notes 8.2).
- Energy per training example = engine energy (dynamic + leakage over the 500 ms of an example) + weight-memory
  accesses × SRAM22 energy per access.
- Operating point: tt, 1.8 V, 25 °C. **[E-D5]** A low-voltage point (as in the delay study) only for the final
  numbers.

## 6. Decisions for Amir

| # | decision | recommendation |
|---|---|---|
| E-D1 | clock and timing template | one 2 MHz clock, gated when idle; iterative units in a faster local domain, unrolled forms measured too |
| E-D2 | trace / timestamp memory | latch array with row clock gates |
| E-D3 | weight memory | not hardened; SRAM22 per-access energy, reported separately |
| E-D4 | variants | the 14 of section 4 at Fo = 4 (and Fo = 8 for the common comparison) |
| E-D5 | voltage | 1.8 V first; low voltage only for the final numbers |
| E-D6 | trace form for the "recommended" design in the paper | decide after E4 (nearest-spike traces need no multiplier; E4 tells whether they cost accuracy) |
