# 语义质量 Judge

- provider：llm；model：glm-4.5-flash
- targets：15；有效评分：15；覆盖率：1.0
- 总分均值：78.73（0-100，仅对已交付路线）
- 双评 kappa 均值：0.5088；合并 kappa：0.5975
- Judge 调用：0；缓存重放：30；估算 Token：37126；缓存命中：30

| 维度 | 均值（0-5） |
|---|---|
| 偏好契合 `preference_fit` | 3.867 |
| 节奏与强度 `pacing` | 3.933 |
| 地理连贯 `geographic_coherence` | 3.667 |
| 时间与开放现实性 `time_realism` | 4.267 |
| 信息完整与可执行 `completeness` | 4.167 |
| 多样性与餐饮 `diversity_and_dining` | 3.633 |

- 低分 target（<60）：[{'target_id': '05b475300de9495bbd600a5e6efcb679', 'overall': 53.0}]
- Judge flags：{'bad_weather_all_days': 7, 'evidence_missing': 1, 'geographic_inefficiency': 9, 'limited_diversity': 1, 'missing_transport': 2, 'other': 13, 'preference_mismatch': 10}
- 按 case：{'lijiang-5d-sunny-slowpace': 81.67, 'nanjing-3d-sunny-history': 84.5, 'nanjing-3d-tighthours-negative': 80.0, 'sanya-3d-allrain-outdoor-negative': 68.5, 'shanghai-1d-sunny-nightlife': 79.0}
- 校准：{'n': 0, 'mae': None, 'spearman': None, 'band_agreement': None}
- 错误：[]

> stub provider 仅用于管线自测，不得当作质量结果。