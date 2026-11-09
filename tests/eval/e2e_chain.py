"""端到端真实链路评测：走生产 `run_stream`（真实高德检索 + 真实 LLM），不注入 fixture。

与 `run_trials` 的区别：
- `run_trials` 冻结候选池，只衡量 planner/reviewer/time_check（跳过 intent、候选补查、路距）；
- 本脚本衡量完整链路：intent 抽取 → 查询改写 → 天气/餐饮/景点检索 → 候选池 → planner
  → 路距 → risk gate → reviewer → time_check → finalize。

真实调用必须显式放行：

    python -m tests.eval.e2e_chain --allow-external-calls
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.env import load_local_env
from app.core.llm_usage import snapshot as usage_snapshot, usage_delta

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "evaluation" / "benchmarks" / "e2e"

# 冻结输入：改了就不再是同一份评测。覆盖「显式日期 / 相对日期 / 天气压力」三类。
FROZEN_QUERIES: list[dict[str, str]] = [
    {
        "id": "hangzhou-1d-date-hint",
        "query": "杭州一日，西湖边慢慢走，11.18开始",
        "focus": "显式月日解析 + 单日节奏",
    },
    {
        "id": "nanjing-3d-history",
        "query": "南京三天，想看历史建筑和博物馆，节奏慢一点，别太赶",
        "focus": "多日 + 偏好约束 + 必去未点名",
    },
    {
        "id": "chengdu-weekend-tea",
        "query": "成都周末两天，想泡茶馆吃火锅，明天中午开始",
        "focus": "相对日期解析 + 餐饮/偏好",
    },
    {
        "id": "vague-request-clarify",
        "query": "我想出去玩几天，你看着安排",
        "focus": "信息不足时应追问（clarify），不得凭空编造目的地",
    },
]


def _spot_names(route: Any) -> list[str]:
    """从两种路线结构里取景点名。

    - fixture / snapshot 结构：``day["spots"]``；
    - 生产 final_plan 结构：``day["timeline"]``，用 ``type == "attraction"`` 区分景点。
    """
    names: list[str] = []
    for day in route or []:
        if not isinstance(day, dict):
            continue
        for spot in (day.get("spots") or []):
            name = str(spot.get("name") or "").strip()
            if name:
                names.append(name)
        for item in (day.get("timeline") or []):
            if str(item.get("type") or "") != "attraction":
                continue
            name = str(item.get("name") or "").strip()
            if name:
                names.append(name)
    return names


async def _run_one(case: dict[str, str]) -> dict[str, Any]:
    from app.planning.graph import run_stream

    before = usage_snapshot()
    started = time.perf_counter()
    node_events: list[dict[str, Any]] = []
    pending: dict[str, float] = {}
    result: dict[str, Any] | None = None
    error: str | None = None

    try:
        async for event in run_stream(case["query"]):
            now = time.perf_counter()
            if event.get("type") == "stage":
                pending[event["node"]] = now
                node_events.append({"node": event["node"], "event": "start", "t": round(now - started, 3)})
            elif event.get("type") == "stage_summary":
                begin = pending.pop(event["node"], None)
                node_events.append({
                    "node": event["node"],
                    "event": "end",
                    "t": round(now - started, 3),
                    "ms": round((now - begin) * 1000, 1) if begin else None,
                    "summary": str(event.get("summary") or "")[:120],
                })
            elif event.get("type") == "result":
                result = {k: v for k, v in event.items() if k != "type"}
    except Exception as exc:  # noqa: BLE001 - 端到端评测要记录任何异常，不能中断整批
        error = f"{type(exc).__name__}: {exc}"

    latency = round(time.perf_counter() - started, 3)
    usage = usage_delta(before, usage_snapshot())

    plan = (result or {}).get("plan") or {}
    # result_envelope 用 ``days`` 承载逐日路线（早期版本叫 ``route``，两种都兼容）。
    route = plan.get("route") or plan.get("days") or []
    names = _spot_names(route)
    node_ms: dict[str, float] = {}
    for item in node_events:
        if item["event"] == "end" and item.get("ms"):
            node_ms[item["node"]] = max(node_ms.get(item["node"], 0.0), float(item["ms"]))

    return {
        "case_id": case["id"],
        "query": case["query"],
        "focus": case["focus"],
        "success": bool((result or {}).get("success")),
        "status": plan.get("status") or (result or {}).get("status"),
        "days": len(route),
        "spots": names,
        "spot_count": len(names),
        "route_issues": list(plan.get("route_issues") or [])[:5],
        "plan": plan,
        "missing_fields": (result or {}).get("missing_fields") or [],
        "plan_id": (result or {}).get("plan_id"),
        "latency_s": latency,
        "llm_calls": int(usage.get("calls_total") or 0),
        "input_tokens_est": int(usage.get("input_tokens") or 0),
        "output_tokens_est": int(usage.get("output_tokens") or 0),
        "node_ms": node_ms,
        "nodes_entered": sorted({item["node"] for item in node_events}),
        "events": node_events,
        "error": error,
    }


def _render(records: list[dict[str, Any]]) -> str:
    lines = ["# 端到端真实链路评测（生产 run_stream）", ""]
    ok = sum(1 for r in records if r["success"])
    lines.append(f"- 案例：{len(records)}；成功交付：{ok}；异常：{sum(1 for r in records if r['error'])}")
    lines.append("")
    lines.append("| 案例 | 成功 | 状态 | 天数 | 景点数 | 缺失字段 | 端到端 | LLM 调用 | 输入Token |")
    lines.append("|---|---|---|---:|---:|---|---:|---:|---:|")
    for r in records:
        lines.append(
            f"| {r['case_id']} | {'✅' if r['success'] else ('⚠️' if r['error'] else '❌')} | "
            f"{r['status'] or '-'} | {r['days']} | {r['spot_count']} | "
            f"{','.join(r['missing_fields']) or '-'} | {r['latency_s']:.1f}s | "
            f"{r['llm_calls']} | {r['input_tokens_est']} |"
        )
    lines.append("")
    lines.append("## 节点耗时（毫秒）")
    lines.append("")
    lines.append("| 案例 | 节点耗时 |")
    lines.append("|---|---|")
    for r in records:
        detail = "、".join(f"{k} {v:.0f}" for k, v in sorted(r["node_ms"].items()))
        lines.append(f"| {r['case_id']} | {detail or '-'} |")
    lines.append("")
    lines.append("## 路线概览")
    lines.append("")
    for r in records:
        lines.append(f"### {r['case_id']}")
        lines.append("")
        lines.append(f"- 输入：`{r['query']}`")
        lines.append(f"- 关注点：{r['focus']}")
        lines.append(f"- 节点序列：{' → '.join(n for n in r['nodes_entered'])}")
        lines.append(f"- 景点：{'、'.join(r['spots']) or '（无）'}")
        if r["error"]:
            lines.append(f"- 异常：`{r['error']}`")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="端到端真实链路评测")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--case", action="append", default=None, help="只跑指定 case id")
    parser.add_argument("--allow-external-calls", action="store_true")
    args = parser.parse_args(argv)

    load_local_env()
    cases = [c for c in FROZEN_QUERIES if not args.case or c["id"] in args.case]
    if not cases:
        print("没有匹配的 case")
        return 1
    print(f"计划运行 {len(cases)} 个端到端案例（真实高德 + 真实 LLM）")
    if not args.allow_external_calls:
        for case in cases:
            print(f"  - {case['id']}: {case['query']}")
        print("确认后追加 --allow-external-calls 再执行。")
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for index, case in enumerate(cases, 1):
        record = asyncio.run(_run_one(case))
        records.append(record)
        print(
            f"[{index}/{len(cases)}] {case['id']} -> "
            f"{'OK' if record['success'] else ('ERROR' if record['error'] else 'NO_PLAN')} "
            f"{record['latency_s']}s spots={record['spot_count']} calls={record['llm_calls']}"
        )
        (args.out / f"e2e_{case['id']}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # 分批跑时把同目录已有的单例结果一起合并，避免后一次覆盖前一次的报告。
    merged: list[dict[str, Any]] = []
    for path in sorted(args.out.glob("e2e_*.json")):
        try:
            merged.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    merged.sort(key=lambda row: str(row.get("case_id") or ""))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": len(merged),
        "success": sum(1 for r in merged if r["success"]),
        "errors": sum(1 for r in merged if r["error"]),
        "records": merged,
    }
    (args.out / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "REPORT.md").write_text(_render(merged), encoding="utf-8")
    print(f"产物目录：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
