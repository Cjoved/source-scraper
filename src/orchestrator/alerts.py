"""Failure alerts for orchestrator runs (P3.6).

Primary free channels: Telegram, Discord, local file (data/alerts/).
Optional: ntfy, generic webhook, Slack, SMTP.
"""

from __future__ import annotations

import json
import os
import smtplib
from dataclasses import dataclass
from email.mime.text import MIMEText
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from src.services.config import data_path

if TYPE_CHECKING:
    from src.orchestrator.run_context import RunContext

ALERTS_DIR = data_path("alerts")

ALERT_BRAND_TITLE = "AGENT SCRAPER"
ALERT_BRAND_SUBTITLE = "ALERT notification"

# Clean Telegram templates (Image-1 style): header → one-liner → emoji bullets → meta → footer.
# Stack trace stays in expandable blockquote only when present (tap to open).
ALERT_FAILURE_MESSAGE_TEMPLATE = (
    "{severity_badge}\n"
    "\n"
    "{agent}\n"
    "{intro_plain}\n"
    "\n"
    "❌ {error_plain}\n"
    "{bullets_plain}"
    "{detail_block_plain}"
    "\n"
    "⏱ {duration_human}  ·  {run_id}\n"
    "\n"
    "🔁 {retry_command}\n"
    "📄 {manifest_short}\n"
    "{validation_block_plain}"
    "\n"
    "Agent Scraper 🤖"
)

ALERT_SUCCESS_MESSAGE_TEMPLATE = (
    "{severity_badge}\n"
    "\n"
    "{agent}\n"
    "{intro_plain}\n"
    "\n"
    "✅ {summary_plain}\n"
    "{bullets_plain}"
    "\n"
    "⏱ {duration_human}  ·  {run_id}\n"
    "\n"
    "📄 {manifest_short}\n"
    "{validation_block_plain}"
    "\n"
    "Agent Scraper 🤖"
)

ALERT_WARNING_MESSAGE_TEMPLATE = (
    "{severity_badge}\n"
    "\n"
    "{agent}\n"
    "{intro_plain}\n"
    "\n"
    "⚠️ {summary_plain}\n"
    "{detail_block_plain}"
    "\n"
    "⏱ {duration_human}  ·  {run_id}\n"
    "\n"
    "📄 {manifest_short}\n"
    "{validation_block_plain}"
    "\n"
    "Agent Scraper 🤖"
)

ALERT_FAILURE_TELEGRAM_TEMPLATE = (
    "<b>{severity_badge}</b>\n"
    "\n"
    "<b>{agent}</b>\n"
    "<i>{intro}</i>\n"
    "\n"
    "❌ {error}\n"
    "{bullets_html}"
    "{detail_block_html}"
    "\n"
    "⏱ <code>{duration_human}</code>  ·  <code>{run_id}</code>\n"
    "\n"
    "🔁 <code>{retry_command}</code>\n"
    "📄 <code>{manifest_short}</code>\n"
    "{validation_block_html}"
    "\n"
    "<i>Agent Scraper 🤖</i>"
)

ALERT_SUCCESS_TELEGRAM_TEMPLATE = (
    "<b>{severity_badge}</b>\n"
    "\n"
    "<b>{agent}</b>\n"
    "<i>{intro}</i>\n"
    "\n"
    "✅ {summary}\n"
    "{bullets_html}"
    "\n"
    "⏱ <code>{duration_human}</code>  ·  <code>{run_id}</code>\n"
    "\n"
    "📄 <code>{manifest_short}</code>\n"
    "{validation_block_html}"
    "\n"
    "<i>Agent Scraper 🤖</i>"
)

ALERT_WARNING_TELEGRAM_TEMPLATE = (
    "<b>{severity_badge}</b>\n"
    "\n"
    "<b>{agent}</b>\n"
    "<i>{intro}</i>\n"
    "\n"
    "⚠️ {summary}\n"
    "{detail_block_html}"
    "\n"
    "⏱ <code>{duration_human}</code>  ·  <code>{run_id}</code>\n"
    "\n"
    "📄 <code>{manifest_short}</code>\n"
    "{validation_block_html}"
    "\n"
    "<i>Agent Scraper 🤖</i>"
)

