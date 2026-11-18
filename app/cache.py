"""In-memory caches for analyses and public repository names."""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.models import AnalysisReport, GeneratedBrief


@dataclass
class StoredAnalysis:
    """A stored analysis with its optional README and generated brief."""

    report: AnalysisReport
    readme: str | None = None
    brief: GeneratedBrief | None = None
    private: bool = False


class AnalysisStore:
    """Stores analysis reports under random IDs with TTL and size eviction."""

    def __init__(
        self,
        ttl_seconds: int,
        *,
        max_entries: int = 500,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a store with the given TTL, entry cap, and clock."""
        self._ttl = ttl_seconds
        self._max_entries = max_entries
        self._clock = clock
        self._entries: dict[str, tuple[StoredAnalysis, float]] = {}

    def put(
        self,
        report: AnalysisReport,
        *,
        readme: str | None = None,
        private: bool = False,
    ) -> str:
        """Store a report and return its new analysis ID."""
        self._drop_expired()
        analysis_id = secrets.token_urlsafe(16)
        entry = StoredAnalysis(report=report, readme=readme, private=private)
        self._entries[analysis_id] = (entry, self._clock() + self._ttl)
        while len(self._entries) > self._max_entries:
            self._entries.pop(next(iter(self._entries)))
        return analysis_id

    def get(self, analysis_id: str) -> AnalysisReport | None:
        """Return a stored report, or ``None`` when missing or expired."""
        stored = self.get_stored(analysis_id)
        return stored.report if stored is not None else None

    def get_stored(self, analysis_id: str) -> StoredAnalysis | None:
        """Return the full stored entry, or ``None`` when missing or expired."""
        entry = self._entries.get(analysis_id)
        if entry is None:
            return None
        stored, expires_at = entry
        if expires_at <= self._clock():
            del self._entries[analysis_id]
            return None
        return stored

    def set_brief(self, analysis_id: str, brief: GeneratedBrief) -> None:
        """Attach a generated brief to an existing entry."""
        entry = self._entries.get(analysis_id)
        if entry is not None:
            entry[0].brief = brief

    def _drop_expired(self) -> None:
        now = self._clock()
        expired = [key for key, (_, expires_at) in self._entries.items() if expires_at <= now]
        for key in expired:
            del self._entries[key]


class RepoAnalysisCache:
    """Maps normalized public repo names to analysis IDs, with a recent list."""

    def __init__(
        self,
        ttl_seconds: int,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create a cache with the given TTL and clock."""
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[str, tuple[str, float]] = {}

    def get(self, full_name: str) -> str | None:
        """Return the cached analysis ID for a repo name, or ``None``."""
        key = self._key(full_name)
        entry = self._entries.get(key)
        if entry is None:
            return None
        analysis_id, expires_at = entry
        if expires_at <= self._clock():
            del self._entries[key]
            return None
        return analysis_id

    def put(self, full_name: str, analysis_id: str) -> None:
        """Cache an analysis ID under the lowercased repo name."""
        key = self._key(full_name)
        self._entries.pop(key, None)
        self._entries[key] = (analysis_id, self._clock() + self._ttl)

    def recent(self) -> list[str]:
        """Return unexpired repo names, most recently cached first."""
        now = self._clock()
        expired = [key for key, (_, expires_at) in self._entries.items() if expires_at <= now]
        for key in expired:
            del self._entries[key]
        return list(reversed(self._entries))

    @staticmethod
    def _key(full_name: str) -> str:
        return full_name.lower()
