# 四臂策略回放（生产 risk gate）

> 口径：**回放**。A/B/C 取自已冻结 trial 的真实结果，D 臂把 A 的首版路线喂给真实 `route_risk_gate_node` 再决定沿用 A 还是 C。
> 覆盖：5 个 case（每个 case 需同时存在 A/B/C 记录）

## 1. 四臂指标

| 臂 | trial | ESR | OMR | HPR | PDR | Token 合计 | P50 耗时 |
|---|---:|---|---|---|---|---:|---:|
| A_planner_only | 5 | 40.0%（2/5） | 40.0%（2/5） | 80.0%（4/5） | 40.0%（2/5） | 16629 | 99.647s |
| B_reviewer | 5 | 60.0%（3/5） | 60.0%（3/5） | 100.0%（5/5） | 0.0%（0/5） | 62283 | 249.565s |
| C_reviewer_time_check | 5 | 60.0%（3/5） | 60.0%（3/5） | 100.0%（5/5） | 0.0%（0/5） | 50235 | 236.281s |
| D_risk_gate | 5 | 60.0%（3/5） | 60.0%（3/5） | 100.0%（5/5） | 0.0%（0/5） | 50235 | 236.281s |

## 2. 草稿级门控分流

- 草稿总数：30（checkpoint 15，trial 15）
- 被跳过审核：**0 / 30（0.0%（0/30））**
- 缺陷已知的草稿：15（checkpoint 草稿无 `l0_codes`）
- 误跳过：0（N/A；checkpoint 草稿无 l0_codes，误跳过只能在 defect_known 子集上计算）
- 跳过意味着沿用 A 臂结果，因此 D 臂收益上限完全取决于门控判断是否正确。

## 3. 增益归因：规则驱动 vs 语义驱动

| 项 | 次数 |
|---|---:|
| 返工 trial（rounds>0） | 5 |
| 其中：首版有 L0、返工后修好（规则驱动） | **2** |
| 其中：首版有 L0、返工后仍在（规则无效） | 0 |
| 其中：首版无 L0、仍发生返工（语义驱动） | 3 |

## 4. 逐 case

| case | 门控 | 跳过 | A | B | C | D(=?) |
|---|---|---|---|---|---|---|
| lijiang-5d-sunny-slowpace | review | False | PARTIAL | SUCCESS_WITH_WARNINGS | SUCCESS | SUCCESS（C） |
| nanjing-3d-sunny-history | review | False | SUCCESS_WITH_WARNINGS | SUCCESS_WITH_WARNINGS | SUCCESS_WITH_WARNINGS | SUCCESS_WITH_WARNINGS（C） |
| nanjing-3d-tighthours-negative | review | False | SUCCESS_WITH_WARNINGS | SUCCESS | SUCCESS | SUCCESS（C） |
| sanya-3d-allrain-outdoor-negative | review | False | PARTIAL | SUCCESS_WITH_WARNINGS | SUCCESS_WITH_WARNINGS | SUCCESS_WITH_WARNINGS（C） |
| shanghai-1d-sunny-nightlife | review | False | HARD_FAIL | SUCCESS_WITH_WARNINGS | SUCCESS_WITH_WARNINGS | SUCCESS_WITH_WARNINGS（C） |

## 5. 读法

- D 臂不是新一轮实测：审核节点看到的状态来自回放，可能比真实运行更干净或更脏。
- 若 D 与 C 完全相同，说明本批草稿全部需要审核，门控没有产生分流。
- 归因结果若显示返工主要由 L0/L1 触发，则不能把增益归给“语义审核能力”。