# Human-readable agent labels for alert messages (channel posts use channel avatar, not bot).
JOB_ALERT_LABELS: dict[str, str] = {
    "philrice": "PhilRice",
    "philrice_news": "PhilRice News",
    "pinoyrice": "PinoyRice",
    "irri": "IRRI",
    "openstat": "OpenSTAT",
    "openstat_index": "OpenSTAT Price Index",
    "prism_scrape": "PRiSM Browser",
    "prism_yield": "PRiSM Yield Export",
    "prism_index": "PRiSM Index",
    "corpus_rag_index": "Corpus RAG Index",
    "alert_test": "Test Alert",
}

JOB_ALERT_EMOJI: dict[str, str] = {
    "philrice": "🌾",
    "philrice_news": "📰",
    "pinoyrice": "🍚",
    "irri": "🔬",
    "openstat": "📊",
    "openstat_index": "💰",
    "prism_scrape": "🌐",
    "prism_yield": "📈",
    "prism_index": "📇",
    "corpus_rag_index": "📚",
    "alert_test": "🔔",
}


def _job_agent_parts(job_id: str) -> tuple[str, str, str]:
    name = JOB_ALERT_LABELS.get(job_id) or job_id.replace("_", " ").title()
    emoji = JOB_ALERT_EMOJI.get(job_id, "🤖")
    return emoji, name, f"{emoji} {name}"


def _job_agent_label(job_id: str) -> str:
    return _job_agent_parts(job_id)[2]


def _truncate_text(text: str, *, limit: int = 280) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3] + "..."


def _truncate_multiline(text: str, *, limit: int = 500) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _duration_human(seconds: float | None) -> str:
    if seconds is None:
        return "n/a"
    total = int(seconds)
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def _short_path(path: str | Path) -> str:
    p = Path(path)
    try:
        return str(p.relative_to(Path.cwd()))
    except ValueError:
        parts = p.parts
        if "data" in parts:
            idx = parts.index("data")
            return str(Path(*parts[idx:]))
    return str(p)


def _run_artifact_path(ctx: RunContext, filename: str) -> str:
    return f"data/runs/{ctx.run_id}/{filename}"


def _traceback_summary(ctx: RunContext) -> str:
    tb = (ctx.error or {}).get("traceback", "")
    if not tb:
        return ""
    lines = [ln.strip() for ln in tb.strip().splitlines() if ln.strip()]
    return "\n".join(lines[-4:])


def _validation_detail(ctx: RunContext) -> str:
    if not ctx.validation_reports:
        return ""
    lines: list[str] = []
    for rep in ctx.validation_reports:
        if rep.status == "ok":
            continue
        if rep.errors:
            lines.append(f"{rep.source_id}: {rep.errors[0]}")
            extra = len(rep.errors) - 1
            if extra > 0:
                lines.append(f"  (+{extra} more errors)")
        else:
            lines.append(f"{rep.source_id}: status={rep.status}")
    return "\n".join(lines[:6])


def _error_detail(ctx: RunContext) -> str:
    error_type = (ctx.error or {}).get("type", "")
    parts: list[str] = []

    validation = _validation_detail(ctx)
    if validation:
        parts.append(validation)

    traceback = _traceback_summary(ctx)
    if traceback:
        parts.append(traceback)

    if ctx.warnings:
        parts.append("Warnings: " + "; ".join(ctx.warnings[:3]))

    if parts:
        return _truncate_multiline("\n".join(parts))

    if error_type in {"TestAlert", "TestError"}:
        return (
            "This is a TEST alert only — not a real failure.\n"
            "Real errors show validation issues or the last traceback lines here."
        )

    return "Open manifest.json → error.traceback for the full stack trace."


AlertKind = str  # failure | success | warning | timeout


@dataclass(frozen=True)
class SeverityTheme:
    badge: str
    bar: str
    discord_color: int


def _is_timeout_warning(ctx: RunContext) -> bool:
    return any("exceeded configured timeout" in w for w in ctx.warnings)


def _alert_kind(ctx: RunContext) -> AlertKind:
    if ctx.status == "failed":
        return "failure"
    if ctx.warnings:
        if _is_timeout_warning(ctx):
            return "timeout"
        return "warning"
    return "success"


