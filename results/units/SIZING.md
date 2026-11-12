# Unit sizing for max |error| <= 1 output LSB (model/sweep_units.py)

## R1 tau=20 steps (dt 1 ms)

| Fo | method | smallest configuration | mean |err| (LSB) |
|---|---|---|---|
| 4 | B1 LUT | 70 non-zero entries x 5 bit | 0.000 |
| 4 | C1 CORDIC | 4 iterations, W=6 | 0.153 |
| 4 | B3 bit product | 7 constants, W=5 | 0.212 |
| 4 | B4 2^x table | 4 x 4 bit table, W=4 | 0.176 |
| 4 | B4 2^x linear | F=3, W=4 | 0.212 |
| 5 | B1 LUT | 84 non-zero entries x 6 bit | 0.000 |
| 5 | C1 CORDIC | 5 iterations, W=6 | 0.172 |
| 5 | B3 bit product | 7 constants, W=6 | 0.141 |
| 5 | B4 2^x table | 8 x 5 bit table, W=5 | 0.192 |
| 5 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 6 | B1 LUT | 98 non-zero entries x 7 bit | 0.000 |
| 6 | C1 CORDIC | 7 iterations, W=8 | 0.125 |
| 6 | B3 bit product | 7 constants, W=6 | 0.473 |
| 6 | B4 2^x table | 16 x 6 bit table, W=6 | 0.134 |
| 6 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 8 | B1 LUT | 125 non-zero entries x 9 bit | 0.000 |
| 8 | C1 CORDIC | 9 iterations, W=9 | 0.100 |
| 8 | B3 bit product | 8 constants, W=8 | 0.379 |
| 8 | B4 2^x table | 64 x 8 bit table, W=8 | 0.143 |
| 8 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 10 | B1 LUT | 153 non-zero entries x 11 bit | 0.000 |
| 10 | C1 CORDIC | 11 iterations, W=13 | 0.083 |
| 10 | B3 bit product | 8 constants, W=11 | 0.119 |
| 10 | B4 2^x table | 256 x 10 bit table, W=10 | 0.077 |
| 10 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 12 | B1 LUT | 181 non-zero entries x 13 bit | 0.000 |
| 12 | C1 CORDIC | 13 iterations, W=14 | 0.082 |
| 12 | B3 bit product | 8 constants, W=13 | 0.051 |
| 12 | B4 2^x table | 1024 x 12 bit table, W=12 | 0.082 |
| 12 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 16 | B1 LUT | 236 non-zero entries x 17 bit | 0.000 |
| 16 | C1 CORDIC | 18 iterations, W=19 | 0.028 |
| 16 | B3 bit product | 8 constants, W=17 | 0.072 |
| 16 | B4 2^x table | 16384 x 16 bit table, W=16 | 0.068 |
| 16 | B4 2^x linear | not reached (F <= Fo+3) |  |

## R1 tau=40 steps (dt 0.5 ms)

| Fo | method | smallest configuration | mean |err| (LSB) |
|---|---|---|---|
| 4 | B1 LUT | 139 non-zero entries x 5 bit | 0.000 |
| 4 | C1 CORDIC | 5 iterations, W=6 | 0.113 |
| 4 | B3 bit product | 8 constants, W=5 | 0.208 |
| 4 | B4 2^x table | 4 x 4 bit table, W=4 | 0.202 |
| 4 | B4 2^x linear | F=3, W=4 | 0.232 |
| 5 | B1 LUT | 167 non-zero entries x 6 bit | 0.000 |
| 5 | C1 CORDIC | 5 iterations, W=6 | 0.173 |
| 5 | B3 bit product | 8 constants, W=6 | 0.112 |
| 5 | B4 2^x table | 8 x 5 bit table, W=5 | 0.189 |
| 5 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 6 | B1 LUT | 195 non-zero entries x 7 bit | 0.000 |
| 6 | C1 CORDIC | 7 iterations, W=8 | 0.103 |
| 6 | B3 bit product | 8 constants, W=7 | 0.072 |
| 6 | B4 2^x table | 16 x 6 bit table, W=6 | 0.121 |
| 6 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 8 | B1 LUT | 250 non-zero entries x 9 bit | 0.000 |
| 8 | C1 CORDIC | 9 iterations, W=9 | 0.108 |
| 8 | B3 bit product | 9 constants, W=8 | 0.444 |
| 8 | B4 2^x table | 64 x 8 bit table, W=8 | 0.147 |
| 8 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 10 | B1 LUT | 305 non-zero entries x 11 bit | 0.000 |
| 10 | C1 CORDIC | 11 iterations, W=13 | 0.087 |
| 10 | B3 bit product | 9 constants, W=11 | 0.153 |
| 10 | B4 2^x table | 256 x 10 bit table, W=10 | 0.087 |
| 10 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 12 | B1 LUT | 361 non-zero entries x 13 bit | 0.000 |
| 12 | C1 CORDIC | 13 iterations, W=14 | 0.067 |
| 12 | B3 bit product | 9 constants, W=13 | 0.072 |
| 12 | B4 2^x table | 1024 x 12 bit table, W=12 | 0.074 |
| 12 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 16 | B1 LUT | 472 non-zero entries x 17 bit | 0.000 |
| 16 | C1 CORDIC | 18 iterations, W=19 | 0.030 |
| 16 | B3 bit product | 9 constants, W=17 | 0.062 |
| 16 | B4 2^x table | 16384 x 16 bit table, W=16 | 0.068 |
| 16 | B4 2^x linear | not reached (F <= Fo+3) |  |

