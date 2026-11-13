| configuration | seeds | test acc. % (labels: 60k frozen pass) | labels: first 10k of that pass | labels: last 10k of training | exc. spikes / test example | rate raises / test example | minutes per run |
|---|---|---|---|---|---|---|---|
| E_beta0.25 | 3 | 83.28 ± 1.33 | 83.17 ± 0.85 | 83.21 ± 0.94 | 10.2 | 0.70 | 3.2 |
| E_beta3 | 3 | 78.92 ± 0.62 | 79.08 ± 0.63 | 78.79 ± 0.66 | 10.3 | 0.84 | 3.3 |
| PP_prepost | 3 | 81.02 ± 1.02 | 80.88 ± 0.92 | 80.92 ± 0.95 | 10.4 | 0.72 | 8.3 |
| P_dt1_reset_nodelay | 3 | 14.11 ± 0.13 | 14.11 ± 0.13 | 13.31 ± 0.71 | 79.2 | 26.79 | 41.6 |
| P_dt1_reset | 3 | 9.80 ± 0.00 | 9.80 ± 0.00 | 9.80 ± 0.00 | 77.4 | 4.71 | 17.0 |
| P_faithful | 3 | 78.02 ± 0.60 | 77.68 ± 0.26 | 77.79 ± 0.39 | 10.8 | 0.78 | 3.1 |
| T_code | 3 | 66.92 ± 3.16 | 67.34 ± 2.86 | 66.38 ± 2.80 | 7.4 | 1.29 | 10.0 |
