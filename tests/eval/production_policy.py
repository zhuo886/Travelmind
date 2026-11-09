"""四臂策略回放：把已有 trial 重新过一遍生产 risk gate。

本轮不跑真实四臂，而是用**已冻结的草稿与结果**做回放：

- A 臂：`planner_only` 记录的真实结果；
- B 臂：`planner_reviewer` 记录的真实结果；
- C 臂：`planner_reviewer_time_check` 记录的真实结果；
- D 臂（生产路由）：把 A 臂的首版路线喂给真实的 ``route_risk_gate_node``，
  被跳过则沿用 A 的结果，未跳过则沿用同 case 的 C 结果。

D 臂是**回放近似**：审核节点看到的状态与真实运行时不完全相同，因此只用于
回答"生产门控在这批草稿上会怎么分流"，不能当成新一轮实测。

增益归因用 ``snapshot_trace``：返工时快照是否带 L0/L1，用于区分
"规则驱动的返工"与"仅语义提醒的返工"。

用法::

    python -m tests.eval.production_policy --dirs evaluation/trials/run-20261107-v2 \
        evaluation/trials/run-20261107-negative --out evaluation/benchmarks/policy
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from app.planning.nodes import route_risk_gate_node
from app.planning.quality import NON_DELIVERABLE_L1_CODES
from app.planning.schemas import TravelPlanState

from tests.eval import harness
from tests.eval.metrics import INFEASIBLE_CODES

DEFAULT_DIRS = (
    Path("evaluation/trials/run-20261107-v2"),
    Path("evaluation/trials/run-20261107-negative"),
)
DEFAULT_OUT = Path("evaluation/benchmarks/policy")
CHECKPOINT_RAW = Path("evaluation/checkpoint_benchmark/raw")
DRAFT_LIMIT = 15  # 从 checkpoint 配对里取的草稿数
ARMS = ("A_planner_only", "B_reviewer", "C_reviewer_time_check", "D_risk_gate")
MODE_TO_ARM = {
    "planner_only": "A_planner_only",
    "planner_reviewer": "B_reviewer",
    "planner_reviewer_time_check": "C_reviewer_time_check",
}
TERMINAL_L0 = {"candidate_pool_preference_conflict"}


# ─── 数据装载 ──────────────────────────────────────────────

def load_case_index(dirs: list[Path]) -> dict[str, dict[str, dict[str, Any]]]:
    """case_id -> {mode: record}，同 mode 取第一条未失败的记录。"""
    fixtures = {case["id"]: case for case in harness.load_cases(version="v2")}
    index: dict[str, dict[str, dict[str, Any]]] = {}
    for directory in dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("trial_*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            case_id = str(record.get("case_id"))
            if case_id not in fixtures or record.get("error"):
                continue
            slot = index.setdefault(case_id, {})
            mode = str(record.get("mode_requested"))
            slot.setdefault(mode, record)
    return {case_id: modes for case_id, modes in index.items()}


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


def build_draft_state(case: dict[str, Any], record: dict[str, Any]) -> TravelPlanState:
    state = harness.build_state_from_fixture(case)
    route = _route_from_record(record)
    return state.model_copy(update={"route": route, "route_history": []})


def build_state_from_route(case: dict[str, Any], route: list[dict[str, Any]]) -> TravelPlanState:
    """用已冻结的路线直接构造门控输入（checkpoint 草稿走这条路）。"""
    state = harness.build_state_from_fixture(case)
    return state.model_copy(update={"route": route, "route_history": []})


# ─── 草稿装载（30 份：15 条 trial + 15 份 checkpoint 路线）───────

def _fixture_index() -> dict[str, dict[str, Any]]:
    return {case["id"]: case for case in harness.load_cases(version="v2")}


def load_trial_drafts(dirs: list[Path]) -> list[dict[str, Any]]:
    fixtures = _fixture_index()
    drafts: list[dict[str, Any]] = []
    for directory in dirs:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("trial_*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            case = fixtures.get(str(record.get("case_id")))
            if not case or record.get("error") or not record.get("route_by_day"):
                continue
            drafts.append({
                "draft_id": f"{record.get('case_id')}::{record.get('mode_requested')}",
                "case_id": str(record.get("case_id")),
                "case": case,
                "source": "trial",
                "record": record,
                "route": _route_from_record(record),
            })
    return drafts


def load_checkpoint_drafts(
    limit: int = DRAFT_LIMIT, raw_dir: Path = CHECKPOINT_RAW
) -> list[dict[str, Any]]:
    """从 E2 配对里取 A 臂路线作为修改草稿。"""
    fixtures = _fixture_index()
    drafts: list[dict[str, Any]] = []
    if not raw_dir.exists():
        return drafts
    for path in sorted(raw_dir.glob("pair_*.json"))[:limit]:
        pair = json.loads(path.read_text(encoding="utf-8"))
        case = fixtures.get(str(pair.get("case_id")))
        arm_a = pair.get("A") or {}
        if not case or not arm_a.get("route"):
            continue
        drafts.append({
            "draft_id": f"checkpoint::{path.stem}",
            "case_id": str(pair.get("case_id")),
            "case": case,
            "source": "checkpoint",
            # checkpoint 记录没有 l0_codes，缺陷未知，统计时单列
            "record": arm_a,
            "route": arm_a["route"],
        })
    return drafts


def load_all_drafts(
    dirs: list[Path], checkpoint_limit: int = DRAFT_LIMIT
) -> list[dict[str, Any]]:
    return load_trial_drafts(dirs) + load_checkpoint_drafts(checkpoint_limit)


def drafts_report(drafts: list[dict[str, Any]]) -> dict[str, Any]:
    """草稿级门控分流：不依赖同 case 的 B/C 记录，因此可覆盖 30 份。"""
    rows: list[dict[str, Any]] = []
    for draft in drafts:
        state = build_state_from_route(draft["case"], draft["route"])
        verdict = gate_verdict(state)
        record = draft["record"] or {}
        known = "l0_codes" in record
        rows.append({
            "draft_id": draft["draft_id"],
            "case_id": draft["case_id"],
            "source": draft["source"],
            "skipped": verdict["review_skipped"],
            "review_required": verdict["review_required"],
            "flags": verdict["flags"],
            "l0_known": known,
            "l0_codes": list(record.get("l0_codes") or []) if known else None,
            "l1_codes": list(record.get("l1_codes") or []) if known else None,
        })
    skipped = [row for row in rows if row["skipped"]]
    known = [row for row in rows if row["l0_known"]]
    false_skip = [
        row for row in skipped
        if row["l0_known"] and (
            row["l0_codes"] or set(row["l1_codes"] or []) & NON_DELIVERABLE_L1_CODES
        )
    ]
    by_source: dict[str, dict[str, Any]] = {}
    for source in sorted({row["source"] for row in rows}):
        subset = [row for row in rows if row["source"] == source]
        by_source[source] = {
            "drafts": len(subset),
            "skipped": sum(1 for row in subset if row["skipped"]),
            "defect_known": sum(1 for row in subset if row["l0_known"]),
        }
    return {
        "drafts": len(rows),
        "by_source": by_source,
        "skipped": len(skipped),
        "skip_rate": round(len(skipped) / len(rows), 4) if rows else None,
        "defect_known": len(known),
        "false_skip": len(false_skip),
        "false_skip_rate": round(len(false_skip) / len(skipped), 4) if skipped else None,
        "false_skip_note": "checkpoint 草稿无 l0_codes，误跳过只能在 defect_known 子集上计算",
        "rows": rows,
    }


# ─── 判定 ──────────────────────────────────────────────────

def gate_verdict(state: TravelPlanState, *, semantic_review: bool = True) -> dict[str, Any]:
    update = route_risk_gate_node(state, semantic_review=semantic_review)
    return {
        "review_required": bool(update.get("review_required")),
        "time_check_required": bool(update.get("time_check_required")),
        "review_skipped": bool(update.get("review_skipped")),
        "flags": list(update.get("route_risk_flags") or []),
    }


def _expected_feasible(record: dict[str, Any]) -> bool:
    return record.get("expected_feasible") is not False


def esr_success(record: dict[str, Any]) -> bool | None:
    """ESR：可行案例要求可交付且无不可交付缺陷；不可行案例只认正确拒绝。"""
    if not _expected_feasible(record):
        return str(record.get("actual_outcome")) == "CORRECT_REJECT"
    if not record.get("plan_generated"):
        return False
    if record.get("l0_codes"):
        return False
    if set(record.get("l1_codes") or []) & NON_DELIVERABLE_L1_CODES:
        return False
    return str(record.get("benchmark_label")) == "MATCH"


def _tokens(record: dict[str, Any]) -> int:
    return int(record.get("input_tokens_est") or 0) + int(record.get("output_tokens_est") or 0)


def summarise_arm(name: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    valid = [record for record in records if record is not None]
    if not valid:
        return {"arm": name, "trials": 0, "esr": None, "omr": None, "hpr": None, "pdr": None}
    esr_vals = [esr_success(record) for record in valid]
    generated = [record for record in valid if record.get("plan_generated")]
    return {
        "arm": name,
        "trials": len(valid),
        "esr": {
            "num": sum(1 for value in esr_vals if value),
            "den": len(valid),
            "value": round(sum(1 for value in esr_vals if value) / len(valid), 4),
        },
        "omr": {
            "num": sum(1 for record in valid if record.get("benchmark_label") == "MATCH"),
            "den": len(valid),
            "value": round(
                sum(1 for record in valid if record.get("benchmark_label") == "MATCH") / len(valid), 4
            ),
        },
        "hpr": {
            "num": sum(1 for record in generated if not record.get("l0_codes")),
            "den": len(generated),
            "value": round(
                sum(1 for record in generated if not record.get("l0_codes")) / len(generated), 4
            ) if generated else None,
        },
        "pdr": {
            "num": sum(1 for record in generated if record.get("status") == "PARTIAL_SUCCESS"),
            "den": len(generated),
            "value": round(
                sum(1 for record in generated if record.get("status") == "PARTIAL_SUCCESS")
                / len(generated), 4
            ) if generated else None,
        },
        "tokens_total": sum(_tokens(record) for record in valid),
        "tokens_median": statistics.median([_tokens(record) for record in valid]),
        "latency_p50_s": statistics.median([float(record.get("latency_s") or 0) for record in valid]),
        "outcomes": dict(Counter(str(record.get("actual_outcome")) for record in valid)),
    }


# ─── 归因 ──────────────────────────────────────────────────

def attribution(case_modes: dict[str, dict[str, dict[str, Any]]]) -> dict[str, Any]:
    """区分“规则驱动返工”与“仅语义提醒返工”。

    不用 ``snapshot_trace.rework_requested``：旧记录里它恒为 False（实测
    shanghai B 返工 3 轮仍全为 False），不足以作归因。改用三件可靠字段：
    ``planning_revision_rounds`` + ``first_draft_l0`` + ``l0_codes``。
    """
    rule_fixed = 0
    rule_ineffective = 0
    semantic_rework = 0
    rework_trials = 0
    details: list[dict[str, Any]] = []
    for case_id, modes in case_modes.items():
        for mode in ("planner_reviewer", "planner_reviewer_time_check"):
            record = modes.get(mode)
            if not record:
                continue
            rounds = int(record.get("planning_revision_rounds") or 0)
            first_l0 = list(record.get("first_draft_l0") or [])
            final_l0 = list(record.get("l0_codes") or [])
            if rounds <= 0:
                continue
            rework_trials += 1
            if first_l0 and not final_l0:
                rule_fixed += 1
                kind = "rule_fixed"
            elif first_l0 and final_l0:
                rule_ineffective += 1
                kind = "rule_ineffective"
            else:
                semantic_rework += 1
                kind = "semantic_only"
            details.append({
                "case_id": case_id,
                "mode": mode,
                "rounds": rounds,
                "first_draft_l0": first_l0,
                "final_l0": final_l0,
                "kind": kind,
            })
    return {
        "rework_trials": rework_trials,
        "rule_fixed": rule_fixed,
        "rule_ineffective": rule_ineffective,
        "semantic_only": semantic_rework,
        "details": details,
        "note": "first_draft_l0 非空→规则触发；首版就无 L0 却发生返工→语义/软约束触发",
    }


# ─── 主流程 ────────────────────────────────────────────────

def replay(dirs: list[Path]) -> dict[str, Any]:
    cases = {case["id"]: case for case in harness.load_cases(version="v2")}
    index = load_case_index(dirs)
    per_arm: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ARMS}
    rows: list[dict[str, Any]] = []

    for case_id, modes in sorted(index.items()):
        case = cases.get(case_id)
        if not case:
            continue
        a_record = modes.get("planner_only")
        b_record = modes.get("planner_reviewer")
        c_record = modes.get("planner_reviewer_time_check")
        if a_record is None:
            continue
        verdict = gate_verdict(build_draft_state(case, a_record))
        d_record = a_record if verdict["review_skipped"] else (c_record or a_record)

        for arm, record in zip(ARMS, (a_record, b_record, c_record, d_record)):
            if record is not None:
                per_arm[arm].append(record)
        rows.append({
            "case_id": case_id,
            "expected_feasible": a_record.get("expected_feasible"),
            "gate": verdict,
            "arm_outcome": {
                "A": a_record.get("actual_outcome"),
                "B": (b_record or {}).get("actual_outcome"),
                "C": (c_record or {}).get("actual_outcome"),
                "D": d_record.get("actual_outcome"),
            },
            "arm_source": {
                "D": "A" if verdict["review_skipped"] else "C",
            },
        })

    summary = {
        "benchmark": "production_policy_replay",
        "kind": "replay",
        "sources": [str(path) for path in dirs],
        "cases": len(rows),
        "arms": {arm: summarise_arm(arm, per_arm[arm]) for arm in ARMS},
        "skip": {
            "cases": len(rows),
            "skipped": sum(1 for row in rows if row["gate"]["review_skipped"]),
            "rate": round(
                sum(1 for row in rows if row["gate"]["review_skipped"]) / len(rows), 4
            ) if rows else None,
        },
        "attribution": attribution(index),
        "drafts": drafts_report(load_all_drafts(dirs)),
        "rows": rows,
    }
    return summary


def _fmt_rate(block: dict[str, Any] | None) -> str:
    if not block or block.get("value") is None:
        return "N/A"
    return f"{block['value'] * 100:.1f}%（{block['num']}/{block['den']}）"


def render_markdown(summary: dict[str, Any]) -> str:
    arms = summary["arms"]
    attr = summary["attribution"]
    lines = [
        "# 四臂策略回放（生产 risk gate）",
        "",
        "> 口径：**回放**。A/B/C 取自已冻结 trial 的真实结果，D 臂把 A 的首版路线"
        "喂给真实 `route_risk_gate_node` 再决定沿用 A 还是 C。",
        f"> 覆盖：{summary['cases']} 个 case（每个 case 需同时存在 A/B/C 记录）",
        "",
        "## 1. 四臂指标",
        "",
        "| 臂 | trial | ESR | OMR | HPR | PDR | Token 合计 | P50 耗时 |",
        "|---|---:|---|---|---|---|---:|---:|",
    ]
    for name in ARMS:
        block = arms[name]
        lines.append(
            f"| {name} | {block['trials']} | {_fmt_rate(block.get('esr'))} | "
            f"{_fmt_rate(block.get('omr'))} | {_fmt_rate(block.get('hpr'))} | "
            f"{_fmt_rate(block.get('pdr'))} | {block.get('tokens_total', 0)} | "
            f"{block.get('latency_p50_s', 0)}s |"
        )
    lines += [
        "",
        "## 2. 草稿级门控分流",
        "",
    ]
    drafts = summary.get("drafts") or {}
    if drafts:
        lines += [
            f"- 草稿总数：{drafts['drafts']}（"
            + "，".join(
                f"{name} {info['drafts']}" for name, info in (drafts.get("by_source") or {}).items()
            )
            + "）",
            f"- 被跳过审核：**{drafts['skipped']} / {drafts['drafts']}"
            f"（{_fmt_rate({'value': drafts['skip_rate'], 'num': drafts['skipped'], 'den': drafts['drafts']})}）**",
            f"- 缺陷已知的草稿：{drafts['defect_known']}（checkpoint 草稿无 `l0_codes`）",
            f"- 误跳过：{drafts['false_skip']}"
            f"（{_fmt_rate({'value': drafts['false_skip_rate'], 'num': drafts['false_skip'], 'den': drafts['skipped']})}；{drafts['false_skip_note']}）",
            "- 跳过意味着沿用 A 臂结果，因此 D 臂收益上限完全取决于门控判断是否正确。",
        ]
    lines += [
        "",
        "## 3. 增益归因：规则驱动 vs 语义驱动",
        "",
        "| 项 | 次数 |",
        "|---|---:|",
        f"| 返工 trial（rounds>0） | {attr['rework_trials']} |",
        f"| 其中：首版有 L0、返工后修好（规则驱动） | **{attr['rule_fixed']}** |",
        f"| 其中：首版有 L0、返工后仍在（规则无效） | {attr['rule_ineffective']} |",
        f"| 其中：首版无 L0、仍发生返工（语义驱动） | {attr['semantic_only']} |",
        "",
        "## 4. 逐 case",
        "",
        "| case | 门控 | 跳过 | A | B | C | D(=?) |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in summary["rows"]:
        gate = "review" if row["gate"]["review_required"] else "time_check" if row["gate"]["time_check_required"] else "skip"
        lines.append(
            f"| {row['case_id']} | {gate} | {row['gate']['review_skipped']} | "
            f"{row['arm_outcome']['A']} | {row['arm_outcome']['B']} | "
            f"{row['arm_outcome']['C']} | {row['arm_outcome']['D']}（{row['arm_source']['D']}） |"
        )
    lines += [
        "",
        "## 5. 读法",
        "",
        "- D 臂不是新一轮实测：审核节点看到的状态来自回放，可能比真实运行更干净或更脏。",
        "- 若 D 与 C 完全相同，说明本批草稿全部需要审核，门控没有产生分流。",
        "- 归因结果若显示返工主要由 L0/L1 触发，则不能把增益归给“语义审核能力”。",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="四臂策略回放（离线）")
    parser.add_argument("--dirs", type=Path, nargs="*", default=list(DEFAULT_DIRS))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    summary = replay(args.dirs)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "REPORT.md").write_text(render_markdown(summary), encoding="utf-8")
    print(f"cases={summary['cases']} skip={summary['skip']['skipped']}/{summary['skip']['cases']}")
    for name in ARMS:
        block = summary["arms"][name]
        print(f"  {name}: trials={block['trials']} ESR={_fmt_rate(block.get('esr'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
