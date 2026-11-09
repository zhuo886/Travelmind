"""语义记忆：开关、用户隔离与去重。"""

from __future__ import annotations

from app.core import semantic_memory


class _FakeCollection:
    """只实现被用到的 query 语义，并按 where 过滤，模拟 Chroma 的用户隔离。"""

    def __init__(self, documents: list[tuple[str, str]]) -> None:
        self.documents = documents
        self.calls: list[dict] = []

    def query(self, query_texts, n_results=3, where=None, include=None):
        self.calls.append({"where": where, "n_results": n_results})
        user_id = (where or {}).get("user_id")
        docs = [text for owner, text in self.documents if owner == user_id]
        return {"documents": [docs[:n_results]]}


def test_disabled_flag_short_circuits_collection(monkeypatch):
    monkeypatch.setenv("SEMANTIC_MEMORY_ENABLED", "0")

    assert semantic_memory._collection() is None
    memories, status = semantic_memory.search_user_memories_with_status("u1", "安静")
    assert memories == []
    assert status == "degraded"


def test_blank_input_is_skipped_not_degraded(monkeypatch):
    monkeypatch.setenv("SEMANTIC_MEMORY_ENABLED", "1")

    memories, status = semantic_memory.search_user_memories_with_status("", "安静")
    assert (memories, status) == ([], "skipped")


def test_query_is_scoped_to_the_requesting_user(monkeypatch):
    monkeypatch.setenv("SEMANTIC_MEMORY_ENABLED", "1")
    collection = _FakeCollection([
        ("u1", "用户对花粉过敏"),
        ("u2", "用户喜欢夜生活"),
        ("u1", "不吃香菜"),
    ])
    monkeypatch.setattr(semantic_memory, "_collection", lambda: collection)

    u1, status = semantic_memory.search_user_memories_with_status("u1", "饮食", limit=3)
    u2, _ = semantic_memory.search_user_memories_with_status("u2", "饮食", limit=3)

    assert status == "ok"
    assert u1 == ["用户对花粉过敏", "不吃香菜"]
    assert u2 == ["用户喜欢夜生活"]
    assert collection.calls[0]["where"] == {"user_id": "u1"}


def test_clean_memories_dedupes_and_caps():
    cleaned = semantic_memory._clean_memories([
        "  不坐红眼航班 ",
        "不坐红眼航班",
        "",
        "怕晒",
        "a", "b", "c",
    ])

    assert cleaned[:2] == ["不坐红眼航班", "怕晒"]
    assert len(cleaned) == 3


def test_memory_id_is_stable_per_user_and_differs_across_users():
    first = semantic_memory._memory_id("u1", "怕晒")
    again = semantic_memory._memory_id("u1", "怕晒")
    other = semantic_memory._memory_id("u2", "怕晒")

    assert first == again
    assert first != other
    assert first.startswith("pref-")


def test_retrieval_failure_degrades_without_raising(monkeypatch):
    monkeypatch.setenv("SEMANTIC_MEMORY_ENABLED", "1")

    class _Broken:
        def query(self, **_kwargs):
            raise RuntimeError("store offline")

    monkeypatch.setattr(semantic_memory, "_collection", lambda: _Broken())

    memories, status = semantic_memory.search_user_memories_with_status("u1", "安静")
    assert memories == []
    assert status == "degraded"
