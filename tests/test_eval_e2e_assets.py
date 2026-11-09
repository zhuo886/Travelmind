"""离线守护：日期解析冻结语料必须 100% 通过；端到端评测资产不得被随手改动。"""

from tests.eval import date_parsing, e2e_chain


def test_frozen_date_corpus_all_pass():
    summary = date_parsing.collect()

    assert summary["failures"] == []
    assert summary["accuracy"] == 1.0


def test_date_corpus_covers_three_fallbacks():
    summary = date_parsing.collect()

    assert set(summary["by_kind"]) == {"explicit", "relative", "days"}


def test_e2e_queries_are_frozen_and_unique():
    ids = [case["id"] for case in e2e_chain.FROZEN_QUERIES]
    queries = [case["query"] for case in e2e_chain.FROZEN_QUERIES]

    assert len(set(ids)) == len(ids)
    assert len(set(queries)) == len(queries)
    assert len(ids) >= 4


def test_e2e_requires_explicit_permission(tmp_path):
    """没有 --allow-external-calls 时必须拒绝真实调用。"""
    code = e2e_chain.main(["--out", str(tmp_path)])

    assert code == 2
    assert not (tmp_path / "summary.json").exists()


def test_spot_names_flattens_days():
    route = [
        {"day": 1, "spots": [{"name": "西湖"}, {"name": " 灵隐寺 "}]},
        {"day": 2, "spots": [{"name": ""}, {"name": "雷峰塔"}]},
    ]

    assert e2e_chain._spot_names(route) == ["西湖", "灵隐寺", "雷峰塔"]
