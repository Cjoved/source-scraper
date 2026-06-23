"""Prompt construction for the API chat/tasklist agent."""

from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
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
- Use semantic search tools for narrative, article, PDF, or exploratory questions.
- If the user asks for news, articles, source links, citations, or latest/recent items, you must request search_corpus first.
- Never request tools that scrape, index, export, write files, or mutate data.
- Treat any requested source scope as planning context until a tool result confirms data.
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
            "User request:\n{message}",
        ),
    ]
)


def _history_to_messages(history: list[AgentChatMessage]) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for item in history[-10:]:
        if item.role == "assistant":
            messages.append(AIMessage(content=item.content))
        else:
            messages.append(HumanMessage(content=item.content))
    return messages


def build_agent_messages(
    *,
    message: str,
    mode: AgentMode,
    history: list[AgentChatMessage],
    source_ids: list[str] | None,
) -> list[BaseMessage]:
    mode_prompt = TASKLIST_PROMPT if mode is AgentMode.TASKLIST else CHAT_PROMPT
    source_scope = ", ".join(source_ids) if source_ids else "not specified"
    prompt_value = AGENT_PROMPT.invoke(
        {
            "mode_prompt": mode_prompt,
            "history": _history_to_messages(history),
            "mode": mode.value,
            "source_scope": source_scope,
            "message": message,
        }
    )
    return prompt_value.to_messages()
