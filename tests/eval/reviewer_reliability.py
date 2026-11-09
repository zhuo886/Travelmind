"""Reviewer 可靠性离线分析（零成本）。

两套口径严格分开：
- ``snapshot_trace``：新运行记录每轮快照、审核决定、返工请求与路线签名；
- ``proxy``：旧 trial 只有首版 L0、最终 L0 与返工轮数，只能做保守代理。

proxy 的 ``rework_ineffective`` 表示“问题最终仍在”，不等于“Planner 忽略审核”。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _rate(num: int, den: int) -> dict[str, Any]:
    return {"num": num, "den": den, "value": round(num / den, 4) if den else None}


def _delivered(record: dict[str, Any]) -> bool:
    if "delivered_plan" in record:
        return bool(record.get("delivered_plan"))
    return bool(record.get("plan_generated")) and str(record.get("status")) != "FAILED"


def _codes(snapshot: dict[str, Any]) -> set[str]:
    return {
        str(code)
        for code in (
            list(snapshot.get("l0_codes") or []) + list(snapshot.get("l1_codes") or [])
        )
        if code
    }


def _trace_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    snapshots = 0
    review_requests = 0
    events = 0
    effective = 0
    ignored = 0
    regression = 0
    approved_snapshots = 0
    clean_snapshots = 0
    clean_blocks = 0
    delivered_trials = 0
    delivered_with_defect = 0
    wrong_accept = 0
    over_reject = 0

    for record in records:
        trace = list(record.get("snapshot_trace") or [])
        snapshots += len(trace)
        for snapshot in trace:
            if snapshot.get("reviewer_approved") is True:
                approved_snapshots += 1
            if int(snapshot.get("defect_count") or 0) == 0:
                clean_snapshots += 1
            if snapshot.get("reviewer_approved") is False and int(snapshot.get("defect_count") or 0) == 0:
                clean_blocks += 1
            if snapshot.get("rework_requested"):
                review_requests += 1

        for previous, current in zip(trace, trace[1:]):
            if not previous.get("rework_requested"):
                continue
            events += 1
            prev_count = int(previous.get("defect_count") or 0)
            curr_count = int(current.get("defect_count") or 0)
            if curr_count < prev_count:
                effective += 1
            if (
                str(current.get("route_signature")) == str(previous.get("route_signature"))
                and curr_count >= prev_count
            ):
                ignored += 1
            if _codes(current) - _codes(previous):
                regression += 1

        if _delivered(record):
            delivered_trials += 1
            delivered_snapshot = next(
                (item for item in trace if item.get("is_delivered")), None
            )
            if delivered_snapshot is not None and int(delivered_snapshot.get("defect_count") or 0) > 0:
                delivered_with_defect += 1
            elif delivered_snapshot is None and (record.get("l0_codes") or record.get("l1_codes")):
                delivered_with_defect += 1
        if record.get("benchmark_label") == "WRONG_ACCEPT":
            wrong_accept += 1
        if record.get("benchmark_label") == "OVER_REJECT":
            over_reject += 1

    reviewed = sum(1 for record in records if int(record.get("reviewer_calls") or 0) > 0)
    return {
        "source": "snapshot_trace",
        "trials": len(records),
        "reviewed_trials": reviewed,
        "snapshots": snapshots,
        "review_requests": review_requests,
        "review_request_rate": _rate(review_requests, snapshots),
        "rework_events": events,
        "rework_effective": effective,
        "rework_ignored": ignored,
        "rework_regression": regression,
        "rework_effective_rate": _rate(effective, events),
        "rework_ignored_rate": _rate(ignored, events),
        "rework_regression_rate": _rate(regression, events),
        "approved_snapshots": approved_snapshots,
        "clean_snapshots": clean_snapshots,
        "clean_block": clean_blocks,
        "clean_block_rate": _rate(clean_blocks, clean_snapshots),
        "delivered_trials": delivered_trials,
        "delivered_with_defect": delivered_with_defect,
        "delivered_with_defect_rate": _rate(delivered_with_defect, delivered_trials),
        "wrong_accept": wrong_accept,
        "over_reject": over_reject,
        "wrong_accept_rate": _rate(wrong_accept, len(records)),
        "over_reject_rate": _rate(over_reject, len(records)),
    }


def _proxy_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    rework_attempted = 0
    rework_events = 0
    effective = 0
    ineffective = 0
    delivered_trials = 0
    delivered_with_defect = 0
    wrong_accept = 0
    over_reject = 0

    for record in records:
        reviewed = (
            str(record.get("mode_requested") or "") != "planner_only"
            or int(record.get("reviewer_calls") or 0) > 0
        )
        if reviewed and int(record.get("planning_revision_rounds") or 0) >= 1:
            rework_attempted += 1
        first_l0 = list(record.get("first_draft_l0") or [])
        final_l0 = list(record.get("l0_codes") or [])
        if reviewed and first_l0 and int(record.get("planning_revision_rounds") or 0) >= 1:
            rework_events += 1
            if final_l0:
                ineffective += 1
            else:
                effective += 1
        if _delivered(record):
            delivered_trials += 1
            if record.get("l1_codes") or record.get("l0_codes"):
                delivered_with_defect += 1
        if record.get("benchmark_label") == "WRONG_ACCEPT":
            wrong_accept += 1
        if record.get("benchmark_label") == "OVER_REJECT":
            over_reject += 1

    return {
        "source": "proxy",
        "trials": len(records),
        "rework_attempted": rework_attempted,
        "rework_events_with_first_l0": rework_events,
        "rework_effective": effective,
        "rework_ineffective": ineffective,
        "rework_effective_rate": _rate(effective, rework_events),
        "rework_ineffective_rate": _rate(ineffective, rework_events),
        "clean_block": None,
        "clean_block_rate": None,
        "rework_regression_rate": None,
        "delivered_trials": delivered_trials,
        "delivered_with_defect": delivered_with_defect,
        "delivered_with_defect_rate": _rate(delivered_with_defect, delivered_trials),
        "wrong_accept": wrong_accept,
        "over_reject": over_reject,
        "wrong_accept_rate": _rate(wrong_accept, len(records)),
        "over_reject_rate": _rate(over_reject, len(records)),
        "note": "proxy 的 rework_ineffective 是“问题仍在”，不等于 Planner 忽略审核；clean_block 与 regression 无法从旧记录判断。",
    }


def evaluate(records: list[dict[str, Any]]) -> dict[str, Any]:
    trace_records = [record for record in records if record.get("snapshot_trace")]
    proxy_records = [record for record in records if not record.get("snapshot_trace")]
    return {
        "total_records": len(records),
        "by_source": {
            "snapshot_trace": _trace_metrics(trace_records) if trace_records else None,
            "proxy": _proxy_metrics(proxy_records) if proxy_records else None,
        },
    }


def _line(name: str, value: dict[str, Any] | None) -> str:
    if not value:
        return f"| {name} | N/A | N/A |"
    shown = "N/A" if value.get("value") is None else f"{value['value'] * 100:.1f}%"
    return f"| {name} | {value.get('num')} / {value.get('den')} | {shown} |"


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Reviewer 可靠性",
        "",
        f"- 记录总数：{report['total_records']}",
        "- 口径：snapshot_trace 与 proxy 分开统计，不混算。",
        "",
    ]
    trace = report["by_source"].get("snapshot_trace")
    if trace:
        lines += [
            "## snapshot_trace",
            "",
            f"- trial：{trace['trials']}；reviewer 实际执行：{trace['reviewed_trials']}；"
            f"快照：{trace['snapshots']}",
            "",
            "| 指标 | 分子 / 分母 | 值 |",
            "|---|---|---|",
            _line("审核请求率", trace["review_request_rate"]),
            _line("返工有效率", trace["rework_effective_rate"]),
            _line("返工未改路线率", trace["rework_ignored_rate"]),
            _line("返工引入新问题率", trace["rework_regression_rate"]),
            _line("clean_block（疑似误打回）", trace["clean_block_rate"]),
            _line("交付仍带缺陷率", trace["delivered_with_defect_rate"]),
            _line("误接受率 WRONG_ACCEPT", trace["wrong_accept_rate"]),
            _line("过度拒绝率 OVER_REJECT", trace["over_reject_rate"]),
            "",
        ]
    else:
        lines += ["## snapshot_trace", "", "- N/A：现有记录没有每轮快照。", ""]

    proxy = report["by_source"].get("proxy")
    if proxy:
        lines += [
            "## proxy",
            "",
            f"- trial：{proxy['trials']}；有返工尝试：{proxy['rework_attempted']}；"
            f"首版 L0 且返工：{proxy['rework_events_with_first_l0']}",
            "",
            "| 指标 | 分子 / 分母 | 值 |",
            "|---|---|---|",
            _line("返工修复率", proxy["rework_effective_rate"]),
            _line("返工未修复率", proxy["rework_ineffective_rate"]),
            _line("交付仍带缺陷率", proxy["delivered_with_defect_rate"]),
            _line("误接受率 WRONG_ACCEPT", proxy["wrong_accept_rate"]),
            _line("过度拒绝率 OVER_REJECT", proxy["over_reject_rate"]),
            "",
            f"> {proxy['note']}",
            "",
        ]
    else:
        lines += ["## proxy", "", "- N/A：没有旧口径记录。", ""]

    lines += [
        "## 边界",
        "",
        "- clean_block 只表示“审核打回了确定性零缺陷草稿”，是否真的误打回仍需 Judge 或人工语义复核。",
        "- proxy 的返工分母只包含“首版 L0 非空且实际返工”的 trial，不能当整体审核收益。",
        "- 本报告是零成本离线基线，不包含任何真实 Reviewer 调用。",
    ]
    return "\n".join(lines)


def load_records(dirs: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for directory in dirs:
        for path in sorted(directory.glob("trial_*.json")):
            records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reviewer 可靠性离线报告")
    parser.add_argument("--dirs", nargs="+", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)

    records = load_records(args.dirs)
    if not records:
        raise SystemExit("没有找到 trial_*.json")
    report = evaluate(records)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "REPORT.md").write_text(render_markdown(report), encoding="utf-8")
    print(f"Reviewer 可靠性：{len(records)} 条记录 -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())