# 端到端真实链路评测（生产 run_stream）

- 案例：4；成功交付：2；异常：0

| 案例 | 成功 | 状态 | 天数 | 景点数 | 缺失字段 | 端到端 | LLM 调用 | 输入Token |
|---|---|---|---:|---:|---|---:|---:|---:|
| chengdu-weekend-tea | ✅ | PARTIAL_SUCCESS | 2 | 6 | - | 241.7s | 9 | 30312 |
| hangzhou-1d-date-hint | ✅ | PARTIAL_SUCCESS | 1 | 3 | - | 208.0s | 13 | 41195 |
| nanjing-3d-history | ❌ | FAILED | 0 | 0 | 出行开始日期,出行结束日期 | 8.6s | 1 | 265 |
| vague-request-clarify | ❌ | FAILED | 0 | 0 | 目的地,出行开始日期,出行结束日期 | 5.4s | 1 | 259 |

## 节点耗时（毫秒）

| 案例 | 节点耗时 |
|---|---|
| chengdu-weekend-tea | attraction_search 592、candidate_react 11406、candidate_ready 1、candidate_search 516、candidate_validator 6、finalize_direct 2503、intent 5968、main_meal_search 428、planner 59631、query_rewrite 6394、reviewer 41923、risk_gate 12、route_distance_check 556、snapshot_gate 15、snapshot_reviewer 11、weather_search 275 |
| hangzhou-1d-date-hint | attraction_search 628、candidate_react 2639、candidate_ready 2、candidate_search 378、candidate_validator 6、finalize_direct 2101、intent 4553、main_meal_search 451、planner 29979、query_rewrite 4224、reviewer 73850、risk_gate 7、route_distance_check 543、snapshot_gate 6、snapshot_reviewer 5、weather_search 260 |
| nanjing-3d-history | clarify 1、intent 7758 |
| vague-request-clarify | clarify 0、intent 4764 |

## 路线概览

### chengdu-weekend-tea

- 输入：`成都周末两天，想泡茶馆吃火锅，明天中午开始`
- 关注点：相对日期解析 + 餐饮/偏好
- 节点序列：attraction_search → candidate_react → candidate_ready → candidate_search → candidate_validator → finalize_direct → intent → main_meal_search → planner → query_rewrite → reviewer → risk_gate → route_distance_check → snapshot_gate → snapshot_reviewer → weather_search
- 景点：空山茶事·三国馆、成都武侯祠博物馆、交子金融博物馆、四川大学博物馆、成都杜甫草堂博物馆、水井坊博物馆

### hangzhou-1d-date-hint

- 输入：`杭州一日，西湖边慢慢走，11.18开始`
- 关注点：显式月日解析 + 单日节奏
- 节点序列：attraction_search → candidate_react → candidate_ready → candidate_search → candidate_validator → finalize_direct → intent → main_meal_search → planner → query_rewrite → reviewer → risk_gate → route_distance_check → snapshot_gate → snapshot_reviewer → weather_search
- 景点：杭州西湖风景名胜区、灵隐寺、中国丝绸博物馆

### nanjing-3d-history

- 输入：`南京三天，想看历史建筑和博物馆，节奏慢一点，别太赶`
- 关注点：多日 + 偏好约束 + 必去未点名
- 节点序列：clarify → intent
- 景点：（无）

### vague-request-clarify

- 输入：`我想出去玩几天，你看着安排`
- 关注点：信息不足时应追问（clarify），不得凭空编造目的地
- 节点序列：clarify → intent
- 景点：（无）
