# Spec: the shared testbed (Diehl & Cook 2015 network on MNIST)

Status: draft 1, 2026-11-13. Implementation: `testbed/dc_sim.py` (float reference) and `testbed/run_dc.py`. The
integer, hardware-faithful model follows once the float reference is validated (planning.md, P2).

## 1. Sources

- **[DC15]** P. U. Diehl, M. Cook, "Unsupervised learning of digit recognition using spike-timing-dependent
  plasticity", Front. Comput. Neurosci. 9:99, 2015. Equations 1–6, sections 2.1–2.6, Results.
- **[DCcode]** their public Brian 1 code, github.com/peter-u-diehl/stdp-mnist, `Diehl&Cook_spiking_MNIST.py`.
  It implements the triplet rule for 400 neurons, and it contains parameter values that the paper does not give.

## 2. Network and parameters

| item | value | source |
|---|---|---|
| input | 784 Poisson trains, rate = pixel/8 × intensity Hz, intensity starts at 2, so 0–63.75 Hz | DC15 2.5; DCcode l.447 |
| presentation / rest | 350 ms with input, then 150 ms without | DC15 2.5–2.6 |
| too little activity | fewer than 5 excitatory spikes in 350 ms: intensity += 1 (+31.9 Hz max rate) and the example is presented again | DC15 2.5; DCcode l.480 |
| excitatory neuron | τ dv/dt = (E_rest − v) + g_e(E_exc − v) + g_i(E_inh − v); τ = 100 ms, E_rest = −65 mV, E_exc = 0, E_inh = −100 mV, v_reset = −65 mV, threshold −52 mV − 20 mV + θ, refractory 5 ms | DC15 eq. 1; DCcode l.267–322 |
| adaptive threshold | θ += 0.05 mV per spike, decays with τ_θ = 10^7 ms, θ(0) = 20 mV; frozen after training | DCcode l.304–306, 371 |
| inhibitory neuron | τ = 10 ms, E_rest = −60, E_inh = −85 mV, threshold −40, reset −45 mV, refractory 2 ms | DCcode l.268–329 |
| synapses | conductance jumps by w, decays with τ_ge = 1 ms, τ_gi = 2 ms | DC15 eq. 2; DCcode l.315–316 |
| excitatory → inhibitory | one-to-one, w = 10.4 | DCcode generator |
| inhibitory → excitatory | all but the own partner, w = 17.0 | DCcode generator; DC15 2.2 |
| input → excitatory | all-to-all, initial w = (U[0,1) + 0.01)·0.3, w ∈ [0, 1], delay U[0, 10) ms | DCcode generator, l.286 |
| time step | 0.5 ms, forward Euler; conductances decay by (1 − dt/τ) per step | DCcode l.213 (Brian 1 default for this system) |
| training | N = 100: 40 000 examples; N = 400: 3 × 60 000, in MNIST order | DC15 Results; DCcode l.444–452 |
| labels | learning off, θ fixed, one presentation of the 60 000 training examples; each neuron gets the class of its highest average response | DC15 2.6 |
| test | 10 000 test examples once; class = highest average response of the neurons assigned to it (ties: highest index, as DCcode) | DC15 2.6 |

## 3. Learning rules (all from DC15; parameters where DC15 is silent come from DCcode)

The presynaptic trace x_pre decays with τ_pre = 20 ms and is **increased by 1** at every presynaptic spike (DC15
2.3). The triplet rule of DCcode instead **sets** its traces to 1. Updates are clipped to [0, w_max = 1].

| rule | on a postsynaptic spike | on a presynaptic spike | parameters |
|---|---|---|---|
| power-law (DC15 eq. 3; the rule of the published 82.9 / 87.0 / 91.9 / 95.0 %) | Δw = η (x_pre − x_tar)(w_max − w)^μ | — | η = 0.01, x_tar = 0.4, μ = 0.2 (DCcode leftovers `nu_ee_post`, `STDP_offset`, `exp_ee_pre`) |
| exponential weight dependence (DC15 eq. 4; Wu 2021 uses it) | Δw = η (x_pre e^(−βw) − x_tar e^(−β(w_max−w))) | — | η = 0.01, x_tar = 0.4; β not given by DC15 (Wu 2021: 0.25; we also try 3) |
| pre-and-post (DC15 eqs. 5–6) | as power-law | Δw = −η_pre x_post w^μ | η_pre = 10^−4, τ_post = 20 ms |
| triplet (DCcode) | Δw = η_post x_pre x_post2 (before reset); x_post1 = x_post2 = 1 | x_pre = 1; Δw = −η_pre x_post1 | η_pre = 10^−4, η_post = 0.01, τ_post1 = 20, τ_post2 = 40 ms, normalisation of each neuron's input weights to sum 78 before every example |

Where the exponentials sit (the two roles of planning.md):
- **R1, the timing kernel:** every trace, e^(−Δt/τ).
- **R2, the weight dependence:** e^(−βw) in the exponential rule, and (w_max − w)^μ = e^(μ ln(w_max − w)) in the
  power-law rule.

## 4. Deviations from DC15 / DCcode (deliberate, to be checked by the pilot)

1. **Delays and the presynaptic trace.** Delays are applied to the conductance only. The presynaptic trace is
   updated when the input neuron fires, not when its spike arrives at each synapse (that would need one trace per
   synapse).
2. **No retuning.** DC15 retuned the adaptive threshold and the inhibition per network size without publishing the
   values for N = 100. We start from DCcode's values (tuned for N = 400).
3. **Our own implementation.** The code is a new implementation in Python/numba, not Brian 1: same equations, same
   update order up to the order within one time step.

## 5. Pilot (planning.md P2) and its questions

- Does the float reference reach DC15's accuracy: 82.9 % at N = 100, 87.0 % at N = 400?
- Do the speed-ups change accuracy (pass: within one standard deviation over seeds)?
  - a 1 ms step;
  - a reset in place of the 150 ms rest;
  - no delays.
- How do the other rules compare?
  - the exponential rule with β = 0.25 and β = 3;
  - pre-and-post;
  - triplet.
- Is a labelling pass of 10 000 examples enough (the sweeps would then be 4× cheaper)?

Results: `results/testbed/SUMMARY.md`.
