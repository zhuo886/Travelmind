"""有界 ReAct 检索的合规性与幻觉阻断（纯聚合，0 次调用）。

只使用已冻结 trial 里真实落盘的字段，不重算、不推测：

- ``candidate_api_calls``：本轮候选检索实际 HTTP 次数，对照 ``effective_api_budget`` 上限 10；
- ``oor``：交付路线里出现在候选池外的景点引用数 / 总引用数；
- ``l0_codes`` / ``first_draft_l0``：``unknown_poi`` 是否出现、是否被 Reviewer 修掉；
- ``must_visit_ok``：点名必去覆盖。

去重（``REPEATED_QUERY``）与候选缓存命中没有写进 trial 记录，本轮只能标 N/A；
``run_trials`` 从本轮起补写 ``candidate_search_trace``，供下一轮复核。

用法::

    python -m tests.eval.candidate_budget --dirs evaluation/trials/run-20261106/s1 ... \
        --out evaluation/benchmarks/candidate_budget
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

DEFAULT_DIRS = (
    Path("evaluation/trials/run-20261106/s1"),
    Path("evaluation/trials/run-20261106/s2"),
    Path("evaluation/trials/run-20261106/s3"),
    Path("evaluation/trials/run-20261107-v2"),
    Path("evaluation/trials/run-20261107-negative"),
)
DEFAULT_OUT = Path("evaluation/benchmarks/candidate_budget")
DEFAULT_SAFETY_DIRS = (Path("evaluation/trials/run-20261107-safety-hardreject-v2"),)
# 预算的真实证据在受控场景里：trial 从未触及检索，不能拿“0 次调用”算 100%。
GAP_FILL_SUMMARY = Path("evaluation/benchmarks/gap_fill/summary.json")
API_BUDGET_CEILING = 10  # candidate_react.effective_api_budget 的硬上限
ROUND_CEILING = 2  # candidate_max_rounds 的产品默认值
# must_visit 必须分批报：v2 的 9/9 不能和安全样本混在一起，
# 不可行样本的 must_visit_ok=False 是“正确拒绝”的结果，不是覆盖失败。
BUCKET_MARKERS = (
    ("v1", "run-20261106"),
    ("v2", "run-20261107-v2"),
    ("negative", "run-20261107-negative"),
    ("v3_safety", "run-20261107-safety"),
)


def load_records(dirs: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for directory in dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("trial_*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            record["_source"] = str(directory)
            records.append(record)
    return records


def _effective(record: dict[str, Any]) -> bool:
    return not record.get("invalid_trial") and not record.get("error")


def budget_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    effective = [record for record in records if _effective(record)]
    calls = [int(record.get("candidate_api_calls") or 0) for record in effective]
    violations = [
        {
            "trial_id": record.get("trial_id"),
            "case_id": record.get("case_id"),
            "mode": record.get("mode_requested"),
            "candidate_api_calls": int(record.get("candidate_api_calls") or 0),
        }
        for record in effective
        if int(record.get("candidate_api_calls") or 0) > API_BUDGET_CEILING
    ]
    by_mode: dict[str, dict[str, Any]] = {}
    for mode in sorted({str(record.get("mode_requested")) for record in effective}):
        values = [
            int(record.get("candidate_api_calls") or 0)
            for record in effective
            if str(record.get("mode_requested")) == mode
        ]
        by_mode[mode] = {
            "trials": len(values),
            "median": statistics.median(values) if values else None,
            "max": max(values) if values else None,
        }
    return {
        "ceiling": API_BUDGET_CEILING,
        "trials": len(effective),
        # 关键：harness 子图从 planner 起跑，不经过检索节点，candidate_api_calls 恒为 0。
        # 这时“合规率 100%”是空转，必须标 N/A，否则等于用没发生的检索证明预算有效。
        "exercised": any(calls),
        "compliant": len(effective) - len(violations),
        "compliance_rate": round((len(effective) - len(violations)) / len(effective), 4)
        if effective and any(calls) else None,
        "violations": violations,
        "calls_total": sum(calls),
        "calls_median": statistics.median(calls) if calls else None,
        "calls_max": max(calls) if calls else None,
        "by_mode": by_mode,
        "reason": None if any(calls) else (
            "已冻结 trial 的 candidate_api_calls 全为 0（harness 从 planner 起跑，不经过检索节点），"
            "预算合规无法由这批数据证明；预算行为改由 gap_fill 的 bounded_react 臂覆盖"
        ),
    }


def hallucination_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    effective = [record for record in records if _effective(record) and record.get("plan_generated")]
    outside = sum(int((record.get("oor") or {}).get("outside") or 0) for record in effective)
    total = sum(int((record.get("oor") or {}).get("total") or 0) for record in effective)

    unknown_by_mode: dict[str, dict[str, int]] = {}
    for mode in sorted({str(record.get("mode_requested")) for record in effective}):
        subset = [r for r in effective if str(r.get("mode_requested")) == mode]
        hits = sum(1 for r in subset if "unknown_poi" in (r.get("l0_codes") or []))
        unknown_by_mode[mode] = {"trials": len(subset), "unknown_poi": hits}

    blocked = [
        {
            "trial_id": record.get("trial_id"),
            "case_id": record.get("case_id"),
            "mode": record.get("mode_requested"),
        }
        for record in effective
        if "unknown_poi" in (record.get("first_draft_l0") or [])
        and "unknown_poi" not in (record.get("l0_codes") or [])
    ]
    first_draft_hits = sum(
        1 for record in effective if "unknown_poi" in (record.get("first_draft_l0") or [])
    )
    return {
        "trials": len(effective),
        "oor": {
            "outside": outside,
            "total": total,
            "rate": round(outside / total, 5) if total else None,
        },
        "unknown_poi_by_mode": unknown_by_mode,
        "first_draft_unknown_poi": first_draft_hits,
        "blocked_by_reviewer": len(blocked),
        "blocked_trials": blocked,
    }


def _bucket_of(record: dict[str, Any]) -> str:
    source = str(record.get("_source") or "")
    for name, marker in BUCKET_MARKERS:
        if marker in source:
            return name
    return "other"


def must_visit_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated = [record for record in records if record.get("must_visit_ok") is not None]
    passed = sum(1 for record in evaluated if record.get("must_visit_ok"))
    infeasible = [
        record for record in records
        if record.get("expected_feasible") is False
    ]
    by_bucket: dict[str, dict[str, Any]] = {}
    for record in evaluated:
        bucket = _bucket_of(record)
        slot = by_bucket.setdefault(bucket, {"evaluated": 0, "passed": 0, "failed_cases": []})
        slot["evaluated"] += 1
        if record.get("must_visit_ok"):
            slot["passed"] += 1
        else:
            slot["failed_cases"].append(f"{record.get('case_id')}::{record.get('mode_requested')}")
    for slot in by_bucket.values():
        slot["rate"] = round(slot["passed"] / slot["evaluated"], 4) if slot["evaluated"] else None
    return {
        "evaluated": len(evaluated),
        "passed": passed,
        "rate": round(passed / len(evaluated), 4) if evaluated else None,
        "by_bucket": dict(sorted(by_bucket.items())),
        "infeasible_trials": len(infeasible),
        "note": "不可行 case 的 must_visit_ok=False 是正确拒绝的结果，不应当作覆盖失败",
    }


def safety_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    """v3 安全样本单列：它们必须与可行集的 must_visit 分母分开。"""
    if not records:
        return {"trials": 0, "note": "未提供安全样本目录"}
    outcomes = Counter(str(record.get("actual_outcome")) for record in records)
    must = [record for record in records if record.get("must_visit_ok") is not None]
    return {
        "trials": len(records),
        "outcomes": dict(outcomes),
        "must_visit_evaluated": len(must),
        "must_visit_passed": sum(1 for record in must if record.get("must_visit_ok")),
        "note": "安全样本 intended 为不可行；must_visit_ok=False 与 CORRECT_REJECT 一致，不算失败",
    }


def dedupe_report(records: list[dict[str, Any]]) -> dict[str, Any]:
    with_trace = [record for record in records if record.get("candidate_search_trace")]
    repeated = 0
    cache_hits = 0
    for record in with_trace:
        for entry in record.get("candidate_search_trace") or []:
            if entry.get("error_code") == "REPEATED_QUERY":
                repeated += 1
            if entry.get("cache_hit"):
                cache_hits += 1
    return {
        "available": bool(with_trace),
        "trials_with_trace": len(with_trace),
        "repeated_query_rejected": repeated if with_trace else None,
        "cache_hits": cache_hits if with_trace else None,
        "reason": (
            "现有 trial 未落盘 candidate_search_trace；该字段自本轮起在 run_trials 中补写，"
            "去重与缓存命中需下一轮运行才有数据"
        ) if not with_trace else "从 candidate_search_trace 统计",
    }


def scenario_budget_check(path: Path = GAP_FILL_SUMMARY) -> dict[str, Any] | None:
    """从 gap_fill 的 bounded_react 臂取“真实执行器下”的预算合规。"""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    rows = [
        row for row in (data.get("rows") or [])
        if row.get("arm") == "bounded_react"
    ]
    if not rows:
        return None
    compliant = [row for row in rows if int(row.get("api_calls") or 0) <= API_BUDGET_CEILING]
    return {
        "source": str(path),
        "scenarios": len(rows),
        "compliant": len(compliant),
        "rate": round(len(compliant) / len(rows), 4),
        "max_calls": max(int(row.get("api_calls") or 0) for row in rows),
        "ceiling": API_BUDGET_CEILING,
        "note": "受控场景跑的是真实决策队列与执行器（仅检索结果被桩替换）",
    }


def build_summary(dirs: list[Path], safety_dirs: list[Path] | None = None) -> dict[str, Any]:
    records = load_records(dirs)
    safety_records = load_records(list(safety_dirs or []))
    budget = budget_report(records)
    budget["scenario_check"] = scenario_budget_check()
    return {
        "benchmark": "candidate_budget",
        "kind": "aggregation",
        "sources": [str(path) for path in dirs],
        "safety_sources": [str(path) for path in (safety_dirs or [])],
        "records": len(records),
        "budget": budget,
        "round_ceiling": ROUND_CEILING,
        "hallucination": hallucination_report(records),
        "must_visit": must_visit_report(records),
        "safety": safety_report(safety_records),
        "dedupe": dedupe_report(records),
        "l0_code_counts": dict(Counter(
            code for record in records for code in (record.get("l0_codes") or [])
        )),
        "l1_code_counts": dict(Counter(
            code for record in records for code in (record.get("l1_codes") or [])
        )),
    }


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


def render_markdown(summary: dict[str, Any]) -> str:
    budget = summary["budget"]
    hall = summary["hallucination"]
    must = summary["must_visit"]
    dedupe = summary["dedupe"]
    lines = [
        "# 有界 ReAct 检索：预算合规与幻觉阻断",
        "",
        "> 数据：已冻结 trial 的落盘字段，纯聚合，0 次调用",
        f"> 样本：{summary['records']} 条（有效 {budget['trials']} 条）",
        "",
        "## 1. 预算合规",
        "",
        f"- 上限：`effective_api_budget ≤ {budget['ceiling']}`、`candidate_max_rounds ≤ {summary['round_ceiling']}`",
    ]
    if budget.get("exercised"):
        lines.append(
            f"- 合规：**{budget['compliant']} / {budget['trials']}"
            f"（{_pct(budget['compliance_rate'])}）**"
        )
        lines.append(
            f"- 单 trial 检索次数：中位 {budget['calls_median']}，最大 {budget['calls_max']}，"
            f"合计 {budget['calls_total']}"
        )
    else:
        lines += [
            "- trial 口径：**N/A**",
            f"- 原因：{budget['reason']}",
        ]
    scenario = budget.get("scenario_check")
    if scenario:
        lines += [
            f"- 受控场景口径：**{scenario['compliant']} / {scenario['scenarios']}"
            f"（{_pct(scenario['rate'])}）**，最大 {scenario['max_calls']} 次（上限 {scenario['ceiling']}）",
            f"- 来源：`{scenario['source']}`；{scenario['note']}",
        ]
    else:
        lines.append("- 受控场景口径：N/A（未找到 gap_fill 结果）")
    lines += [
        "",
        "| 模式 | trial | 中位检索次数 | 最大 |",
        "|---|---:|---:|---:|",
    ]
    for mode, value in budget["by_mode"].items():
        lines.append(f"| {mode} | {value['trials']} | {value['median']} | {value['max']} |")
    if budget["violations"]:
        lines += ["", "### 越界 trial", "", "| trial | case | 模式 | 次数 |", "|---|---|---|---:|"]
        for item in budget["violations"]:
            lines.append(
                f"| {item['trial_id'][:8]} | {item['case_id']} | {item['mode']} | "
                f"{item['candidate_api_calls']} |"
            )
    lines += [
        "",
        "## 2. 幻觉阻断（三段证据）",
        "",
        "| 层级 | 指标 | 值 |",
        "|---|---|---:|",
        f"| 引用级 | 池外景点引用 / 总引用 | {hall['oor']['outside']} / {hall['oor']['total']}"
        f"（{_pct(hall['oor']['rate'])}） |",
        f"| trial 级 | 首版含 `unknown_poi` 的 trial | {hall['first_draft_unknown_poi']} |",
        f"| 拦截级 | 首版有、交付已修掉的 trial | **{hall['blocked_by_reviewer']}** |",
        "",
        "| 模式 | trial | `unknown_poi` L0 |",
        "|---|---:|---:|",
    ]
    for mode, value in hall["unknown_poi_by_mode"].items():
        lines.append(f"| {mode} | {value['trials']} | {value['unknown_poi']} |")
    lines += [
        "",
        "## 3. 点名必去覆盖",
        "",
        f"- 全量：{must['evaluated']} 条参与，通过 {must['passed']} 条（{_pct(must['rate'])}）",
        "",
        "| 数据桶 | 参与 | 通过 | 覆盖率 | 未通过 trial |",
        "|---|---:|---:|---:|---|",
    ]
    for bucket, slot in (must.get("by_bucket") or {}).items():
        failed = slot.get("failed_cases") or []
        lines.append(
            f"| {bucket} | {slot['evaluated']} | {slot['passed']} | {_pct(slot['rate'])} | "
            f"{('、'.join(failed[:3]) + ('…' if len(failed) > 3 else '')) or '—'} |"
        )
    safety = summary.get("safety") or {}
    lines += [
        "",
        "### v3 安全样本（单列，不进可行集分母）",
        "",
        f"- trial：{safety.get('trials', 0)}；结果分布：{safety.get('outcomes') or '—'}",
        f"- `must_visit` 参与 {safety.get('must_visit_evaluated', 0)} 条，通过 "
        f"{safety.get('must_visit_passed', 0)} 条",
        f"- {safety.get('note')}",
        "",
        "## 4. 去重与缓存",
        "",
        f"- 可复核：**{dedupe['available']}**",
        f"- {dedupe['reason']}",
        "",
        "## 5. 读法",
        "",
        "- “从源头阻断幻觉”的可复核表述是：池外引用率 + 首版 unknown_poi 被 Reviewer 修掉的数量，"
        "不能只写池外引用率。",
        "- 预算合规率 100% 只说明没超上限，不说明检索是否高效。",
        "- 去重与缓存命中本轮为 N/A，不得用 0 代替。",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="有界 ReAct 合规与幻觉阻断（离线聚合）")
    parser.add_argument("--dirs", type=Path, nargs="*", default=list(DEFAULT_DIRS))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--safety-dirs", type=Path, nargs="*", default=list(DEFAULT_SAFETY_DIRS),
                        help="v3 安全样本目录，单列统计，不进可行集分母")
    args = parser.parse_args(argv)

    summary = build_summary(args.dirs, args.safety_dirs)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "REPORT.md").write_text(render_markdown(summary), encoding="utf-8")
    budget = summary["budget"]
    hall = summary["hallucination"]
    compliance = (
        f"{budget['compliant']}/{budget['trials']}" if budget.get("exercised") else "N/A(未触及)"
    )
    print(f"records={summary['records']} compliance={compliance} "
          f"oor={hall['oor']['outside']}/{hall['oor']['total']} "
          f"blocked={hall['blocked_by_reviewer']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
