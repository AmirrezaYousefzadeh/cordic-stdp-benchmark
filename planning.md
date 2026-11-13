# CORDIC for on-chip STDP learning: implementation plan

Status: draft 3, 2026-11-13 (Claude, for Amir and Edris). Amir answered decisions D1–D9 on 2026-11-12 (section 11);
D2 and D5 he will check again later. My reasoning, the evidence from the papers and my predictions are in
`claude_toughts.md`; the results so far are in `results/README.md`. Code and results: public GitHub repository
`AmirrezaYousefzadeh/cordic-stdp-benchmark`, which is also where Edris follows the work (Google Drive is no
longer used, Amir's decision of 2026-11-13).

## Progress (2026-11-13, afternoon)

| phase | state |
|---|---|
| P0 specs | testbed (`specs/testbed.md`), exponential units batch 1 (`specs/exp_units.md`, draft 3), RTL (`specs/rtl_units.md`) written; paper-specific methods (Wu 2021 angle recoding, Heidarpur/Bahrami) still to do |
| P1 models | batch 1 (LUT, CORDIC, bit product, 2^x, shift decay) done; 305 independent tests pass |
| P2 testbed | float reference validated at N = 100 (Wu's rule 82.8 %, D&C power-law 78.5 %, 10 seeds) and N = 400 (85.4 % / 82.6 %, backward Euler); forward Euler is unstable at N = 400; one integrator to choose for all final numbers |
| P3 sweeps | E2 (precision knee), E3 (methods, ablations), E4 (10 seeds, bias test, nearest-spike traces) done; see `results/README.md` |
| P4 RTL | batch 1: 96 modules, all bit-exact against the models; synthesis-only area probe done |
| P5 sky130, P6 engine, P7 paper | not started |

## 0. Decisions so far

Taken by Amir (2026-11-12):
1. **Paper type:** a benchmark on one shared testbed. We do not reproduce the papers' own numbers. We take each
   paper's proposed CORDIC method, build it in hardware ourselves and compare.
2. **Use case:** STDP learning on chip, the most impactful use of CORDIC in SNNs.
3. **Baselines:** non-CORDIC baselines are included (lookup table, simple shift-based decay), because reviewers
   will ask "why CORDIC?". The answer may be "CORDIC is not needed".
4. **Hardware:** sky130.
5. **Dataset:** MNIST (Amir wrote "MNIST?", so confirm; see D1).

Kept from earlier: the paper goes to TCAS-II (5 pages: at most 4.5 of content plus 0.5 of references), and the
paper lives in the Overleaf project (`paper/` is a local git clone of it).

Taken by Amir on 2026-11-12: D1–D9 of section 11. In short: MNIST only; the recommended methods (D2, to be checked
again); N_exc = 100 and 400; iso-accuracy within 0.5 pp over 10 seeds; Level 1 for all methods and Level 2 for the
best ones (D5, to be checked again); a GitHub repository (made public on 2026-11-13 at Amir's request); **we do not contact the papers' authors**; neutral
wording on the papers' inconsistencies; Edris follows everything through the GitHub repository (first through a
shared Drive folder; Drive was dropped on 2026-11-13).

## 1. The question and the claim

**Question.** In an on-chip STDP learning engine, which way of computing the exponential terms gives the lowest
energy (and area) for the same learning accuracy?

**Planned claim (it must survive the data).** "Under one network, one dataset, one precision criterion and one
technology (sky130, post-layout, gate-level power), method X reaches iso-accuracy with Y pJ per weight update and
Z µm²; CORDIC is (or is not) on the Pareto front."

**What the paper is not.** It is not a reproduction of the papers' reported accuracies, and not a review of all 21
papers. The 21 papers give a short related-work paragraph and one classification table.

## 2. What the papers actually propose (from reading all 27 PDFs)

The reading notes per paper are in section 4 of `claude_toughts.md`. In short:

- The exponential appears in STDP in **two roles**:
  - **R1, the timing kernel:** exp(−Δt/τ), or equivalently the decay of a trace. Used by Sheng 2024 (async
    CORDIC), Heidarpur 2019 (CORDIC-SNN), Wang 2026 (adaptive pipelined CORDIC) and Wu 2025 (pair/triplet).
  - **R2, weight dependence:** exp(−βw) and exp(−β(w_max−w)). This is Wu 2021 (Fast CORDIC), which is Diehl &
    Cook's exponential weight-dependent rule. Bahrami 2024's (w_max−w)^μ is the same idea, done as
    exp(μ·ln(·)).
  - Wu 2021's traces do not decay at all, so its CORDIC sits only in R2.
- The "CORDIC" methods fall into **four families**:

| family | papers | what it really computes | our implementable version |
|---|---|---|---|
| C1 conventional hyperbolic CORDIC (Walther 1971) | baseline in Wu 2021, Bahrami 2024, Sheng 2024, Wang 2026 | e^z = cosh z + sinh z, rotation mode, iterations 4 and 13 repeated, \|z\| ≤ 1.118 | textbook; range extension by e^z = 2^A·e^(b·ln2) |
| C2 angle-recoding ("fast", "adaptive") hyperbolic CORDIC | Wu 2021 (from Wang 2018), Wang 2026 | picks the micro-rotation closest to the residual; data-dependent iteration count, early stop | our own clean design of the idea; both papers' pseudocode has bugs and missing tables |
| C3 multiplicative normalisation with e^(±2^-i) constants (called "Exp CORDIC") | Heidarpur 2019 (from their 2016 AdEx paper), Bahrami & Nazari 2024 (plus a short Taylor tail, ln and pow) | e^x as a product of constants chosen by the bits of x | bit-exact from the papers after fixing their stated bugs |
| C4 asynchronous dual-rail CORDIC | Sheng 2024 | a conventional CORDIC in another logic style; the algorithm and widths are not given | not buildable in our synchronous flow; described only (see D2) |

- **Non-CORDIC baselines:**

| baseline | what | where it comes from |
|---|---|---|
| B1 LUT | ROM indexed by Δt (R1) or by w (R2), as standard-cell logic | Zhang 2020 (57 LUTs vs 831 for CORDIC), Wu 2025 matrix, SpiNNaker |
| B2 shift-decay trace | stored trace, x ← x − (x >> k) every time step; no exp unit at all | Loihi-style traces; Bahrami's own hardware trace |
| B3 bit-controlled constant product | exp(−Δt/τ) = Π over the set bits k of Δt of the constant e^(−2^k/τ); no residual datapath | UD-CORDIC idea (Garrido 2025) applied to exp; C3 without the comparisons |
| B4 2^x by shift | e^(−Δt/τ) ≈ 2^(−Δt/τ′): shift by the integer part plus a small table for the fraction | Heidarpur's own "2^x" baseline |
| B5 no exponential | rectangular or linear STDP window (ablation: does the shape matter at all?) | Cassidy-style digital STDP, shown in Sheng Fig. 2a |
| REF | float64 exp, and the exact exp rounded to the same output format | upper bound on accuracy |

**D2 (decided 2026-11-12, Amir will check again):** which methods enter the hardware comparison:
- C1, C2, C3, B1, B2, B3 and B4 in hardware.
- B5 only in the accuracy study.
- C4 described in the text, not built: its algorithm is not given, and an asynchronous design needs a different
  flow.

## 3. The shared testbed

### 3.1 Network (D3, decided 2026-11-12)
- **Diehl & Cook 2015 (D&C) network on MNIST:**
  - 784 Poisson inputs, N_exc LIF neurons with adaptive threshold θ, lateral inhibition (WTA), STDP on the
    input-to-excitatory weights.
  - Classification by label assignment (each neuron gets the class it fires most for).
  - Wu 2021, Sheng 2024 and Wang 2026 all used this network.
- **N_exc = 100** (primary: cheap, and Wu 2021's operating point) and **400** (secondary: Wang 2026's point).
  - D&C reference values: 82.9 % at 100 neurons, 87.0 % at 400.
- **Two implementations of the same network:**
  - **Float reference** (D&C equations, conductance-based) to validate against D&C's numbers.
  - **Integer, hardware-faithful model** in which only the exponential operator is swapped. Lateral inhibition
    becomes direct inhibitory synapses, as in Wu 2021's hardware.
  - Rule from flow notes 11: the integer model must reproduce itself bit-exactly, and it is the model the RTL is
    checked against.
- **Time step:** 1 ms (D&C used 0.5 ms). Presentation 350 ms, then a state reset in place of the 150 ms rest.
  Both are speed-ups that I will validate against the float reference before using them.
- **Seeds:** 10 for every point in the final figures (flow notes 11), 3 for screening sweeps.

### 3.2 Learning rules (both roles of the exponential)
- **Rule T (timing kernel, R1).** D&C's pre/post-trace STDP. Weight update on post spike:
  Δw = η_post·(x_pre − x_tar)·(w_max − w)^μ; on pre spike: Δw = −η_pre·x_post.
  The trace is the place where the exponential sits, and there are two ways to hold it:
  - **Clock-driven:** store the trace and decay it every step (B2, or a multiply by a constant).
  - **Event-driven:** store the trace together with the time it was last updated; on access, multiply it by
    exp(−Δt/τ) from an exp unit (C1–C3, B1, B3, B4).
  - With nearest-spike traces, the trace equals exp(−(t − t_last)/τ) exactly. So the timestamp form and the
    pair-based Δt rule of Sheng, Heidarpur and Wang are the same rule. One rule therefore covers all of them, and
    the comparison becomes "state representation × exp method".
- **Rule W (weight dependence, R2).** D&C's exponential weight-dependent rule as used by Wu 2021:
  Δw = η·(x_pre·e^(−βw) − x_tar·e^(−β(w_max−w))), β = 0.25. The exp input is the weight (8 bits).
- **Not modelled:** Bahrami's spatial-pow rule. Its parameters are not published. Its exp, ln and pow units are
  still compared at unit level (section 5.1).

### 3.3 What the testbed records for the hardware
- Accuracy (mean ± std over seeds).
- Per training image:
  - the number of exp evaluations, per role;
  - the number of trace decays (clock-driven form);
  - the number of weight and state reads and writes.
- **Operand streams** (Δt values, weights) from real training. They drive the gate-level simulations, because the
  energy of a data-dependent unit (C2, C3) depends on its operands.

### 3.4 Precision and the iso-accuracy criterion (D4, decided 2026-11-12)
- Sweep the output precision of every exp method over 4, 5, 6, 8, 10, 12 bits (input widths follow from Δt range
  and τ).
- **Iso-accuracy point** of a method: the smallest precision whose MNIST accuracy is within 0.5 pp of the REF
  model, over 10 seeds.
- Hardware is compared at each method's iso-accuracy point, and additionally at a common 8 bits (the precision
  most papers use).

## 4. Specifications before code (phase 0)

For each method one file `specs/<method>.md`:
- the equations;
- the bit-level definition (formats, rounding, iteration order, tables);
- every ambiguity of the paper and how we resolve it, with the reason;
- a list of deviations from the paper.

Specs come before code and are reviewed by Amir and Edris (section 9). We do not contact the authors (D7), so
every gap in a paper is resolved by us, documented in the spec, and the method is called "after [ref]" in the paper. The open questions found so far for
the papers we build are listed in `claude_toughts.md`, section 4; for example:
- Heidarpur's exp: handling of negative inputs, 6 or 8 iterations, constants as shift-add terms.
- Wu 2021's fast CORDIC: findProperAngle, ListScale, the iteration-index typo.
- Bahrami: floor vs truncation, the ln series bug.

Where the paper has published error figures, the model has to reproduce them before we trust it:
- Bahrami Tables 1–3: one reading agent already reproduced them in float64.
- Wu 2021 Table I: average iteration counts.
- Wu 2021 Fig. 7: average error per width.
- Heidarpur: normalised RMS deviation (NRMSD) 2.38e-3 at n = 8.

If a published figure cannot be reproduced from the published description, we say so in the spec and use the most
plausible correct version, stated as our assumption.

## 5. Phases, deliverables and "done when"

Each phase ends with a short report to Amir. No phase starts its expensive runs before Amir has seen the previous
report.

| phase | what | done when |
|---|---|---|
| P0 specs | `specs/*.md` for the chosen methods and the testbed; corrected version of Edris's comparison table | Amir (and Edris) approved the specs |
| P1 bit-accurate models | `model/`: one Python module per method, integer-only, parameterised by precision; `tests/` written by a separate agent from the spec only (it does not see the implementation) | all tests pass; published error figures reproduced or the discrepancy documented |
| P2 testbed | `testbed/`: float D&C reference and integer model on the GPU, both rules, both state forms | float model at N = 100 within ~1 pp of 82.9 %; integer model with REF exp within 0.5 pp of float; deterministic reruns |
| P3 accuracy sweeps | methods × precisions × rules × N × seeds, through `jobq` | accuracy-vs-precision curves, iso-accuracy points, operand streams and event counts saved |
| P4 RTL | `rtl/`: Verilog per method, two forms each (iterative: one iteration per cycle, minimum area; unrolled/pipelined: one result per cycle); testbenches driven by vectors from the models | bit-exact against the model on exhaustive inputs (input ≤ 16 bits, so exhaustive is cheap) plus the recorded operand streams |
| P5 sky130 measurement | LibreLane 3.0.16 hardening, SDF gate-level simulation with the recorded operand streams, OpenSTA per-pin power; strictly the flow notes' checklist (section 10) | per method: area, cells, cycles/latency, energy per evaluation (dynamic and leakage separately), all checklist items green |
| P6 learning-engine energy | energy per training image = event counts (P3) × energies per operation (P5), including state-memory accesses; a gate-level check of one small engine over a few images | model vs GLS check agrees within ~10 %, or the difference is explained |
| P7 paper | TCAS-II brief in `paper/` | Amir and Edris agree to submit |

### 5.1 Hardware scope (D5, decided 2026-11-12; Amir will check again)
- **Level 1, the exp unit alone (all methods, both roles).** Inputs:
  - Δt plus the τ shift, for R1.
  - An 8-bit weight, for R2.
  Bahrami's exp, ln and pow units are included here as published (they are combinational).
- **Level 2, the learning engine for the best methods plus B2.** One update unit that serves one post-neuron row
  through time multiplexing, with the state it needs:
  - timestamps for the event-driven form;
  - traces for the clock-driven form;
  - weights.
  Level 2 is where B2 (shift-decay) can be fairly compared, because B2 changes the state and adds a decay
  operation for every trace at every step, while the exp-on-demand methods pay per event. The crossover depends on
  the spike activity, and that crossover is likely the most useful result of the paper.
- **Memory:** one storage model for all methods (flip-flop or latch array of the same organisation; SRAM22 only if
  Amir prefers it). Memory energy per access comes from the same flow.
- **Operating point:** one clock for all units (proposal: 50 MHz; it is far above what MNIST learning needs, so
  energy per operation, not speed, is the figure), typical corner 1.8 V, 25 °C; leakage reported separately.
  Setup and hold signed off at all 9 corners, as the flow notes require.

## 6. Repository layout

```
CORDIC/
  planning.md            this file
  claude_toughts.md      my reasoning, reading notes, log
  references/            the PDFs (read-only)
  paper/                 Overleaf git clone (pushes only after Amir's OK; Edris sees every push); not in this repo
  specs/                 one spec per method + testbed spec
  model/                 bit-accurate Python models (integer only)
  tests/                 independent tests of the models
  testbed/               SNN simulator (PyTorch, GPU), configs, run scripts
  rtl/  tb/              Verilog units, testbenches and vectors
  flow/                  LibreLane configs and scripts (copied from flow_notes/tools, flow_notes commit recorded)
  results/               CSV/JSON results, each with tool versions and the git commit that produced it
  figures/               scripts that make every paper figure from results/
```

- **Git:** one local git repository for everything except `paper/` (it has its own Overleaf remote).
- **D6 (decided), GitHub:** created private on 2026-11-13 and made public the same day at Amir's request
  (`AmirrezaYousefzadeh/cordic-stdp-benchmark`; noreply author email, no Claude trailer, Drive ids never committed).
- **Collaboration with Edris:** through the public GitHub repository (D9, changed on 2026-11-13). The Google
  Drive mirror used before is dropped. The papers stay outside the repository (copyright); Edris has them
  ("CORDIC for SNNs.rar").

## 7. How the agents work (Amir's rule: "if the tests pass, trust the implementation")

For every method:
1. A **spec** agent writes `specs/<m>.md` from the paper. Claude reviews it, then Amir does.
2. A **model** agent implements it from the spec.
3. A separate **test** agent writes tests from the spec alone, without seeing the implementation. The tests cover
   error bounds against float64, reproduce the paper's published error tables and include edge cases (Δt = 0, the
   largest Δt, w = 0, w = w_max).
