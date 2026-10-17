Python engine: 40 seeds. Scale Lab: 200 replicates. 95% CIs. SIMULATED.

| Metric | Python engine | Scale Lab | Scale Lab - Python | |
|---|---|---|---|---|
| share_refused_offline | 0.548 [0.491, 0.604] | 0.529 [0.504, 0.554] | -0.019 [-0.080, 0.042] | agree |
| share_caught_at_settlement | 0.452 [0.396, 0.509] | 0.471 [0.446, 0.496] | 0.018 [-0.043, 0.079] | agree |
| mean_loss_per_cheater_cents | 553 [426, 680] | 541 [485, 596] | -12 [-150, 126] | agree |
| median_hours_to_settlement | 2.26 [2.16, 2.35] | 2.23 [2.18, 2.27] | -0.03 [-0.14, 0.07] | agree |
| mean_hops_to_server | 2.45 [2.38, 2.52] | 2.41 [2.38, 2.44] | -0.04 [-0.12, 0.03] | agree |
| double_spend_attempts | 7.80 [7.40, 8.20] | 7.90 [7.75, 8.05] | 0.10 [-0.32, 0.52] | agree |
| payments | 825 [812, 838] | 821 [816, 826] | -4 [-18, 10] | agree |
| refused_payments | 15.6 [14.3, 16.9] | 16.0 [15.5, 16.6] | 0.4 [-1.0, 1.8] | agree |
| out_of_money | 1,898 [1,874, 1,923] | 1,887 [1,875, 1,900] | -11 [-38, 16] | agree |
| contacts | 6,452 [6,221, 6,682] | 6,394 [6,275, 6,513] | -58 [-316, 200] | agree |

Pooled: Python 312 attempts, refused 0.548, caught 0.452; Scale Lab 1580 attempts, refused 0.528, caught 0.471

Hops to the server (share of PAYs that reached it):
| Hops | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9+ |
|---|---|---|---|---|---|---|---|---|---|---|
| Python engine | 0.098 | 0.254 | 0.215 | 0.191 | 0.117 | 0.068 | 0.030 | 0.016 | 0.007 | 0.004 |
| Scale Lab | 0.101 | 0.258 | 0.219 | 0.190 | 0.114 | 0.063 | 0.031 | 0.014 | 0.006 | 0.004 |

wrote cpp/scale/results/validation/comparison.json
