"""trial 记录的结果分类与指标聚合（零成本，不调用任何外部服务）。

口径见 ``docs/EVAL_SPEC_V1.md``：
- ``actual_outcome`` 是执行事实；
- ``benchmark_label`` 是评价标签，不写入生产状态；
- 质量指标使用有效试验分母（invalid_trial 单独统计）。
"""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any

SUCCESS_FAMILY = {"SUCCESS", "SUCCESS_WITH_WARNINGS"}
INFEASIBLE_CODES = {
    "candidate_pool_preference_conflict",
    "missing_must_visit",
    "physical_time_deadlock",
}


def _codes(items: Any) -> set[str]:
    return {
        str(item.get("code"))
        for item in (items or [])
        if isinstance(item, dict) and item.get("code")
    }


def classify_trial(record: dict[str, Any], benchmark: dict[str, Any] | None = None) -> dict[str, Any]:
    """计算 actual_outcome / benchmark_label / expected_outcome_match。"""
    benchmark = benchmark or {}
    allowed = list(benchmark.get("allowed_outcomes") or [])
    status = str(record.get("status") or "")
    generated = bool(record.get("plan_generated"))
    l0 = record.get("l0_codes") or []
    failure_codes = set(record.get("failure_codes") or [])
    error_kind = str(record.get("error_kind") or "")

    if not generated:
        if error_kind == "infra":
            actual = "INFRA_FAILURE"
        elif error_kind == "timeout":
            actual = "TIMEOUT"
        elif error_kind == "clarify" or status == "CLARIFY":
            actual = "CLARIFY"
        elif failure_codes & INFEASIBLE_CODES:
            actual = "CORRECT_REJECT"
        else:
            actual = "FAILED"
    elif l0:
        actual = "HARD_FAIL"
    elif status == "SUCCESS":
        actual = "SUCCESS"
    elif status == "SUCCESS_WITH_WARNINGS":
        actual = "SUCCESS_WITH_WARNINGS"
    elif status == "PARTIAL_SUCCESS":
        actual = "PARTIAL"
    else:
        actual = "FAILED"

    if record.get("invalid_trial"):
        label = "INVALID"
    elif actual in allowed:
        label = "MATCH"
    elif set(allowed) <= {"PARTIAL", "CORRECT_REJECT"} and actual == "SUCCESS":
        label = "WRONG_ACCEPT"
    elif actual == "HARD_FAIL":
        label = "HARD_FAIL"
    elif set(allowed) <= SUCCESS_FAMILY and actual in {"FAILED", "CORRECT_REJECT", "CLARIFY"}:
        label = "OVER_REJECT"
    else:
        label = "MISMATCH"

    return {
        **record,
        "actual_outcome": actual,
        "benchmark_label": label,
        "expected_outcome_match": label == "MATCH",
    }


def _rate(num: int, den: int) -> dict[str, Any]:
    return {"num": num, "den": den, "value": round(num / den, 4) if den else None}


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 3) if values else None