def _resolve_severity_theme(ctx: RunContext) -> SeverityTheme:
    kind = _alert_kind(ctx)
    # Discord sidebar colors — official palette where possible (decimal int, not hex string).
    # https://discord.com/branding — blurple 0x5865F2, green 0x57F287, red 0xED4245, yellow 0xFEE75C
    if kind == "success":
        return SeverityTheme(
            badge="🟢 JOB OK",
            bar="🟢 ━━━━━━━━━━━━━━━━",
            discord_color=0x57F287,
        )
    if kind == "timeout":
        return SeverityTheme(
            badge="🟣 TIMEOUT WARNING",
            bar="🟣 ━━━━━━━━━━━━━━━━",
            discord_color=0x9B59B6,
        )
    if kind == "warning":
        return SeverityTheme(
            badge="🟡 JOB WARNING",
            bar="🟡 ━━━━━━━━━━━━━━━━",
            discord_color=0xFEE75C,
        )

    error_type = (ctx.error or {}).get("type", "JobError")
    themes: dict[str, SeverityTheme] = {
        "ValidationError": SeverityTheme(
            badge="🟠 VALIDATION FAILED",
            bar="🟠 ━━━━━━━━━━━━━━━━",
            discord_color=0xE67E22,
        ),
        "PreflightError": SeverityTheme(
            badge="🟡 PREFLIGHT FAILED",
            bar="🟡 ━━━━━━━━━━━━━━━━",
            discord_color=0xFEE75C,
        ),
        "TestAlert": SeverityTheme(
            badge="🔵 TEST ALERT",
            bar="🔵 ━━━━━━━━━━━━━━━━",
            discord_color=0x5865F2,
        ),
        "TestError": SeverityTheme(
            badge="🔵 TEST ALERT",
            bar="🔵 ━━━━━━━━━━━━━━━━",
            discord_color=0x5865F2,
        ),
    }
    return themes.get(
        error_type,
        SeverityTheme(
            badge="🔴 JOB FAILED",
            bar="🔴 ━━━━━━━━━━━━━━━━",
            discord_color=0xED4245,
        ),
    )


def _retry_command(job_id: str) -> str:
    return f"uv run python -m src.orchestrator run {job_id}"


def _outputs_summary(ctx: RunContext) -> str:
    if not ctx.validation_reports:
        return "No corpus outputs tracked for this job."
    lines: list[str] = []
    for rep in ctx.validation_reports:
        if rep.status == "ok":
            lines.append(f"✓ {rep.source_id}: {rep.records:,} records")
        elif rep.status == "skipped":
            lines.append(f"○ {rep.source_id}: skipped")
        else:
            lines.append(f"✗ {rep.source_id}: {rep.status}")
    return "\n".join(lines) if lines else "Job completed."


def _success_summary(ctx: RunContext) -> str:
    if ctx.validation_passed:
        return "Job completed — corpus validation passed."
    if ctx.validation_passed is None:
        return "Job completed successfully."
    return "Job completed."


def _warning_summary(ctx: RunContext) -> str:
    if ctx.warnings:
        return _truncate_text("; ".join(ctx.warnings[:3]), limit=400)
    return "Warning detected during run."


def _intro_line(ctx: RunContext) -> str:
    _, agent_name, _ = _job_agent_parts(ctx.job_id)
    kind = _alert_kind(ctx)
    if kind == "success":
        return f"{agent_name} job completed successfully."
    if kind == "timeout":
        return f"{agent_name} job finished but exceeded the time limit."
    if kind == "warning":
        return f"{agent_name} job finished with warnings."
    return f"{agent_name} job did not finish."


def _output_bullets(ctx: RunContext) -> str:
    if not ctx.validation_reports:
        return ""
    lines: list[str] = []
    for rep in ctx.validation_reports:
        if rep.status == "ok" and rep.records:
            lines.append(f"✅ {rep.source_id}: {rep.records:,} records")
        elif rep.status == "ok":
            lines.append(f"✅ {rep.source_id}: validated")
    if not lines:
        return ""
    return "\n".join(lines) + "\n"


def _detail_block(ctx: RunContext) -> tuple[str, str]:
    """Plain + HTML detail blocks; traceback collapsed in Telegram when long."""
    tb = _traceback_summary(ctx)
    if tb:
        plain = f"\n{tb}\n"
        html = f"\n<blockquote expandable>{escape(tb)}</blockquote>\n"
        return plain, html

    if _alert_kind(ctx) not in {"failure", "warning", "timeout"}:
        return "", ""

    detail = _validation_detail(ctx)
    if not detail:
        return "", ""
    plain = f"\n{detail}\n"
    html = f"\n<blockquote>{escape(_truncate_multiline(detail))}</blockquote>\n"
    return plain, html


