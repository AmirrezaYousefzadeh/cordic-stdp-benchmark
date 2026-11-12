# Spec: exponential units, batch 1 (methods that need no paper interpretation)

Status: draft 3, 2026-11-13. Draft 2 added the extra constant bits P in C1 and B4. Draft 3 resolves the
ambiguities found by the independent test agent (A1–A7, E1 below). Implementation: `model/exp_units.py`. Tests: `tests/test_exp_units.py` (written by a
separate agent from this spec only). Paper-specific methods (C2 angle recoding after Wu 2021 / Wang 2026, C3 exactly
as Heidarpur 2019 and Bahrami 2024) get their own spec later.

## 1. The function and the number formats

Every unit computes y = e^(−x) for x ≥ 0.

- **Input:** an unsigned integer code `n` (0 ≤ n < 2^b). The unit has a fixed positive constant `c`, and
  x = n·c. Role R1 (timing kernel): n = Δt in time steps, c = dt/τ. Role R2 (weight dependence): n = weight code,
  c = β/2^(weight fraction bits).
- **Output:** an unsigned integer code `y` with 0 ≤ y ≤ 2^Fo. Its value is y/2^Fo, so e^0 = 1 is the code 2^Fo; the
  output bus is Fo+1 bits wide.
- **Internal width:** fixed point with W = Fo + g fractional bits, where g is the number of guard bits (a parameter).
- **Reference:** `ref(n) = floor(2^Fo · e^(−n·c) + 1/2)` computed in float64 (round half up).
- **Error of a unit:** `err(n) = y(n) − ref(n)` in output LSBs. Reported: max |err|, mean |err|, and the fraction of
  inputs with err = 0, each over all n in the input range.
- **Rounding rule inside the units:** right shifts are arithmetic shifts (floor) unless a step says "round", which
  means adding half an LSB of the target position before the shift (round half up). A rounding shift by 0 adds
  nothing. **Constants** written round(v) are floor(v + 1/2) (half up, as the reference); they are computed in
  float64 once per unit. Parameters guard, const_frac and frac_bits are ≥ 0; Fo ≥ 1, iters ≥ 1, k ≥ 1, steps ≥ 0.

## 2. Methods

### B1 `lut_exp(n, c, fo)`: lookup table
- y(n) = ref(n) for every n. Exact by definition: it is the yardstick for the other units.
- In hardware it is a ROM of 2^b words of Fo+1 bits. The entries that are 0 (n ≥ n_zero) can be replaced by a
  comparator.

### C1 `cordic_exp(n, c, fo, guard=3, iters=None, const_frac=16)`: hyperbolic CORDIC, rotation mode, one datapath
1. **Angle:** Z = (n·C + 2^(P−1)) >> P, with C = round(c·2^(W+P)) and P = 16 extra constant bits (keyword
   `const_frac=16`). This is a constant multiplier in hardware. (Draft 1 had C = round(c·2^W), which rounds to 0
   when c < 2^−W, e.g. in the weight role.)
2. **Range reduction:** L = round(ln2·2^W), q = floor(Z / L), r = Z − q·L, so 0 ≤ r < L. The value is
   x ≈ q·ln2 + r/2^W.
3. **Underflow:** if q > Fo + 1, the output is 0.
4. **Iteration list:** the indices are 1, 2, 3, 4, 4, 5, …, 13, 13, 14, …, 40, 40, …; indices 4, 13 and 40 are taken
   twice. `iters` = m is the total number of iterations, repeats included. The default is m = Fo + g + 1.
5. **Initial value:** G = Π over the **first m entries** of the list (the iterations performed) of √(1 − 2^(−2i)),
   and Y = round(2^W / G).
6. **Rotations:** z = −r. For each index i in the first m entries of the list:
   - d = +1 if z ≥ 0, else −1;
   - Y = Y + d·(Y >> i) (floor shift);
   - z = z − d·A_i, with A_i = round(atanh(2^−i)·2^W).

   Then Y ≈ 2^W·e^(−r/2^W). (The usual two-datapath form, with x = cosh and y = sinh, gives the same product; this
   is the one-datapath form with x = y.)
7. **Output:** y = (Y + 2^(q+g−1)) >> (q + g), i.e. rounded to Fo bits after the shift by q. Clamp to [0, 2^Fo].

### B3 `bitprod_exp(n, c, fo, guard=3)`: product of constants selected by the bits of n (no comparisons, no z path)
1. **Constants:** K_k = round(e^(−2^k·c)·2^W) for each input bit k = 0 … b−1. Here b is the bit length of the
   largest n of the call, taken as `max(1, int(n.max()).bit_length())`.
