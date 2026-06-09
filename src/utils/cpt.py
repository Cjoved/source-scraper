"""CPT (Continued Pre-Training) record format."""

from src.utils.text_sanitize import sanitize_corpus_text


def make_cpt_record(
    text: str,
    source: str,
    doc_id: str,
    *,
    url: str | None = None,
    title: str | None = None,
    filename: str | None = None,
    page: int | None = None,
) -> dict:
    """Build one CPT chunk record."""
    text = sanitize_corpus_text(text)
    rec = {
        "text": text,
        "input": text,
        "content": text,
        "source": source,
        "doc_id": doc_id,
    }
    if url is not None:
        rec["url"] = url
    if title is not None:
        rec["title"] = title
    if filename is not None:
        rec["filename"] = filename
    if page is not None:
        rec["page"] = page
    return rec
