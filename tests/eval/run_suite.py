"""按冻结口径顺序跑完 S1 → S2（两批）→ S3，并生成合并报告。

    python -m tests.eval.run_suite --allow-external-calls
    python -m tests.eval.run_suite --allow-external-calls --out-root evaluation/trials/run-1

S1 未通过 DoD（存在 invalid_trial 或 C 组未执行 time_check）时立即中止，
不会继续消耗 S2/S3 的 API 额度。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from tests.eval import run_trials
from tests.eval.aggregate_trials import main as aggregate_main

S1_CASES = [
    "nanjing-3d-sunny-history",
    "nanjing-3d-tighthours-negative",
    "sanya-3d-allrain-outdoor-negative",
]
S2A_CASES = [
    "jingdezhen-3d-sunny-history",
    "lijiang-3d-allrain-history",
    "lijiang-5d-sunny-slowpace",
    "nanjing-3d-singlerain-history",
    "nanjing-3d-sunny-history",
]
S2B_CASES = [
    "nanjing-3d-tighthours-negative",
    "sanya-3d-allrain-outdoor-negative",
    "shanghai-1d-sunny-nightlife",
    "shanghai-3d-beyond-forecast",
    "shanghai-3d-smallpool-negative",
]
S2_CASES = [*S2A_CASES, *S2B_CASES]
S3_CASES = [
    "nanjing-3d-sunny-history",
    "shanghai-1d-sunny-nightlife",
    "sanya-3d-allrain-outdoor-negative",
]


def _load_records(directory: Path) -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("trial_*.json"))]


def check_s1(directory: Path) -> list[str]:
    """S1 DoD：字段完整、模式一致、C 组执行 time_check、首版快照可取。"""
    records = _load_records(directory)
    problems: list[str] = []
    if len(records) != len(S1_CASES) * 3:
        problems.append(f"S1 trial 数为 {len(records)}，预期 {len(S1_CASES) * 3}")
    for record in records:
        if record.get("invalid_trial"):
            problems.append(f"{record['case_id']}/{record['mode_requested']}: {record.get('invalid_reason')}")
        if (record.get("mode_requested") == "planner_reviewer_time_check"
                and "time_check" not in (record.get("nodes_entered") or [])):
            problems.append(f"{record['case_id']}: C 组未执行 time_check")
        if not record.get("nodes_entered"):
            problems.append(f"{record['case_id']}/{record.get('mode_requested')}: nodes_entered 为空")
    return problems


def _run_stage(name: str, cases: list[str], k: int, out_root: Path) -> Path:
    out = out_root / name
    case_args = [item for case in cases for item in ("--case", case)]
    rc = run_trials.main([
        *case_args, "--k", str(k),
        "--out", str(out), "--allow-external-calls", "--skip-existing",
    ])
    if rc != 0:
        raise SystemExit(f"阶段 {name} 失败，退出码 {rc}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="顺序执行完整评测矩阵")
    parser.add_argument("--allow-external-calls", action="store_true")
    parser.add_argument("--out-root", default=None)
    args = parser.parse_args(argv)

    if not args.allow_external_calls:
        print("完整矩阵会产生 66 次真实 trial；确认后追加 --allow-external-calls。", file=sys.stderr)
        return 2

    root = Path(args.out_root) if args.out_root else (
        Path("evaluation/trials") / datetime.now().strftime("run-%Y%m%d-%H%M%S")
    )
    root.mkdir(parents=True, exist_ok=True)

    stages = [
        ("s1", S1_CASES, 1),
        ("s2a", S2A_CASES, 1),
        ("s2b", S2B_CASES, 1),
        ("s3", S3_CASES, 3),
    ]
    dirs: list[Path] = []
    for name, cases, k in stages:
        print(f"\n=== 阶段 {name}：{len(cases)} 例 × 3 模式 × k={k} ===")
        directory = _run_stage(name, cases, k, root)
        dirs.append(directory)
        if name == "s1":
            problems = check_s1(directory)
            if problems:
                print("S1 DoD 未通过，已中止后续阶段：", file=sys.stderr)
                for problem in problems:
                    print(f"  - {problem}", file=sys.stderr)
                return 4
            print("S1 DoD 通过。")

    print("\n=== 合并报告 ===")
    aggregate_main(["--dirs", *(str(d) for d in dirs), "--out", str(root / "final")])
    print(f"最终报告：{root / 'final' / 'REPORT.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