def _message_templates(ctx: RunContext) -> tuple[str, str]:
    kind = _alert_kind(ctx)
    if kind == "success":
        return ALERT_SUCCESS_MESSAGE_TEMPLATE, ALERT_SUCCESS_TELEGRAM_TEMPLATE
    if kind in {"warning", "timeout"}:
        return ALERT_WARNING_MESSAGE_TEMPLATE, ALERT_WARNING_TELEGRAM_TEMPLATE
    return ALERT_FAILURE_MESSAGE_TEMPLATE, ALERT_FAILURE_TELEGRAM_TEMPLATE


def _validation_blocks(ctx: RunContext) -> tuple[str, str]:
    if ctx.validation_passed is not False:
        return "", ""
    short = _run_artifact_path(ctx, "validation_report.json")
    return (
        f"validation: {short}\n",
        f"validation → <code>{escape(short)}</code>\n",
    )


def _apply_template(template: str, values: dict[str, str]) -> str:
    """Replace {placeholders} without using str.format (errors may contain braces)."""
    rendered = template.replace("\\n", "\n")
    for key, value in values.items():
        rendered = rendered.replace("{" + key + "}", value)
    return rendered


def _alert_template_values(ctx: RunContext) -> dict[str, str]:
    kind = _alert_kind(ctx)
    err = (ctx.error or {}).get("message", "unknown error")
    error_type = (ctx.error or {}).get("type", "JobError")
    emoji, agent_name, agent = _job_agent_parts(ctx.job_id)
    warnings = "; ".join(ctx.warnings[:3]) if ctx.warnings else ""
    outputs_plain = _outputs_summary(ctx)
    summary_plain = (
        _success_summary(ctx)
        if kind == "success"
        else _warning_summary(ctx)
        if kind in {"warning", "timeout"}
        else _truncate_text(err)
    )
    err_plain = summary_plain
    detail_plain = (
        _error_detail(ctx)
        if kind in {"failure", "warning", "timeout"}
        else outputs_plain
    )
    if kind == "success":
        error_type = "Success"
    elif kind == "timeout":
        error_type = "TimeoutWarning"
    elif kind == "warning":
        error_type = "Warning"

    validation_plain, validation_html = _validation_blocks(ctx)
    theme = _resolve_severity_theme(ctx)
    intro = _intro_line(ctx)
    bullets_plain = _output_bullets(ctx)
    bullets_html = escape(bullets_plain.rstrip("\n")) + ("\n" if bullets_plain else "")
    detail_block_plain, detail_block_html = _detail_block(ctx)
    return {
        "brand_title": ALERT_BRAND_TITLE,
        "brand_subtitle": ALERT_BRAND_SUBTITLE,
        "severity_badge": theme.badge,
        "severity_bar": theme.bar,
        "severity_line": theme.badge,
        "discord_color": str(theme.discord_color),
        "agent": agent,
        "agent_name": agent_name,
        "agent_emoji": emoji,
        "job_id": ctx.job_id,
        "run_id": ctx.run_id,
        "status": ctx.status,
        "intro": escape(intro),
        "intro_plain": intro,
        "summary": escape(summary_plain),
        "summary_plain": summary_plain,
        "outputs": escape(outputs_plain),
        "outputs_plain": outputs_plain,
        "bullets_plain": bullets_plain,
        "bullets_html": bullets_html,
        "error": escape(err_plain),
        "error_plain": err_plain,
        "error_detail": escape(detail_plain),
        "error_detail_plain": detail_plain,
        "detail_block_plain": detail_block_plain,
        "detail_block_html": detail_block_html,
        "error_type": error_type,
        "manifest": str(ctx.manifest_path),
        "manifest_short": _run_artifact_path(ctx, "manifest.json"),
        "duration": (
            f"{ctx.duration_seconds}s" if ctx.duration_seconds is not None else "n/a"
        ),
        "duration_human": _duration_human(ctx.duration_seconds),
        "retry_command": _retry_command(ctx.job_id) if kind == "failure" else "",
        "validation_block_plain": validation_plain,
        "validation_block_html": validation_html,
        "warnings": warnings,
    }


def _render_alert_template(template: str, ctx: RunContext) -> str:
    return _apply_template(template, _alert_template_values(ctx))


def alerts_enabled() -> bool:
    return os.getenv("ALERT_ENABLED", "false").strip().lower() in ("true", "1", "yes")