def _latency_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "median": None, "min": None, "max": None, "p95": None}
    ordered = sorted(values)
    p95 = ordered[max(0, int(round(0.95 * (len(ordered) - 1))))] if len(ordered) >= 20 else None
    return {
        "n": len(ordered),
        "median": _median(values),
        "min": round(ordered[0], 3),
        "max": round(ordered[-1], 3),
        "p95": round(p95, 3) if p95 is not None else None,
        "p95_note": None if p95 is not None else "样本不足（n<20）",
    }


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    """按冻结口径聚合一组已分类的 trial 记录。"""
    total = len(records)
    invalid = [r for r in records if r.get("invalid_trial")]
    effective = [r for r in records if not r.get("invalid_trial")]
    generated = [r for r in effective if r.get("plan_generated")]

    fdr = _rate(sum(1 for r in effective if r["actual_outcome"] in SUCCESS_FAMILY), len(effective))
    pdr = _rate(sum(1 for r in effective if r["actual_outcome"] == "PARTIAL"), len(effective))
    omr = _rate(sum(1 for r in effective if r["benchmark_label"] == "MATCH"), len(effective))
    hpr = _rate(sum(1 for r in generated if r.get("hard_pass")), len(generated))
    fpr = _rate(
        sum(1 for r in generated if not (r.get("first_draft_l0") or [])),
        len(generated),
    )

    outside = sum(int((r.get("oor") or {}).get("outside", 0)) for r in generated)
    references = sum(int((r.get("oor") or {}).get("total", 0)) for r in generated)

    must_visit_trials = [r for r in effective if r.get("must_visit_expected")]
    msr = _rate(sum(1 for r in must_visit_trials if r.get("must_visit_ok")), len(must_visit_trials))

    rework = [
        r for r in effective
        if (r.get("first_draft_l0") or []) and int(r.get("planning_revision_rounds") or 0) >= 1
    ]
    rrr = _rate(sum(1 for r in rework if not (r.get("l0_codes") or [])), len(rework))

    rounds = [int(r.get("planning_revision_rounds") or 0) for r in effective]
    scores = [float(r.get("soft_score") or 0.0) for r in generated if r.get("soft_score") is not None]
    latencies = [float(r.get("latency_s") or 0.0) for r in effective]
    input_tokens = [int(r.get("input_tokens_est") or 0) for r in effective]
    output_tokens = [int(r.get("output_tokens_est") or 0) for r in effective]
    calls = [int(r.get("llm_calls") or 0) for r in effective]

    def _bucket(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "trials": 1,
            "match": int(record["benchmark_label"] == "MATCH"),
            "hard_pass": int(bool(record.get("hard_pass"))),
            "generated": int(bool(record.get("plan_generated"))),
            "latency": [float(record.get("latency_s") or 0.0)],
            "soft": [float(record["soft_score"])] if record.get("soft_score") is not None else [],
            "input_tokens": [int(record.get("input_tokens_est") or 0)],
            "output_tokens": [int(record.get("output_tokens_est") or 0)],
            "llm_calls": [int(record.get("llm_calls") or 0)],
        }

    def _merge(bucket: dict[str, Any], record: dict[str, Any]) -> None:
        bucket["trials"] += 1
        bucket["match"] += int(record["benchmark_label"] == "MATCH")
        bucket["hard_pass"] += int(bool(record.get("hard_pass")))
        bucket["generated"] += int(bool(record.get("plan_generated")))
        bucket["latency"].append(float(record.get("latency_s") or 0.0))
        if record.get("soft_score") is not None:
            bucket["soft"].append(float(record["soft_score"]))
        bucket["input_tokens"].append(int(record.get("input_tokens_est") or 0))
        bucket["output_tokens"].append(int(record.get("output_tokens_est") or 0))
        bucket["llm_calls"].append(int(record.get("llm_calls") or 0))

    def _finalize(bucket: dict[str, Any]) -> dict[str, Any]:
        return {
            "trials": bucket["trials"],
            "generated": bucket["generated"],
            "hard_pass": bucket["hard_pass"],
            "match": bucket["match"],
            "hpr": _rate(bucket["hard_pass"], bucket["generated"]),
            "omr": _rate(bucket["match"], bucket["trials"]),
            "median_latency_s": _median(bucket["latency"]),
            "soft_score_mean": round(sum(bucket["soft"]) / len(bucket["soft"]), 2) if bucket["soft"] else None,
            "input_tokens_est_mean": round(sum(bucket["input_tokens"]) / len(bucket["input_tokens"]), 1),
            "output_tokens_est_mean": round(sum(bucket["output_tokens"]) / len(bucket["output_tokens"]), 1),
            "total_tokens_est_mean": round(
                (sum(bucket["input_tokens"]) + sum(bucket["output_tokens"])) / len(bucket["input_tokens"]), 1
            ),
            "llm_calls_mean": round(sum(bucket["llm_calls"]) / len(bucket["llm_calls"]), 2),
        }

    node_latency: dict[str, list[float]] = {}
    for record in effective:
        for name, value in (record.get("node_latency_ms") or {}).items():
            node_latency.setdefault(str(name), []).append(float(value))
    node_stats = {
        name: {"n": len(values), "median": _median(values), "max": round(max(values), 1)}
        for name, values in node_latency.items()
    }

    candidate_calls = [int(r.get("candidate_api_calls") or 0) for r in effective]
    route_legs = [int(r.get("route_leg_count") or 0) for r in effective]

    bases = {
        "delivered_plan" if "delivered_plan" in record else "plan_generated"
        for record in records
    }
    denominator_basis = bases.pop() if len(bases) == 1 else "mixed"

    def _safety() -> dict[str, Any] | None:
        infeasible = [r for r in effective if r.get("expected_feasible") is False]
        feasible = [r for r in effective if r.get("expected_feasible") is True]
        if not infeasible and not feasible:
            return None
        outcomes = Counter(str(r.get("actual_outcome")) for r in infeasible)
        correct_reject = outcomes.get("CORRECT_REJECT", 0)
        partial = outcomes.get("PARTIAL", 0)
        hard_fail = outcomes.get("HARD_FAIL", 0)
        wrong_accept = sum(
            1 for r in infeasible if r.get("benchmark_label") == "WRONG_ACCEPT"
        )
        over_reject = sum(1 for r in feasible if r.get("benchmark_label") == "OVER_REJECT")
        by_code: Counter[str] = Counter()
        for record in infeasible:
            codes = set(record.get("failure_codes") or []) | set(record.get("l0_codes") or []) | set(record.get("l1_codes") or [])
            for code in codes:
                if code:
                    by_code[str(code)] += 1
        unsafe = wrong_accept + hard_fail
        return {
            "infeasible_trials": len(infeasible),
            "correct_reject": correct_reject,
            "partial": partial,
            "hard_fail": hard_fail,
            "wrong_accept": wrong_accept,
            "srr": _rate(correct_reject, len(infeasible)),
            "war": _rate(wrong_accept, len(infeasible)),
            "unsafe_delivery_rate": _rate(unsafe, len(infeasible)),
            "partial_delivery_rate": _rate(partial, len(infeasible)),
            "non_reject_delivery_rate": _rate(
                partial + hard_fail + wrong_accept, len(infeasible)
            ),
            "feasible_trials": len(feasible),
            "over_reject": over_reject,
            "orr": _rate(over_reject, len(feasible)),
            "infeasible_outcomes": dict(outcomes),
            "by_code": dict(sorted(by_code.items())),
        }

    def _expectations() -> dict[str, Any] | None:
        evaluated = [r for r in effective if r.get("expectations_evaluated")]
        if not evaluated:
            return None
        by_rule: Counter[str] = Counter()
        trials_with = 0
        violations = 0
        for record in evaluated:
            items = list(record.get("expectation_violations") or [])
            if items:
                trials_with += 1
            violations += len(items)
            for item in items:
                by_rule[str(item.get("rule") or "unknown")] += 1
        return {
            "evaluated_trials": len(evaluated),
            "violations": violations,
            "trials_with_violations": trials_with,
            "by_rule": dict(sorted(by_rule.items())),
        }

    def _judge() -> dict[str, Any] | None:
        scored = [
            r for r in effective
            if isinstance(r.get("judge"), dict)
            and not r["judge"].get("skipped")
            and r["judge"].get("overall_mean") is not None
        ]
        if not scored:
            return None
        dims = [
            r["judge"].get("dimension_mean") or {}
            for r in scored
        ]
        dimension_mean = {
            name: round(sum(float(item.get(name) or 0) for item in dims) / len(dims), 3)
            for name in sorted({key for item in dims for key in item})
        }
        kappas = [
            r["judge"]["agreement"]["quadratic_weighted_kappa"]
            for r in scored
            if isinstance(r["judge"].get("agreement"), dict)
            and r["judge"]["agreement"].get("quadratic_weighted_kappa") is not None
        ]
        by_mode: dict[str, list[float]] = {}
        by_case: dict[str, list[float]] = {}
        for record in scored:
            value = float(record["judge"]["overall_mean"])
            by_mode.setdefault(str(record.get("mode_requested")), []).append(value)
            by_case.setdefault(str(record.get("case_id")), []).append(value)
        return {
            "scored_trials": len(scored),
            "coverage": _rate(len(scored), len(effective)),
            "overall_mean": round(
                sum(float(r["judge"]["overall_mean"]) for r in scored) / len(scored), 2
            ),
            "dimension_mean": dimension_mean,
            "kappa_mean": round(sum(kappas) / len(kappas), 4) if kappas else None,
            "low_score_trials": sum(
                1 for r in scored if float(r["judge"].get("overall_mean") or 0) < 60.0
            ),
            "error_trials": sum(1 for r in scored if r["judge"].get("error")),
            "by_mode": {key: round(sum(values) / len(values), 2) for key, values in sorted(by_mode.items())},
            "by_case": {key: round(sum(values) / len(values), 2) for key, values in sorted(by_case.items())},
        }

    groups: dict[str, list[dict[str, Any]]] = {}
    for record in effective:
        key = f"{record.get('case_id')}__{record.get('mode_requested')}"
        groups.setdefault(key, []).append(record)
    pass_at_k_by_case_mode: dict[str, dict[str, Any]] = {}
    for key, items in groups.items():
        if len(items) < 2:
            continue
        matches = sum(1 for item in items if item.get("benchmark_label") == "MATCH")
        pass_at_k_by_case_mode[key] = {
            "k": len(items),
            "match": matches,
            "pass_at_k": matches > 0,
            "pass_pow_k": matches == len(items),
            "hpr_pass_at_k": any(bool(item.get("hard_pass")) for item in items),
        }

    by_case: dict[str, dict[str, Any]] = {}
    by_mode: dict[str, dict[str, Any]] = {}
    for record in effective:
        case_id = str(record.get("case_id") or "")
        mode = str(record.get("mode_requested") or "")
        for store, key in ((by_case, case_id), (by_mode, mode)):
            if key not in store:
                store[key] = _bucket(record)
            else:
                _merge(store[key], record)

    cases_with_k = {
        case_id: bucket for case_id, bucket in by_case.items() if bucket["trials"] >= 2
    }

    return {
        "total_trials": total,
        "invalid_trials": len(invalid),
        "invalid_rate": _rate(len(invalid), total),
        "effective_trials": len(effective),
        "denominator_basis": denominator_basis,
        "outcome_counts": {
            value: sum(1 for r in effective if r["actual_outcome"] == value)
            for value in sorted({r["actual_outcome"] for r in effective})
        },
        "label_counts": {
            value: sum(1 for r in effective if r["benchmark_label"] == value)
            for value in sorted({r["benchmark_label"] for r in effective})
        },
        "fdr": fdr,
        "pdr": pdr,
        "omr": omr,
        "hpr": hpr,
        "fpr": fpr,
        "oor": {"outside": outside, "references": references, "value": round(outside / references, 4) if references else None},
        "msr": msr,
        "mar": {"value": None, "note": "N/A：v1 未启用 must_avoid"},
        "rrr": rrr,
        "rounds": {
            "mean": round(sum(rounds) / len(rounds), 3) if rounds else None,
            "snapshot_count_mean": round(
                sum(int(r.get("snapshot_count") or 0) for r in effective) / len(effective), 3
            ) if effective else None,
        },
        "soft_score": {"mean": round(sum(scores) / len(scores), 2) if scores else None, "n": len(scores)},
        "latency_s": _latency_stats(latencies),
        "node_latency_ms": node_stats,
        "tool_calls": {
            "candidate_api_calls_mean": round(sum(candidate_calls) / len(candidate_calls), 2) if candidate_calls else None,
            "route_leg_count_mean": round(sum(route_legs) / len(route_legs), 2) if route_legs else None,
        },
        "usage": {
            "input_tokens_est_mean": round(sum(input_tokens) / len(input_tokens), 1) if input_tokens else None,
            "output_tokens_est_mean": round(sum(output_tokens) / len(output_tokens), 1) if output_tokens else None,
            "llm_calls_mean": round(sum(calls) / len(calls), 2) if calls else None,
        },
        "by_case": {key: _finalize(value) for key, value in by_case.items()},
        "by_mode": {key: _finalize(value) for key, value in by_mode.items()},
        "safety": _safety(),
        "expectations": _expectations(),
        "judge": _judge(),
        "pass_at_k_by_case_mode": pass_at_k_by_case_mode,
        "pass_at_k": {
            case_id: {
                "k": bucket["trials"],
                "outcome_pass_at_k": bucket["match"] > 0,
                "outcome_pass_pow_k": bucket["match"] == bucket["trials"],
            }
            for case_id, bucket in cases_with_k.items()
        },
        "outcome_pass_at_k_rate": _rate(
            sum(1 for b in cases_with_k.values() if b["match"] > 0), len(cases_with_k)
        ),
        "outcome_pass_pow_k_rate": _rate(
            sum(1 for b in cases_with_k.values() if b["match"] == b["trials"]), len(cases_with_k)
        ),
    }


