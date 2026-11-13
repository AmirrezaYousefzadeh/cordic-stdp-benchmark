"""Float reference of the Diehl & Cook (2015) network: 784 Poisson inputs -> N excitatory LIF neurons with adaptive
threshold, one-to-one excitatory->inhibitory, all-but-self inhibitory->excitatory (lateral inhibition), STDP on the
input weights.

Equations and parameters: Diehl & Cook 2015 (Front. Comput. Neurosci. 9:99), eqs. 1-6, and their public Brian code
(github.com/peter-u-diehl/stdp-mnist, Diehl&Cook_spiking_MNIST.py). See specs/testbed.md for every value, its source,
and the deviations.

Time stepping as in Brian 1 for this nonlinear system: forward Euler with step dt; conductances decay by (1 - dt/tau)
per step. Presynaptic and postsynaptic traces are evaluated lazily (value and time of the last update), which is exact
for exponential decay and costs nothing between spikes.

All state is float64; this file is the reference the integer, hardware-faithful model is checked against.
"""
import math
import numpy as np
import numba as nb

# ---- learning rules -------------------------------------------------------------------------------------------
RULE_POWER = 0     # D&C eq. 3: on post spike  dw = eta_post (x_pre - x_tar) (w_max - w)^mu
RULE_EXPW = 1      # D&C eq. 4: on post spike  dw = eta_post (x_pre e^{-beta w} - x_tar e^{-beta (w_max - w)})
RULE_PREPOST = 2   # D&C eqs. 5-6: on pre spike dw = -eta_pre x_post w^mu ; on post spike as eq. 3
RULE_TRIPLET = 3   # D&C public code: on pre  pre=1; w -= eta_pre post1 ; on post  w += eta_post pre post2before
RULES = {"power": RULE_POWER, "expw": RULE_EXPW, "prepost": RULE_PREPOST, "triplet": RULE_TRIPLET}

# ---- parameter vector layout (float64) --------------------------------------------------------------------------
(DT, TAU_E, TAU_I, TAU_GE, TAU_GI, VREST_E, VREST_I, VRESET_E, VRESET_I, VTH_E, VTH_I, OFFSET, EEXC, EINH_E, EINH_I,
 REFR_E, REFR_I, THETA_PLUS, TAU_THETA, THETA0, W_EI, W_IE, TAU_PRE, TAU_POST1, TAU_POST2, ETA_PRE, ETA_POST, XTAR,
 MU, BETA, WMAX, NORM_SUM, T_PRES, T_REST, INTENSITY0, MIN_SPIKES, MAX_DELAY, W_INIT, NPARAM) = range(39)
# ---- option vector layout (int64) -------------------------------------------------------------------------------
(O_RULE, O_TRACE_SET, O_NORM, O_DELAYS, O_RESET, O_MAX_BUMPS, NOPT) = range(7)
# ---- statistics vector layout (int64) ---------------------------------------------------------------------------
(S_IN_SPIKES, S_E_SPIKES, S_I_SPIKES, S_BUMPS, S_PRESENTATIONS, S_GAVE_UP, S_STEPS,
 S_PRE_UPD, S_PRE_EVAL, S_POST_LEARN, S_POST_READ, S_WUPD, S_W_EVAL, NSTAT) = range(14)
# learning-engine event counts (only while learning):
#   pre_upd    presynaptic trace updates (one per input spike)
#   pre_eval   of those, the ones that need an exp evaluation (accumulating traces: X = X e(dt) + 1)
#   post_learn postsynaptic spikes that trigger a weight-update sweep
#   post_read  trace reads in those sweeps (n_in per post spike; each one is an exp evaluation, role R1)
#   wupd       synapse weight updates
#   w_eval     weight-dependence exp evaluations (role R2; two per update in the exponential rule)
HIST_D = 4096        # histogram bins of dt (in steps) at R1 evaluations; the last bin collects dt >= HIST_D - 1

PARAM_NAMES = ["dt", "tau_e", "tau_i", "tau_ge", "tau_gi", "vrest_e", "vrest_i", "vreset_e", "vreset_i", "vth_e",
               "vth_i", "offset", "e_exc", "e_inh_e", "e_inh_i", "refr_e", "refr_i", "theta_plus", "tau_theta",
               "theta0", "w_ei", "w_ie", "tau_pre", "tau_post1", "tau_post2", "eta_pre", "eta_post", "x_tar", "mu",
               "beta", "w_max", "norm_sum", "t_pres", "t_rest", "intensity0", "min_spikes", "max_delay", "w_init"]
