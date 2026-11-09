"""缓存命中/未命中/降级计数与 Prometheus 输出。"""

from __future__ import annotations

import json

from app.core import cache


class _FakeRedis:
    def __init__(self, store: dict[str, str] | None = None) -> None:
        self.store = store or {}

    def get(self, key: str):
        return self.store.get(key)

    def ping(self) -> bool:
        return True


def test_hit_miss_and_disabled_are_counted(monkeypatch):
    cache.reset_cache_counters()

    monkeypatch.setattr(cache, "_get_redis", lambda: None)
    assert cache.get_cached("k") is None

    store = {"k": json.dumps({"a": 1})}
    monkeypatch.setattr(cache, "_get_redis", lambda: _FakeRedis(store))
    assert cache.get_cached("k") == {"a": 1}
    assert cache.get_cached("missing") is None

    snapshot = cache.cache_snapshot()
    assert snapshot["hit"] == 1
    assert snapshot["miss"] == 1
    assert snapshot["disabled"] == 1
    assert snapshot["error"] == 0


def test_error_path_is_counted_without_raising(monkeypatch):
    cache.reset_cache_counters()

    class _Broken:
        def get(self, _key):
            raise RuntimeError("boom")

    monkeypatch.setattr(cache, "_get_redis", lambda: _Broken())

    assert cache.get_cached("k") is None
    assert cache.cache_snapshot()["error"] == 1


def test_prometheus_lines_expose_every_outcome(monkeypatch):
    cache.reset_cache_counters()
    monkeypatch.setattr(cache, "_get_redis", lambda: None)
    cache.get_cached("k")

    text = "\n".join(cache.prometheus_lines())

    assert "travelmind_cache_hits_total" in text
    for outcome in ("hit", "miss", "disabled", "error"):
        assert f'result="{outcome}"' in text


def test_counters_do_not_change_cache_behaviour(monkeypatch):
    """计数是只读的：未配置 Redis 时仍然返回 None，不新建连接。"""
    cache.reset_cache_counters()
    monkeypatch.setattr(cache, "_get_redis", lambda: None)

    assert cache.get_cached("anything") is None
    assert cache.cache_snapshot()["disabled"] == 1

    cache.set_cached("anything", {"x": 1}, 60)  # 不应抛错


def test_metrics_endpoint_exposes_cache_counters(monkeypatch):
    """Spec 要求 `/metrics` 能查到缓存结果，而不只是模块内计数器。"""
    from fastapi.testclient import TestClient

    from app.main import app

    cache.reset_cache_counters()
    monkeypatch.setattr(cache, "_get_redis", lambda: None)
    cache.get_cached("k")

    response = TestClient(app).get("/api/metrics")

    assert response.status_code == 200
    assert "travelmind_cache_hits_total" in response.text
    assert 'travelmind_cache_hits_total{result="disabled"}' in response.text
