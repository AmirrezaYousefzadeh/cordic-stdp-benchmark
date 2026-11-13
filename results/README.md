# Results so far (2026-11-13)

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

- 10 seeds at the key points:
  - float;
  - β = 0;
  - the 4-bit table;
  - the smallest CORDIC;
  - the bit product.
- The biased-table test.
- A nearest-spike trace variant (it needs no multiplier in hardware).
- The learning-engine model (Level 2) and the sky130 energy flow with operand streams recorded from the testbed.
- Specs of the paper-specific methods (Wu 2021's angle-recoding CORDIC, and Heidarpur/Bahrami's
  product-of-constants).
