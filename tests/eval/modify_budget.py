"""Checkpoint 修改的输入预算精算（0 次 LLM 调用）。

两臂的差别不在"同一个子图跑两遍"，而在**入口不同**：

- A 臂（全量重规划）：``intent`` → ``query_rewrite`` → ``attraction_search``
  → ``candidate_react`` → ``candidate_search`` → ``validator`` → ``planner``
- B 臂（checkpoint 增量修改）：``planner`` → 距离/审核/时间/收尾

因此 A 臂的输入预算包含 intent / query_rewrite / candidate_react 三次结构化
调用，B 臂只付一次 planner。但 B 臂的 planner prompt 里塞进了上一版路线，
必须如实计入，不能只算省下的部分。

本模块把两臂**真实构造出的 prompt** 捕获下来（patch 掉 LLM 客户端，调用真实
节点函数），再用 ``llm_usage.estimate_tokens`` 计数。耗时不做推算：仓库里没有
检索阶段的实测耗时，凭空补一个延迟就等于伪造。

用法::

    python -m tests.eval.modify_budget --out evaluation/benchmarks/modify_budget
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

from app.core.llm_usage import estimate_tokens
from app.planning.graph import restore_modification_state
from app.planning.nodes import (
    make_intent_node,
    make_joint_planner_node,
    make_query_rewrite_node,
)
from app.planning.schemas import IntentExtraction, RewrittenQuery, TravelRoute

from tests.eval import harness
from tests.eval.checkpoint_benchmark import load_pairs

DEFAULT_TRIAL_DIRS = (
    Path("evaluation/trials/run-20261107-v2"),
    Path("evaluation/trials/run-20261107-negative"),
)
DEFAULT_OUT = Path("evaluation/benchmarks/modify_budget")
E2_SUMMARY = Path("evaluation/checkpoint_benchmark/summary.json")
DEFAULT_INSTRUCTION = "把第 1 天下午的景点换成室内的，其他天尽量保持不变。"

# 两臂的节点集合（按 app/planning/graph.py 的真实拓扑）。
ARM_A_NODES = (
    "intent", "query_rewrite", "weather_search",
    "attraction_search", "candidate_react", "candidate_search",
    "candidate_validator", "main_meal_search",
    "planner", "route_distance_check", "risk_gate", "reviewer", "time_check",
    "main_meal_output", "spot_tips", "finalize",
)
ARM_B_NODES = (
    "planner", "route_distance_check", "risk_gate", "reviewer", "time_check",
    "main_meal_output", "spot_tips", "finalize",
)
STAGE_NODES: dict[str, tuple[str, ...]] = {
    "intake": ("intent", "query_rewrite", "weather_search"),
    "retrieval": (
        "attraction_search", "candidate_react", "candidate_search",
        "candidate_validator", "main_meal_search",
    ),
    "planning": ("planner", "route_distance_check"),
    "review": ("risk_gate", "reviewer", "time_check"),
    "finishing": ("main_meal_output", "spot_tips", "finalize"),
}
# 仓库里能查到 node_latency_ms 的 trial 目录。
LATENCY_SOURCES = (
    Path("evaluation/trials/run-20261106"),
    Path("evaluation/trials/run-20261107-v2"),
)

Capture = list[dict[str, Any]]


# ─── 捕获层 ────────────────────────────────────────────────

class _FakeLLM:
    """只承载 schema，真正的调用被 ``_capture_structured`` 接管。"""

    def __init__(self, schema: Any, task_type: str | None) -> None:
        self.schema = schema
        self.model_name = f"offline:{task_type or 'unknown'}"

    def invoke(self, _messages: Any) -> Any:  # pragma: no cover - 不应到达
        raise AssertionError("离线预算不应真正调用模型")


def _fake_build_structured_llm(schema: Any, **kwargs: Any) -> _FakeLLM:
    return _FakeLLM(schema, kwargs.get("task_type"))


_RESPONSE_BUILDERS: dict[str, Callable[[Any], Any]] = {
    "IntentExtraction": lambda state: IntentExtraction(
        destination=state.destination or "",
        travel_start_date=str(state.travel_start_date or ""),
        travel_end_date=str(state.travel_end_date or ""),
        travel_days=int(state.days or 0),
        attraction_preference=state.attraction_preference or "",
        food_preference=state.food_preference or "",
        habit_preference=state.habit_preference or "",
    ),
    "RewrittenQuery": lambda state: RewrittenQuery(
        rewritten_query=state.query,
        attraction_preference=state.attraction_preference,
        food_preference=state.food_preference,
        habit_preference=state.habit_preference,
    ),
    # Planner 结果只用于让节点跑完，不参与计数，所以跳过校验。
    "TravelRoute": lambda state: TravelRoute.model_construct(
        reasoning="", days=[], meal_slots=[], selection_reasons=[], notes="",
    ),
}


def _capture_structured(llm: Any, messages: list[tuple[str, str]], **_kwargs: Any) -> Any:
    schema_name = getattr(getattr(llm, "schema", None), "__name__", "unknown")
    sink = _CAPTURE_STACK[-1]
    sink.append({
        "schema": schema_name,
        "task": getattr(llm, "model_name", ""),
        "tokens": sum(estimate_tokens(content) for _role, content in messages),
        "chars": sum(len(role) + len(content) for role, content in messages),
    })
    return _RESPONSE_STACK[-1][schema_name](_STATE_STACK[-1])


_CAPTURE_STACK: list[Capture] = []
_RESPONSE_STACK: list[dict[str, Callable[[Any], Any]]] = []
_STATE_STACK: list[Any] = []


class _capture_scope:
    """在上下文里把 nodes/candidate_react 的 LLM 全部换成捕获器。"""

    def __init__(self, state: Any) -> None:
        self.state = state
        self.sink: Capture = []
        self._patches: list[Any] = []

    def __enter__(self) -> Capture:
        _CAPTURE_STACK.append(self.sink)
        _RESPONSE_STACK.append(_RESPONSE_BUILDERS)
        _STATE_STACK.append(self.state)
        for target in (
            "app.planning.nodes.build_structured_llm",
            "app.planning.candidate_react.build_structured_llm",
            "app.planning.nodes.invoke_structured",
            "app.planning.candidate_react.invoke_structured",
        ):
            patcher = (
                patch(target, _fake_build_structured_llm)
                if target.endswith("build_structured_llm")
                else patch(target, _capture_structured)
            )
            patcher.start()
            self._patches.append(patcher)
        return self.sink

    def __exit__(self, *_exc: Any) -> None:
        for patcher in reversed(self._patches):
            patcher.stop()
        _STATE_STACK.pop()
        _RESPONSE_STACK.pop()
        _CAPTURE_STACK.pop()


# ─── 两臂 prompt 采集 ───────────────────────────────────────

def measure_entry_prompts(case: dict[str, Any], checkpoint: dict[str, Any] | None,
                          instruction: str = DEFAULT_INSTRUCTION) -> dict[str, Any]:
    """返回 A/B 两臂的逐调用 token 与节点集合。"""
    fixture_state = harness.build_state_from_fixture(case)

    a_state = fixture_state.model_copy(update={"route": []})
    with _capture_scope(a_state) as sink:
        make_intent_node(None, profile_hint="")(a_state)
        rewritten = make_query_rewrite_node(None, None)(a_state)
        a_state = a_state.model_copy(update={
            "rewritten_query": (rewritten or {}).get("rewritten_query") or a_state.query,
        })
        # candidate_react 只在存在缺口时才问模型；无缺口则本次不产生 prompt。
        try:
            from app.planning.candidate_react import make_candidate_react_node

            make_candidate_react_node(None)(a_state)
        except Exception:  # noqa: BLE001 - 预算基准不因单节点异常中断
            pass
        make_joint_planner_node(None, knowledge_lookup=lambda *a, **k: [])(
            a_state.model_copy(update={"route": []})
        )
    a_calls = list(sink)

    b_calls: list[dict[str, Any]] = []
    if checkpoint is not None:
        b_state = restore_modification_state(checkpoint, instruction)
        with _capture_scope(b_state) as b_sink:
            make_joint_planner_node(None, knowledge_lookup=lambda *a, **k: [])(
                b_state.model_copy(update={"route": b_state.route})
            )
        b_calls = list(b_sink)

    def _total(calls: list[dict[str, Any]]) -> int:
        return sum(int(call["tokens"]) for call in calls)

    return {
        "case_id": case["id"],
        "a_calls": a_calls,
        "b_calls": b_calls,
        "a_tokens": _total(a_calls),
        "b_tokens": _total(b_calls),
        "a_llm_calls": len(a_calls),
        "b_llm_calls": len(b_calls),
        "a_nodes": [call["schema"] for call in a_calls],
        "b_nodes": [call["schema"] for call in b_calls],
    }


# ─── 汇总 ──────────────────────────────────────────────────

def _pct(new: float, old: float) -> float | None:
    return round((new - old) / old, 4) if old else None


def load_e2_reference(path: Path = E2_SUMMARY) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "pairs": data.get("pairs"),
        "mode": data.get("mode"),
        "latency_reduction": data.get("latency_reduction"),
        "token_reduction": data.get("token_reduction"),
        "retention": data.get("retention"),
        "note": "A/B 同为 planner 起跑的同子图配对；不跳过检索，因此只作下界参照",
    }


def node_latency_medians(sources: tuple[Path, ...] = LATENCY_SOURCES) -> dict[str, float]:
    """从已冻结 trial 的 ``node_latency_ms`` 取每个节点的中位耗时。"""
    samples: dict[str, list[float]] = {}
    for base in sources:
        if not base.exists():
            continue
        for path in sorted(base.rglob("trial_*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            for node, value in (record.get("node_latency_ms") or {}).items():
                if isinstance(value, (int, float)):
                    samples.setdefault(str(node), []).append(float(value))
    return {
        node: round(statistics.median(values), 1)
        for node, values in samples.items() if values
    }


def latency_decomposition(sources: tuple[Path, ...] = LATENCY_SOURCES) -> dict[str, Any]:
    """按两臂节点集合求和，给出**只覆盖已测节点**的拆解估算。

    仓库里只记录了 planner / reviewer / time_check / snapshot 这类节点的耗时，
    检索、餐食、贴士、finalize 都没有实测。因此这里给的是"部分覆盖"的估算，
    覆盖率和未测节点必须一起报，不能当成全链路 P50。
    """
    medians = node_latency_medians(sources)

    def _arm(nodes: tuple[str, ...]) -> dict[str, Any]:
        measured = {node: medians[node] for node in nodes if node in medians}
        missing = [node for node in nodes if node not in medians]
        return {
            "nodes": list(nodes),
            "measured": measured,
            "unmeasured": missing,
            "measured_p50_ms": round(sum(measured.values()), 1),
            "coverage": round(len(measured) / len(nodes), 3),
        }

    stages: dict[str, dict[str, Any]] = {}
    for name, nodes in STAGE_NODES.items():
        measured = {node: medians[node] for node in nodes if node in medians}
        stages[name] = {
            "nodes": len(nodes),
            "measured_nodes": len(measured),
            "estimated_ms": round(sum(measured.values()), 1),
            "in_arm_b": any(node in ARM_B_NODES for node in nodes),
        }
    total = sum(stage["estimated_ms"] for stage in stages.values())
    for stage in stages.values():
        if not stage["measured_nodes"] or not total:
            # 未测阶段不能用 0% 冒充“完全不耗时”。
            stage["share"] = None
        else:
            stage["share"] = round(stage["estimated_ms"] / total, 4)

    return {
        "sources": [str(path) for path in sources],
        "node_medians_ms": dict(sorted(medians.items())),
        "arm_a": _arm(ARM_A_NODES),
        "arm_b": _arm(ARM_B_NODES),
        "stages": stages,
        "measured_total_ms": round(total, 1),
    }


def build_summary(dirs: list[Path], instruction: str = DEFAULT_INSTRUCTION) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pair in load_pairs(list(dirs)):
        case = pair["case"]
        if case["id"] in seen:
            continue
        seen.add(case["id"])
        rows.append(measure_entry_prompts(case, pair["checkpoint"], instruction))
    a_tokens = [row["a_tokens"] for row in rows if row["b_calls"]]
    b_tokens = [row["b_tokens"] for row in rows if row["b_calls"]]
    return {
        "benchmark": "modify_input_budget",
        "kind": "offline_prompt_capture",
        "instruction": instruction,
        "cases": len(rows),
        "rows": rows,
        "a_tokens_median": statistics.median(a_tokens) if a_tokens else None,
        "b_tokens_median": statistics.median(b_tokens) if b_tokens else None,
        "a_tokens_mean": round(statistics.fmean(a_tokens), 1) if a_tokens else None,
        "b_tokens_mean": round(statistics.fmean(b_tokens), 1) if b_tokens else None,
        "token_reduction": _pct(
            statistics.fmean(b_tokens) if b_tokens else 0,
            statistics.fmean(a_tokens) if a_tokens else 0,
        ),
        "a_call_median": statistics.median([row["a_llm_calls"] for row in rows]) if rows else None,
        "b_call_median": statistics.median([row["b_llm_calls"] for row in rows]) if rows else None,
        "latency": {
            "status": "partial_decomposition",
            "full_chain_status": "not_measured",
            "reason": "仓库内没有检索阶段（attraction_search/candidate_search）的实测耗时，"
                      "补一个延迟即伪造；因此只给已测节点的拆解，全链路 P50 仍标 not_measured",
            "decomposition": latency_decomposition(),
        },
        "e2_reference": load_e2_reference(),
    }


def node_token_table(rows: list[dict[str, Any]]) -> dict[str, list[int]]:
    table: dict[str, list[int]] = {}
    for label, key in (("A", "a_calls"), ("B", "b_calls")):
        for row in rows:
            for call in row[key]:
                table.setdefault(f"{label}:{call['schema']}", []).append(int(call["tokens"]))
    return {name: sorted(values) for name, values in sorted(table.items())}


def render_markdown(summary: dict[str, Any]) -> str:
    rows = summary["rows"]
    token_table = node_token_table(rows)
    reduction = summary["token_reduction"]
    e2 = summary["e2_reference"]
    lines = [
        "# Checkpoint 修改：输入预算与耗时拆解",
        "",
        "> 口径：捕获两臂**真实构造出的 prompt**，用 `estimate_tokens` 计数；0 次 LLM 调用",
        "> A 臂 = 全量重规划入口（intent + query_rewrite + planner，含缺口时的 candidate_react）",
        "> B 臂 = checkpoint 增量修改入口（仅 planner，但 prompt 内含上一版路线）",
        "",
        "## 1. 输入预算",
        "",
        f"- 有效 case：{summary['cases']}",
        f"- A 臂 token 均值 / 中位：{summary['a_tokens_mean']} / {summary['a_tokens_median']}",
        f"- B 臂 token 均值 / 中位：{summary['b_tokens_mean']} / {summary['b_tokens_median']}",
        f"- 变化：{_fmt_pct(reduction)}（负数=更省）",
        f"- LLM 调用数中位：A {summary['a_call_median']} → B {summary['b_call_median']}",
        "",
        "### 逐调用（token 中位）",
        "",
        "| 调用 | 样本数 | token 中位 |",
        "|---|---:|---:|",
    ]
    for name, values in token_table.items():
        lines.append(f"| {name} | {len(values)} | {statistics.median(values)} |")
    regressions = [row for row in rows if row["b_tokens"] > row["a_tokens"]]
    lines += [
        "",
        "### 逐 case",
        "",
        "| case | A token | A 调用 | B token | B 调用 | 变化 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['case_id']} | {row['a_tokens']} | {row['a_llm_calls']} | "
            f"{row['b_tokens']} | {row['b_llm_calls']} | "
            f"{_fmt_pct(_pct(row['b_tokens'], row['a_tokens']))} |"
        )
    lines += [
        "",
        f"- B 臂反而更贵的 case：{len(regressions)} / {len(rows)}"
        + (f"（{'、'.join(row['case_id'] for row in regressions)}）" if regressions else ""),
        "- 原因：B 臂 planner prompt 里含完整上一版路线，天数越多、路线越长，这笔开销越可能抵消省下的 intent/query_rewrite。",
        "",
        "## 2. 耗时",
        "",
        f"- 全链路状态：**{summary['latency'].get('full_chain_status', summary['latency']['status'])}**",
        f"- 原因：{summary['latency']['reason']}",
        "",
        "### 2.1 阶段拆解（仅已测节点）",
        "",
        "| 阶段 | 节点数 | 已测 | 估算耗时 | 占已测总量 | B 臂是否执行 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    decomposition = summary["latency"].get("decomposition") or {}
    for stage_name, stage in (decomposition.get("stages") or {}).items():
        share = stage.get("share")
        lines.append(
            f"| {stage_name} | {stage['nodes']} | {stage['measured_nodes']} | "
            f"{stage['estimated_ms']}ms | {'N/A' if share is None else f'{share * 100:.1f}%'} | "
            f"{'是' if stage['in_arm_b'] else '否'} |"
        )
    arm_a = decomposition.get("arm_a") or {}
    arm_b = decomposition.get("arm_b") or {}
    lines += [
        "",
        f"- A 臂已测覆盖：{arm_a.get('coverage')}（{arm_a.get('measured_p50_ms')}ms）；"
        f"未测：{arm_a.get('unmeasured')}",
        f"- B 臂已测覆盖：{arm_b.get('coverage')}（{arm_b.get('measured_p50_ms')}ms）；"
        f"未测：{arm_b.get('unmeasured')}",
        "- 两臂的已测节点几乎相同（planner/reviewer/time_check），所以这张表**不能**推出耗时降幅；"
        "它只说明哪些阶段根本没有耗时数据。",
        "",
        "### 2.2 E2 真实配对参照（同子图，27 组）",
    ]
    if e2:
        latency_reduction = e2.get("latency_reduction")
        token_reduction = e2.get("token_reduction")
        retention = e2.get("retention") or {}
        lines += [
            "",
            f"- 重规划 P50 降幅：{_fmt_pct(latency_reduction)}（正数=更快）",
            f"- 输入 Token 降幅：{_fmt_pct(token_reduction)}（负数=反而更多）",
            f"- 未修改内容保留率：A {_fmt_pct(retention.get('A'))} → "
            f"B {_fmt_pct(retention.get('B'))}",
            "",
            "> 该配对两臂都从 `planner` 起跑，检索阶段没进分母，所以它证明的是"
            "“不跳过检索时确实不省”，不能当成全链路收益。",
        ]
    lines += [
        "",
        "## 3. 读法",
        "",
        "- 只能说“入口输入预算下降 X%”，不能说“重规划耗时降低 X%”（耗时本轮未测）。",
        "- B 臂 planner prompt 更大（含上一版路线），因此不能只报省下的部分。",
        "- 若 X 为正（B 更贵），说明 checkpoint 的价值在保留率与硬约束，不在 Token。",
    ]
    return "\n".join(lines)


def _fmt_pct(value: float | None) -> str:
    return "N/A" if value is None else f"{value * 100:+.1f}%"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Checkpoint 修改输入预算（离线）")
    parser.add_argument("--dirs", type=Path, nargs="*", default=list(DEFAULT_TRIAL_DIRS))
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--instruction", default=DEFAULT_INSTRUCTION)
    args = parser.parse_args(argv)

    summary = build_summary(args.dirs, args.instruction)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.out / "REPORT.md").write_text(render_markdown(summary), encoding="utf-8")
    print(f"cases={summary['cases']} token_reduction={_fmt_pct(summary['token_reduction'])} "
          f"A={summary['a_tokens_mean']} B={summary['b_tokens_mean']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
