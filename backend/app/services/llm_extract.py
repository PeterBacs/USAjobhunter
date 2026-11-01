"""Optional LLM field extraction from already-retrieved source text (JH_LLM=1 + Anthropic credentials).

The model only reads text the scanner actually fetched. Every returned field must carry a verbatim
quote; fields whose quote is not found in the source text are discarded, and low-confidence
fields are flagged NEEDS REVIEW instead of being stored as facts.
"""
from pydantic import BaseModel

from ..config import ANTHROPIC_MODEL, LLM_ENABLED


class ExtractedField(BaseModel):
    value: str | None
    quote: str | None
    confidence: str  # HIGH | MEDIUM | LOW


class ExtractedPosting(BaseModel):
    job_title: ExtractedField
    salary: ExtractedField
    deadline: ExtractedField
    grade_level: ExtractedField
    requirements: ExtractedField
    certification: ExtractedField
    contact_name: ExtractedField
    contact_title: ExtractedField
    contact_email: ExtractedField
    j1_evidence: ExtractedField


SYSTEM = (
    "You extract fields from a U.S. school job posting. Use ONLY the provided text. For each field return the "
    "value, a verbatim quote from the text that supports it, and a confidence. If the text does not state a "
    "field, return value null and quote null. Never infer or construct names, emails, salaries or visa status."
)


def extract(source_text: str, source_url: str) -> dict | None:
    if not LLM_ENABLED or not source_text:
        return None
    import anthropic
    client = anthropic.Anthropic()
    try:
        resp = client.messages.parse(
            model=ANTHROPIC_MODEL,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": f"Source URL: {source_url}\n\n<posting>\n{source_text}\n</posting>"}],
            output_format=ExtractedPosting,
            # Server-side fallback if the primary model declines a request.
            extra_headers={"anthropic-beta": "server-side-fallback-2026-07-01"},
            extra_body={"fallbacks": "default"},
        )
    except anthropic.RateLimitError:
        return None
    except anthropic.APIStatusError:
        return None
    except anthropic.APIConnectionError:
        return None
    if resp.stop_reason == "refusal" or resp.parsed_output is None:
        return None
    out = {}
    low_text = source_text.lower()
    for name, f in resp.parsed_output.model_dump().items():
        if not f["value"]:
            continue
        quote_ok = bool(f["quote"]) and f["quote"].lower().strip() in low_text
        if not quote_ok:
            continue  # unsupported by the source -> discard
        out[name] = {"value": f["value"], "source": source_url, "quote": f["quote"], "confidence": f["confidence"],
                     "status": "NEEDS_REVIEW" if f["confidence"] == "LOW" else "EXTRACTED"}
    return out
