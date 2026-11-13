# Claude's thoughts on the CORDIC project

My working notes for Amir and Edris: what I think the story is, what the papers really contain, my predictions, the risks,
and a log. The plan itself is in `planning.md`. Facts about the papers come from four reading agents that read all
27 PDFs in `references/` (2026-11-12). They give page numbers; I spot-checked the key claims but not every one. Items
marked *(memory)* are from my background knowledge and must be checked before they go into the paper.

## 1. The story I expect the paper to tell

1. **CORDIC is used in SNN learning for two kinds of exponentials:**
   - the STDP timing kernel exp(−Δt/τ);
   - the weight-dependence factor exp(−βw).

   Both have small inputs (Δt ≤ ~100–200 steps, so 7–8 bits; w is 8 bits) and need little output precision
   (accuracy is flat above ~6–8 bits; Wu 2021 Fig. 8 collapses only at 4 bits).
2. **For such small inputs every exact method is a function of ≤ 8 input bits,** so a 128–256-entry table is the
   natural competitor. Iterative CORDIC pays for n cycles of register clocking per evaluation. My expectation:
   - The table wins on energy at ≤ 8 bits.
   - CORDIC wins on area only at high precision (≥ 12 bits), which learning does not need.
3. **For the timing kernel there is an even simpler option:** a trace decayed by a shift every step (no exp
   at all). The fair question is then not "CORDIC vs LUT" but "exp-on-demand (event-driven) vs decay-every-step
   (clock-driven)". The crossover depends on spike activity. That is a real, useful result, and it links to Amir's
   Async_inference work (event-driven vs stepped).
