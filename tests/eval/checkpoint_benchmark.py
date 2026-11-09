"""E2：Checkpoint 增量修改配对实验。

同一 fixture、同一条修改指令，只改变“是否复用应用层 checkpoint”：

- A（全量重规划）：保留 pois / 天气等冻结输入，但清空历史路线；
- B（Checkpoint 子图）：复用历史路线（``restore_modification_state``）。

两臂走同一套 planner/reviewer/time_check 子图（``tests.eval.harness``），
不包含 route_distance_check、餐食与贴士节点，因此只衡量本地重规划。

用法：

    python -m tests.eval.checkpoint_benchmark --dry-run
    python -m tests.eval.checkpoint_benchmark --allow-external-calls \
        --dirs evaluation/trials/run-20261107-negative evaluation/trials/run-20261107-v2 \
        --out evaluation/checkpoint_benchmark
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any, Callable

from app.core.env import load_local_env
from app.core.llm_usage import snapshot as usage_snapshot, usage_delta
from app.planning.graph import restore_modification_state
from app.planning.helpers import normalize_poi_name, poi_name_matches
from app.planning.quality import choose_snapshot
from app.planning.schemas import TravelPlanState

from tests.eval import harness

TRIAL_DIRS = (
    Path("evaluation/trials/run-20261107-negative"),
    Path("evaluation/trials/run-20261107-v2"),
)
DEFAULT_OUT = Path("evaluation/checkpoint_benchmark")
EDIT_TYPES = ("replace_indoor", "add_must_visit", "remove_spot", "change_time", "cross_day", "slow_pace")


# ─── 数据重建 ──────────────────────────────────────────────

def _fixture_map() -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for version in ("v2", "v1"):
        for case in harness.load_cases(version=version):
            cases.setdefault(case["id"], case)
    return cases


def _route_from_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "day": int(day.get("day") or index + 1),
            "spots": [
                {
                    "name": spot.get("name"),
                    "period": spot.get("period"),
                    "start_time": spot.get("start"),
                    "end_time": spot.get("end"),
                }
                for spot in (day.get("spots") or [])
            ],
        }
        for index, day in enumerate(record.get("route_by_day") or [])
    ]


def build_checkpoint(case: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    checkpoint = dict(case)
    checkpoint["route"] = _route_from_record(record)
    return checkpoint


def load_pairs(dirs: list[Path]) -> list[dict[str, Any]]:
    fixtures = _fixture_map()
    pairs: list[dict[str, Any]] = []
    for directory in dirs:
        for path in sorted(directory.glob("trial_*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            if not record.get("plan_generated") or not record.get("route_by_day"):
                continue
            case = fixtures.get(str(record.get("case_id")))
            if not case:
                continue
            pairs.append({
                "case": case,
                "record": record,
                "checkpoint": build_checkpoint(case, record),
            })
    return pairs


# ─── 修改探针 ──────────────────────────────────────────────

def _minutes(value: Any) -> int | None:
    text = str(value or "")
    if ":" not in text:
        return None
    try:
        hour, minute = text.split(":")[:2]
        return int(hour) * 60 + int(minute)
    except ValueError:
        return None


def _day_spots(route: list[dict[str, Any]], day_no: int) -> list[dict[str, Any]]:
    for day in route:
        if int(day.get("day") or 0) == day_no:
            return list(day.get("spots") or [])
    return []


def _names(route: list[dict[str, Any]]) -> list[str]:
    return [str(spot.get("name") or "") for day in route for spot in (day.get("spots") or [])]


def _indoor_map(case: dict[str, Any]) -> dict[str, bool]:
    return {str(item.get("name")): bool(item.get("indoor")) for item in (case.get("pois") or [])}


def _pick(indoor: dict[str, bool], route: list[dict[str, Any]], *, want_indoor: bool) -> str | None:
    used = {normalize_poi_name(name) for name in _names(route)}
    for name, is_indoor in indoor.items():
        if is_indoor is want_indoor and normalize_poi_name(name) not in used:
            return name
    return None


def _edit_replace_indoor(case, route, index) -> dict[str, Any] | None:
    indoor = _indoor_map(case)
    new_spot = _pick(indoor, route, want_indoor=True)
    if not new_spot:
        return None
    for day in route:
        afternoon = [
            spot for spot in (day.get("spots") or [])
            if str(spot.get("period") or "") in {"afternoon", "evening"}
        ]
        if afternoon:
            old = str(afternoon[0].get("name"))
            day_no = int(day.get("day") or 1)

            def check(state, day_no=day_no, old=old, new_spot=new_spot):
                spots = _day_spots(state.route or [], day_no)
                names = [str(item.get("name") or "") for item in spots]
                return (not any(poi_name_matches(n, old, state.destination or "") for n in names)
                        and any(poi_name_matches(n, new_spot, state.destination or "") for n in names))

            return {
                "type": "replace_indoor",
                "instruction": f"把第{day_no}天下午的“{old}”换成室内的“{new_spot}”，其他天尽量保持不变。",
                "check": check,
                "involved": {old},
            }
    return None


def _edit_add_must_visit(case, route, index) -> dict[str, Any] | None:
    candidate = _pick(_indoor_map(case), route, want_indoor=True) or _pick(_indoor_map(case), route, want_indoor=False)
    if not candidate:
        return None
    day_no = int(route[min(1, len(route) - 1)].get("day") or 1)
    instruction = f"第{day_no}天一定去“{candidate}”，其他安排尽量保持不变。"

    def check(state, candidate=candidate):
        return any(poi_name_matches(name, candidate, state.destination or "")
                   for name in _names(state.route or []))

    return {"type": "add_must_visit", "instruction": instruction, "check": check, "involved": set()}


def _edit_remove_spot(case, route, index) -> dict[str, Any] | None:
    for day in route:
        spots = list(day.get("spots") or [])
        if len(spots) < 2:
            continue
        old = str(spots[-1].get("name"))
        day_no = int(day.get("day") or 1)

        def check(state, day_no=day_no, old=old):
            names = [str(item.get("name") or "") for item in _day_spots(state.route or [], day_no)]
            return (not any(poi_name_matches(n, old, state.destination or "") for n in names)
                    and len(state.route or []) == int(state.days or 0))

        return {
            "type": "remove_spot",
            "instruction": f"去掉第{day_no}天的“{old}”，其他安排尽量保持不变。",
            "check": check,
            "involved": {old},
        }
    return None


def _edit_change_time(case, route, index) -> dict[str, Any] | None:
    spots = _day_spots(route, int(route[0].get("day") or 1))
    if not spots:
        return None

    def check(state):
        first = (_day_spots(state.route or [], int(route[0].get("day") or 1)) or [{}])[0]
        start = _minutes(first.get("start_time"))
        return start is not None and start >= 600

    return {
        "type": "change_time",
        "instruction": "第1天第一个景点改到10:00以后开始，其他安排尽量保持不变。",
        "check": check,
        "involved": set(),
    }


def _edit_cross_day(case, route, index) -> dict[str, Any] | None:
    if len(route) < 3:
        return None
    source, dest = int(route[1].get("day") or 2), int(route[2].get("day") or 3)
    spots = _day_spots(route, source)
    if not spots:
        return None
    moving = str(spots[0].get("name"))

    def check(state, source=source, dest=dest, moving=moving):
        source_names = [str(item.get("name") or "") for item in _day_spots(state.route or [], source)]
        dest_names = [str(item.get("name") or "") for item in _day_spots(state.route or [], dest)]
        return (not any(poi_name_matches(n, moving, state.destination or "") for n in source_names)
                and any(poi_name_matches(n, moving, state.destination or "") for n in dest_names))

    return {
        "type": "cross_day",
        "instruction": f"把第{source}天第一个景点“{moving}”移到第{dest}天，其他安排尽量保持不变。",
        "check": check,
        "involved": {moving},
    }


def _edit_slow_pace(case, route, index) -> dict[str, Any] | None:
    if not route:
        return None

    def check(state):
        return all(len(day.get("spots") or []) <= 2 for day in (state.route or []))

    return {
        "type": "slow_pace",
        "instruction": "整体改成慢节奏，每天最多安排2个景点，其他安排尽量保持不变。",
        "check": check,
        "involved": set(),
    }


EDIT_BUILDERS: dict[str, Callable[[dict, list, int], dict | None]] = {
    "replace_indoor": _edit_replace_indoor,
    "add_must_visit": _edit_add_must_visit,
    "remove_spot": _edit_remove_spot,
    "change_time": _edit_change_time,
    "cross_day": _edit_cross_day,
    "slow_pace": _edit_slow_pace,
}


def build_edits(case: dict[str, Any], checkpoint: dict[str, Any], index: int) -> list[dict[str, Any]]:
    """为单个 checkpoint 生成所有可执行的修改类型；去重与截断在 main 中完成。"""
    edits: list[dict[str, Any]] = []
    for offset in range(len(EDIT_TYPES)):
        builder = EDIT_BUILDERS[EDIT_TYPES[(index + offset) % len(EDIT_TYPES)]]
        edit = builder(case, checkpoint["route"], index)
        if edit:
            edits.append(edit)
    return edits


def retention(case: dict[str, Any], checkpoint: dict[str, Any], result_route: list[dict[str, Any]],
              involved: set[str]) -> float:
    original = [name for name in _names(checkpoint["route"])
                if not any(poi_name_matches(name, item, case.get("destination") or "") for item in involved)]
    if not original:
        return 1.0
    result = _names(result_route)
    kept = [name for name in original
            if any(poi_name_matches(name, other, case.get("destination") or "") for other in result)]
    return round(len(kept) / len(original), 4)


# ─── 运行 ──────────────────────────────────────────────────

def run_arm(case: dict[str, Any], checkpoint: dict[str, Any], instruction: str,
            use_checkpoint: bool, mode: str) -> dict[str, Any]:
    state_checkpoint = dict(checkpoint)
    if not use_checkpoint:
        state_checkpoint["route"] = []
    state = restore_modification_state(state_checkpoint, instruction).model_copy(
        update={"max_review_rounds": 1}
    )

    counts: dict[str, int] = {}
    durations: dict[str, list[float]] = {}
    app = harness.build_evaluation_graph(
        mode, state.model_name,
        counts=counts, durations=durations,
    )
    before = usage_snapshot()
    started = time.perf_counter()
    result = app.invoke(state, config={"recursion_limit": harness.recursion_limit(state)})
    latency = time.perf_counter() - started
    usage = usage_delta(before, usage_snapshot())
    # ``invoke`` 返回状态字典；统一转成 TravelPlanState 以便读取快照。
    final_state = TravelPlanState(**result)
    chosen, status, warnings, failures = choose_snapshot(final_state)
    route = list((chosen or {}).get("plan", {}).get("route") or [])
    return {
        "latency_s": round(latency, 3),
        "input_tokens": int(usage.get("input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
        "llm_calls": int(usage.get("calls_total") or 0),
        "status": status,
        "hard_pass": bool(route) and not ((chosen or {}).get("l0_violations") or []),
        "plan_generated": bool(route),
        "route_names": _names(route),
        "route": route,
        "warnings": warnings,
        "failure_codes": [item.get("code") for item in failures],
        "nodes": sorted(counts.keys()),
    }


def run_pair(case: dict[str, Any], checkpoint: dict[str, Any], edit: dict[str, Any],
             mode: str) -> dict[str, Any]:
    instruction = edit["instruction"]
    arm_a = run_arm(case, checkpoint, instruction, use_checkpoint=False, mode=mode)
    arm_b = run_arm(case, checkpoint, instruction, use_checkpoint=True, mode=mode)
    satisfaction = {
        "A": bool(arm_a["plan_generated"] and edit["check"](
            restore_modification_state(dict(checkpoint, route=arm_a["route"]), instruction))),
        "B": bool(arm_b["plan_generated"] and edit["check"](
            restore_modification_state(dict(checkpoint, route=arm_b["route"]), instruction))),
    }
    return {
        "case_id": case["id"],
        "edit_type": edit["type"],
        "instruction": instruction,
        "A": arm_a,
        "B": arm_b,
        "edit_satisfied": satisfaction,
        "retention": {
            "A": retention(case, checkpoint, arm_a["route"], edit["involved"]),
            "B": retention(case, checkpoint, arm_b["route"], edit["involved"]),
        },
    }


def _p50(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def summarize(records: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    lat_a = [item["A"]["latency_s"] * 1000 for item in records]
    lat_b = [item["B"]["latency_s"] * 1000 for item in records]
    token_a = sum(item["A"]["input_tokens"] for item in records)
    token_b = sum(item["B"]["input_tokens"] for item in records)
    p50_a, p50_b = _p50(lat_a), _p50(lat_b)
    return {
        "mode": mode,
        "pairs": len(records),
        "p50_ms": {"A": p50_a, "B": p50_b},
        "latency_reduction": round((p50_a - p50_b) / p50_a, 4) if p50_a and p50_b else None,
        "input_tokens": {"A": token_a, "B": token_b},
        "token_reduction": round((token_a - token_b) / token_a, 4) if token_a else None,
        "edit_satisfaction": {
            arm: round(sum(1 for item in records if item["edit_satisfied"][arm]) / len(records), 4)
            for arm in ("A", "B")
        } if records else {"A": None, "B": None},
        "retention": {
            arm: round(sum(item["retention"][arm] for item in records) / len(records), 4)
            for arm in ("A", "B")
        } if records else {"A": None, "B": None},
        "hard_pass": {
            arm: round(sum(1 for item in records if item[arm]["hard_pass"]) / len(records), 4)
            for arm in ("A", "B")
        } if records else {"A": None, "B": None},
    }


def render_report(summary: dict[str, Any], records: list[dict[str, Any]]) -> str:
    lines = [
        "# E2 Checkpoint 增量修改配对实验",
        "",
        f"> {summary['pairs']} 组配对（同 fixture、同修改指令）；A=全量重规划，B=复用应用层 checkpoint。",
        f"> 执行模式：`{summary['mode']}`；不含 route_distance_check、餐食与贴士。",
        "",
        "## 汇总",
        "",
        "| 指标 | A 全量重规划 | B Checkpoint | 变化 |",
        "|---|---|---|---|",
        f"| 重规划 P50 (ms) | {summary['p50_ms']['A']} | {summary['p50_ms']['B']} | {_pct(summary['latency_reduction'])} |",
        f"| 输入 Token 合计 | {summary['input_tokens']['A']} | {summary['input_tokens']['B']} | {_pct(summary['token_reduction'])} |",
        f"| 修改指令满足率 | {_pct(summary['edit_satisfaction']['A'])} | {_pct(summary['edit_satisfaction']['B'])} | - |",
        f"| 未修改内容保留率 | {_pct(summary['retention']['A'])} | {_pct(summary['retention']['B'])} | - |",
        f"| 修改后硬约束通过率 | {_pct(summary['hard_pass']['A'])} | {_pct(summary['hard_pass']['B'])} | - |",
        "",
        "## 逐组结果",
        "",
        "| # | case | 类型 | A 秒 | B 秒 | A Token | B Token | 满足 A/B | 保留 A/B | 硬通过 A/B |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for index, item in enumerate(records, 1):
        lines.append(
            f"| {index} | {item['case_id']} | {item['edit_type']} | "
            f"{item['A']['latency_s']} | {item['B']['latency_s']} | "
            f"{item['A']['input_tokens']} | {item['B']['input_tokens']} | "
            f"{item['edit_satisfied']['A']}/{item['edit_satisfied']['B']} | "
            f"{item['retention']['A']}/{item['retention']['B']} | "
            f"{item['A']['hard_pass']}/{item['B']['hard_pass']} |"
        )
    return "\n".join(lines) + "\n"


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="E2 checkpoint paired benchmark")
    parser.add_argument("--dirs", nargs="*", type=Path, default=list(TRIAL_DIRS))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-pairs", type=int, default=30)
    parser.add_argument("--mode", default="planner_reviewer_time_check",
                        choices=["planner_only", "planner_reviewer", "planner_reviewer_time_check"],
                        help="重规划子图模式；planner_only 可显著降低调用成本")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-external-calls", action="store_true")
    args = parser.parse_args(argv)

    load_local_env()
    sources = load_pairs([path for path in args.dirs if path.exists()])
    # 同一案例优先使用审核最完整的 checkpoint；同案例同类型的指令只保留第一条，
    # 避免 A/B/C 三条 trial 产生完全重复的探针。
    priority = {"planner_reviewer_time_check": 0, "planner_reviewer": 1, "planner_only": 2}
    sources.sort(key=lambda item: (item["case"]["id"], priority.get(
        str(item["record"].get("mode_requested")), 3)))
    jobs: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    seen: set[tuple[str, str]] = set()
    for index, source in enumerate(sources):
        for edit in build_edits(source["case"], source["checkpoint"], index):
            key = (source["case"]["id"], edit["type"])
            if key in seen:
                continue
            seen.add(key)
            jobs.append((source["case"], source["checkpoint"], edit))
            if len(jobs) >= args.max_pairs:
                break
        if len(jobs) >= args.max_pairs:
            break

    print(f"checkpoint 数：{len(sources)}；配对探针：{len(jobs)}")
    if args.dry_run:
        for case, _checkpoint, edit in jobs:
            print(f"  - {case['id']} / {edit['type']}：{edit['instruction']}")
        return 0
    if not args.allow_external_calls:
        print("真实运行会调用 LLM；确认后追加 --allow-external-calls。", file=__import__("sys").stderr)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    raw = args.out / "raw"
    raw.mkdir(exist_ok=True)
    records: list[dict[str, Any]] = []
    for index, (case, checkpoint, edit) in enumerate(jobs, 1):
        path = raw / f"pair_{index:02d}_{case['id']}_{edit['type']}.json"
        if path.exists():
            records.append(json.loads(path.read_text(encoding="utf-8")))
            print(f"[skip] {path.name}")
            continue
        record = run_pair(case, checkpoint, edit, args.mode)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        records.append(record)
        print(f"[{index}/{len(jobs)}] {case['id']} / {edit['type']} "
              f"A={record['A']['latency_s']}s B={record['B']['latency_s']}s "
              f"A_token={record['A']['input_tokens']} B_token={record['B']['input_tokens']}")

    summary = summarize(records, args.mode)
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "REPORT.md").write_text(render_report(summary, records), encoding="utf-8")
    print(f"产物目录：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
