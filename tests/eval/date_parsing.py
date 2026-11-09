"""日期解析确定性兜底的零成本评测（不发任何网络请求）。

为什么值得单独评：`11.18 开始`、`成都周末两天…明天中午开始` 这类输入如果解析失败，
请求会被推进 clarify 分支（追问用户），用户感知就是"系统听不懂"。这三个函数是纯确定性
兜底，正确率可以离线冻结、逐条断言，且不需要 LLM。

    python -m tests.eval.date_parsing            # 打印报告
    python -m tests.eval.date_parsing --out DIR  # 落盘 summary.json / REPORT.md
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, Callable

from app.planning.helpers import (
    extract_travel_days,
    parse_explicit_travel_dates,
    parse_relative_travel_date,
)

# 冻结基准日：2026-11-08 是周日，方便覆盖"周末/下周"的边界。
FROZEN_TODAY = date(2026, 11, 8)

EXPLICIT_CASES: list[tuple[str, list[date]]] = [
    ("11.18开始", [date(2026, 11, 18)]),
    ("11/18", [date(2026, 11, 18)]),
    ("11-18", [date(2026, 11, 18)]),
    ("11月18日", [date(2026, 11, 18)]),
    ("2026-11-18", [date(2026, 11, 18)]),
    ("2026年11月18日住两天", [date(2026, 11, 18)]),
    ("11.18 到 11.20", [date(2026, 11, 18), date(2026, 11, 20)]),
    ("从12.30到1.2", [date(2026, 12, 30), date(2027, 1, 2)]),
    ("走1.5小时", []),
    ("3.5公里", []),
    ("明天出发", []),
    ("周末两天", []),
]

RELATIVE_CASES: list[tuple[str, date | None]] = [
    ("今天下午出发", date(2026, 11, 8)),
    ("明天中午开始", date(2026, 11, 9)),
    ("后天", date(2026, 11, 10)),
    ("大后天走", date(2026, 11, 11)),
    ("3天后出发", date(2026, 11, 11)),
    ("周末两天", date(2026, 11, 14)),
    ("本周末去", date(2026, 11, 14)),
    ("本周六", date(2026, 11, 14)),
    ("下周六", date(2026, 11, 14)),
    ("下周末", date(2026, 11, 14)),
    ("成都周末两天，想泡茶馆吃火锅，明天中午开始", date(2026, 11, 9)),
    ("没有日期信息", None),
]

DAYS_CASES: list[tuple[str, int | None]] = [
    ("杭州一日", 1),
    ("杭州一日游", 1),
    ("三天两夜", 3),
    ("5日游", 5),
    ("南京两天", 2),
    ("周末两天", 2),
    ("11月18日", None),
    ("第3日去博物馆", None),
    ("没有天数", None),
]


def _jsonable(value: Any) -> Any:
    """把 date / date 列表转成字符串，便于落盘。"""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _run(kind: str, cases: list[tuple[str, Any]], fn: Callable[[str], Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for text, expected in cases:
        actual = fn(text)
        rows.append({
            "kind": kind,
            "input": text,
            "expected": _jsonable(expected),
            "actual": _jsonable(actual),
            "pass": actual == expected,
        })
    return rows


def collect() -> dict[str, Any]:
    rows = []
    rows += _run("explicit", EXPLICIT_CASES, lambda t: parse_explicit_travel_dates(t, FROZEN_TODAY))
    rows += _run("relative", RELATIVE_CASES, lambda t: parse_relative_travel_date(t, FROZEN_TODAY))
    rows += _run("days", DAYS_CASES, lambda t: extract_travel_days(t))

    total = len(rows)
    passed = sum(1 for row in rows if row["pass"])
    by_kind: dict[str, dict[str, int]] = {}
    for row in rows:
        bucket = by_kind.setdefault(row["kind"], {"total": 0, "passed": 0})
        bucket["total"] += 1
        bucket["passed"] += 1 if row["pass"] else 0
    return {
        "frozen_today": FROZEN_TODAY.isoformat(),
        "total": total,
        "passed": passed,
        "accuracy": round(passed / total, 4) if total else None,
        "by_kind": by_kind,
        "failures": [row for row in rows if not row["pass"]],
        "rows": rows,
    }


def _render(summary: dict[str, Any]) -> str:
    lines = [
        "# 日期解析确定性兜底评测",
        "",
        f"- 冻结基准日：`{summary['frozen_today']}`（周日）",
        f"- 用例：{summary['total']}；通过：{summary['passed']}；"
        f"准确率：{(summary['accuracy'] or 0) * 100:.1f}%",
        "",
        "| 类别 | 用例 | 通过 | 准确率 |",
        "|---|---:|---:|---:|",
    ]
    for kind, bucket in summary["by_kind"].items():
        lines.append(
            f"| {kind} | {bucket['total']} | {bucket['passed']} | "
            f"{bucket['passed'] / bucket['total'] * 100:.1f}% |"
        )
    lines.append("")
    if summary["failures"]:
        lines.append("## 失败用例")
        lines.append("")
        for row in summary["failures"]:
            lines.append(f"- `{row['input']}` 期望 `{row['expected']}`，实际 `{row['actual']}`")
    else:
        lines.append("无失败用例。")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="日期解析兜底评测")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    summary = collect()
    print(_render(summary))
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (args.out / "REPORT.md").write_text(_render(summary), encoding="utf-8")
        print(f"产物目录：{args.out}")
    return 0 if not summary["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