4. **So the likely headline:** "for on-chip STDP at the precision learning needs, CORDIC is never on the energy
   Pareto front; a table or a shift-decayed trace is". Amir decided to include the baselines knowing this may be
   the outcome. If the data say otherwise (for example, CORDIC wins when several functions share one unit, as in
   Bahrami's exp/ln/pow, or when τ must be programmable at run time), that is the story instead.

## 2. Technical insights to build on

### 2.1 Two roles, one rule, two state forms
- With nearest-spike traces, trace(t) = exp(−(t − t_last)/τ) exactly. So:
  - the Δt-based pair rule (Sheng 2024, Heidarpur 2019, Wang 2026);
  - and the trace rule with a stored timestamp
  
  are the same learning rule.
- The implementation choice is the **state representation**:
  - **Timestamp plus exp unit on demand** (event-driven): this is where CORDIC or a table competes.
  - **Trace decayed every step** (clock-driven): no exp unit.
- All-to-all traces can also be event-driven with "lazy decay": store the trace and its last-update time, multiply by
  exp(−Δt/τ) when read. That needs an exp unit too.
- This lets one testbed cover all the timing-kernel papers.

### 2.2 Hyperbolic CORDIC for exp is multiplicative normalisation, and needs only one datapath
- With x₀ = y₀ = 1/G, the two CORDIC datapaths stay equal (x = y at every step). Then
  x_{i+1} = x_i·(1 + d_i·2^−i) and x_n = e^{z₀}.
- I checked it in float64: the two-datapath x+y and the one-datapath product agree to 1.3e-15 over z ∈ [−1.1, 1.1],
  with 12 iterations including the repeat of iteration 4.
- Consequences:
  - **The cosh + sinh structure is wasteful.** Wu 2021, Sheng 2024 and Wang 2026 all compute exp as cosh + sinh
    with two shift-add datapaths. Half of that datapath is redundant. Our C1 should use the one-datapath form,
    otherwise we compare against a strawman CORDIC.
  - **C1 and C3 belong to one family.** Heidarpur's and Bahrami's "Exp CORDIC" (products of e^(2^−i) constants
    chosen by the bits of x) is the same idea with a different constant set: binary digits of x instead of a
    signed residual with atanh(2^−i).
- **With a fixed τ the residual datapath disappears.** exp(−Δt/τ) = Π over the set bits k of Δt of e^(−2^k/τ). The
  bits of Δt choose the constants directly (B3, the UD-CORDIC idea applied to exp). That is at most 7–8
  constant-multiplications, and for a fixed τ, a 7–8-bit-input function is again just a small table. The whole
  "CORDIC" family collapses towards the LUT once τ is fixed.
- The remaining argument for CORDIC is a **programmable τ** at run time (the reason Wu 2025 gives) or **sharing
  one unit for several functions**. Both need to be in the paper as the conditions under which CORDIC could make
  sense.
- One more point on Bahrami's e^(r/Ds) distance factor: it is a constant per synapse pair. It can be precomputed
  and stored, so it needs no run-time exp at all.

### 2.3 What real neuromorphic chips do *(memory, verify)*
- Loihi: decaying traces, no exp unit.
- SpiNNaker: lookup tables for the STDP exponentials.
- ODIN and ReckOn: learning rules without exponentials.
- Industry practice already points at tables and traces. This is good context for the introduction, and it makes
  the "why CORDIC?" question legitimate rather than provocative.
- The only silicon with a CORDIC exp in STDP that I found in our set is ISSCC 2026 ANP-OT (TSMC 22 nm,
  0.46 pJ/SOP). It must be cited and positioned against: it is the strongest pro-CORDIC data point.

## 3. Predictions (to check against the data, not to steer it)

| question | prediction | why |
|---|---|---|
| accuracy vs precision | flat from ~6–8 bits; all methods equal there | Wu 2021: 8 bits = 24 bits; Bahrami: CORDIC = float within 0.05 pp |
| energy per exp evaluation at 8 bits | LUT < B3 ≈ B4 < C3 < C1 < C2 | iterative units clock registers for n cycles; C2's angle selection adds comparators |
| area at 8 bits | LUT, B4 and iterative C1/C3 within ~2× of each other | 256 × 8 bits as logic is a few hundred cells |
| area at 12+ bits | iterative CORDIC smallest | LUT grows 2^b |
| shift-decay vs exp-on-demand | shift-decay wins at high input activity, exp-on-demand at sparse activity | decay costs (#traces × #steps), exp costs (#events) |
| rectangular window (B5) | a few pp worse at N = 100 | the shape matters, but less than network size |

If the LUT does not win at 8 bits, I will look for the reason before trusting the number (flow notes 11).

## 4. Reading notes per paper (the ones relevant to STDP)

### 4.1 Wu et al., TCAS-I 2021, "Fast CORDIC" (the main target)
- **Role R2 only.** D&C's exponential weight-dependent rule Δw = η(x_pre·e^(−βw) − x_tar·e^(−β(w_max−w))),
  β = 0.25 (shifts), update on post spike (p.4). The pre trace is an undecayed spike counter (8 bits); removing the
  leak cost 0.7 pp at N = 100.
- **CORDIC:** two per synapse. Conventional hyperbolic as the baseline (Alg. 1). The proposed one is angle
  recoding (Alg. 2, from Wang 2018, Microelectronics J.).
  - Alg. 1 as printed has no repeated iterations. The agent's model of it floors at ~1e-3 error, while the paper
    reports 9e-5 at 16 bits, so their simulation was not Alg. 1 as printed.
  - Alg. 2: shift and angle use i instead of AngleIndex (typo); findProperAngle, the angle set and ListScale are
    not given.
- The actual CORDIC inputs lie in about [−0.5, 0.25] (β = 0.25, w in [0, 1]), much narrower than the [−1, 1] they
  evaluate.
- **Accuracy at N = 100 (Table II):**

| variant | accuracy |
|---|---|
| exact | 82.9 % (equals D&C's own 100-neuron number) |
| fast, 8 bits | 83.4 % |
| conventional, 8 bits | 83.0 % |
| fast, 6 bits | 80.8 % |
| 2^x | 73.6 % |

- **Hardware:** Zynq; the text says xc7z035, the table caption xc7z030.
  - 8-bit fast: 533 LUT/synapse; 30.2 ns/SOP; 176.6 pJ/SOP.
  - Conventional 8-bit: 244 LUT; 322.8 pJ.
  - LUT version (BRAM, 140 BRAMs): 543.6 pJ.
- **Inconsistencies:**
  - Energy per image ≠ SOPs × pJ/SOP (19.6 M × 176.6 pJ = 3.46 mJ vs 6.646 mJ reported).
  - 176.6 pJ in 71.8 ns = 2.46 W for one synapse module.
  - The LUT baseline uses one BRAM per synapse for an 8-bit function, which is over-provisioned and explains
    "LUT costs more energy".
  - This is the paper whose "CORDIC beats LUT" claim our benchmark tests most directly.
- **Open for our spec:**
  - θ adaptation and weight normalisation are not mentioned; they probably come from BindsNET's eth_mnist.
  - η, w_max, dt and the input rate are not stated.
  - The angle set has to be designed by us (an angle-recoding hyperbolic CORDIC, documented as our design
    following their idea).

### 4.2 Sheng et al., APCCAS 2024, "Asynchronous CORDIC"
- **Rule:** pair-based Δt STDP (R1), nearest-neighbour, update on post spike.
- **Method:** "asynchronous" is the logic style (dual-rail, 4 kernels in a ring, 8 iterations instead of 12). The
  CORDIC mode is contradictory (atan2 LUT and circular pre-rotation, yet cosh/sinh). The angle sequence, repeats
  and pre-rotation are not given. A 5-bit phase sits next to 24-bit x/y.
- **The ~95 % MNIST claim is not supported by any experiment in the paper.** The only network is 784-10-10. It
  matches D&C's 6400-neuron number.
- **Numbers copied from Wu 2021:** the "conventional" error 9.043e-5, the Heidarpur 195.4 MHz/110 ns and the LUT
  50 ns are identical to Wu 2021's values.
- No resource numbers. Power "29 mW at 50 MHz" with unknown scope.
- **Verdict:** cannot be rebuilt; describe only (C4).

### 4.3 Bahrami & Nazari, Sci Rep 2024, "spatial-pow-STDP"
- **Rule:** Δw = e^(r/Ds)·η·(x_pre − x_tar)·(w_max − w)^μ on post spikes. r is the distance on a 100×50 grid; the
  exponent is positive. No numeric values for η, x_tar, μ, w_max, τ, Ds, dt or the presentation time. The rule
  cannot be rebuilt.
- **"Exp/Ln/Pow CORDIC" are not CORDIC.** They are multiplicative normalisation with exp(2^−i) constants plus a
  short Maclaurin tail. Their algorithms reproduce their own Tables 1–3 in float64 only if:
  - `int()` is floor;
  - the Ln series uses a wrong formula (x − x²/2 − x³/6 + x⁴/24 instead of x − x²/2 + x³/3 − x⁴/4).

  On the (0, 1) range their rule uses, that bug costs ~1000× accuracy.
- **Hardware:**
  - Only the learning block was built: single-cycle combinational exp (370 LUT), ln (2393), pow (2876).
  - 776 MHz with 0 registers in the exp block is not a register-to-register timing.
  - The power is ~140 mW device static plus ~20 µW/MHz dynamic (≈ 20 pJ per cycle for the STDP block, estimate).
- **93 % on CIFAR-10** from 8×8 average-pooled inputs with an unsupervised network has no explanation in the
  paper. Unverified.
- **Use for us:** their exp, ln and pow units at unit level (C3 family, bug fixed, both versions reported). Not
  the rule, and not the accuracies.

### 4.4 Heidarpur et al., TCAS-I 2019, "CORDIC-SNN"
- **Rule:** pair-based Δt, additive, τ± = 20 ms, A+ = 2, A− = 4, w clamped. Spike history in 41-bit shift
  registers (all-to-all within ±20 samples).
- **Exp:** C3 (product of e^(2^−i) constants, from their 2016 AdEx paper), input restricted to [−1, 0]. The
  pseudocode has an indexing bug and computes e^(+x). How negative inputs are handled, 6 or 8 iterations, the word
  length and the constant approximations are not stated.
- **No dataset;** 20-1 network, bimodal weights only.
- **Useful data point:** the exp unit vs a "2^x by shift" unit cost 142 LUTs and 41 registers in a whole design
  (Table VII). Even its own authors' numbers say the exp is a small part of the design.

### 4.5 Wang et al., IJCTA 2026, "Adaptive pipelined CORDIC"
- **Extends Heidarpur.** Angle recoding with early stop, two-stage pipeline; Δt-indexed tables with τ folded in.
  Nearest-neighbour Δt rule, τ = 20 ms, w ∈ [0, 10].
- The pseudocode has three bugs, and ListAngle and ListScale are not given. It cannot be rebuilt as published.
- **MNIST (D&C, N = 400, software only, 10k training images):** float 91.51 %, adaptive 8-bit 90.02 %,
  traditional 8-bit 87.11 %, plain fixed point 8-bit ≈ 89.3 %.
  - Adaptive CORDIC beating exact fixed point at the same width is implausible.
  - 91.5 % at N = 400 is above D&C's own 87 %.
- **Use for us:** the idea feeds C2 (our own angle-recoding design); the numbers do not.

### 4.6 Others
- **Wu et al., ISCAS 2025 (pair/triplet):** the CORDIC is incidental and unspecified. The exp matrix has at most
  11×10 entries, so it is a table in all but name. Useful as an argument.
- **Zhang et al., Neurocomputing 2020:** a 101-entry LUT (57 LUTs, 1 cycle) replaced CORDIC (831 LUTs, 16 cycles)
  for a fixed exp kernel. Published support for our expectation.
- **Udeji & Margala, SOCC 2022:** no STDP; the "CORDIC" is an ordinary shift-and-add multiplier; the 4 W / 7.46 W
  figures are whole-device tool estimates dominated by I/O. Not usable.
- **ReLANCE (TVLSI 2026):** the neuron is HH. The repository's "cordic" functions are exact arithmetic and float
  np.exp, with no STDP. Out of scope.
- **The four general CORDIC papers** (Volder, CORDIC II, UD CORDIC, Hybrid CORDIC) are all circular-mode only.
  Hyperbolic exp rests on Walther 1971, which we do not have locally yet; I would add it. UD CORDIC's
  bit-controlled constant product is the idea behind B3.

## 5. Tables

### 5.1 Corrections to Edris's comparison table (CORDIC_SNN_Comparison_Tables.pdf)

| ref | Edris's entry | correction |
|---|---|---|
| [1] Wu 2021 | CORDIC "computes STDP terms" | it computes the weight-dependence factors e^(−βw), e^(−β(w_max−w)); traces have no decay |
| [1] | xc7z035fbg676-2 | the text says xc7z035, the Table IV caption xc7z030; cite both or neither |
| [1] | 6.646 mJ/image, 176.6 pJ/SOP | the two do not agree (SOPs × pJ/SOP = 3.46 mJ); per-module power implausible |
| [2] Udeji 2022 | ≈4 W vs 7.46 W per neuron | whole-device tool estimates (the paper says 92 % went to I/O); not usable |
| [3] Bahrami 2024 | "Exp, Ln, Pow CORDIC" | not CORDIC (multiplicative normalisation + Maclaurin); Ln series bug |
| [3] | 776 MHz | the exp block has 0 registers; not a register-to-register timing |
| [3] | 0.155 W at 776 MHz | ~140 mW of it is device static power |
| [4] Sheng 2024 | ~95 % MNIST | no experiment in the paper supports it; the network is 784-10-10 |
| [4] | comparison numbers | several are identical to Wu 2021's and probably copied |
| [5] ReLANCE | open-source code | incomplete: no CORDIC in the Python model, no STDP, fixed weights |
| missing | | Heidarpur 2019 (CORDIC-SNN, STDP), Wang 2026 (adaptive CORDIC, STDP, MNIST), Wu 2025 (pair/triplet, MNIST), ANP-OT ISSCC 2026 (silicon) |

### 5.2 The STDP-relevant papers in one view

| paper | exp role | CORDIC family | rebuildable? | dataset |
|---|---|---|---|---|
| Wu 2021 TCAS-I | R2 weight dependence | C1, C2 | C1 yes; C2 as our own design | MNIST, D&C N = 100…6400 |
| Sheng 2024 APCCAS | R1 timing | C4 (async) | no | claims MNIST, no experiment |
| Bahrami 2024 Sci Rep | R2 pow, distance factor | C3 + Maclaurin | units yes (bug fixed); rule no | MNIST/EMNIST/CIFAR (unverified) |
| Heidarpur 2019 TCAS-I | R1 timing | C3 | mostly, with stated assumptions | none |
| Wang 2026 IJCTA | R1 timing | C2 | idea only | MNIST, D&C N = 400 (software) |
| Wu 2025 ISCAS | R1 timing (matrix) | unspecified | no (but it is a LUT in practice) | MNIST |
| ANP-OT ISSCC 2026 | weight update exp/log | fused CORDIC sub-operators | no (silicon, few details) | gas/VOC, clinical breath |

### 5.3 The other papers in the collection (for related work)

| paper | CORDIC used for | learning | dataset | platform |
|---|---|---|---|---|
| Hao 2021 Neurocomputing (respiratory CPG) | exp, cosh, tanh, division | no | no | Stratix III |
| Seyedbarhagh 2023 T-MRB (neuro-glial) | mult/div, nonlinear functions | no | no | Virtex-7 |
| Yang 2019 NER (retina) | hyperbolic/exp | no | no (camera) | Cyclone IV |
| Abdel-Hafez 2024 Access (memristive Wilson) | cosh (hybrid with piecewise linear) | no | no | Virtex-5 |
| Chen 2026 TCAS-II (Rulkov) | exponential binary power | no | no | Virtex-4 |
| Bonabi 2014 Front. Neurosci. (HH network) | exp fraction + LUT integer part | no | no | Virtex-7 |
| Khoyratee 2019 Front. Neurosci. (HH) | exp, tanh | no | no | Kintex-7 |
| Hao 2019 Front. Neurosci. (Purkinje) | exp with 2^A·e^(b·ln2) range extension, division | no | no | Stratix III |
| Zakaleh 2026 ESL (FitzHugh-Nagumo) | sinh for the cubic term | no | no | Zynq 7100 |
| Haghiri 2026 TIM (Hindmarsh-Rose) | sin/cos | no | no | Spartan-3, Virtex-5 |
| Nazari 2024 Sci Rep (Hindmarsh-Rose) | x², x³ (linear mode) | no | image processing, no training | Xilinx |
| ReLANCE 2026 TVLSI (HH) | exp, mult, div | "STDP-trained", not on chip | MNIST (drop only) | VC707 |

## 6. Risks and how I would handle them

- **"Your implementation of method X is not theirs."**
  - Specs that list every assumption.
  - Reproduce their published error figures where possible.
  - Where a paper's method is under-specified, call our version "after [ref]" and say so.
- **A strawman CORDIC.** Use the best CORDIC we can build: the one-datapath form (2.2), the best iteration count
  for the precision, and both iterative and unrolled forms. A reviewer must not be able to say we compared a good
  LUT with a bad CORDIC. Likewise, the LUT must be a proper logic ROM, not one BRAM per synapse as in Wu 2021.
- **Tone.** Several papers have unsupported or copied numbers. A benchmark paper is not a takedown:
  - mention only what affects the comparison;
  - use neutral wording;
  - no contact with the authors (decided 2026-11-12), so we report what the papers say, not what we suspect.
- **The outcome.** The project started from an interest in CORDIC, and the benchmark may end with "CORDIC is not
  needed". Both of us know that from the start; the paper is useful either way.
- **Accuracy noise.** D&C accuracy varies by ±1 pp between seeds at N = 100. That is why we use 10 seeds and
  iso-accuracy points instead of single runs.
- **Page budget.** 4.5 pages means one method table, one accuracy-vs-precision figure, one energy/area Pareto
  figure and one activity-crossover figure at most. Everything else goes into a supplementary document or the
  repository.
- **Weak link to Amir's priority of open, reproducible flows.** It is fine: LibreLane and sky130 are open, and the
  models and RTL can be released.

## 7. Things I am unsure of

- **The exact D&C learning rule for rule T.** D&C's code uses the triplet-like "post2-before" term; BindsNET's
  eth_mnist uses PostPre with weight normalisation. To be fixed in the testbed spec. The choice does not change the
  comparison, because every exp method sees the same rule.
- **Whether the 1 ms step and state reset** (instead of 0.5 ms and a 150 ms rest) change accuracy noticeably.
  The P2 pilot will tell.
- **Memory energy at Level 2.** If state memory dominates, the exp-method differences shrink at system level. That
  is a valid result, but it changes the headline from "LUT beats CORDIC" to "the exp method does not matter,
  pick the cheapest". Worth knowing early: I would do a quick estimate in P1 from the cell counts.
- **GPU time for N = 400 with 10 seeds and all methods.** Measure in the pilot before promising.

## 8. Log

- **2026-11-09:**
  - Read the e-mail thread and Edris's tables.
  - Cloned the Overleaf to `paper/`; it contains only the IEEEtran how-to template.
  - Checked the ReLANCE repository (incomplete).
  - Recommended the benchmark approach.
- **2026-11-12:**
  - Amir decided: benchmark on one shared testbed; STDP on chip; LUT and shift-decay baselines; sky130; MNIST
    (to confirm).
  - Four agents read all 27 PDFs in `references/` (reports summarised in section 4).
  - Checked the one-datapath CORDIC identity in float64.
  - Wrote `planning.md` and this file.
  - Nothing pushed to Overleaf, nothing sent to Edris.
- **2026-11-12 (later):**
  - Amir answered D1–D9: all recommendations accepted (D2 and D5 to be checked again later); we do not contact the
    authors; Edris follows the work through the shared Google Drive folder `CORDIC`.
  - Both files updated with the decisions and rewritten for Amir and Edris as readers; uploaded to Drive.
- **2026-11-13 (night):** Amir asked to start experiments. Everything is in `results/README.md`; in short:
  - **Testbed:** the float Diehl & Cook reference is validated at N = 100.
    - Wu 2021's rule (exponential weight dependence, β = 0.25): 83.3 %.
    - D&C's power-law rule with the public code's parameters: 78.0 %. D&C retuned two parameters for N = 100
      without publishing them.
    - A 1 ms step makes forward Euler unstable, so the testbed keeps 0.5 ms.
    - The simulator is CPU numba: 3.3 min per run, so the GPU is not needed.
    - N = 400 was about 15× slower than estimated and was stopped; to be profiled.
  - **Units:** batch 1 is implemented bit-exactly. A separate test agent wrote 305 tests from the spec alone, found
    one spec error (the shift-decay bound) and several ambiguities, now resolved in draft 3. Unit sizing for 1 LSB
    is in `results/units/SIZING.md`.
  - **E2 (precision knee):** the trace needs about 4 bits. Wu's weight-dependence factor works at 2 bits.
  - **E3 (methods at the knee and ablations):**
    - β = 0 (no weight-dependence exponential at all) costs at most about 1 pp, which is n.s. with 3 seeds. Wu's
      two CORDICs per synapse may be unnecessary.
    - A box kernel loses 12–32 pp, so the trace does need an exponential, but a coarse one.
    - The cheapest CORDIC that meets max |err| ≤ 1 loses 3–6 pp on the power-law rule. Its error is biased upward
      (+0.23 LSB over the first 2τ at 3 bits), so the accumulating trace decays too slowly.
    - Lesson: a unit-level error bound is not enough; compare at network-level iso-accuracy (as planned), and
      report the bias.
  - **RTL:** batch 1 (96 modules) is bit-exact against the models. The Yosys area probe has the LUT smallest at
    every precision in both roles, so my prediction "CORDIC is smallest at 12+ bits" does not hold for these short
    input ranges.
  - **Flow note:** I reported a Yosys/ABC hang with a long TMPDIR to `flow_notes/inbox/`.
  - **Repository:** the private GitHub repository was created (D6).
  - **Mistake on my side:** I edited `testbed/dc_sim.py` while the pilot was forking workers from it. I noticed it
    and reverted within a minute; no run was affected (verified: no worker started in that window). Since then every
    campaign runs from a frozen copy of the code (`testbed/campaign.py prepare`).
- **2026-11-13 (day):**
  - Amir agreed with D10 (Wu's rule as the main rule) and D11 (N = 400 only for final points, after profiling).
  - **E4 (10 seeds, paired):**
    - the bias hypothesis is confirmed (+0.25 LSB: −3 to −7 pp; −0.25 LSB: +1.2 to +2.5 pp);
    - a 4-bit trace and a 2-bit weight dependence equal float;
    - β = 0 costs 1.3 pp;
    - nearest-spike traces cost 5 pp, so accumulating traces and a multiplier are needed.
  - **N = 400 profiling (E5):** forward Euler explodes; backward Euler is stable. Wu's rule reaches 85.4 % and the
    power-law rule 82.6 % at N = 400. Backward Euler moves N = 100 by up to −2.5 pp, so one integrator is needed
    for all final numbers.
  - Wrote proposals: `specs/engine.md` (D5) and `specs/exp_units_batch2.md` (D2).
  - **Repository made public at Amir's request:**
    - the history was rewritten to remove `drive_ids.json` (the Drive folder is link-editable);
    - author email changed to the GitHub noreply address and the Claude trailers removed (Amir's choices);
    - a recovery bundle of the old history is in the session scratchpad.
    - GitHub may keep the unreachable old commits until its garbage collection; their SHAs were never public.