def alert_on_timeout() -> bool:
    return os.getenv("ALERT_ON_TIMEOUT", "false").strip().lower() in ("true", "1", "yes")


def alert_on_success() -> bool:
    return os.getenv("ALERT_ON_SUCCESS", "false").strip().lower() in ("true", "1", "yes")


def alert_on_warning() -> bool:
    return os.getenv("ALERT_ON_WARNING", "false").strip().lower() in ("true", "1", "yes")


def local_alerts_enabled() -> bool:
    raw = os.getenv("ALERT_LOCAL_FILE", "true").strip().lower()
    return raw in ("true", "1", "yes")


def telegram_configured() -> bool:
    return bool(
        os.getenv("ALERT_TELEGRAM_BOT_TOKEN", "").strip()
        and os.getenv("ALERT_TELEGRAM_CHAT_ID", "").strip()
    )


def discord_configured() -> bool:
    return bool(os.getenv("ALERT_DISCORD_WEBHOOK_URL", "").strip())


def _alert_message(ctx: RunContext) -> str:
    plain_tpl, _ = _message_templates(ctx)
    return _render_alert_template(plain_tpl, ctx)


def _alert_message_html(ctx: RunContext) -> str:
    _, html_tpl = _message_templates(ctx)
    return _render_alert_template(html_tpl, ctx)


def _alert_payload(ctx: RunContext) -> dict[str, object]:
    return {
        "run_id": ctx.run_id,
        "job_id": ctx.job_id,
        "status": ctx.status,
        "error": ctx.error,
        "warnings": ctx.warnings,
        "manifest_path": str(ctx.manifest_path),
        "duration_seconds": ctx.duration_seconds,
    }


def _should_alert(ctx: RunContext) -> bool:
    if ctx.status == "failed":
        return True
    if ctx.status != "ok":
        return False
    if ctx.warnings:
        if _is_timeout_warning(ctx) and alert_on_timeout():
            return True
        if not _is_timeout_warning(ctx) and alert_on_warning():
            return True
        if _is_timeout_warning(ctx) and alert_on_warning() and not alert_on_timeout():
            return True
        return False
    return alert_on_success()


_HTTP_USER_AGENT = "AgentScraper/1.0 (+https://github.com/source-scraper)"


def _post_json(url: str, payload: dict[str, object], *, timeout: float = 15.0) -> None:
    body = json.dumps(payload).encode("utf-8")
    req = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "User-Agent": _HTTP_USER_AGENT,
        },
        method="POST",
    )
    with urlopen(req, timeout=timeout) as resp:
        resp.read()


