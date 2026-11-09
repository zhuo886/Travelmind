"""把多个 trial 目录合并成一份零成本的评测报告。

用法：
    python -m tests.eval.aggregate_trials --dirs evaluation/trials/s1 evaluation/trials/s2 \\
        --out evaluation/trials/final
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from tests.eval.metrics import aggregate, render_markdown


def load_records(dirs: list[Path]) -> list[dict]:
    records: list[dict] = []
    for directory in dirs:
        for path in sorted(directory.glob("trial_*.json")):
            records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def merge_judge(records: list[dict], judge_dir: Path | None) -> list[dict]:
    """按 trial_id 合并 Judge 结果；只在内存里合并，不改原始 trial。"""
    if judge_dir is None or not judge_dir.exists():
        return records
    index: dict[str, dict] = {}
    for path in sorted(judge_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        trial_id = str(data.get("trial_id") or "")
        if trial_id and isinstance(data.get("judge"), dict):
            index[trial_id] = data["judge"]
    for record in records:
        block = index.get(str(record.get("trial_id") or ""))
        if block is not None:
            record["judge"] = block
    return records


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="合并 trial 目录并生成报告")
    parser.add_argument("--dirs", nargs="+", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--judge-dir", type=Path, default=None,
                        help="可选：合并 tests.eval.judge 产出的 judge_*.json")
    args = parser.parse_args(argv)

    records = load_records(args.dirs)
    if not records:
        raise SystemExit("没有找到 trial_*.json")
    records = merge_judge(records, args.judge_dir)

    args.out.mkdir(parents=True, exist_ok=True)
    summary = aggregate(records)
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "REPORT.md").write_text(render_markdown(summary), encoding="utf-8")
    print(f"合并 {len(records)} 条 trial -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
