"""Benchmark scoring is tested with synthetic responses, never live services."""
from tools import benchmark_identification as benchmark


def test_benchmark_separates_wrong_selection_from_top_five_retrieval():
    cases = [{"id": "a", "query": "first", "expected_ids": ["doi:10.1000/correct"]},
             {"id": "b", "query": "vague", "expected_ids": [], "must_abstain": True},
             {"id": "c", "query": "offline", "expected_ids": ["doi:10.1000/third"]}]
    responses = {
        "first": {"status": "matched", "selected": {"doi": "10.1000/wrong"}, "candidates": [{"doi": "10.1000/wrong"}, {"doi": "10.1000/correct"}], "errors": {}},
        "vague": {"status": "ambiguous", "selected": None, "candidates": [{"doi": "10.1000/topic"}], "errors": {}},
        "offline": {"status": "unavailable", "selected": None, "candidates": [], "errors": {"crossref": {"kind": "timeout", "message": "timeout"}}},
    }
    class Service:
        def search(self, query, **kwargs):
            assert kwargs["mode"] == "identify"
            return responses[query]
    report = benchmark.run_benchmark(Service(), cases)
    totals = report["summary"]
    assert totals["top1_correct"] == 0
    assert totals["top5_correct"] == 1
    assert totals["wrong_automatic"] == 1
    assert totals["correct_automatic"] == 0
    assert totals["abstained"] == 1
    assert totals["correct_abstention"] == 1
    assert totals["unavailable"] == 1
    assert totals["api_errors"] == 1
    assert totals["target_cases"] == 2


def test_versioned_arxiv_and_doi_alias_normalization():
    candidate = {"identifier": {"type": "arxiv", "value": "1706.03762v7"}}
    assert benchmark.matches(candidate, ["doi:10.48550/arXiv.1706.03762"])
    assert benchmark.matches({"doi": "https://doi.org/10.1038/S41586-021-03819-2"}, ["doi:10.1038/s41586-021-03819-2"])
    assert not benchmark.matches({"title": "same title"}, ["doi:10.1000/expected"])


def test_benchmark_requires_live_opt_in(monkeypatch, capsys):
    assert benchmark.main([]) == 0
    assert "--live" in capsys.readouterr().out


def test_case_fixture_has_clear_labels_and_provenance():
    cases = benchmark.load_cases(benchmark.DEFAULT_CASES)
    assert len(cases) >= 10
    assert len({case["id"] for case in cases}) == len(cases)
    assert {"exact", "partial", "description", "citation", "ambiguous", "impossible"} <= {case["category"] for case in cases}
    for case in cases:
        assert case.get("expected_ids") or case.get("must_abstain")
        assert case.get("source") or case.get("synthetic")
