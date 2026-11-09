# E2 Checkpoint 增量修改配对实验

> 27 组配对（同 fixture、同修改指令）；A=全量重规划，B=复用应用层 checkpoint。
> 执行模式：`planner_only`；不含 route_distance_check、餐食与贴士。

## 汇总

| 指标 | A 全量重规划 | B Checkpoint | 变化 |
|---|---|---|---|
| 重规划 P50 (ms) | 69119.0 | 61048.0 | 11.7% |
| 输入 Token 合计 | 62904 | 67052 | -6.6% |
| 修改指令满足率 | 100.0% | 100.0% | - |
| 未修改内容保留率 | 73.5% | 90.6% | - |
| 修改后硬约束通过率 | 81.5% | 92.6% | - |

## 逐组结果

| # | case | 类型 | A 秒 | B 秒 | A Token | B Token | 满足 A/B | 保留 A/B | 硬通过 A/B |
|---|---|---|---|---|---|---|---|---|---|
| 1 | lijiang-5d-sunny-slowpace | replace_indoor | 119.915 | 68.283 | 2399 | 2896 | True/True | 0.8889/1.0 | True/True |
| 2 | lijiang-5d-sunny-slowpace | add_must_visit | 90.651 | 59.655 | 2384 | 2881 | True/True | 0.7/0.9 | False/True |
| 3 | lijiang-5d-sunny-slowpace | remove_spot | 101.057 | 201.935 | 2385 | 2882 | True/True | 0.8889/1.0 | True/True |
| 4 | lijiang-5d-sunny-slowpace | change_time | 64.019 | 35.398 | 2388 | 2885 | True/True | 0.8/1.0 | True/True |
| 5 | lijiang-5d-sunny-slowpace | cross_day | 39.563 | 69.396 | 2389 | 2886 | True/True | 0.8889/0.8889 | True/True |
| 6 | lijiang-5d-sunny-slowpace | slow_pace | 116.844 | 75.077 | 2387 | 2884 | True/True | 0.9/1.0 | True/True |
| 7 | nanjing-3d-sunny-history | change_time | 74.427 | 64.635 | 2108 | 2402 | True/True | 0.8333/1.0 | True/True |
| 8 | nanjing-3d-sunny-history | cross_day | 60.401 | 52.037 | 2118 | 2412 | True/True | 0.8/0.8 | True/True |
| 9 | nanjing-3d-sunny-history | slow_pace | 42.62 | 32.123 | 2107 | 2401 | True/True | 0.6667/1.0 | True/True |
| 10 | nanjing-3d-sunny-history | replace_indoor | 51.493 | 164.751 | 2124 | 2418 | True/True | 0.6/1.0 | True/True |
| 11 | nanjing-3d-sunny-history | add_must_visit | 96.436 | 67.181 | 2114 | 2408 | True/True | 0.6667/0.8333 | True/True |
| 12 | nanjing-3d-sunny-history | remove_spot | 56.322 | 63.789 | 2100 | 2394 | True/True | 0.6/1.0 | True/True |
| 13 | nanjing-3d-tighthours-negative | add_must_visit | 182.561 | 46.985 | 1329 | 1623 | True/True | 1.0/0.8333 | True/True |
| 14 | nanjing-3d-tighthours-negative | remove_spot | 61.535 | 61.048 | 1324 | 1618 | True/True | 1.0/1.0 | True/True |
| 15 | nanjing-3d-tighthours-negative | change_time | 58.052 | 46.38 | 1330 | 1624 | True/True | 0.8333/1.0 | True/True |
| 16 | nanjing-3d-tighthours-negative | cross_day | 59.936 | 54.393 | 1344 | 1638 | True/True | 1.0/1.0 | True/True |
| 17 | nanjing-3d-tighthours-negative | slow_pace | 55.033 | 94.132 | 1329 | 1623 | True/True | 0.8333/1.0 | True/True |
| 18 | sanya-3d-allrain-outdoor-negative | change_time | 94.471 | 94.088 | 2561 | 2989 | True/True | 0.4444/1.0 | True/True |
| 19 | sanya-3d-allrain-outdoor-negative | cross_day | 72.671 | 156.491 | 2565 | 2993 | True/True | 0.5/0.875 | True/True |
| 20 | sanya-3d-allrain-outdoor-negative | slow_pace | 89.915 | 136.203 | 2560 | 2988 | True/True | 0.3333/0.6667 | True/True |
| 21 | sanya-3d-allrain-outdoor-negative | add_must_visit | 69.613 | 56.118 | 2561 | 2989 | True/True | 0.6667/0.6667 | True/True |
| 22 | sanya-3d-allrain-outdoor-negative | remove_spot | 69.119 | 70.687 | 2563 | 2991 | True/True | 0.5/1.0 | True/True |
| 23 | shanghai-1d-sunny-nightlife | add_must_visit | 45.462 | 34.657 | 2347 | 2444 | True/True | 0.5/0.5 | True/True |
| 24 | shanghai-1d-sunny-nightlife | remove_spot | 108.143 | 31.443 | 4688 | 2441 | True/True | 1.0/1.0 | False/False |
| 25 | shanghai-1d-sunny-nightlife | change_time | 51.67 | 33.166 | 2348 | 2445 | True/True | 0.5/0.5 | False/True |
| 26 | shanghai-1d-sunny-nightlife | slow_pace | 110.123 | 35.651 | 4694 | 2444 | True/True | 0.5/1.0 | False/True |
| 27 | shanghai-1d-sunny-nightlife | replace_indoor | 35.119 | 27.366 | 2358 | 2453 | True/True | 1.0/1.0 | False/False |