2. **Products:** Y = 2^W. For k = 0, 1, …, b−1 (least significant bit first): if bit k of n is 1, then
   Y = (Y·K_k) >> W (floor).
3. **Output:** y = (Y + 2^(g−1)) >> g, clamped to [0, 2^Fo].
4. **Hardware note:** for a fixed c the K_k are constants, so each step is a constant multiplier. A serial version
   uses one constant table and one multiplier.

### B4 `pow2_exp(n, c, fo, guard=3, frac_bits=4, mode="table", const_frac=16)`: e^(−x) = 2^(−x·log2 e), shift plus small table
1. **Exponent:** U = (n·Cu + 2^(P−1)) >> P, with Cu = round(c·log2(e)·2^(F+P)), F = `frac_bits` and P = 16
   (keyword `const_frac=16`). Then q = U >> F and f = U mod 2^F.
2. **Fraction:**
   - `mode="table"`: T[f] = round(2^(−f/2^F)·2^W), a table of 2^F entries;
   - `mode="linear"`: T[f] = 2^W − ((f·2^W) >> (F+1)), i.e. 2^(−u) ≈ 1 − u/2 for 0 ≤ u < 1 (Mitchell-style, no
     table).
3. **Output:** if q + g > W + 1 the output is 0; otherwise y = (T[f] + 2^(q+g−1)) >> (q + g), clamped to [0, 2^Fo].
4. **Note:** when c·log2(e) is a power of two (τ·ln2 a power of two in steps), Cu is a shift and the constant
   multiplier disappears.

### B2 `shift_decay_trace(k, steps, fo, guard=3, rounding="floor")`: clock-driven trace, no exponential unit
- At a spike the trace is set to Y = 2^W. Every time step, Y = Y − (Y >> k) (`rounding="floor"`), or
  Y = Y − ((Y + 2^(k−1)) >> k) (`rounding="round"`).
- The function returns the output codes y_t = (Y_t + 2^(g−1)) >> g for t = 0 … steps.
- Its exact counterpart is e^(−t·c_eff) with c_eff = −ln(1 − 2^(−k)). The time constant it implements is
  τ_eff = 1/c_eff ≈ 2^k − 1/2 steps.
- The unit does not take n; the error is computed against ref(t) with c = c_eff.

## 3. Properties every unit must have (tests check these)

Properties 1 and 6 hold at any setting; properties 2–5 at the default settings unless stated.

1. **Output range:** y(n) ∈ [0, 2^Fo] for every input.
2. **Zero input:**
   - B1, B3 and B4 give y(0) = 2^Fo exactly.
   - C1 gives y(0) within 1 LSB of 2^Fo at its default settings.
   - B2 gives y_0 = 2^Fo.
3. **Shape:** y is non-increasing in n for B1, B3 and B4, and in t for B2. For C1, y(n2) ≤ y(n1) + 1 for all
   n1 < n2. (At non-default settings, B3 with guard ≤ 2 and C1 with very few iterations can rise by 1–2 LSB.)
4. **Large inputs:** y(n) = 0 whenever e^(−n·c) < 2^−(Fo+2), for C1, B3 and B4.
5. **Accuracy at default settings** (Fo from 4 to 16, c in {1/40, 1/20, 1/16, 0.25/2^4, 3/2^8}, n over 0 …
   ⌈(Fo+2)·ln2/c⌉):
   - C1: max |err| ≤ 1;
   - B3: max |err| ≤ 1;
   - B4 table, `frac_bits` ≥ Fo + 1: max |err| ≤ 1 (a table without interpolation quantises the fraction to
     2^−F, so it needs about Fo fraction bits; draft 1 said Fo/2 + 2, which is wrong);
   - B2 against its own c_eff, `rounding="round"`, steps ≤ ⌈(Fo+2)·ln2/c_eff⌉: max |err| ≤ max(1, 2^(k−1−g)),
     with equality for 1 ≤ g ≤ k − 1 while 2^(k−1−g) ≤ 2^Fo; guard = k − 1 gives exactly 1. So **guard ≥ k − 1 is
     needed for max |err| ≤ 1** (with "round", the decrement (Y + 2^(k−1)) >> k becomes 0
     once Y < 2^(k−1), and the trace sticks there; draft 2's "≤ 2 at guard 3" was false for k ≥ 6). Tested for
     k = 1 … 8 with guard = k − 1.
6. **Function signatures:** all accept numpy integer arrays of any shape for `n` (B2 takes Python or numpy integer
   scalars) and return numpy int64 arrays of the same shape (a 0-d input gives a 0-d array, not a scalar); an empty `n` returns an empty array.
   `ref_exp(n, c, fo)` is part of the module.
