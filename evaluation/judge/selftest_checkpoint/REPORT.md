# 语义质量 Judge

- provider：stub；model：default
- targets：54；有效评分：54；覆盖率：1.0
- 总分均值：79.78（0-100，仅对已交付路线）
- 双评 kappa 均值：None
- Judge 调用：52；估算 Token：0；缓存命中：2

| 维度 | 均值（0-5） |
|---|---|
| 偏好契合 `preference_fit` | 4.0 |
| 节奏与强度 `pacing` | 4.0 |
| 地理连贯 `geographic_coherence` | 3.926 |
| 时间与开放现实性 `time_realism` | 4.0 |
| 信息完整与可执行 `completeness` | 5.0 |
| 多样性与餐饮 `diversity_and_dining` | 3.0 |

- 低分维度 target：[{'target_id': 'pair_03_lijiang-5d-sunny-slowpace_remove_spot_B', 'overall': 74.0}, {'target_id': 'pair_05_lijiang-5d-sunny-slowpace_cross_day_B', 'overall': 74.0}]
- 按 case：{'lijiang-5d-sunny-slowpace': 79.0, 'nanjing-3d-sunny-history': 80.0, 'nanjing-3d-tighthours-negative': 80.0, 'sanya-3d-allrain-outdoor-negative': 80.0, 'shanghai-1d-sunny-nightlife': 80.0}
- 校准：{'n': 0, 'mae': None, 'spearman': None, 'band_agreement': None, 'note': '没有人工校准标签；N/A'}
- 错误：[]

> stub provider 仅用于管线自测，不得当作质量结果。