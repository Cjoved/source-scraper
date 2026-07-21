"""Prompt construction for the API chat/tasklist agent."""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.api.schemas import AgentChatMessage, AgentMode

SYSTEM_PROMPT = """You are AgriDataAgent, the API-first assistant for a PRiSM/OpenSTAT source-scraper project.

Answer in the user's language. If the user writes in Filipino or Taglish, answer in clear Taglish.
Be concise, practical, and implementation-oriented.

Current phase:
- You can produce chat answers and tasklists.
- You can request read-only tools when project data is needed.
- Do not claim that you queried project data, Qdrant, scrapers, or files.
- Only claim project data was checked after tool results are provided.
- Use deterministic summary tools for exact numeric yield or price questions.
- Use list_openstat_commodities for questions about which crops/commodities OpenSTAT covers.
- Use semantic search tools for narrative, article, PDF, or exploratory questions.
- If the user asks for news, articles, source links, citations, or latest/recent items, you must request search_corpus first.
- If tool results are empty, say no matching data was found and mention what was searched.
- Do not cite or invent source links that are not present in tool results.
- Include source links in the answer only when tool results include URLs.
- For news or paper listings from search_corpus, copy each item title exactly from tool results.
  Do not paraphrase, translate, or rewrite titles; the database title is the source of truth.
- Never request tools that scrape, index, export, write files, or mutate data.
- Treat any requested source scope as planning context until a tool result confirms data.
- Treat the Authoritative query plan as the source of truth for tool arguments.
- If the query plan conflicts with the user's source scope, follow the query plan.
- After tool results, final response must still be exactly one valid JSON object.
- Do not add extra fallback suggestions unless tool results are empty or confidence would be low.

Farmer-facing rules:
- If user_type is farmer, answer simply and practically in the user's language.
- For vague farmer questions, ask at most one short clarifying question.
- If a general answer is still useful, give the general answer first, then ask one follow-up.
- For pest, disease, fertilizer, or chemical advice, provide safe next steps and recommend a local agriculture technician for severe cases or chemical decisions.
- Do not overload farmer answers with API, Qdrant, or implementation details.
"""

TASKLIST_PROMPT = """Return only valid JSON with this shape:
{
  "answer": "short answer",
  "tasklist": [
    {"status": "pending", "task": "clear actionable task"}
  ]
}

Rules:
- Return exactly one JSON object.
- Do not add extra keys.
- If tool results were provided, base the answer and tasklist on those results.
- Use 3 to 7 tasks.
- Keep each task specific and implementation-ready.
- Use status "pending" for every task. Valid statuses are: pending, in_progress, completed, cancelled.
- Do not include markdown fences.
"""

CHAT_PROMPT = """Return only valid JSON with this shape:
{
  "answer": "short conversational answer",
  "tasklist": []
}

Rules:
- Keep the answer concise.
- If tool results were provided, base the answer on those results.
- The tasklist field must be an empty array.
- Return exactly one JSON object.
- Do not add extra keys.
- Do not include markdown fences.
"""

METADATA_FOLLOW_UP_SYSTEM = """You format follow-up answers about prior news or corpus sources.

Rules:
- Use ONLY the verified source facts provided. Do not invent dates, titles, or URLs.
- Copy each title and published_date exactly from the facts block.
- If published_date is null or missing, say the date is not available in the index (never guess).
- Match the user's question focus: one referenced item → one short sentence; several items → concise numbered lines.
- Do not repeat long boilerplate intros like "Here are the dates for the referenced news items".
- Include a URL only when the user asks for a link or source, or when a single-item answer needs citation.
- Return only valid JSON: {"answer": "..."} with no markdown fences.
"""

CORPUS_RESULTS_SYSTEM = """You format initial corpus search results for Filipino farmers.

Rules:
- Use ONLY the verified source facts provided. Do not invent titles, dates, URLs, or story details.
- Copy each item title EXACTLY from the facts block (no translation or paraphrase of titles).
- Start with 1–2 short sentences that directly answer the user's question in plain language.
  Base the summary ONLY on the provided snippets/titles — never guess missing facts.
- Then list each item as a numbered entry: exact title, optional one-line plain-language hint from snippet only, then URL on the next line if available.
- Match the user's language: Taglish question → Taglish answer; English question → English answer.
- Keep hints farmer-friendly and under 20 words each.
- Do not mention "database", "index", or "exact titles from the database".
- Return only valid JSON: {"answer": "..."} with no markdown fences.
"""


