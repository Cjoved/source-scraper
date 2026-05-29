"""Paragraph-aware text chunking for CPT pipelines."""


def chunk_text(text: str, max_chars: int) -> list[str]:
    """
    Split text into chunks of at most max_chars, respecting blank-line paragraphs.
    If max_chars <= 0 or text is shorter, returns [text] (or [] if empty).
    """
    if not text:
        return []
    text = text.strip()
    if not max_chars or max_chars <= 0 or len(text) <= max_chars:
        return [text]

    out: list[str] = []
    paragraphs = text.split("\n\n")
    current = ""
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if len(current) + len(p) + 2 <= max_chars:
            current = (current + "\n\n" + p).strip() if current else p
        else:
            if current:
                out.append(current)
            if len(p) > max_chars:
                for i in range(0, len(p), max_chars):
                    chunk = p[i : i + max_chars].strip()
                    if chunk:
                        out.append(chunk)
                current = ""
            else:
                current = p
    if current:
        out.append(current)
    return out
