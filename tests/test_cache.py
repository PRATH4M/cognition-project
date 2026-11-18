"""Tests for the in-memory caches."""

from __future__ import annotations

from helpers import make_repo, make_report

from app.cache import AnalysisStore, RepoAnalysisCache


def make_clock(start: float = 1000.0) -> tuple[dict[str, float], object]:
    """Return a mutable clock state and a clock callable."""
    state = {"t": start}
    return state, lambda: state["t"]


def test_analysis_store_put_get() -> None:
    """A stored report is returned by its analysis ID."""
    _, clock = make_clock()
    store = AnalysisStore(60, clock=clock)
    report = make_report()
    analysis_id = store.put(report)
    assert store.get(analysis_id) is report


def test_analysis_store_unknown_id() -> None:
    """Unknown IDs return None."""
    _, clock = make_clock()
    store = AnalysisStore(60, clock=clock)
    assert store.get("missing") is None


def test_analysis_store_ttl_expiry() -> None:
    """Expired entries return None and are removed."""
    state, clock = make_clock()
    store = AnalysisStore(60, clock=clock)
    analysis_id = store.put(make_report())
    state["t"] += 61
    assert store.get(analysis_id) is None


def test_analysis_store_evicts_oldest_at_limit() -> None:
    """The oldest entry is evicted when the cap is exceeded."""
    _, clock = make_clock()
    store = AnalysisStore(60, max_entries=3, clock=clock)
    ids = [store.put(make_report()) for _ in range(4)]
    assert store.get(ids[0]) is None
    assert store.get(ids[3]) is not None


def test_repo_cache_put_get_case_insensitive() -> None:
    """Lookups are case-insensitive on the repo name."""
    _, clock = make_clock()
    cache = RepoAnalysisCache(60, clock=clock)
    cache.put("Octo/Repo", "id-1")
    assert cache.get("octo/repo") == "id-1"
    assert cache.get("OCTO/REPO") == "id-1"
    assert cache.get("other/repo") is None


def test_repo_cache_recent_newest_first() -> None:
    """Recent lists the newest entry first and refreshes on re-put."""
    _, clock = make_clock()
    cache = RepoAnalysisCache(60, clock=clock)
    cache.put("a/one", "id-1")
    cache.put("b/two", "id-2")
    cache.put("a/one", "id-3")
    assert cache.recent() == ["a/one", "b/two"]


def test_repo_cache_ttl_expiry() -> None:
    """Expired entries miss and leave the recent list."""
    state, clock = make_clock()
    cache = RepoAnalysisCache(60, clock=clock)
    cache.put("a/one", "id-1")
    state["t"] += 61
    assert cache.get("a/one") is None
    assert cache.recent() == []


def test_repo_cache_stores_github_full_name() -> None:
    """The cache key comes from the report's GitHub full_name."""
    _, clock = make_clock()
    cache = RepoAnalysisCache(60, clock=clock)
    cache.put(make_repo(full_name="Octo/Repo").full_name, "id-1")
    assert cache.get("octo/repo") == "id-1"
