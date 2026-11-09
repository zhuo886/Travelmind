# 语义质量 Judge

- provider：llm；model：glm-4.5-flash
- targets：6；有效评分：5；覆盖率：0.8333
- 总分均值：79.2（0-100，仅对已交付路线）
- 双评 kappa 均值：1.0；合并 kappa：1.0
- Judge 调用：10；缓存重放：0；估算 Token：11521；缓存命中：0

| 维度 | 均值（0-5） |
|---|---|
| 偏好契合 `preference_fit` | 4.0 |
| 节奏与强度 `pacing` | 4.6 |
| 地理连贯 `geographic_coherence` | 3.0 |
| 时间与开放现实性 `time_realism` | 5.0 |
| 信息完整与可执行 `completeness` | 3.6 |
| 多样性与餐饮 `diversity_and_dining` | 3.2 |

- 低分 target（<60）：[]
- Judge flags：{'geographic_inefficiency': 1, 'incomplete_practical_info': 1, 'missing_dining': 1, 'missing_transport': 3, 'other': 3, 'preference_mismatch': 1}
- 按 case：{'nanjing-3d-sunny-history': 80.0, 'shanghai-1d-sunny-nightlife': 78.0}
- 校准：{'n': 0, 'mae': None, 'spearman': None, 'band_agreement': None, 'note': '没有人工校准标签；N/A'}
- 错误：[]

> stub provider 仅用于管线自测，不得当作质量结果。