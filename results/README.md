# Results so far (2026-11-13, updated in the afternoon with E4 and E5)

For Amir and Edris. Plan: `planning.md`. Reasoning and log: `claude_toughts.md`. Every number below comes from a
script in this repository (private GitHub `AmirrezaYousefzadeh/cordic-stdp-benchmark`) and can be rerun.

**Caveat:** these are **screening results with 3 seeds** at N = 100 excitatory neurons. Differences under about
1.5 pp are within the seed spread. The final figures will use 10 seeds (planning.md D4).

## 1. The testbed (P2): Diehl & Cook network, float reference

Spec: `specs/testbed.md`; numbers: `testbed/SUMMARY.md`. All runs: N = 100, 40 000 training examples, MNIST test
accuracy.

| learning rule | accuracy % |
|---|---|
| exponential weight dependence, β = 0.25 (**Wu 2021's rule and setting**) | **83.3 ± 1.3** |
| pre-and-post (Diehl & Cook eqs. 5–6) | 81.0 ± 1.0 |
| exponential weight dependence, β = 3 | 78.9 ± 0.6 |
| power-law (Diehl & Cook's main rule) | 78.0 ± 0.6 |
| triplet + normalisation (the rule of D&C's public code) | 66.9 ± 3.2 |

- Diehl & Cook report 82.9 % for N = 100. Wu's rule reaches it.
- The power-law rule is about 5 pp lower with the parameters left in the public code, because D&C retuned two
  parameters for N = 100 without publishing them.
- **Proposal:** Wu's rule is the primary testbed rule. It contains both uses of the exponential: the trace decay
  e^(−Δt/τ) and the weight dependence e^(−βw).
- A 1 ms time step makes the forward-Euler integration unstable (accuracy at chance level), so the testbed uses
  0.5 ms, as the original.
- One run takes about 3.3 min on one CPU core.

## 2. How much precision does the exponential need? (E2, ideal units = exactly rounded table)

Numbers: `e2_precision/SUMMARY.md`.

| output bits Fo | power-law rule, trace unit | Wu's rule, trace unit | Wu's rule, weight-dependence unit |
|---|---|---|---|
| float | 78.0 ± 0.6 | 83.3 ± 1.3 | 83.3 ± 1.3 |
| 8 | 78.1 ± 0.6 | 82.9 ± 1.1 | 82.1 ± 0.7 |
| 6 | 78.6 ± 1.0 | 82.7 ± 1.2 | 82.3 ± 0.6 |
| 4 | 79.0 ± 0.3 | 81.8 ± 0.5 | 82.9 ± 0.6 |
| 3 | 76.2 ± 0.8 | 82.7 ± 0.2 | 82.2 ± 0.6 |
| 2 | 74.9 ± 1.5 | 80.6 ± 0.2 | 83.9 ± 0.9 |

- **The trace exponential needs only about 4 output bits.**
- **Wu's weight-dependence exponential works at 2 bits, where it is just "1 or 0.75".**

## 3. Do the methods differ at the knee, and is an exponential needed at all? (E3)

Numbers: `e3_methods_ablations/SUMMARY.md`. Every unit is set to max |error| ≤ 1 LSB; "smallest" is the cheapest
such setting.

| trace unit | power-law, Fo = 3 | power-law, Fo = 4 | Wu's rule, Fo = 3 | Wu's rule, Fo = 4 |
|---|---|---|---|---|
| exact table (LUT) | 76.2 ± 0.8 | 79.0 ± 0.3 | 82.7 ± 0.2 | 81.8 ± 0.5 |
| CORDIC, default iterations | 77.0 ± 1.6 | 77.2 ± 1.3 | 81.1 ± 1.6 | 82.4 ± 0.2 |
| CORDIC, smallest | **70.3 ± 1.0** | **75.4 ± 1.6** | 79.9 ± 1.1 | 81.7 ± 0.3 |
| bit-selected constant product | 77.7 ± 1.3 | 80.4 ± 1.4 | 82.6 ± 0.5 | 82.9 ± 0.4 |
| 2^x by shift + table | 76.7 ± 1.2 | 78.9 ± 0.3 | 82.3 ± 0.7 | 82.4 ± 1.1 |

Ablations (Wu's rule unless stated):

| variant | accuracy % |
|---|---|
| **no weight-dependence exponential at all (β = 0)** | **81.9 ± 0.8** |
| β = 0 and a 3-bit trace table | 82.4 ± 1.7 |
| trace at 1 bit | 79.6 ± 1.3 |
| box kernel instead of an exponential trace | 70.7 ± 1.0 (power-law: 46.2 ± 1.1) |

Findings:
1. **Wu 2021's weight-dependence exponential may not be needed at all.** Wu 2021 spends two CORDIC units per synapse
   on it (533 LUTs per synapse). Removing it costs at most about 1 pp here, which is within the spread of 3 seeds.
   To be confirmed with 10 seeds.
2. **The trace needs an exponential, but a coarse one.** A box kernel loses 12–32 pp; 3–4 bits are enough.
3. **"Max error ≤ 1 LSB" is not enough to make units equivalent.** The cheapest CORDIC loses 3–6 pp on the
   power-law rule. Its error is biased upward in the first two time constants (+0.23 LSB on average at 3 bits), so
   an accumulating trace decays too slowly. The bit product is biased downward (−0.2 LSB) and does not hurt.
   Every method therefore has to be compared at network-level iso-accuracy, as planned, not at a unit-level error
   bound. This is a hypothesis, to be tested with a deliberately biased table.

## 3b. Confirmation with 10 seeds, the bias test, nearest-spike traces (E4)

Numbers: `e4_confirm/PAIRED.md`. Each configuration is compared with its float reference seed by seed: same
initial weights and delays, 10 seeds, paired t-test.

| configuration | accuracy % | vs float (pp) | 95 % CI | p |
|---|---|---|---|---|
| **Wu's rule, float** | 82.79 ± 1.02 | – | – | – |
| trace: LUT, 4 bits | 82.59 ± 0.87 | −0.20 | [−1.36, +0.95] | 0.70 |
| trace: bit product, 4 bits | 83.38 ± 0.80 | +0.58 | [−0.58, +1.75] | 0.29 |
| trace: cheapest CORDIC, 4 bits | 81.08 ± 0.70 | **−1.71** | [−2.47, −0.95] | 0.001 |
| weight dependence: LUT, 2 bits | 83.67 ± 1.15 | +0.88 | [+0.15, +1.61] | 0.02 |
| no weight dependence (β = 0) | 81.49 ± 0.72 | **−1.30** | [−1.88, −0.72] | 0.001 |
| β = 0 and trace LUT 4 bits | 82.33 ± 0.83 | −0.46 | [−1.12, +0.20] | 0.15 |
| trace LUT 3 bits, biased +0.25 LSB | 79.84 ± 1.33 | **−2.95** | [−4.30, −1.61] | 0.001 |
| trace LUT 3 bits, biased −0.25 LSB | 84.04 ± 0.53 | +1.24 | [+0.40, +2.09] | 0.009 |
| nearest-spike trace, float | 77.60 ± 1.21 | **−5.19** | [−6.38, −4.00] | < 0.001 |
| nearest-spike trace, LUT 4 bits | 77.77 ± 0.64 | −5.02 | [−6.01, −4.03] | < 0.001 |
| **power-law rule, float** | 78.47 ± 0.67 | – | – | – |
| trace: LUT, 3 bits | 77.30 ± 1.09 | −1.17 | [−2.11, −0.23] | 0.02 |
| trace: cheapest CORDIC, 3 bits | 70.39 ± 0.91 | **−8.08** | [−8.83, −7.32] | < 0.001 |
| trace LUT 3 bits, biased +0.25 LSB | 71.49 ± 1.46 | **−6.98** | [−7.97, −5.99] | < 0.001 |
| trace LUT 3 bits, biased −0.25 LSB | 81.02 ± 0.98 | +2.54 | [+1.58, +3.51] | < 0.001 |

Conclusions:
1. **The bias hypothesis is confirmed.** A table biased by +0.25 LSB loses as much as the cheapest CORDIC (whose
   bias is about +0.23 LSB); a table biased by −0.25 LSB even gains.
   - A unit's error bound says little. **What matters is the sign of its mean error:** a positive bias makes the
     accumulating trace decay too slowly, which acts like a longer τ.
   - The gain of the negative bias means the default τ = 20 ms is not optimal for these rules. A paper comparison
     must therefore hold τ fixed and compare at iso-accuracy, as we do.
2. **A 4-bit trace table and a 2-bit weight-dependence table equal float.**
3. **Removing the weight-dependence exponential costs 1.3 pp** (significant, but small). Wu 2021 spends two CORDIC
   units per synapse on a factor that a 2-bit table reproduces exactly.
4. **Nearest-spike traces cost about 5 pp with Wu's rule.** The traces must accumulate (X·e(Δt) + 1). An
   event-driven engine therefore needs a multiplier (or the clock-driven form) — engine spec E-D6.

## 3c. Integrator and N = 400 (E5)

Numbers: `e5_integrator/SUMMARY.md`.

- **Forward Euler explodes at N = 400** (more than about 23 simultaneous inhibitory spikes give dt/τ·g_i > 2).
  **Backward Euler is stable.**
- **N = 400 with backward Euler, 3 epochs, 3 seeds:**
  - Wu's rule: 85.35 ± 0.12 %;
  - power-law: 82.55 ± 0.25 %.
  - D&C report 87.0 % for the power-law rule. Our power-law reference is about 4.5 pp below their published
    numbers at both sizes, consistent with their unpublished per-size retuning; the gain from N = 100 to N = 400
    is reproduced.
- **At N = 100, backward Euler moves the numbers** (Wu's rule 83.3 → 80.8 %, power-law 78.0 → 77.5 %, 3 seeds).
  The final numbers must therefore use one integrator for every N (decision for Amir).

## 4. Unit sizing and RTL (P1, P4)

- **Models:** `model/exp_units.py` (spec `specs/exp_units.md`). 305 independent tests, written by a separate agent
  from the spec only, all pass.
- **Smallest configuration per precision:** `units/SIZING.md`.
- **RTL:** 96 Verilog modules (LUT, CORDIC iterative and unrolled, bit product, 2^x, shift-decay trace; both roles;
  Fo = 4–12), all bit-exact against the models on every input (`rtl/VERIFY.md`).
- **Early area probe** (Yosys synthesis only, sky130 cells, untimed; `rtl/synth_probe.md`): **the table is the
  smallest unit at every precision in both roles.**

  | trace unit, cell area µm² | Fo = 4 | Fo = 8 | Fo = 12 |
  |---|---|---|---|
  | LUT | 539 | 1 704 | 3 243 |
  | CORDIC (smallest, unrolled) | 2 800 | 6 893 | 12 414 |
  | bit product (unrolled) | 1 160 | 3 102 | 9 951 |

  Energy (the real comparison) comes from the sky130 flow with gate-level power, next.

## 5. Next

- **Decision:** one integrator for all final numbers (backward Euler recommended: stable at every N; the E2–E4
  screening used forward Euler).
- **Decisions:** the engine spec (`specs/engine.md`, E-D1 … E-D6) and batch 2 (`specs/exp_units_batch2.md`).
- Then: the batch-2 models, the engine RTL, the sky130 energy flow.
