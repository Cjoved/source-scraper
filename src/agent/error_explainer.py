"""AI-assisted explanations for orchestrator failures.

The explainer is advisory only: scraper/orchestrator status is decided before
this module runs. If model setup is missing or the model returns bad output, a
deterministic fallback is returned so alerts remain useful.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field

from src.api.settings import Settings, get_settings


MAX_ACTIONS = 5


@dataclass(frozen=True)
class ErrorExplanation:
    summary: str
    likely_cause: str
    suggested_actions: list[str]
    generated_by: str = "fallback"
    model: str | None = None
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "summary": self.summary,
            "likely_cause": self.likely_cause,
            "suggested_actions": list(self.suggested_actions[:MAX_ACTIONS]),
            "generated_by": self.generated_by,
        }
        if self.model:
            payload["model"] = self.model
        if self.warning:
            payload["warning"] = self.warning
        return payload


@dataclass(frozen=True)
class ErrorSnapshot:
    job_id: str
    run_id: str
    error_type: str
    message: str
    traceback_tail: str = ""
    warnings: list[str] = field(default_factory=list)
    validation_errors: list[str] = field(default_factory=list)


class ErrorExplanationModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=300)
    likely_cause: str = Field(min_length=1, max_length=500)
    suggested_actions: list[str] = Field(min_length=1, max_length=MAX_ACTIONS)


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, flags=re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text


def _content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return str(content)


def _traceback_tail(traceback_text: str, *, lines: int = 8) -> str:
    clean = [ln.strip() for ln in traceback_text.strip().splitlines() if ln.strip()]
    return "\n".join(clean[-lines:])


def snapshot_from_run(ctx: Any) -> ErrorSnapshot:
    error = ctx.error or {}
    validation_errors: list[str] = []
    for rep in getattr(ctx, "validation_reports", []) or []:
        source_id = getattr(rep, "source_id", "unknown_source")
        errors = list(getattr(rep, "errors", []) or [])
        if errors:
            validation_errors.append(f"{source_id}: {errors[0]}")
        elif getattr(rep, "status", "ok") != "ok":
            validation_errors.append(f"{source_id}: status={getattr(rep, 'status', 'unknown')}")

    return ErrorSnapshot(
        job_id=ctx.job_id,
        run_id=ctx.run_id,
        error_type=str(error.get("type") or "JobError"),
        message=str(error.get("message") or "unknown error"),
        traceback_tail=_traceback_tail(str(error.get("traceback") or "")),
        warnings=list(getattr(ctx, "warnings", []) or [])[:5],
        validation_errors=validation_errors[:5],
    )


def _fallback_for(snapshot: ErrorSnapshot, *, warning: str | None = None) -> ErrorExplanation:
    text = " ".join(
        [
            snapshot.job_id,
            snapshot.error_type,
            snapshot.message,
            snapshot.traceback_tail,
            " ".join(snapshot.validation_errors),
        ]
    ).lower()

    if "flaresolverr" in text:
        return ErrorExplanation(
            summary="Hindi natuloy ang scrape dahil hindi available ang FlareSolverr.",
            likely_cause="Kailangan ng OpenSTAT/browser flow ang FlareSolverr para makalusot sa protected pages, pero hindi ito reachable.",
            suggested_actions=[
                "Start FlareSolverr or the compose service used by this project.",
                "Check that the FlareSolverr URL/port is reachable from this machine.",
                f"Retry the job with: uv run python -m src.orchestrator run {snapshot.job_id}",
            ],
            warning=warning,
        )

    if "qdrant" in text or "connection refused" in text or "connecterror" in text:
        return ErrorExplanation(
            summary="Hindi natuloy ang index/search step dahil hindi reachable ang Qdrant.",
            likely_cause="Down ang Qdrant service, mali ang QDRANT_URL, o may network/API key issue.",
            suggested_actions=[
                "Start Qdrant and verify the configured QDRANT_URL.",
                "Check QDRANT_API_KEY if the service requires authentication.",
                f"Retry the job with: uv run python -m src.orchestrator run {snapshot.job_id}",
            ],
            warning=warning,
        )

    if snapshot.error_type == "ValidationError" or snapshot.validation_errors:
        return ErrorExplanation(
            summary="Natapos ang scrape pero bagsak ang output validation.",
            likely_cause="May kulang, empty, duplicate, o malformed records sa generated corpus/output file.",
            suggested_actions=[
                f"Open data/runs/{snapshot.run_id}/validation_report.json and review the failed source.",
                "Inspect the first validation error before rerunning, especially record counts and required fields.",
                f"After fixing the source/output issue, rerun: uv run python -m src.orchestrator run {snapshot.job_id}",
            ],
            warning=warning,
        )

    if "wasabi" in text or "s3" in text:
        return ErrorExplanation(
            summary="Nag-fail ang backup/upload step after the scraper run.",
            likely_cause="Possible Wasabi/S3 credentials, bucket, region, permission, or network problem.",
            suggested_actions=[
                "Check Wasabi/S3 environment variables and bucket permissions.",
                "Confirm network access to the object storage endpoint.",
                f"Retry the job after storage is healthy: uv run python -m src.orchestrator run {snapshot.job_id}",
            ],
            warning=warning,
        )

    if "timeout" in text or "timed out" in text:
        return ErrorExplanation(
            summary="The job took longer than expected or a request timed out.",
            likely_cause="The source site, browser fetcher, network, or downstream service responded too slowly.",
            suggested_actions=[
                "Check recent logs for the slow request or scraper step.",
                "Verify source site, browser service, and network stability.",
                f"Retry when dependencies are stable: uv run python -m src.orchestrator run {snapshot.job_id}",
            ],
            warning=warning,
        )

    return ErrorExplanation(
        summary="Nag-fail ang job habang tumatakbo ang scraper/orchestrator.",
        likely_cause="Generic job error. The exact cause is in the traceback and manifest for this run.",
        suggested_actions=[
            f"Open data/runs/{snapshot.run_id}/manifest.json and inspect error.traceback.",
            "Check the latest orchestrator logs around this run_id.",
            f"Fix the root cause, then rerun: uv run python -m src.orchestrator run {snapshot.job_id}",
        ],
        warning=warning,
    )


def _prompt(snapshot: ErrorSnapshot) -> str:
    payload = {
        "job_id": snapshot.job_id,
        "run_id": snapshot.run_id,
        "error_type": snapshot.error_type,
        "message": snapshot.message,
        "traceback_tail": snapshot.traceback_tail,
        "warnings": snapshot.warnings,
        "validation_errors": snapshot.validation_errors,
    }
    return (
        "Explain this scraper/orchestrator failure for an operator in concise Filipino/English.\n"
        "Return only strict JSON with keys: summary, likely_cause, suggested_actions.\n"
        "Use practical actions. Do not invent file paths, URLs, secrets, or successful recovery.\n"
        f"Failure snapshot:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def explain_error(
    snapshot: ErrorSnapshot,
    *,
    settings: Settings | None = None,
    model_factory: Callable[[Settings], Any] | None = None,
) -> ErrorExplanation:
    settings = settings or get_settings()
    if not settings.agent_enabled:
        return _fallback_for(snapshot, warning="AI explanation skipped because AGENT_ENABLED=false.")

    try:
        if model_factory is None:
            from src.agent.client import create_chat_model

            model_factory = create_chat_model
        model = model_factory(settings)

        from langchain_core.messages import HumanMessage, SystemMessage

        response = model.invoke(
            [
                SystemMessage(
                    content=(
                        "You are an operations assistant for an agricultural data scraper. "
                        "Explain failures clearly and recommend safe next steps."
                    )
                ),
                HumanMessage(content=_prompt(snapshot)),
            ]
        )
        raw = _content_to_text(getattr(response, "content", response))
        data = json.loads(_strip_code_fence(raw))
        parsed = ErrorExplanationModelOutput.model_validate(data)
        return ErrorExplanation(
            summary=parsed.summary.strip(),
            likely_cause=parsed.likely_cause.strip(),
            suggested_actions=[action.strip() for action in parsed.suggested_actions if action.strip()],
            generated_by="ai",
            model=settings.agent_model.strip() or settings.agent_provider,
        )
    except Exception as exc:
        return _fallback_for(
            snapshot,
            warning=f"AI explanation fallback used: {exc.__class__.__name__}: {exc}",
        )


def explain_run_failure(
    ctx: Any,
    *,
    settings: Settings | None = None,
    model_factory: Callable[[Settings], Any] | None = None,
) -> ErrorExplanation:
    return explain_error(snapshot_from_run(ctx), settings=settings, model_factory=model_factory)