def _post_raw(
    url: str,
    data: bytes,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 15.0,
) -> None:
    req = Request(url, data=data, headers=headers or {}, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        resp.read()


def _send_local_file(ctx: RunContext) -> list[str]:
    if not local_alerts_enabled():
        return []
    try:
        ALERTS_DIR.mkdir(parents=True, exist_ok=True)
        payload = _alert_payload(ctx)
        payload["message"] = _alert_message(ctx)
        run_path = ALERTS_DIR / f"{ctx.run_id}.json"
        kind = _alert_kind(ctx)
        latest_name = {
            "success": "last_success.json",
            "warning": "last_warning.json",
            "timeout": "last_warning.json",
        }.get(kind, "last_failure.json")
        latest_path = ALERTS_DIR / latest_name
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        run_path.write_text(text, encoding="utf-8")
        latest_path.write_text(text, encoding="utf-8")
        return ["local_file"]
    except OSError as exc:
        return [f"local_file_failed:{exc}"]


def _send_telegram(ctx: RunContext) -> list[str]:
    token = os.getenv("ALERT_TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("ALERT_TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        return []
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": _alert_message_html(ctx),
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        _post_json(url, payload)
        return ["telegram"]
    except (URLError, OSError, TimeoutError) as exc:
        return [f"telegram_failed:{exc}"]


def _discord_description(ctx: RunContext, values: dict[str, str]) -> str:
    """Embed body — Markdown (not HTML). Max 4096 chars."""
    kind = _alert_kind(ctx)
    lines = [
        f"**{values['agent']}**",
        f"*{values['intro_plain']}*",
        "",
    ]
    if kind == "success":
        lines.append(f"✅ {values['summary_plain']}")
        bullets = values["bullets_plain"].strip()
        if bullets:
            lines.extend(["", bullets])
    elif kind in {"warning", "timeout"}:
        lines.append(f"⚠️ {values['summary_plain']}")
    else:
        lines.append(f"❌ {values['summary_plain']}")
    return "\n".join(lines)[:4096]


def _discord_embed_fields(ctx: RunContext, values: dict[str, str]) -> list[dict[str, object]]:
    """Structured fields — inline pairs first, full-width detail last."""
    fields: list[dict[str, object]] = [
        {"name": "⏱ Duration", "value": values["duration_human"], "inline": True},
        {"name": "🏷 Type", "value": values["error_type"], "inline": True},
        {"name": "🆔 Run ID", "value": f"`{values['run_id']}`", "inline": False},
    ]
    if values["retry_command"]:
        fields.append(
            {
                "name": "🔁 Retry",
                "value": f"```{values['retry_command']}```",
                "inline": False,
            }
        )
    tb = _traceback_summary(ctx)
    if tb:
        fields.append(
            {"name": "🔍 Detail", "value": f"```{tb[:900]}```", "inline": False}
        )
    elif values["error_detail_plain"] and _alert_kind(ctx) != "success":
        fields.append(
            {
                "name": "🔍 Detail",
                "value": values["error_detail_plain"][:1024],
                "inline": False,
            }
        )
    fields.append(
        {"name": "📄 Manifest", "value": f"`{values['manifest_short']}`", "inline": False}
    )
    if values["validation_block_plain"].strip():
        path = values["validation_block_plain"].replace("validation:", "").strip()
        fields.append(
            {"name": "📋 Validation", "value": f"`{path}`", "inline": False}
        )
    return fields


def _build_discord_payload(ctx: RunContext) -> dict[str, object]:
    """
    Discord webhook embed template.

    API: POST webhook URL with JSON { username, embeds: [{ title, description, color, fields, footer, timestamp }] }
    - color: decimal integer (0xED4245 red, 0x57F287 green) — NOT hex string
    - description/fields: Markdown (**bold**, *italic*, `code`, ```blocks```)
    - max 25 fields, 6000 chars total per embed
    """
    values = _alert_template_values(ctx)
    embed: dict[str, object] = {
        "title": values["severity_badge"],
        "description": _discord_description(ctx, values),
        "color": int(values["discord_color"]),
        "fields": _discord_embed_fields(ctx, values),
        "footer": {"text": "Agent Scraper 🤖"},
    }
    if ctx.ended_at is not None:
        embed["timestamp"] = ctx.ended_at.isoformat()
    return {
        "username": ALERT_BRAND_TITLE,
        "embeds": [embed],
    }


def _send_discord(ctx: RunContext) -> list[str]:
    url = os.getenv("ALERT_DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        return []
    try:
        _post_json(url, _build_discord_payload(ctx))
        return ["discord"]
    except (URLError, OSError, TimeoutError) as exc:
        return [f"discord_failed:{exc}"]


def _send_ntfy(ctx: RunContext) -> list[str]:
    topic = os.getenv("ALERT_NTFY_TOPIC", "").strip()
    if not topic:
        return []
    server = os.getenv("ALERT_NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/")
    url = f"{server}/{quote(topic, safe='')}"
    title = f"scraper failed: {ctx.job_id}"
    headers = {
        "Title": title,
        "Tags": "warning,skull",
        "Priority": "high",
    }
    try:
        _post_raw(url, _alert_message(ctx).encode("utf-8"), headers=headers)
        return ["ntfy"]
    except (URLError, OSError, TimeoutError) as exc:
        return [f"ntfy_failed:{exc}"]


def _send_webhook(ctx: RunContext) -> list[str]:
    url = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        return []
    try:
        _post_json(url, _alert_payload(ctx))
        return ["webhook"]
    except (URLError, OSError, TimeoutError) as exc:
        return [f"webhook_failed:{exc}"]


def _send_slack(ctx: RunContext) -> list[str]:
    url = os.getenv("ALERT_SLACK_WEBHOOK_URL", "").strip()
    if not url:
        return []
    err = (ctx.error or {}).get("message", "unknown error")
    text = (
        f":x: Orchestrator job failed: *{ctx.job_id}*\n"
        f"run_id: `{ctx.run_id}`\n"
        f"error: {err}\n"
        f"manifest: `{ctx.manifest_path}`"
    )
    try:
        _post_json(url, {"text": text})
        return ["slack"]
    except (URLError, OSError, TimeoutError) as exc:
        return [f"slack_failed:{exc}"]


def _send_email(ctx: RunContext) -> list[str]:
    host = os.getenv("ALERT_SMTP_HOST", "").strip()
    to_raw = os.getenv("ALERT_EMAIL_TO", "").strip()
    from_addr = os.getenv("ALERT_EMAIL_FROM", "").strip()
    if not host or not to_raw or not from_addr:
        return []

    port = int(os.getenv("ALERT_SMTP_PORT", "587"))
    user = os.getenv("ALERT_SMTP_USER", "").strip()
    password = os.getenv("ALERT_SMTP_PASSWORD", "")
    recipients = [a.strip() for a in to_raw.split(",") if a.strip()]
    subject = f"[source-scraper] job failed: {ctx.job_id} ({ctx.run_id})"
    msg = MIMEText(_alert_message(ctx))
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(recipients)

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.sendmail(from_addr, recipients, msg.as_string())
        return ["email"]
    except (OSError, smtplib.SMTPException) as exc:
        return [f"email_failed:{exc}"]


def send_run_alert(ctx: RunContext) -> list[str]:
    """Send job alerts when ALERT_ENABLED=true (failures always; success/warning opt-in)."""
    if not alerts_enabled() or not _should_alert(ctx):
        return []

    sent: list[str] = []
    sent.extend(_send_local_file(ctx))
    sent.extend(_send_telegram(ctx))
    sent.extend(_send_discord(ctx))
    sent.extend(_send_ntfy(ctx))
    sent.extend(_send_webhook(ctx))
    sent.extend(_send_slack(ctx))
    sent.extend(_send_email(ctx))
    return sent


def send_test_alerts(
    *,
    job_id: str = "alert_test",
    kind: AlertKind = "failure",
) -> list[str]:
    """Send a test notification to every configured channel."""
    from datetime import UTC, datetime

    from src.orchestrator.config import JobSpec, OrchestratorConfig
    from src.orchestrator.run_context import RunContext
    from src.scripts.validate_corpus import FileReport

    spec = JobSpec(
        id=job_id,
        enabled=True,
        cron="0 0 * * *",
        browser_heavy=False,
        env_overrides={},
        timeout_minutes=180,
    )
    cfg = OrchestratorConfig(timezone="Asia/Manila", default_timeout_minutes=180, jobs=(spec,))
    when = datetime.now(UTC)
    ctx = RunContext.start(job_id, spec, cfg, now=when)

    if kind == "success":
        ctx.set_validation(
            [
                FileReport(
                    source_id=job_id,
                    path=f"data/test/{job_id}.jsonl",
                    status="ok",
                    records=8544,
                )
            ],
            passed=True,
        )
        ctx.mark_ok()
    elif kind == "warning":
        ctx.mark_ok()
        ctx.add_warning("TEST warning — sample quality issue (not a real failure)")
    elif kind == "timeout":
        ctx.mark_ok()
        ctx.add_warning(
            f"Job {job_id} exceeded configured timeout (200.0m > {spec.timeout_minutes}m)"
        )
    elif kind == "test":
        ctx.mark_failed(
            message="TEST ONLY — alert wiring OK, not a real scrape failure",
            error_type="TestAlert",
        )
    elif kind == "validation":
        ctx.set_validation(
            [
                FileReport(
                    source_id=job_id,
                    path=f"data/test/{job_id}.jsonl",
                    status="failed",
                    errors=["Line 42: missing required key 'doc_id'"],
                )
            ],
            passed=False,
        )
        ctx.mark_failed(
            message=f"Corpus validation failed — {job_id}: Line 42: missing required key 'doc_id'",
            error_type="ValidationError",
        )
    else:  # failure — real red JOB FAILED styling
        try:
            raise RuntimeError(f"Simulated scrape crash for {job_id}")
        except RuntimeError as exc:
            ctx.mark_failed(
                message=f"TEST failure — simulated error for {job_id} (not a real run)",
                exc=exc,
                error_type="JobError",
            )

    if not alerts_enabled():
        return ["skipped: ALERT_ENABLED is not true"]

    sent: list[str] = []
    sent.extend(_send_local_file(ctx))
    sent.extend(_send_telegram(ctx))
    sent.extend(_send_discord(ctx))
    sent.extend(_send_ntfy(ctx))
    sent.extend(_send_webhook(ctx))
    sent.extend(_send_slack(ctx))
    sent.extend(_send_email(ctx))
    return sent