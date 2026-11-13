# Spec (proposal): exponential units batch 2, the methods of the papers

Status: draft 1, 2026-11-13, **proposal for Amir's D2 check**. Same formats, reference and error definition as
batch 1 (`specs/exp_units.md`, draft 3).

We cannot ask the authors (D7). Wherever a paper is ambiguous or wrong, the spec says so and states our resolution,
and the paper calls our unit "after [ref]". The source facts, with page numbers, are in `claude_toughts.md`
section 4.

## C2 `recode_exp(n, c, fo, guard=3, max_iters=None, gain_terms=2)`: angle-recoding hyperbolic CORDIC

After Wu et al., TCAS-I 2021 (their "fast CORDIC", from Wang et al. 2018), and Hu & Naganathan's angle recoding.
Wang et al., IJCTA 2026 ("adaptive" CORDIC with early termination) is the same idea.

**The idea:** a conventional CORDIC runs every index i = 1 … m. Angle recoding picks, at each step, the index whose
angle atanh(2^−i) is closest to the residual. The number of steps then depends on the input, and is about half of m
on average (Wu 2021 Table I: 4.18 instead of 8 at 8 bits).

**Our specification:**
1. **Angle and range reduction:** z = −r with 0 ≤ r < ln 2, and q, exactly as C1 (P = 16 extra constant bits).
2. **Iterations.** Repeat while |z| ≥ 2^−W and fewer than `max_iters` (default Fo + g + 1) steps have been taken:
   - d = sign(z) (+1 for z ≥ 0);
   - i = the index in 1 … W that minimises | |z| − A_i |, with A_i = round(atanh(2^−i)·2^W); on a tie, the larger
     i. This is a priority encoder plus one comparison in hardware;
   - Y ← Y + d·(Y >> i);
   - **gain correction:** Y ← Y + (Y >> (2i+1)) + (Y >> (4i+3)) (`gain_terms` = 2; the first terms of
     1/√(1 − 2^−2i)), skipped for 2i+1 > W;
   - z ← z − d·A_i.
3. **Initial and final value:** Y starts at 2^W; there is no constant gain, because the gain is corrected in every
   step. The output is rounded and shifted by q as in C1.

**Where Wu's paper is ambiguous, and what we choose:**
- Alg. 2 applies the scale factor once, from the last angle only (ListScale[AngleIndex]). That is wrong for a
  varying set of angles. We correct the gain in every step, as Wu's text describes ("scaling per iteration, by
  shift-and-add").
- Wu's typo (shift by i instead of the chosen index) is not reproduced.
- The candidate set is all indices 1 … W, and repeats are allowed.

**What we report:** besides the error and the area, the **average and maximum iteration count** over the operand
histogram of the testbed. The energy depends on it, and the paper claims its advantage from it.

## C3 `heidarpur_exp(n, c, fo, guard=3, frac_bits=None, csd_terms=3, tail=False)`: product of constants by shift-add

After Heidarpur et al., TCAS-I 2019 (the STDP exponential), and Bahrami & Nazari, Sci. Rep. 2024 ("Exp CORDIC";
it adds `tail`).

**The idea:** e^(−x) = Π over the set bits k of x of e^(−2^k·2^−F). This is our B3, but the multiplications by the
constants a_k = e^(−2^k·2^−F) are done by **shift-and-add with a few terms**: each constant rounded to `csd_terms`
non-zero canonical-signed-digit digits. That makes C3 cheaper than B3 and less accurate.

**Our specification:**
1. **Input:** x = n·c converted to F fraction bits (F = `frac_bits`, default Fo + 2):
   X = round(n·c·2^F) via the constant multiplier (P = 16 extra bits).
2. **Integer part:** x_int = X >> F; the output is 0 if x_int > Fo + 1.
   - Heidarpur restricts x to [−1, 0], so it has no integer part. Bahrami multiplies by e^−1 x_int times.
   - We implement the integer part as a table of e^(−x_int) (at most Fo + 2 entries) followed by one more
     constant-product step, the cheapest correct choice. It is stated as our extension.
3. **Fraction bits:** Y = 2^W; for every set bit k of X mod 2^F (k = 0 … F−1, LSB first),
   Y ← Y·CSD_t(a_k) using shifts and adds, where CSD_t(a) is a rounded to t = `csd_terms` non-zero digits.
4. **Tail (`tail=True`, Bahrami):** the residual fraction below 2^−F is not discarded; Y ← Y − (Y·z) with z the
   residual (Bahrami keeps only f·(1+z), "the first component" of their Maclaurin series).
5. **Output:** round to Fo bits.

**Where the papers are ambiguous, and what we choose:**
- **Negative inputs (Heidarpur):** Heidarpur's pseudocode computes e^(+frac); we use constants e^(−2^−i)
  (resolution (b) of the reading report).
- **Iterations (Heidarpur):** 6 vs 8 — here they are the `frac_bits` actually used.
- **Constant approximation (Heidarpur):** the number of shift-add terms is not stated; `csd_terms` is swept over
  2, 3, 4.
- **Bahrami's ln series bug:** it does not affect the exp unit. Their ln and pow units are needed only for the
  power-law rule, which is our second rule (D10), so they are not part of batch 2.

## Not in batch 2

- **Sheng 2024 (asynchronous CORDIC):** the algorithm is not given, and an asynchronous circuit needs a different
  flow (described in the paper, not built; D2).
- **Wu 2025 (pair/triplet):** its "CORDIC" is unspecified, and its exp matrix is a table, i.e. our B1.

## Tests and RTL

As batch 1:
- the tests are written by a separate agent from this spec;
- the RTL is generated from the model and checked bit-exact on every input.

For C2, the RTL has a data-dependent latency (busy/done handshake). Its testbench checks the iteration count of
every input against the model.
