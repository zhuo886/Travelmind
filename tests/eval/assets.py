"""评测资产指纹与版本校验（零成本，不调用外部服务）。

用途：
- 为每次 trial manifest 提供 fixture / benchmark 的 sha256；
- 校验 v3 benchmark 中的 ``fixture_sha256`` 与实际文件一致；
- 守护 v1/v2 冻结资产，避免评测口径被静默改写。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tests.eval import harness

FROZEN_FILE = Path(__file__).resolve().parent / "frozen_assets_v1_v2.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture_manifest(version: str) -> dict[str, dict[str, Any]]:
    """按继承顺序返回 case_id -> 路径/哈希/来源目录。"""
    manifest: dict[str, dict[str, Any]] = {}
    for directory in harness._fixture_dirs(version):
        for path in sorted(directory.glob("*.json")):
            fx = json.loads(path.read_text(encoding="utf-8"))
            case_id = str(fx.get("id") or path.stem)
            manifest[case_id] = {
                "path": str(path),
                "filename": path.name,
                "sha256": sha256_file(path),
                "source": directory.name,
            }
    return manifest


def version_manifest(version: str) -> dict[str, Any]:
    """返回某个版本的完整资产指纹，可直接写入 trial manifest。"""
    _fixtures_dir, benchmark_file = harness._assets(version)
    return {
        "version": version,
        "benchmark": {
            "path": str(benchmark_file),
            "sha256": sha256_file(benchmark_file) if benchmark_file.exists() else None,
        },
        "fixtures": fixture_manifest(version),
    }


def validate_version(version: str) -> list[str]:
    """校验 benchmark 与 fixture 集合/哈希一致；返回问题列表。"""
    problems: list[str] = []
    _fixtures_dir, benchmark_file = harness._assets(version)
    if not benchmark_file.exists():
        return [f"benchmark 不存在：{benchmark_file}"]
    benchmark = harness.load_benchmark(version)
    fixtures = fixture_manifest(version)
    if not benchmark:
        problems.append("benchmark 没有 cases")

    for case_id, case in benchmark.items():
        fixture = fixtures.get(case_id)
        if fixture is None:
            problems.append(f"{case_id}: benchmark 有记录但 fixture 不存在")
            continue
        expected = case.get("fixture_sha256")
        if expected and expected != fixture["sha256"]:
            problems.append(
                f"{case_id}: fixture sha256 不一致（benchmark={expected[:12]}…, "
                f"actual={fixture['sha256'][:12]}…）"
            )

    for case_id in sorted(set(fixtures) - set(benchmark)):
        problems.append(f"{case_id}: fixture 存在但 benchmark 未登记")
    return problems


def frozen_mismatches() -> list[str]:
    """对照 frozen_assets_v1_v2.json，返回被改动的 v1/v2 资产。"""
    if not FROZEN_FILE.exists():
        return [f"冻结指纹文件不存在：{FROZEN_FILE}"]
    frozen = json.loads(FROZEN_FILE.read_text(encoding="utf-8"))
    problems: list[str] = []
    for version in ("v1", "v2"):
        expected = frozen.get(version) or {}
        actual = version_manifest(version)
        expected_benchmark = expected.get("benchmark")
        if expected_benchmark and expected_benchmark != actual["benchmark"]["sha256"]:
            problems.append(f"{version}: benchmark 哈希已变化")
        expected_fixtures = expected.get("fixtures") or {}
        actual_fixtures = {
            item["filename"]: item["sha256"] for item in actual["fixtures"].values()
        }
        for name, digest in expected_fixtures.items():
            if actual_fixtures.get(name) != digest:
                problems.append(f"{version}: fixture {name} 哈希已变化")
        for name in sorted(set(actual_fixtures) - set(expected_fixtures)):
            problems.append(f"{version}: 新增未登记 fixture {name}")
    return problems