OPT_NAMES = ["rule", "trace_set", "normalize", "delays", "reset", "max_bumps"]
STAT_NAMES = ["input_spikes", "exc_spikes", "inh_spikes", "bumps", "presentations", "gave_up", "steps",
              "pre_upd", "pre_eval", "post_learn", "post_read", "wupd", "w_eval"]


def default_params():
    """D&C values (ms, mV, conductances relative to the leak). Sources in specs/testbed.md."""
    p = np.zeros(NPARAM)
    p[DT] = 0.5
    p[TAU_E], p[TAU_I], p[TAU_GE], p[TAU_GI] = 100.0, 10.0, 1.0, 2.0
    p[VREST_E], p[VREST_I], p[VRESET_E], p[VRESET_I] = -65.0, -60.0, -65.0, -45.0
    p[VTH_E], p[VTH_I], p[OFFSET] = -52.0, -40.0, 20.0
    p[EEXC], p[EINH_E], p[EINH_I] = 0.0, -100.0, -85.0
    p[REFR_E], p[REFR_I] = 5.0, 2.0
    p[THETA_PLUS], p[TAU_THETA], p[THETA0] = 0.05, 1e7, 20.0
    p[W_EI], p[W_IE] = 10.4, 17.0
    p[TAU_PRE], p[TAU_POST1], p[TAU_POST2] = 20.0, 20.0, 40.0
    p[ETA_PRE], p[ETA_POST] = 0.0001, 0.01
    p[XTAR], p[MU], p[BETA], p[WMAX] = 0.4, 0.2, 3.0, 1.0
    p[NORM_SUM] = 78.0
    p[T_PRES], p[T_REST] = 350.0, 150.0
    p[INTENSITY0], p[MIN_SPIKES] = 2.0, 5.0
    p[MAX_DELAY] = 10.0
    p[W_INIT] = 0.3
    return p


def default_opts():
    o = np.zeros(NOPT, dtype=np.int64)
    o[O_RULE] = RULE_POWER
    o[O_TRACE_SET] = 0      # 0: trace += 1 (paper, rules 1-3); 1: trace = 1 (public code, triplet)
    o[O_NORM] = 0           # divisive normalisation of each neuron's input weights before every example
    o[O_DELAYS] = 1         # input->excitatory delays, uniform in [0, MAX_DELAY) ms, as in the public code
    o[O_RESET] = 0          # 0: 150 ms rest without input; 1: reset all variables instead (faster)
    o[O_MAX_BUMPS] = 30     # give up raising the input rate after this many repetitions of one example
    return o


@nb.njit(cache=True)
def seed_rng(seed):
    np.random.seed(seed)


@nb.njit(cache=True)
def init_network(n_in, n, prm, seed):
    """Initial weights uniform in [0.01, 1.01) * w_init (public code), delays in steps, initial theta."""
    np.random.seed(seed)
    W = np.empty((n_in, n))
    for i in range(n_in):
        for j in range(n):
            W[i, j] = (np.random.random() + 0.01) * prm[W_INIT]
    dsteps = int(prm[MAX_DELAY] / prm[DT])
    delays = np.empty((n_in, n), dtype=np.int64)
    for i in range(n_in):
        for j in range(n):
            delays[i, j] = int(np.random.random() * dsteps)   # [0, dsteps-1]
    theta = np.full(n, prm[THETA0])
    return W, delays, theta


@nb.njit(cache=True)
def _geometric_gap(p):
    """Number of empty steps before the next spike of a Bernoulli(p)-per-step train (exact for Brian's
    per-step Poisson process)."""
    if p >= 1.0:
        return 0
    u = 1.0 - np.random.random()          # (0, 1]
    return int(math.floor(math.log(u) / math.log1p(-p)))