def build_metadata_follow_up_messages(
    *,
    user_question: str,
    facts_json: str,
    language: str,
) -> list[BaseMessage]:
    from src.agent.intent import is_taglish

    tone = (
        "Answer in clear Taglish suitable for Filipino farmers."
        if is_taglish(language, user_question)
        else "Answer in clear English."
    )
    return [
        SystemMessage(content=f"{METADATA_FOLLOW_UP_SYSTEM}\n{tone}"),
        HumanMessage(
            content=(
                f"User question:\n{user_question.strip()}\n\n"
                f"Verified source facts (JSON):\n{facts_json}\n\n"
                'Return JSON: {"answer": "..."}'
            )
        ),
    ]


def build_corpus_results_messages(
    *,
    user_question: str,
    facts_json: str,
    language: str,
    intent: str,
) -> list[BaseMessage]:
    from src.agent.intent import is_taglish

    content_type = "research papers/publications" if intent == "paper_query" else "agri news"
    tone = (
        "Answer in clear Taglish suitable for Filipino farmers."
        if is_taglish(language, user_question)
        else "Answer in clear English."
    )
    return [
        SystemMessage(content=f"{CORPUS_RESULTS_SYSTEM}\n{tone}"),
        HumanMessage(
            content=(
                f"User question:\n{user_question.strip()}\n\n"
                f"Content type: {content_type}\n\n"
                f"Verified source facts (JSON):\n{facts_json}\n\n"
                'Return JSON: {"answer": "..."}'
            )
        ),
    ]


AGENT_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", SYSTEM_PROMPT),
        ("system", "{mode_prompt}"),
        MessagesPlaceholder("history"),
        (
            "human",
            "Mode: {mode}\n"
            "Requested source scope for planning only: {source_scope}\n"
            "Do not claim these sources were searched.\n\n"
            "Farmer context:\n{farmer_context}\n\n"
            "Session context (verified from prior tool calls):\n{session_state_context}\n\n"
            "Authoritative query plan:\n{query_plan_context}\n\n"
            "User request:\n{message}",
        ),
    ]
)


def _history_to_messages(history: list[AgentChatMessage]) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for item in history[-10:]:
        if item.role == "assistant":
            messages.append(AIMessage(content=_assistant_history_content(item)))
        else:
            messages.append(HumanMessage(content=item.content))
    return messages


def _assistant_history_content(item: AgentChatMessage) -> str:
    content = item.content
    if not item.sources:
        return content
    lines = [content, "", "Sources from this turn:"]
    for index, source in enumerate(item.sources[:10], start=1):
        title = source.title or source.filename or "Untitled"
        bits = [f"{index}. {title}"]
        if source.published_date:
            bits.append(f"date={source.published_date}")
        if source.url:
            bits.append(f"url={source.url}")
        lines.append(" | ".join(bits))
    return "\n".join(lines)


def build_agent_messages(
    *,
    message: str,
    mode: AgentMode,
    history: list[AgentChatMessage],
    source_ids: list[str] | None,
    farmer_context: str = "not provided",
    query_plan_context: str = "not provided",
    session_state_context: str = "not provided",
) -> list[BaseMessage]:
    mode_prompt = TASKLIST_PROMPT if mode is AgentMode.TASKLIST else CHAT_PROMPT
    source_scope = ", ".join(source_ids) if source_ids else "not specified"
    prompt_value = AGENT_PROMPT.invoke(
        {
            "mode_prompt": mode_prompt,
            "history": _history_to_messages(history),
            "mode": mode.value,
            "source_scope": source_scope,
            "farmer_context": farmer_context,
            "session_state_context": session_state_context,
            "query_plan_context": query_plan_context,
            "message": message,
        }
    )
    return prompt_value.to_messages()
