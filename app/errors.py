"""Typed application errors."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import RateLimitInfo


class AppError(Exception):
    """Base error rendered by the global exception handler."""

    status_code = 502

    def __init__(self, message: str, *, rate_limit: RateLimitInfo | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.rate_limit = rate_limit


class InvalidRepoInputError(AppError):
    """Raised when the repository input cannot be normalized."""

    status_code = 400


class RepoNotFoundError(AppError):
    """Raised when a repository does not exist or is private."""

    status_code = 404


class InvalidTokenError(AppError):
    """Raised when GitHub rejects the supplied token."""

    status_code = 403


class AccessDeniedError(AppError):
    """Raised when GitHub denies access to a resource."""

    status_code = 403


class RateLimitError(AppError):
    """Raised when GitHub rate limits the request."""

    status_code = 429


class GitHubUnavailableError(AppError):
    """Raised when GitHub or the network is unavailable."""

    status_code = 502


class AnalysisNotFoundError(AppError):
    """Raised when an analysis ID is unknown or expired."""

    status_code = 404


class BriefGenerationError(AppError):
    """Raised when the LLM brief request fails."""

    status_code = 502


class GitHubStatusError(Exception):
    """Internal non-fatal GitHub HTTP status used for section mapping."""

    def __init__(self, status_code: int, message: str, *, rate_limit: RateLimitInfo) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.rate_limit = rate_limit


class SectionUnavailableError(Exception):
    """Raised when one report section cannot be fetched."""

    def __init__(self, section: str, message: str) -> None:
        super().__init__(message)
        self.section = section
        self.message = message
