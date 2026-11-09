"""候选补查离线消融：有界 ReAct 到底补上了哪些缺口。

28 个受控场景，每个场景 = 冻结查询 + 冻结种子候选池 + 桩化检索结果。
两臂：

- ``seed_only``：只用给定种子池，跑一次覆盖度检查；
- ``bounded_react``：跑真实的 ``make_candidate_react_node`` 决策队列
  （确定性点名队列 / 服务端基线动作）+ 真实的 ``candidate_search_node``
  执行器（预算、去重、候选池过滤全部生效），只有检索结果被桩替换。

因此本实验测的是**决策与预算逻辑能否把缺口补上**，不是高德召回率。
桩化检索让 28 个场景可逐条复核，也保证 0 网络。

``boundary`` 类场景代表"池里根本不存在"的请求（点名的景点不存在、池里没有任何
室内场馆）。这类场景的正确行为是**补不上**，且不能凭空造景点；把它们混进修复率
会虚高成功率，所以单独统计。

用法::

    python -m tests.eval.gap_fill_ablation --out evaluation/benchmarks/gap_fill
    python -m tests.eval.gap_fill_ablation --freeze  # 首次生成冻结场景文件
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

from app.planning.candidate_react import (
    active_gaps,
    baseline_actions,
    candidate_search_node,
    deterministic_named_actions,
)
from app.planning.schemas import TravelPlanState

DEFAULT_OUT = Path("evaluation/benchmarks/gap_fill")
SCENARIO_FILE = Path(__file__).resolve().parent / "scenarios_v4" / "gap_fill.json"
CITIES = ("南京", "上海", "丽江", "三亚")
VARIANTS = 7


# ─── 场景构造 ──────────────────────────────────────────────

def _spot(name: str, indoor: bool, index: int) -> dict[str, Any]:
    return {
        "name": name,
        "indoor": indoor,
        "rating": 4.7,
        "adname": "玄武区",
        "category": "博物馆" if indoor else "风景名胜",
        "location": {"lng": round(118.7 + index * 0.01, 4), "lat": round(32.0 + index * 0.01, 4)},
    }


def _row(name: str, indoor: bool, index: int) -> dict[str, Any]:
    return {
        "name": name,
        "location": f"{round(118.7 + index * 0.01, 4)},{round(32.0 + index * 0.01, 4)}",
        "type": "科教文化服务;博物馆" if indoor else "风景名胜;公园",
        "typecode": "140100" if indoor else "110000",
        "adname": "玄武区",
        "biz_ext": {"rating": "4.7"},
    }


def _scenarios() -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    for kind in ("named", "indoor", "count", "boundary"):
        for variant in range(VARIANTS):
            city = CITIES[variant % len(CITIES)]
            days = 1 + variant % 2
            seed: list[dict[str, Any]] = []
            index: dict[str, list[dict[str, Any]]] = {}
            if kind == "named":
                wanted = f"{city}博物院" if variant % 2 == 0 else f"{city}美术馆"
                query = f"{city}1天游，一定要去“{wanted}”。"
                seed = [_spot(f"{city}种子景点{i}", indoor=(i % 2 == 1), index=i)
                        for i in range(variant % 4)]
                index[wanted] = [_row(wanted, indoor=True, index=90 + variant)]
                expected_fixable = True
            elif kind == "indoor":
                # 必须用产品识别的固定短语，否则 indoor_shortage 不会触发。
                query = f"{city}1天游，只去室内景点。"
                seed = [_spot(f"{city}室外种子{i}", indoor=False, index=i) for i in range(2)]
                index["博物馆"] = [
                    _row(f"{city}补充博物馆{i}", indoor=True, index=70 + variant * 6 + i)
                    for i in range(6)
                ]
                expected_fixable = True
            elif kind == "count":
                query = f"{city}{days}天游，想多看几个不同类型的景点。"
                # 种子里室内/室外都有，避免修好数量后反而引入 diversity 缺口。
                seed = [_spot(f"{city}种子景点{i}", indoor=(i % 2 == 1), index=i)
                        for i in range(2)]
                index["博物馆"] = [
                    _row(f"{city}补充博物馆{i}", indoor=True, index=50 + variant * 6 + i)
                    for i in range(6)
                ]
                expected_fixable = True
            else:  # boundary：池里和检索源里都没有
                seed = [_spot(f"{city}种子景点{i}", indoor=(i % 2 == 1), index=i)
                        for i in range(variant % 4)]
                if variant % 2 == 0:
                    wanted = f"{city}不存在的测试景点"
                    query = f"{city}1天游，一定要去“{wanted}”。"
                    index[wanted] = []
                else:
                    query = f"{city}1天游，只去室内景点。"
                    for word in ("博物馆", "美术馆"):
                        index[word] = []
                expected_fixable = False
            scenarios.append({
                "id": f"{kind}-{variant:02d}",
                "kind": kind,
                "city": city,
                "query": query,
                "days": days,
                "seed": seed,
                "index": index,
                "expected_fixable": expected_fixable,
            })
    return scenarios


def freeze(path: Path = SCENARIO_FILE) -> list[dict[str, Any]]:
    data = _scenarios()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": "gap-fill-v1", "scenarios": data},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def load_scenarios(path: Path = SCENARIO_FILE) -> list[dict[str, Any]]:
    if not path.exists():
        return freeze(path)
    return json.loads(path.read_text(encoding="utf-8"))["scenarios"]


# ─── 执行 ──────────────────────────────────────────────────

def build_state(spec: dict[str, Any]) -> TravelPlanState:
    return TravelPlanState(
        query=spec["query"],
        destination=spec["city"],
        days=int(spec["days"]),
        max_per_day=3,
        min_rating=4.5,
        pois=list(spec["seed"]),
    )


def gap_units(state: TravelPlanState) -> set[str]:
    gaps = active_gaps(state)
    units = {f"named:{name}" for name in gaps["missing_named_pois"]}
    if gaps["indoor_shortage"]:
        units.add("indoor")
    if gaps["count_shortage"]:
        units.add("count")
    units.update(f"other:{item}" for item in gaps["other_gaps"])
    return units


def _stub_search(spec: dict[str, Any]):
    def fake(destination: str, api_key: str, *, keywords: str = "", types: str = "",
             offset: int = 25, request_budget: dict[str, int] | None = None):
        if request_budget is not None:
            request_budget["used"] = request_budget.get("used", 0) + 1
        rows = spec["index"].get(keywords)
        if rows is not None:
            return [dict(row) for row in rows]
        # 非点名类查询：返回该场景所有可检索结果，模拟"检索到但可能不匹配"。
        return [dict(row) for items in spec["index"].values() for row in items]

    return fake


def run_arm(spec: dict[str, Any], arm: str) -> dict[str, Any]:
    state = build_state(spec)
    before = gap_units(state)
    trace: list[dict[str, Any]] = []
    if arm == "bounded_react":
        with patch("app.planning.candidate_react.search_city_pois", _stub_search(spec)), \
                patch("app.planning.candidate_react.amap_key", lambda: "offline"), \
                patch("app.planning.candidate_react.get_cached", lambda _key: None), \
                patch("app.planning.candidate_react.set_cached", lambda *a, **k: None):
            for _round in range(state.candidate_max_rounds):
                actions = deterministic_named_actions(state) or baseline_actions(state)
                if not actions:
                    break
                update = candidate_search_node(
                    state.model_copy(update={"candidate_search_actions": actions})
                )
                trace.extend(update.get("candidate_search_trace") or [])
                state = state.model_copy(update=update)
    after = gap_units(state)
    return {
        "scenario_id": spec["id"],
        "kind": spec["kind"],
        "arm": arm,
        "expected_fixable": spec["expected_fixable"],
        "gaps_before": sorted(before),
        "gaps_after": sorted(after),
        "fixed": sorted(before - after),
        "introduced": sorted(after - before),
        "pool_after": len(state.pois),
        "api_calls": int(state.candidate_api_calls or 0),
        "rounds": int(state.candidate_search_round or 0),
        "repeated_query_rejections": sum(
            1 for item in trace if item.get("error_code") == "REPEATED_QUERY"
        ),
        "pool_names": [str(poi.get("name")) for poi in state.pois],
    }


def build_summary(scenarios: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    scenarios = scenarios or load_scenarios()
    rows: list[dict[str, Any]] = []
    for spec in scenarios:
        for arm in ("seed_only", "bounded_react"):
            rows.append(run_arm(spec, arm))

    def _bucket(arm: str, fixable: bool) -> dict[str, Any]:
        subset = [
            row for row in rows
            if row["arm"] == arm and row["expected_fixable"] is fixable
        ]
        return {
            "scenarios": len(subset),
            "gaps": sum(len(row["gaps_before"]) for row in subset),
            "fixed": sum(len(row["fixed"]) for row in subset),
            "introduced": sum(len(row["introduced"]) for row in subset),
        }

    react_fixable = _bucket("bounded_react", True)
    seed_fixable = _bucket("seed_only", True)
    react_boundary = _bucket("bounded_react", False)
    invented = [
        row for row in rows
        if row["arm"] == "bounded_react" and not row["expected_fixable"] and row["fixed"]
    ]
    residual: dict[str, int] = {}
    for row in rows:
        if row["arm"] != "bounded_react" or not row["expected_fixable"]:
            continue
        for gap in row["gaps_after"]:
            key = gap.split(":", 1)[0]
            residual[key] = residual.get(key, 0) + 1
    return {
        "benchmark": "gap_fill_ablation",
        "kind": "offline_controlled_scenarios",
        "scenarios": len(scenarios),
        "rows": rows,
        "seed_only_fixable": seed_fixable,
        "bounded_react_fixable": react_fixable,
        "bounded_react_boundary": react_boundary,
        "boundary_false_fix": len(invented),
        "closure_rate": round(
            react_fixable["fixed"] / react_fixable["gaps"], 4
        ) if react_fixable["gaps"] else None,
        "seed_closure_rate": round(
            seed_fixable["fixed"] / seed_fixable["gaps"], 4
        ) if seed_fixable["gaps"] else None,
        "budget_max_calls": max((row["api_calls"] for row in rows), default=0),
        "residual_by_kind": dict(sorted(residual.items())),
        "note": "桩化检索：只测决策/预算/去重逻辑，不代表高德召回率",
    }


def render_markdown(summary: dict[str, Any]) -> str:
    react = summary["bounded_react_fixable"]
    seed = summary["seed_only_fixable"]
    boundary = summary["bounded_react_boundary"]
    lines = [
        "# 候选补查离线消融（28 个受控场景）",
        "",
        "> 口径：冻结场景 + 桩化检索，跑真实的决策队列与 `candidate_search_node`",
        "> 测的是**缺口补齐逻辑**（预算 / 去重 / 过滤），不是高德召回率",
        "",
        "## 1. 结论",
        "",
        f"- 非边界缺口：{react['gaps']} 个，有界 ReAct 补上 **{react['fixed']} 个"
        f"（{react['fixed']}/{react['gaps']}）**",
        f"- 仅种子池（无补查）：{seed['fixed']}/{seed['gaps']} 个，说明缺口确实来自补查",
        f"- 边界场景：{boundary['scenarios']} 个，错误补上 **{summary['boundary_false_fix']}** 个"
        "（应为 0，验证不会凭空造景点）",
        f"- 单场景最大检索次数：{summary['budget_max_calls']}（上限 10）",
        f"- 未补齐缺口按类型：{summary.get('residual_by_kind') or '无'}",
        "",
        "## 2. 分场景",
        "",
        "| 场景 | 类型 | 前 | 后 | 修复 | 新增缺口 | 池大小 | 调用 |",
        "|---|---|---|---|---:|---:|---:|---:|",
    ]
    for row in summary["rows"]:
        if row["arm"] != "bounded_react":
            continue
        lines.append(
            f"| {row['scenario_id']} | {row['kind']} | {len(row['gaps_before'])} | "
            f"{len(row['gaps_after'])} | {len(row['fixed'])} | {len(row['introduced'])} | "
            f"{row['pool_after']} | {row['api_calls']} |"
        )
    lines += [
        "",
        "## 3. 读法",
        "",
        "- 只能说“受控场景下修复 X/Y 个非边界缺口”，不能换算成最终路线成功率。",
        "- 边界场景的 0 修复是正确结果；若出现非 0，说明存在凭空补点，属缺陷。",
        "- 桩化检索把召回率固定住，因此结果不能外推到真实高德。",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="候选补查离线消融")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--freeze", action="store_true", help="重新生成冻结场景文件")
    args = parser.parse_args(argv)

    if args.freeze:
        freeze()
    summary = build_summary()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "REPORT.md").write_text(render_markdown(summary), encoding="utf-8")
    react = summary["bounded_react_fixable"]
    print(f"scenarios={summary['scenarios']} fixed={react['fixed']}/{react['gaps']} "
          f"boundary_false_fix={summary['boundary_false_fix']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
