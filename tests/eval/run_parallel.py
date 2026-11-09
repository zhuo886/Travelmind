"""按案例分片、多进程并行的评测矩阵。

每个 trial 仍是独立进程、同一份冻结输入与模型；分片只改变调度顺序，
不改变单次运行的语义。S1 完成后先过 DoD，再继续 S2/S3。

    python -m tests.eval.run_parallel --allow-external-calls --workers 3
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from tests.eval.aggregate_trials import main as aggregate_main
from tests.eval.run_suite import S1_CASES, S2_CASES, S3_CASES, check_s1


def chunks(items: list[str], count: int) -> list[list[str]]:
    """把案例尽量均匀地分成 count 份。"""
    count = max(1, min(count, len(items)))
    return [items[index::count] for index in range(count)]


def _stage_args(cases: list[str], k: int, out: Path) -> list[str]:
    case_args = [item for case in cases for item in ("--case", case)]
    return [
        sys.executable, "-m", "tests.eval.run_trials",
        *case_args, "--k", str(k),
        "--out", str(out),
        "--allow-external-calls", "--skip-existing",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="分片并行执行评测矩阵")
    parser.add_argument("--allow-external-calls", action="store_true")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--out-root", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    stages = [("s1", S1_CASES, 1), ("s2", S2_CASES, 1), ("s3", S3_CASES, 3)]
    if args.dry_run:
        for name, cases, k in stages:
            print(f"{name}: {len(cases)} 例 × 3 模式 × k={k}，分片 {chunks(cases, args.workers)}")
        return 0
    if not args.allow_external_calls:
        print("真实运行会产生 API 调用；确认后追加 --allow-external-calls。", file=sys.stderr)
        return 2

    root = Path(args.out_root) if args.out_root else (
        Path("evaluation/trials") / datetime.now().strftime("run-%Y%m%d-%H%M%S")
    )
    root.mkdir(parents=True, exist_ok=True)
    dirs: list[Path] = []

    for name, cases, k in stages:
        out = root / name
        out.mkdir(parents=True, exist_ok=True)
        dirs.append(out)
        shards = chunks(cases, args.workers)
        print(f"\n=== {name}: {len(cases)} 例 × 3 模式 × k={k}，{len(shards)} 个分片 ===")
        processes = [
            subprocess.Popen(_stage_args(shard, k, out), cwd=Path.cwd())
            for shard in shards
        ]
        for process in processes:
            code = process.wait()
            if code != 0:
                print(f"{name} 分片失败，退出码 {code}", file=sys.stderr)
                return code
        if name == "s1":
            problems = check_s1(out)
            if problems:
                print("S1 DoD 未通过，已中止：", file=sys.stderr)
                for problem in problems:
                    print(f"  - {problem}", file=sys.stderr)
                return 4
            print("S1 DoD 通过。")

    aggregate_main(["--dirs", *(str(d) for d in dirs), "--out", str(root / "final")])
    print(f"最终报告：{root / 'final' / 'REPORT.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