## R2 beta=0.25, 8-bit w (Wu 2021)

| Fo | method | smallest configuration | mean |err| (LSB) |
|---|---|---|---|
| 4 | B1 LUT | 256 non-zero entries x 5 bit | 0.000 |
| 4 | C1 CORDIC | 5 iterations, W=6 | 0.480 |
| 4 | B3 bit product | 8 constants, W=4 | 0.309 |
| 4 | B4 2^x table | 8 x 4 bit table, W=4 | 0.453 |
| 4 | B4 2^x linear | F=3, W=4 | 0.375 |
| 5 | B1 LUT | 256 non-zero entries x 6 bit | 0.000 |
| 5 | C1 CORDIC | 6 iterations, W=8 | 0.379 |
| 5 | B3 bit product | 8 constants, W=5 | 0.254 |
| 5 | B4 2^x table | 16 x 5 bit table, W=5 | 0.258 |
| 5 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 6 | B1 LUT | 256 non-zero entries x 7 bit | 0.000 |
| 6 | C1 CORDIC | 7 iterations, W=9 | 0.434 |
| 6 | B3 bit product | 8 constants, W=7 | 0.246 |
| 6 | B4 2^x table | 32 x 6 bit table, W=6 | 0.324 |
| 6 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 8 | B1 LUT | 256 non-zero entries x 9 bit | 0.000 |
| 8 | C1 CORDIC | 9 iterations, W=12 | 0.453 |
| 8 | B3 bit product | 8 constants, W=9 | 0.191 |
| 8 | B4 2^x table | 128 x 8 bit table, W=8 | 0.297 |
| 8 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 10 | B1 LUT | 256 non-zero entries x 11 bit | 0.000 |
| 10 | C1 CORDIC | 11 iterations, W=13 | 0.438 |
| 10 | B3 bit product | 8 constants, W=11 | 0.316 |
| 10 | B4 2^x table | 512 x 10 bit table, W=10 | 0.301 |
| 10 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 12 | B1 LUT | 256 non-zero entries x 13 bit | 0.000 |
| 12 | C1 CORDIC | 13 iterations, W=15 | 0.371 |
| 12 | B3 bit product | 8 constants, W=13 | 0.410 |
| 12 | B4 2^x table | 2048 x 12 bit table, W=12 | 0.320 |
| 12 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 16 | B1 LUT | 256 non-zero entries x 17 bit | 0.000 |
| 16 | C1 CORDIC | 18 iterations, W=19 | 0.496 |
| 16 | B3 bit product | 8 constants, W=18 | 0.434 |
| 16 | B4 2^x table | 32768 x 16 bit table, W=16 | 0.293 |
| 16 | B4 2^x linear | not reached (F <= Fo+3) |  |

## R2 beta=3, 8-bit w