def _pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


def _extra_sections(summary: dict[str, Any]) -> list[str]:
    """v3 新增表：仅在数据存在时渲染，保持 v1/v2 报告可复现。"""
    lines: list[str] = []
    safety = summary.get("safety")
    if safety:
        lines += [
            "",
            "## 安全（仅 expected_feasible 标签）",
            "",
            "| 指标 | 分子 / 分母 | 值 |",
            "|---|---|---|",
            f"| 不可行 trial 数 | - | {safety['infeasible_trials']} |",
            f"| 正确拒绝率 SRR | {safety['correct_reject']} / {safety['infeasible_trials']} | "
            f"{_pct(safety['srr']['value'])} |",
            f"| 误接受率 WAR | {safety['wrong_accept']} / {safety['infeasible_trials']} | "
            f"{_pct(safety['war']['value'])} |",
            f"| 不安全交付率 | {safety['wrong_accept'] + safety['hard_fail']} / "
            f"{safety['infeasible_trials']} | {_pct(safety['unsafe_delivery_rate']['value'])} |",
            f"| 部分交付率（不可行样本） | {safety['partial']} / {safety['infeasible_trials']} | "
            f"{_pct(safety['partial_delivery_rate']['value'])} |",
            f"| 非硬拒绝交付率 | {safety['partial'] + safety['hard_fail'] + safety['wrong_accept']} / "
            f"{safety['infeasible_trials']} | {_pct(safety['non_reject_delivery_rate']['value'])} |",
            f"| 过度拒绝率 ORR | {safety['over_reject']} / {safety['feasible_trials']} | "
            f"{_pct(safety['orr']['value'])} |",
            f"- 不可行 trial 结果分布：{safety['infeasible_outcomes']}",
            f"- 不可行 trial 触发码：{safety['by_code']}",
        ]
    expectations = summary.get("expectations")
    if expectations:
        lines += [
            "",
            "## Fixture Expectations",
            "",
            f"- 已评估 trial：{expectations['evaluated_trials']}",
            f"- 违规次数 / 涉及 trial：{expectations['violations']} / "
            f"{expectations['trials_with_violations']}",
            f"- 按规则：{expectations['by_rule']}",
        ]
    judge = summary.get("judge")
    if judge:
        lines += [
            "",
            "## 语义质量 Judge",
            "",
            f"- 已评分 trial：{judge['scored_trials']} / 有效 trial "
            f"（覆盖 {_pct(judge['coverage']['value'])}）",
            f"- 总分均值：{judge['overall_mean']}（0-100）",
            f"- 双评 kappa 均值：{judge['kappa_mean']}",
            f"- 低分 trial / 错误 trial：{judge['low_score_trials']} / {judge['error_trials']}",
            f"- 按模式：{judge['by_mode']}",
            f"- 维度均值：{judge['dimension_mean']}",
        ]
    passk = summary.get("pass_at_k_by_case_mode") or {}
    if passk:
        lines += [
            "",
            "## Pass@K（按 case × mode）",
            "",
            "| case__mode | k | match | pass@k | pass^k | HPR pass@k |",
            "|---|---|---|---|---|---|",
            *[
                f"| {key} | {value['k']} | {value['match']} | {value['pass_at_k']} | "
                f"{value['pass_pow_k']} | {value['hpr_pass_at_k']} |"
                for key, value in sorted(passk.items())
            ],
        ]
    return lines


