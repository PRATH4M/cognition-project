"""FastAPI routes and error handlers."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, FastAPI, Form, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, SecretStr

from app.cache import AnalysisStore, RepoAnalysisCache
from app.config import Settings
from app.errors import AppError
from app.github_client import GitHubClient
from app.service import AnalysisOutcome, AnalysisService


class AnalyzeRequest(BaseModel):
    """JSON body for ``POST /api/analyze``."""

    repo: str
    token: str | None = None


router = APIRouter()


def _service(request: Request) -> AnalysisService:
    return cast(AnalysisService, request.app.state.service)


def _templates(request: Request) -> Jinja2Templates:
    return cast(Jinja2Templates, request.app.state.templates)


def _is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness probe for Docker and Compose."""
    return {"status": "ok"}


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> Response:
    """Render the repo input form and recent public analyses."""
    return _templates(request).TemplateResponse(
        request, "index.html", {"recent": _service(request).recent()}
    )


@router.post("/analyze", response_class=HTMLResponse)
async def analyze_form(
    request: Request,
    repo: Annotated[str, Form()],
    token: Annotated[str, Form()] = "",
) -> Response:
    """Analyze a repo from the HTML form."""
    outcome = await _service(request).analyze(repo, user_token=SecretStr(token) if token else None)
    template = "partials/report.html" if _is_htmx(request) else "report.html"
    return _templates(request).TemplateResponse(request, template, _report_context(outcome))


@router.post("/api/analyze")
async def api_analyze(request: Request, body: AnalyzeRequest) -> JSONResponse:
    """Analyze a repo and return the report as JSON."""
    outcome = await _service(request).analyze(
        body.repo, user_token=SecretStr(body.token) if body.token else None
    )
    return JSONResponse(_api_payload(outcome))


async def app_error_handler(request: Request, exc: Exception) -> Response:
    """Render typed application errors without stack traces."""
    app_exc = cast(AppError, exc)
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": app_exc.message}, status_code=app_exc.status_code)
    template = "partials/error.html" if _is_htmx(request) else "error.html"
    return _templates(request).TemplateResponse(
        request,
        template,
        {"message": app_exc.message, "rate_limit": app_exc.rate_limit},
        status_code=app_exc.status_code,
    )


async def validation_error_handler(request: Request, _exc: Exception) -> Response:
    """Return a generic 400 for request validation errors, never echoing input."""
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Invalid request"}, status_code=400)
    return _templates(request).TemplateResponse(
        request, "error.html", {"message": "Invalid request"}, status_code=400
    )


async def unexpected_error_handler(request: Request, _exc: Exception) -> Response:
    """Return a plain 500 for unexpected errors."""
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Internal server error"}, status_code=500)
    return HTMLResponse("Internal server error", status_code=500)


def _report_context(outcome: AnalysisOutcome) -> dict[str, object]:
    weeks = [{"week": w.week, "total": w.total} for w in reversed(outcome.report.activity.weeks)]
    return {
        "outcome": outcome,
        "report": outcome.report,
        "rate_limit": outcome.rate_limit,
        "chart_data": weeks,
    }


def _api_payload(outcome: AnalysisOutcome) -> dict[str, object]:
    rate_limit = outcome.rate_limit.model_dump(mode="json") if outcome.rate_limit else None
    return {
        "analysis_id": outcome.analysis_id,
        "cached": outcome.cached,
        "is_private": outcome.is_private,
        "rate_limit": rate_limit,
        "report": outcome.report.model_dump(mode="json"),
    }


def _commas(value: int) -> str:
    """Format an integer with thousands separators."""
    return f"{value:,}"


def _lifespan(
    settings: Settings | None,
    service: AnalysisService | None,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if service is None:
            resolved = settings or Settings()
            client = GitHubClient(server_token=resolved.github_token)
            app.state.service = AnalysisService(
                client,
                AnalysisStore(resolved.cache_ttl_seconds),
                RepoAnalysisCache(resolved.cache_ttl_seconds),
            )
            app.state.github_client = client
        yield
        existing: GitHubClient | None = getattr(app.state, "github_client", None)
        if existing is not None:
            await existing.aclose()

    return lifespan


def create_app(
    settings: Settings | None = None,
    service: AnalysisService | None = None,
) -> FastAPI:
    """Build the FastAPI app, optionally with injected settings or service."""
    app = FastAPI(title="GitHub Repo Analyzer", lifespan=_lifespan(settings, service))
    if service is not None:
        app.state.service = service
    templates = Jinja2Templates(directory=Path(__file__).parent / "templates")
    templates.env.filters["commas"] = _commas
    app.state.templates = templates
    app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent / "static"),
        name="static",
    )
    app.include_router(router)
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)
    return app


app = create_app()