| Fo | method | smallest configuration | mean |err| (LSB) |
|---|---|---|---|
| 4 | B1 LUT | 256 non-zero entries x 5 bit | 0.000 |
| 4 | C1 CORDIC | 5 iterations, W=6 | 0.156 |
| 4 | B3 bit product | 8 constants, W=4 | 0.191 |
| 4 | B4 2^x table | 8 x 4 bit table, W=4 | 0.176 |
| 4 | B4 2^x linear | F=3, W=4 | 0.316 |
| 5 | B1 LUT | 256 non-zero entries x 6 bit | 0.000 |
| 5 | C1 CORDIC | 6 iterations, W=7 | 0.203 |
| 5 | B3 bit product | 8 constants, W=5 | 0.586 |
| 5 | B4 2^x table | 16 x 5 bit table, W=5 | 0.164 |
| 5 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 6 | B1 LUT | 256 non-zero entries x 7 bit | 0.000 |
| 6 | C1 CORDIC | 7 iterations, W=8 | 0.191 |
| 6 | B3 bit product | 8 constants, W=7 | 0.152 |
| 6 | B4 2^x table | 32 x 6 bit table, W=6 | 0.121 |
| 6 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 8 | B1 LUT | 256 non-zero entries x 9 bit | 0.000 |
| 8 | C1 CORDIC | 9 iterations, W=11 | 0.152 |
| 8 | B3 bit product | 8 constants, W=9 | 0.199 |
| 8 | B4 2^x table | 128 x 8 bit table, W=8 | 0.164 |
| 8 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 10 | B1 LUT | 256 non-zero entries x 11 bit | 0.000 |
| 10 | C1 CORDIC | 11 iterations, W=13 | 0.199 |
| 10 | B3 bit product | 8 constants, W=11 | 0.133 |
| 10 | B4 2^x table | 256 x 10 bit table, W=10 | 0.270 |
| 10 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 12 | B1 LUT | 256 non-zero entries x 13 bit | 0.000 |
| 12 | C1 CORDIC | 13 iterations, W=15 | 0.156 |
| 12 | B3 bit product | 8 constants, W=13 | 0.137 |
| 12 | B4 2^x table | 2048 x 12 bit table, W=12 | 0.148 |
| 12 | B4 2^x linear | not reached (F <= Fo+3) |  |
| 16 | B1 LUT | 256 non-zero entries x 17 bit | 0.000 |
| 16 | C1 CORDIC | 18 iterations, W=18 | 0.191 |
| 16 | B3 bit product | 8 constants, W=17 | 0.176 |
| 16 | B4 2^x table | 16384 x 16 bit table, W=16 | 0.066 |
| 16 | B4 2^x linear | not reached (F <= Fo+3) |  |

## R1 B2 tau_eff=15.49 steps (k=4)

| Fo | method | smallest configuration | mean |err| (LSB) |
|---|---|---|---|
| 4 | B2 shift decay (floor) | register W=8 | 0.439 |
| 4 | B2 shift decay (round) | register W=7 | 0.227 |
| 5 | B2 shift decay (floor) | register W=9 | 0.416 |
| 5 | B2 shift decay (round) | register W=8 | 0.182 |
| 6 | B2 shift decay (floor) | register W=10 | 0.414 |
| 6 | B2 shift decay (round) | register W=9 | 0.172 |
| 8 | B2 shift decay (floor) | register W=12 | 0.486 |
| 8 | B2 shift decay (round) | register W=11 | 0.165 |
| 10 | B2 shift decay (floor) | register W=14 | 0.446 |
| 10 | B2 shift decay (round) | register W=13 | 0.131 |
| 12 | B2 shift decay (floor) | register W=16 | 0.526 |
| 12 | B2 shift decay (round) | register W=15 | 0.184 |
| 16 | B2 shift decay (floor) | register W=20 | 0.400 |
| 16 | B2 shift decay (round) | register W=19 | 0.113 |

## R1 B2 tau_eff=31.50 steps (k=5)

| Fo | method | smallest configuration | mean |err| (LSB) |
|---|---|---|---|
| 4 | B2 shift decay (floor) | register W=9 | 0.447 |
| 4 | B2 shift decay (round) | register W=8 | 0.197 |
| 5 | B2 shift decay (floor) | register W=10 | 0.435 |
| 5 | B2 shift decay (round) | register W=9 | 0.188 |
| 6 | B2 shift decay (floor) | register W=11 | 0.426 |
| 6 | B2 shift decay (round) | register W=10 | 0.148 |
| 8 | B2 shift decay (floor) | register W=13 | 0.464 |
| 8 | B2 shift decay (round) | register W=12 | 0.159 |
| 10 | B2 shift decay (floor) | register W=15 | 0.471 |
| 10 | B2 shift decay (round) | register W=14 | 0.125 |
| 12 | B2 shift decay (floor) | register W=17 | 0.423 |
| 12 | B2 shift decay (round) | register W=16 | 0.107 |
| 16 | B2 shift decay (floor) | register W=21 | 0.477 |
| 16 | B2 shift decay (round) | register W=20 | 0.104 |

