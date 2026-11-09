"""自适应审核跳过的真实收益（离线回放，0 次调用）。

三件事分开算：

1. ``Phase 1`` 现状门控：把每份真实草稿（trial 15 份 + checkpoint 15 份）喂给
   ``route_risk_gate_node``，数出有多少份会被跳过审核；
2. ``Phase 2`` 策略对照：把 ``semantic_review`` 关掉（只看确定性 flag）后的
   跳过情况，用来看"放宽语义升级"能不能产生跳过；
3. ``Phase 3`` 误跳过：被跳过的草稿若本身带 L0 或不可交付 L1，就是一次错误跳过。
   checkpoint 草稿没有 `l0_codes`，只能在"缺陷已知"的子集上算。

Token 节省是**反事实**：对会被跳过的 case，用同 case ``planner_reviewer`` 与
``planner_only`` 记录的差值作为"省下的审核增量"，不叫实测节省。

用法::

    python -m tests.eval.adaptive_review --out evaluation/benchmarks/adaptive
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from app.planning.quality import NON_DELIVERABLE_L1_CODES

from tests.eval.production_policy import (
    build_state_from_route,
    gate_verdict,
    load_all_drafts,
    load_case_index,
)

DEFAULT_DIRS = (
    Path("evaluation/trials/run-20261107-v2"),
    Path("evaluation/trials/run-20261107-negative"),
)
DEFAULT_OUT = Path("evaluation/benchmarks/adaptive")


def _tokens(record: dict[str, Any] | None) -> int:
    if not record:
        return 0
    return int(record.get("input_tokens_est") or 0) + int(record.get("output_tokens_est") or 0)


def _has_defect(row: dict[str, Any]) -> bool:
    if not row.get("l0_known"):
        return False
    return bool(row.get("l0_codes")) or bool(
        set(row.get("l1_codes") or []) & NON_DELIVERABLE_L1_CODES
    )


def _policy(rows: list[dict[str, Any]], semantic_review: bool) -> dict[str, Any]:
    skipped = [row for row in rows if row["verdicts"][semantic_review]["review_skipped"]]
    false_skip = [row for row in skipped if _has_defect(row)]
    defects: Counter[str] = Counter()
    for row in skipped:
        if not row.get("l0_known"):
            continue
        defects.update(row.get("l0_codes") or [])
        defects.update(row.get("l1_codes") or [])
    with_counterpart = [row for row in rows if row.get("review_increment") is not None]
    token_saved = sum(
        int(row["review_increment"]) for row in skipped
        if row.get("review_increment")
    )
    total_tokens = sum(int(row["review_increment"]) for row in with_counterpart)
    return {
        "policy": "semantic_review" if semantic_review else "deterministic_only",
        "drafts": len(rows),
        "skipped": len(skipped),
        "skip_rate": round(len(skipped) / len(rows), 4) if rows else None,
        "false_skip": len(false_skip),
        "false_skip_rate": round(len(false_skip) / len(skipped), 4) if skipped else None,
        # 被跳过草稿里实际带多少缺陷（仅缺陷已知的草稿可数）
        "skipped_defect_total": sum(defects.values()),
        "skipped_defect_counts": dict(sorted(defects.items())),
        "defect_known": sum(1 for row in rows if row.get("l0_known")),
        "counterpart_drafts": len(with_counterpart),
        "token_saved_counterfactual": token_saved,
        "token_saved_share": round(token_saved / total_tokens, 4) if total_tokens else None,
        "skipped_drafts": [row["draft_id"] for row in skipped],
    }


def build_summary(dirs: list[Path], checkpoint_limit: int = 15) -> dict[str, Any]:
    index = load_case_index(dirs)
    drafts = load_all_drafts(dirs, checkpoint_limit)
    rows: list[dict[str, Any]] = []
    for draft in drafts:
        state = build_state_from_route(draft["case"], draft["route"])
        record = draft["record"] or {}
        known = "l0_codes" in record
        modes = index.get(draft["case_id"], {})
        a_record, b_record = modes.get("planner_only"), modes.get("planner_reviewer")
        increment = (
            max(0, _tokens(b_record) - _tokens(a_record)) if a_record and b_record else None
        )
        rows.append({
            "draft_id": draft["draft_id"],
            "case_id": draft["case_id"],
            "source": draft["source"],
            "l0_known": known,
            "l0_codes": list(record.get("l0_codes") or []) if known else None,
            "l1_codes": list(record.get("l1_codes") or []) if known else None,
            "review_increment": increment,
            "verdicts": {
                True: gate_verdict(state, semantic_review=True),
                False: gate_verdict(state, semantic_review=False),
            },
        })
    return {
        "benchmark": "adaptive_review",
        "kind": "offline_replay",
        "sources": [str(path) for path in dirs],
        "drafts": len(rows),
        "by_source": {
            source: sum(1 for row in rows if row["source"] == source)
            for source in sorted({row["source"] for row in rows})
        },
        "current": _policy(rows, True),
        "relaxed": _policy(rows, False),
        "rows": [
            {
                "draft_id": row["draft_id"],
                "case_id": row["case_id"],
                "source": row["source"],
                "current_skipped": row["verdicts"][True]["review_skipped"],
                "relaxed_skipped": row["verdicts"][False]["review_skipped"],
                "current_flags": row["verdicts"][True]["flags"],
                "review_increment": row["review_increment"],
                "l0_known": row["l0_known"],
            }
            for row in rows
        ],
        "note": "Token 节省为反事实估算：跳过时省掉同 case 的审核增量；同 case 多份草稿共用同一增量，故合计为上限",
    }


def _fmt(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:.1f}%"


def render_markdown(summary: dict[str, Any]) -> str:
    current = summary["current"]
    relaxed = summary["relaxed"]
    lines = [
        "# 自适应审核跳过：现状与放宽策略",
        "",
        "> 口径：把真实草稿回放进 `route_risk_gate_node`，0 次模型调用",
        f"> 样本：{summary['drafts']} 份草稿（"
        + "，".join(f"{name} {count}" for name, count in summary["by_source"].items())
        + "）",
        "",
        "## 1. 现状门控（semantic_review=True）",
        "",
        f"- 跳过审核：**{current['skipped']} / {current['drafts']}"
        f"（{_fmt(current['skip_rate'])}）**",
        f"- 误跳过（草稿自带 L0 或不可交付 L1）：{current['false_skip']}"
        f"（{_fmt(current['false_skip_rate'])}；缺陷已知 {current['defect_known']} 份）",
        f"- 反事实 Token 节省：{current['token_saved_counterfactual']}"
        f"（占可比审核 Token {_fmt(current['token_saved_share'])}）",
        "",
        "## 2. 放宽策略（semantic_review=False）",
        "",
        f"- 跳过审核：{relaxed['skipped']} / {relaxed['drafts']}（{_fmt(relaxed['skip_rate'])}）",
        f"- 误跳过：{relaxed['false_skip']}（{_fmt(relaxed['false_skip_rate'])}）",
        f"- 被跳过草稿的缺陷分布：{relaxed['skipped_defect_counts'] or '无'}（仅缺陷已知草稿可数）",
        f"- 反事实 Token 节省：{relaxed['token_saved_counterfactual']}"
        f"（{_fmt(relaxed['token_saved_share'])}）",
        f"- 被跳过的草稿：{relaxed['skipped_drafts'] or '无'}",
        "",
        "## 3. 逐草稿",
        "",
        "| 草稿 | 来源 | 现状跳过 | 放宽跳过 | 审核增量 Token |",
        "|---|---|---|---|---:|",
    ]
    for row in summary["rows"]:
        increment = row["review_increment"]
        lines.append(
            f"| {row['draft_id']} | {row['source']} | {row['current_skipped']} | "
            f"{row['relaxed_skipped']} | {'N/A' if increment is None else increment} |"
        )
    lines += [
        "",
        "## 4. 结论",
        "",
    ]
    if current["skip_rate"] == 0:
        lines += [
            "- 现状跳过率 **0%**：`preference_review` 对任何含偏好的 query 都强制升级审核，"
            "所以“自适应跳过低风险审核节省 Token”在当前实现下不可复现。",
            f"- 放宽 `semantic_review` 后才出现跳过（{relaxed['skipped']}/{relaxed['drafts']}）；"
            f"误跳过 {_fmt(relaxed['false_skip_rate'])}，需先确认可接受才能上线。",
            "- 修复方向：把 `preference_review` 从“无条件强制升级”改为按偏好文本强度分级"
            "（如仅弱偏好走确定性门控），并用本脚本回归。",
        ]
    else:
        lines += [
            f"- 现状跳过率 {_fmt(current['skip_rate'])}，误跳过 {_fmt(current['false_skip_rate'])}；"
            "两者必须同时报，不能只报节省。",
        ]
    lines += [
        "",
        "## 5. 读法",
        "",
        "- 反事实节省不等于账单节省：跳过审核只省掉审核增量，主体规划成本不变。",
        "- 同一 case 的多份草稿共用同一份审核增量，因此合计值对同 case 重复计数，只能当中上限。",
        "- checkpoint 草稿没有 `l0_codes`，因此误跳过率只在 train 子集上有意义。",
        "- 放宽策略不是产品默认；若要上线需另开一轮改门控并回归 HPR/ESR。",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="自适应审核跳过（离线回放）")
    parser.add_argument("--dirs", type=Path, nargs="*", default=list(DEFAULT_DIRS))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--checkpoint-limit", type=int, default=15)
    args = parser.parse_args(argv)

    summary = build_summary(args.dirs, args.checkpoint_limit)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "REPORT.md").write_text(render_markdown(summary), encoding="utf-8")
    current = summary["current"]
    relaxed = summary["relaxed"]
    print(f"drafts={summary['drafts']} current_skip={_fmt(current['skip_rate'])} "
          f"relaxed_skip={_fmt(relaxed['skip_rate'])} "
          f"relaxed_false_skip={_fmt(relaxed['false_skip_rate'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