def render_markdown(summary: dict[str, Any], title: str = "Travelmind 评测报告") -> str:
    """把聚合结果渲染成便于粘贴的 Markdown。"""
    def line(name: str, item: dict[str, Any]) -> str:
        value = item.get("value")
        shown = "N/A" if value is None else f"{value * 100:.1f}%"
        return f"| {name} | {item.get('num')} / {item.get('den')} | {shown} |"

    latency = summary["latency_s"]
    p95 = "N/A" if latency["p95"] is None else f"{latency['p95']}s"
    return "\n".join([
        f"# {title}",
        "",
        f"- 全部 trial：{summary['total_trials']}；有效：{summary['effective_trials']}；"
        f"invalid：{summary['invalid_trials']}",
        f"- 分母口径：{summary.get('denominator_basis', 'plan_generated')}",
        "",
        "| 指标 | 分子 / 分母 | 值 |",
        "|---|---|---|",
        line("完整交付率 FDR", summary["fdr"]),
        line("部分交付率 PDR", summary["pdr"]),
        line("预期结果匹配率 OMR", summary["omr"]),
        line("硬约束通过率 HPR", summary["hpr"]),
        line("首轮通过率 FPR", summary["fpr"]),
        line("必去满足率 MSR", summary["msr"]),
        line("返工修复率 RRR", summary["rrr"]),
        "",
        f"- 池外实体率：{summary['oor']['outside']} / {summary['oor']['references']} 个引用",
        f"- 平均规划修订轮数：{summary['rounds']['mean']}；平均快照数：{summary['rounds']['snapshot_count_mean']}",
        f"- 软质量分均值：{summary['soft_score']['mean']}（n={summary['soft_score']['n']}）",
        f"- 端到端耗时 median/min/max/P95：{latency['median']}/{latency['min']}/{latency['max']}/{p95}"
        f"（{latency.get('p95_note') or 'n=' + str(latency['n'])}）",
        f"- 结果分布：{summary['outcome_counts']}",
        f"- 评价标签分布：{summary['label_counts']}",
        *_extra_sections(summary),
        "",
        "## 按模式对照（A/B/C）",
        "",
        "| 模式 | trial | 生成规划 | 硬约束通过率 | 预期匹配率 | 软质量均分 | 中位耗时 | 输入 Token | 输出 Token | 总 Token | 平均 LLM 调用 |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
        *[
            "| {mode} | {trials} | {generated} | {hpr} | {omr} | {soft} | {latency}s | "
            "{tin} | {tout} | {ttotal} | {calls} |".format(
                mode=mode,
                trials=value["trials"],
                generated=value["generated"],
                hpr=_pct(value["hpr"]["value"]),
                omr=_pct(value["omr"]["value"]),
                soft=value["soft_score_mean"],
                latency=value["median_latency_s"],
                tin=value["input_tokens_est_mean"],
                tout=value["output_tokens_est_mean"],
                ttotal=value["total_tokens_est_mean"],
                calls=value["llm_calls_mean"],
            )
            for mode, value in summary["by_mode"].items()
        ],
        "",
        "## 按案例",
        "",
        "| 案例 | trial | 生成规划 | 硬约束通过率 | 预期匹配率 | 软质量均分 |",
        "|---|---|---|---|---|---|",
        *[
            "| {case} | {trials} | {generated} | {hpr} | {omr} | {soft} |".format(
                case=case_id,
                trials=value["trials"],
                generated=value["generated"],
                hpr=_pct(value["hpr"]["value"]),
                omr=_pct(value["omr"]["value"]),
                soft=value["soft_score_mean"],
            )
            for case_id, value in summary["by_case"].items()
        ],
        "",
        "## 节点耗时（中位 / 最大，毫秒）",
        "",
        "| 节点 | n | 中位 | 最大 |",
        "|---|---|---|---|",
        *[
            f"| {name} | {value['n']} | {value['median']} | {value['max']} |"
            for name, value in sorted(
                summary.get("node_latency_ms", {}).items(),
                key=lambda item: -(item[1]["median"] or 0),
            )[:12]
        ],
        "",
        "## 工具调用（代理指标，不相加）",
        "",
        f"- 候选补查 API 调用均值：{summary.get('tool_calls', {}).get('candidate_api_calls_mean')}"
        "（fixture 模式跳过候选补查，0 属预期）",
        f"- 路距 leg 数均值：{summary.get('tool_calls', {}).get('route_leg_count_mean')}"
        "（fixture 模式不含 route_distance_check，0 属预期）",
        "",
        "> invalid_trial 不计入质量分母；外部 API 故障、超时、clarify 属于有效试验。",
    ])
