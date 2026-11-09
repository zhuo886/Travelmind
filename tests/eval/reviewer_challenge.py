"""Reviewer 受控挑战集（离线框架，真实运行需显式放行）。

每个挑战 = 冻结 fixture + 冻结草稿路线 + 一个人为注入的缺陷标签。
本轮只做 dry-run 与 stub 测试；真实 Reviewer 调用下一轮执行。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

from app.core.llm_usage import snapshot as usage_snapshot, usage_delta

from tests.eval import harness

CHALLENGE_DIR = Path(__file__).resolve().parent / "challenges_v3"
DEFAULT_OUT = Path("evaluation/reviewer_challenge")


def load_challenges(directory: Path = CHALLENGE_DIR) -> list[dict[str, Any]]:
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    ]


def build_challenge_state(case: dict[str, Any], challenge: dict[str, Any]):
    state = harness.build_state_from_fixture(case)
    return state.model_copy(update={
        "route": list(challenge.get("route") or []),
        "route_history": [],
        "review_round": 1,
        "approved": False,
        "reviewer_issues": [],
        "route_modify_opinion": None,
    })


def _text(update: dict[str, Any]) -> str:
    issues = update.get("reviewer_issues") or []
    opinion = update.get("route_modify_opinion") or ""
    return "\n".join([*(str(item) for item in issues), str(opinion)])


def evaluate(
    challenges: list[dict[str, Any]],
    cases: dict[str, dict[str, Any]],
    reviewer: Callable[[Any], dict[str, Any]],
    *,
    k: int = 1,
    provider: str = "injected",
    model: str | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for challenge in challenges:
        case = cases.get(str(challenge.get("base_fixture")))
        if case is None:
            results.append({**challenge, "error": "base_fixture_not_found"})
            continue
        state = build_challenge_state(case, challenge)
        runs: list[dict[str, Any]] = []
        for _ in range(max(1, int(k))):
            before = usage_snapshot()
            started = time.perf_counter()
            try:
                update = reviewer(state) or {}
                error = None
            except Exception as exc:  # noqa: BLE001 - 失败也要计入
                update = {}
                error = f"{type(exc).__name__}: {exc}"
            usage = usage_delta(before, usage_snapshot())
            text = _text(update)
            verdict = "approve" if bool(update.get("approved")) else "reject"
            keywords = [
                keyword for keyword in (challenge.get("expected_keywords") or [])
                if keyword in text
            ]
            runs.append({
                "verdict": verdict,
                "expected": challenge.get("expected_verdict"),
                "correct": verdict == challenge.get("expected_verdict"),
                "keywords_hit": keywords,
                "keyword_match": bool(keywords) if challenge.get("expected_keywords") else None,
                "issues": list(update.get("reviewer_issues") or []),
                "opinion": update.get("route_modify_opinion"),
                "latency_s": round(time.perf_counter() - started, 3),
                "tokens_est": int(usage.get("total_tokens") or 0),
                "error": error,
            })
        verdicts = [run["verdict"] for run in runs]
        consensus = max(set(verdicts), key=verdicts.count) if verdicts else None
        results.append({
            "challenge_id": challenge.get("id"),
            "base_fixture": challenge.get("base_fixture"),
            "injected_defect": challenge.get("injected_defect"),
            "expected_verdict": challenge.get("expected_verdict"),
            "expected_keywords": challenge.get("expected_keywords") or [],
            "runs": runs,
            "consensus": consensus,
            "consistent": len(set(verdicts)) <= 1,
            "consensus_correct": consensus == challenge.get("expected_verdict"),
        })
    summary = summarize(results)
    summary.update({"provider": provider, "model": model})
    return summary


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    defect_results = [item for item in results if item.get("expected_verdict") == "reject"]
    clean_results = [item for item in results if item.get("expected_verdict") == "approve"]
    by_defect: dict[str, dict[str, Any]] = {}
    for item in defect_results:
        runs = item.get("runs") or []
        total = len(runs)
        detected = sum(1 for run in runs if run.get("verdict") == "reject")
        keywords = sum(1 for run in runs if run.get("keyword_match"))
        by_defect[str(item.get("injected_defect"))] = {
            "runs": total,
            "detected": detected,
            "detection_rate": round(detected / total, 4) if total else None,
            "keyword_match": keywords,
            "keyword_match_rate": round(keywords / total, 4) if total else None,
        }
    def _rate(num: int, den: int) -> dict[str, Any]:
        return {"num": num, "den": den, "value": round(num / den, 4) if den else None}

    defect_runs = sum(len(item.get("runs") or []) for item in defect_results)
    detected = sum(1 for item in defect_results for run in (item.get("runs") or []) if run.get("verdict") == "reject")
    keyword_hits = sum(1 for item in defect_results for run in (item.get("runs") or []) if run.get("keyword_match"))
    clean_runs = sum(len(item.get("runs") or []) for item in clean_results)
    clean_blocks = sum(1 for item in clean_results for run in (item.get("runs") or []) if run.get("verdict") == "reject")
    clean_issue_runs = sum(
        1 for item in clean_results for run in (item.get("runs") or []) if run.get("issues")
    )
    all_runs = [run for item in results for run in (item.get("runs") or [])]
    latencies = [float(run.get("latency_s") or 0.0) for run in all_runs]
    return {
        "challenges": len(results),
        "k": max((len(item.get("runs") or []) for item in results), default=0),
        "defect_challenges": len(defect_results),
        "clean_challenges": len(clean_results),
        "defect_runs": defect_runs,
        "detection_rate": _rate(detected, defect_runs),
        "keyword_match_rate": _rate(keyword_hits, defect_runs),
        "clean_runs": clean_runs,
        "clean_block_rate": _rate(clean_blocks, clean_runs),
        "clean_issue_runs": clean_issue_runs,
        "errors": sum(1 for run in all_runs if run.get("error")),
        "tokens_est": sum(int(run.get("tokens_est") or 0) for run in all_runs),
        "latency_median_s": round(sorted(latencies)[len(latencies) // 2], 3) if latencies else None,
        "latency_max_s": round(max(latencies), 3) if latencies else None,
        "consensus_accuracy": _rate(
            sum(1 for item in results if item.get("consensus_correct")), len(results)
        ),
        "consistency_rate": _rate(
            sum(1 for item in results if item.get("consistent")), len(results)
        ),
        "by_defect": dict(sorted(by_defect.items())),
        "results": results,
    }


def render_markdown(summary: dict[str, Any]) -> str:
    def _pct(item: dict[str, Any]) -> str:
        value = item.get("value")
        return "N/A" if value is None else f"{value * 100:.1f}%"

    return "\n".join([
        "# Reviewer 受控挑战集",
        "",
        f"- provider：{summary.get('provider')}；model：{summary.get('model') or 'default'}",
        f"- 挑战数：{summary['challenges']}；k={summary['k']}；"
        f"缺陷挑战：{summary['defect_challenges']}；正常对照：{summary['clean_challenges']}",
        f"- 缺陷检出率：{summary['detection_rate']['num']} / {summary['detection_rate']['den']} "
        f"= {_pct(summary['detection_rate'])}",
        f"- 缺陷关键词命中率：{summary['keyword_match_rate']['num']} / "
        f"{summary['keyword_match_rate']['den']} = {_pct(summary['keyword_match_rate'])}",
        f"- 正常对照误打回率：{summary['clean_block_rate']['num']} / "
        f"{summary['clean_block_rate']['den']} = {_pct(summary['clean_block_rate'])}",
        f"- 正常对照带提醒 run：{summary['clean_issue_runs']} / {summary['clean_runs']}",
        f"- 共识正确率：{_pct(summary['consensus_accuracy'])}；"
        f"k 次一致率：{_pct(summary['consistency_rate'])}",
        f"- Token 合计：{summary['tokens_est']}；"
        f"延迟 median/max：{summary['latency_median_s']}/{summary['latency_max_s']}s；"
        f"错误：{summary['errors']}",
        "",
        "## 按缺陷类型",
        "",
        "| 缺陷 | runs | 检出 | 检出率 | 关键词命中 | 关键词命中率 |",
        "|---|---|---|---|---|---|",
        *[
            f"| {name} | {value['runs']} | {value['detected']} | "
            f"{value['detection_rate']} | {value['keyword_match']} | {value['keyword_match_rate']} |"
            for name, value in summary["by_defect"].items()
        ],
        "",
        (
            "> 本轮为 stub / injected reviewer，只证明挑战集与指标可运行。"
            if summary.get("provider") != "llm"
            else "> 本轮为真实 Reviewer 调用；正常对照误打回只按 verdict 统计，提醒质量需人工复核。"
        ),
    ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reviewer 受控挑战集")
    parser.add_argument("--challenge-dir", type=Path, default=CHALLENGE_DIR)
    parser.add_argument("--version", default="v2", choices=["v1", "v2", "v3"])
    parser.add_argument("--model", default=None)
    parser.add_argument("--k", type=int, default=1)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--replay-summary", type=Path, default=None,
                        help="不调用 Reviewer，只从已有 summary.json 重算报告")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--allow-external-calls", action="store_true")
    args = parser.parse_args(argv)

    challenges = load_challenges(args.challenge_dir)
    if not challenges:
        print("没有找到挑战集", file=sys.stderr)
        return 1
    if args.replay_summary:
        from app.core.env import load_local_env

        load_local_env()
        existing = json.loads(args.replay_summary.read_text(encoding="utf-8"))
        results = list(existing.get("results") or [])
        summary = summarize(results)
        model = args.model or existing.get("model") or os.getenv("OPENAI_MODEL") or os.getenv("LLM_MODEL")
        summary.update({
            "provider": existing.get("provider") or "llm",
            "model": model,
        })
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (args.out / "REPORT.md").write_text(render_markdown(summary), encoding="utf-8")
        print(f"Reviewer 挑战报告重算：{args.out}")
        return 0
    if args.dry_run:
        print(f"计划运行 {len(challenges)} 个挑战 × k={max(1, args.k)}")
        for challenge in challenges:
            print(f"  - {challenge.get('id')} / {challenge.get('injected_defect')} "
                  f"-> {challenge.get('expected_verdict')}")
        return 0
    if not args.allow_external_calls:
        print("真实 Reviewer 调用会产生外部请求；确认后追加 --allow-external-calls。", file=sys.stderr)
        return 2

    from app.planning.nodes import make_reviewer_node
    from app.core.env import load_local_env

    load_local_env()

    cases = {case["id"]: case for case in harness.load_cases(version=args.version)}
    model = args.model or os.getenv("OPENAI_MODEL") or os.getenv("LLM_MODEL")
    summary = evaluate(
        challenges, cases, make_reviewer_node(model), k=args.k,
        provider="llm", model=model,
    )
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "REPORT.md").write_text(render_markdown(summary), encoding="utf-8")
    print(f"Reviewer 挑战结果：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())