4. An **RTL** agent writes the Verilog. Equivalence is proved with exhaustive vectors from the model.
5. Hardening and measurement happen in one script per unit that a second person can rerun (flow notes 11).

Claude coordinates, reviews every diff and reports to Amir at the end of each phase.

## 8. Compute and machine rules

- **CPU, not GPU (measured 2026-11-13).** The testbed is an event-driven numba simulator. One N = 100 run
  (40 000 training examples, a 60 000-example labelling pass, 10 000 test examples) takes about 3.3 min on one
  core. A campaign with 8 workers does about 60 runs in 30 min. The GPU stays free for the other projects.
  N = 400 is about 15× slower than expected and is profiled before it is used.
- **sky130 hardening.** Small blocks (a few hundred to a few thousand cells). Minutes each; up to roughly 30
  configurations (methods × forms × precisions), plus the Level-2 engines.
- **Every heavy job goes through `jobq`**:
  - realistic `--mem` and `--time`;
  - `--high` only if Amir asks;
  - pinned tool versions (LibreLane 3.0.16, `/media/pdk/sky130_8afc834`, OSS CAD Suite 2026-10-24), checked by the
    scripts;
  - `ANNOUNCEMENTS.md` re-read before each measurement campaign.
- Findings about the flow go to `flow_notes/inbox/`, never into flow_notes itself.
- Snellius is not needed unless the N = 400 sweep proves too slow locally (ask Amir first).

