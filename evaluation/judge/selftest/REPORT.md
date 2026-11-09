# 语义质量 Judge

- provider：stub；model：glm-4.5-flash
- targets：9；有效评分：9；覆盖率：1.0
- 总分均值：81.5（0-100，仅对已交付路线）
- 双评 kappa 均值：0.8；合并 kappa：0.8
- Judge 调用：18；缓存重放：0；估算 Token：0；缓存命中：0

| 维度 | 均值（0-5） |
|---|---|
| 偏好契合 `preference_fit` | 4.0 |
| 节奏与强度 `pacing` | 4.5 |
| 地理连贯 `geographic_coherence` | 4.0 |
| 时间与开放现实性 `time_realism` | 4.0 |
| 信息完整与可执行 `completeness` | 5.0 |
| 多样性与餐饮 `diversity_and_dining` | 3.0 |

- 低分 target（<60）：[]
- Judge flags：{'other': 18}
- 按 case：{'lijiang-5d-sunny-slowpace': 81.5, 'nanjing-3d-sunny-history': 81.5, 'shanghai-1d-sunny-nightlife': 81.5}
- 校准：{'n': 0, 'mae': None, 'spearman': None, 'band_agreement': None}
- 错误：[]

> stub provider 仅用于管线自测，不得当作质量结果。