@nb.njit(cache=True)
def run_phase(images, order, learn, prm, opt, W, theta, delays, counts, stats, seed,
              tab_pre, fo_pre, tab_w, fo_w, hist_d, hist_w):
    """Present images[order[k]] for k = 0..K-1. counts[k, j] = spikes of excitatory neuron j during the accepted
    presentation of example k. learn=True: STDP, adaptive threshold and normalisation on. Mutates W, theta, stats.

    Quantised exponential units (empty table = float64 as in the reference):
    tab_pre[d] = output code (fo_pre fraction bits) of an exp unit for e^(-d dt/tau_pre), d in steps; d beyond the
        table gives 0. The presynaptic trace is then an integer with fo_pre fraction bits: on a presynaptic spike
        X = round(X e(d)) + 1 (or X = 1 with trace_set), read as round(X e(d)). This is exactly what an
        event-driven learning engine with that unit and one multiplier computes.
    tab_w[nw] = output code (fo_w fraction bits) of an exp unit for e^(-beta nw/256), nw = round(256 w) in 0..256,
        used for both weight-dependence factors of the exponential rule (e^(-beta w) and e^(-beta (1 - w))).
    hist_d[min(dt, HIST_D-1)] and hist_w[nw] count the operands of the R1 and R2 evaluations while learning (the
    operand streams for the gate-level power simulation); they are counted in float mode too."""
    np.random.seed(seed)
    n_in = W.shape[0]
    n = W.shape[1]
    dt = prm[DT]
    rule = opt[O_RULE]
    dec_ge = max(0.0, 1.0 - dt / prm[TAU_GE])
    dec_gi = max(0.0, 1.0 - dt / prm[TAU_GI])
    ke = dt / prm[TAU_E]
    ki = dt / prm[TAU_I]
    dec_th = 1.0 - dt / prm[TAU_THETA]
    n_pres = int(round(prm[T_PRES] / dt))
    n_rest = int(round(prm[T_REST] / dt))
    refr_e_steps = int(round(prm[REFR_E] / dt))
    refr_i_steps = int(round(prm[REFR_I] / dt))
    vrest_e = prm[VREST_E]; vrest_i = prm[VREST_I]
    vreset_e = prm[VRESET_E]; vreset_i = prm[VRESET_I]
    vth_e = prm[VTH_E] - prm[OFFSET]; vth_i = prm[VTH_I]
    eexc = prm[EEXC]; einh_e = prm[EINH_E]; einh_i = prm[EINH_I]
    a_pre = dt / prm[TAU_PRE]; a_p1 = dt / prm[TAU_POST1]; a_p2 = dt / prm[TAU_POST2]
    eta_pre = prm[ETA_PRE]; eta_post = prm[ETA_POST]; xtar = prm[XTAR]; mu = prm[MU]; beta = prm[BETA]
    wmax = prm[WMAX]
    use_delays = opt[O_DELAYS] == 1
    D = int(prm[MAX_DELAY] / dt) + 1
    ring = np.zeros((D, n))

    v_e = np.full(n, vrest_e - 40.0)
    v_i = np.full(n, vrest_i - 40.0)
    ge_e = np.zeros(n); gi_e = np.zeros(n); ge_i = np.zeros(n); gi_i = np.zeros(n)
    refr_e = np.zeros(n, dtype=np.int64); refr_i = np.zeros(n, dtype=np.int64)
    xpre = np.zeros(n_in); tpre = np.zeros(n_in, dtype=np.int64)
    qpre = tab_pre.shape[0] > 0
    if qpre and rule == RULE_TRIPLET:
        raise ValueError("quantised presynaptic traces are not implemented for the triplet rule")
    lpre = tab_pre.shape[0]
    one_pre = 1 << fo_pre
    half_pre = (1 << (fo_pre - 1)) if fo_pre > 0 else 0
    xq = np.zeros(n_in, dtype=np.int64)
    qw = tab_w.shape[0] > 0
    sc_w = 1.0 / (1 << fo_w)
    xp1 = np.zeros(n); xp2 = np.zeros(n); tpost = np.zeros(n, dtype=np.int64)
    nxt = np.zeros(n_in, dtype=np.int64)
    act = np.zeros(n_in, dtype=np.int64)
    prob = np.zeros(n_in)
    spk_e = np.zeros(n, dtype=np.int64); spk_i = np.zeros(n, dtype=np.int64)
    cnt = np.zeros(n, dtype=np.int64)
    t = 0
    for k in range(order.shape[0]):
        img = images[order[k]]
        intensity = prm[INTENSITY0]
        bumps = 0
        while True:
            if learn and opt[O_NORM] == 1:
                for j in range(n):
                    s = 0.0
                    for i in range(n_in):
                        s += W[i, j]
                    f = prm[NORM_SUM] / s
                    for i in range(n_in):
                        W[i, j] *= f
            nact = 0
            for i in range(n_in):
                if img[i] > 0:
                    act[nact] = i
                    prob[nact] = min(1.0, img[i] / 8.0 * intensity * dt * 1e-3)
                    nxt[i] = t + _geometric_gap(prob[nact])
                    nact += 1
            for j in range(n):
                cnt[j] = 0
            nsteps = n_pres if opt[O_RESET] == 1 else n_pres + n_rest
            for s in range(nsteps):
                inp = s < n_pres
                # 1. input spikes
                if inp:
                    for a in range(nact):
                        i = act[a]
                        if nxt[i] == t:
                            nxt[i] = t + 1 + _geometric_gap(prob[a])
                            stats[S_IN_SPIKES] += 1
                            if use_delays:
                                for j in range(n):
                                    ring[(t + delays[i, j]) % D, j] += W[i, j]
                            else:
                                for j in range(n):
                                    ge_e[j] += W[i, j]
                            if learn:
                                if rule == RULE_TRIPLET or rule == RULE_PREPOST:
                                    for j in range(n):
                                        if rule == RULE_TRIPLET:
                                            p1 = xp1[j] * math.exp(-(t - tpost[j]) * a_p1)
                                            w = W[i, j] - eta_pre * p1
                                        else:
                                            p1 = xp1[j] * math.exp(-(t - tpost[j]) * a_p1)
                                            w = W[i, j] - eta_pre * p1 * W[i, j] ** mu
                                        W[i, j] = w if w > 0.0 else 0.0
                                stats[S_PRE_UPD] += 1
                                if opt[O_TRACE_SET] == 0:
                                    stats[S_PRE_EVAL] += 1
                                    dh = t - tpre[i]
                                    hist_d[dh if dh < HIST_D else HIST_D - 1] += 1
                                if qpre:
                                    if opt[O_TRACE_SET] == 1:
                                        xq[i] = one_pre
                                    else:
                                        dd = t - tpre[i]
                                        e = tab_pre[dd] if dd < lpre else 0
                                        xq[i] = ((xq[i] * e + half_pre) >> fo_pre) + one_pre
                                elif opt[O_TRACE_SET] == 1:
                                    xpre[i] = 1.0
                                else:
                                    xpre[i] = xpre[i] * math.exp(-(t - tpre[i]) * a_pre) + 1.0
                                tpre[i] = t
                if use_delays:
                    slot = t % D
                    for j in range(n):
                        ge_e[j] += ring[slot, j]
                        ring[slot, j] = 0.0
                # 2. excitatory neurons
                ne = 0
                for j in range(n):
                    if refr_e[j] > 0:
                        refr_e[j] -= 1
                        v_e[j] = vreset_e
                    else:
                        v = v_e[j]
                        v_e[j] = v + ke * ((vrest_e - v) + ge_e[j] * (eexc - v) + gi_e[j] * (einh_e - v))
                    ge_e[j] *= dec_ge
                    gi_e[j] *= dec_gi
                    if learn:
                        theta[j] *= dec_th
                    if refr_e[j] == 0 and v_e[j] > theta[j] + vth_e:
                        spk_e[ne] = j
                        ne += 1
                        v_e[j] = vreset_e
                        refr_e[j] = refr_e_steps
                        if learn:
                            theta[j] += prm[THETA_PLUS]
                        if inp:
                            cnt[j] += 1
                # 3. inhibitory neurons
                ni = 0
                for j in range(n):
                    if refr_i[j] > 0:
                        refr_i[j] -= 1
                        v_i[j] = vreset_i
                    else:
                        v = v_i[j]
                        v_i[j] = v + ki * ((vrest_i - v) + ge_i[j] * (eexc - v) + gi_i[j] * (einh_i - v))
                    ge_i[j] *= dec_ge
                    gi_i[j] *= dec_gi
                    if refr_i[j] == 0 and v_i[j] > vth_i:
                        spk_i[ni] = j
                        ni += 1
                        v_i[j] = vreset_i
                        refr_i[j] = refr_i_steps
                # 4. excitatory spikes: one-to-one excitation of the inhibitory partner; STDP on the post spike
                for a in range(ne):
                    j = spk_e[a]
                    ge_i[j] += prm[W_EI]
                    stats[S_E_SPIKES] += 1
                    if learn:
                        stats[S_POST_LEARN] += 1
                        stats[S_POST_READ] += n_in
                        stats[S_WUPD] += n_in
                        if rule == RULE_EXPW:
                            stats[S_W_EVAL] += 2 * n_in
                        if rule == RULE_TRIPLET:
                            p2b = xp2[j] * math.exp(-(t - tpost[j]) * a_p2)
                            for i in range(n_in):
                                x = xpre[i] * math.exp(-(t - tpre[i]) * a_pre)
                                w = W[i, j] + eta_post * x * p2b
                                W[i, j] = w if w < wmax else wmax
                            xp1[j] = 1.0
                            xp2[j] = 1.0
                            tpost[j] = t
                        else:
                            for i in range(n_in):
                                dh = t - tpre[i]
                                hist_d[dh if dh < HIST_D else HIST_D - 1] += 1
                                if qpre:
                                    dd = t - tpre[i]
                                    e = tab_pre[dd] if dd < lpre else 0
                                    x = ((xq[i] * e + half_pre) >> fo_pre) / one_pre
                                else:
                                    x = xpre[i] * math.exp(-(t - tpre[i]) * a_pre)
                                w = W[i, j]
                                if rule == RULE_EXPW:
                                    nh = int(w * 256.0 + 0.5)
                                    if nh > 256:
                                        nh = 256
                                    hist_w[nh] += 1
                                    hist_w[256 - nh] += 1
                                    if qw:
                                        nw = int(w * 256.0 + 0.5)
                                        if nw > 256:
                                            nw = 256
                                        w += eta_post * (x * (tab_w[nw] * sc_w) - xtar * (tab_w[256 - nw] * sc_w))
                                    else:
                                        w += eta_post * (x * math.exp(-beta * w) - xtar * math.exp(-beta * (wmax - w)))
                                else:
                                    w += eta_post * (x - xtar) * (wmax - w) ** mu
                                if w < 0.0:
                                    w = 0.0
                                elif w > wmax:
                                    w = wmax
                                W[i, j] = w
                            if rule == RULE_PREPOST:
                                if opt[O_TRACE_SET] == 1:
                                    xp1[j] = 1.0
                                else:
                                    xp1[j] = xp1[j] * math.exp(-(t - tpost[j]) * a_p1) + 1.0
                                tpost[j] = t
                # 5. inhibitory spikes: all-but-self inhibition of the excitatory layer
                for a in range(ni):
                    kk = spk_i[a]
                    stats[S_I_SPIKES] += 1
                    for j in range(n):
                        if j != kk:
                            gi_e[j] += prm[W_IE]
                t += 1
                stats[S_STEPS] += 1
            if opt[O_RESET] == 1:
                # replace the rest period by a reset of everything except theta and the weights
                for j in range(n):
                    v_e[j] = vrest_e; v_i[j] = vrest_i
                    ge_e[j] = 0.0; gi_e[j] = 0.0; ge_i[j] = 0.0; gi_i[j] = 0.0
                    refr_e[j] = 0; refr_i[j] = 0
                    xp1[j] = 0.0; xp2[j] = 0.0
                    if learn:
                        theta[j] *= dec_th ** n_rest
                for i in range(n_in):
                    xpre[i] = 0.0
                    xq[i] = 0
                for dd in range(D):
                    for j in range(n):
                        ring[dd, j] = 0.0
                t += n_rest
            stats[S_PRESENTATIONS] += 1
            total = 0
            for j in range(n):
                total += cnt[j]
            if total >= prm[MIN_SPIKES]:
                break
            bumps += 1
            stats[S_BUMPS] += 1
            if bumps > opt[O_MAX_BUMPS]:
                stats[S_GAVE_UP] += 1
                break
            intensity += 1.0
        for j in range(n):
            counts[k, j] = cnt[j]


def assign_labels(counts, labels, n_classes=10):
    """D&C: each neuron gets the class with its highest average response; neurons that never fired stay -1."""
    n = counts.shape[1]
    rates = np.zeros((n_classes, n))
    for c in range(n_classes):
        m = labels == c
        if m.any():
            rates[c] = counts[m].mean(axis=0)
    assign = np.full(n, -1)
    best = np.zeros(n)
    for c in range(n_classes):
        better = rates[c] > best
        assign[better] = c
        best[better] = rates[c][better]
    return assign


def predict(counts, assign, n_classes=10):
    """Average response of the neurons of each class, then the highest one. Ties are broken as in D&C's
    get_recognized_number_ranking (np.argsort(...)[::-1][0]: the highest class index among equal values)."""
    summed = np.zeros((counts.shape[0], n_classes))
    for c in range(n_classes):
        m = assign == c
        if m.any():
            summed[:, c] = counts[:, m].sum(axis=1) / m.sum()
    return np.argsort(summed, axis=1, kind="stable")[:, ::-1][:, 0]