## 9. Split of the work (D7, decided 2026-11-12)

- **Edris:**
  - Review the specs (a second pair of eyes on our reading of each paper).
  - Write the introduction and the related work over the 21 papers (classification table in `claude_toughts.md`
    5.3), including ISSCC 2026 ANP-OT, the only silicon STDP chip with a CORDIC exp.
  - Correct his comparison table with the findings in `claude_toughts.md` 5.1.
- **Amir and Claude:** specs, models, testbed, RTL, sky130 measurement, results, figures.
- **Both:** the paper text.

## 10. Rough timeline (to be confirmed after the P2 pilot)

| weeks from start (start = Amir's approval of this plan) | phase |
|---|---|
| 1 | P0 specs, testbed spec, pilot timing of the simulator |
| 2 | P1 models and tests; P2 testbed (in parallel) |
| 3–4 | P3 sweeps (GPU, through the queue); P4 RTL in parallel |
| 5–6 | P5 sky130 measurement; P6 learning engine |
| 7–8 | P7 paper draft, written with Edris |

A first full draft is possible about 8 weeks after approval; TCAS-II has no fixed deadline.

## 11. Decisions (answered by Amir on 2026-11-12)

| # | decision | my recommendation | Amir's answer |
|---|---|---|---|
| D1 | dataset | MNIST only (the common denominator; a second dataset does not fit 4.5 pages); Fashion-MNIST only if a reviewer asks | agreed |
| D2 | methods built in hardware | C1, C2, C3, B1, B2, B3, B4; B5 in the accuracy study only; C4 described, not built | agreed; will check later |
| D3 | network size and rules | N_exc = 100 primary, 400 secondary; rule T in both state forms, plus rule W | agreed |
| D4 | iso-accuracy criterion | within 0.5 pp of the REF model, 10 seeds; also a common 8-bit comparison | agreed |
| D5 | hardware scope | Level 1 for all, Level 2 (learning engine with state) for the best 2–3 plus B2; one storage model for all | agreed; will check later |
| D6 | code hosting | private GitHub now, public at submission | agreed |
| D7 | split of the work | as in section 9 (originally including e-mails to the authors) | agreed, but **we cannot contact the authors** |
| D8 | how to treat the papers' inconsistencies | neutral and factual: a short "reproducibility notes" paragraph or supplementary table, only for what affects the comparison | agreed |
| D9 | when to tell Edris | after Amir approves this plan | Edris follows everything through the shared Drive folder; changed on 2026-11-13: through the GitHub repository, Drive dropped |
| D10 | main learning rule of the testbed (new, 2026-11-13) | Wu 2021's exponential weight-dependence rule with β = 0.25 as the main rule (83.3 %, and it uses the exponential in both roles); D&C's power-law rule second | agreed (2026-11-13) |
| D11 | N = 400 (new, 2026-11-13) | only for the final confirmation points, after profiling why it ran about 15× slower than estimated | agreed (2026-11-13) |
