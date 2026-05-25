"""
LLM Analyzer — Sends extracted PDF text to an LLM (Groq/OpenAI/Anthropic)
and receives structured JSON defining what sheets to create.
The LLM acts like a human analyst — reads the document, understands its
structure, and outputs a schema that replicates manual-quality Excel output.
"""
import json
import re
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """You are a document analyst. Your job is to read PDF text, understand
the document's structure, and output a JSON that would let someone build a
professional Excel workbook from it.

You think like an analyst: you identify sections, themes, tables, lists, quotes,
metadata — everything a human would notice when organizing this document into a
spreadsheet. You NEVER just dump raw text. You always organize and structure."""

USER_PROMPT_TEMPLATE = """I extracted all text from a PDF. Here it is:

--- DOCUMENT TEXT ---
{text}
--- END ---

Now analyze this document deeply and output a JSON object with this EXACT schema:

{{
  "document_type": "one-line description of document type (e.g., 'Event Partner Kit', 'Research Report', 'Invoice', 'Contract', 'Brochure')",
  "summary": "one-sentence summary of the document",
  "sheets": [
    {{
      "name": "Short clear sheet name like 'Event Overview' or 'Testimonials'",
      "type": "table",
      "headers": ["Column1", "Column2"],
      "rows": [["val1", "val2"], ["val3", "val4"]]
    }}
  ]
}}

SHEET TYPE RULES:
- "table" = has headers and rows of data (for lists, directories, pricing grids, schedules)
- "key_value" = has pairs like {{"field": "Name", "value": "John"}} (for metadata, specs, properties)
- "text" = has a single content field (for sections of prose/paragraphs)

GUIDELINES (CRITICAL):
1. Create 4-12 sheets — whatever best organizes the document.
2. Sheet names MUST be meaningful and descriptive (NOT "Sheet1").
3. Extract EVERY data point — do not skip rows, do not truncate.
4. For large tables (like attendee lists, price lists) include ALL rows.
5. For quotes/testimonials, extract quote text + who said it + their title.
6. For contact lists, extract name, title, organization, location as structured columns.
7. For pricing, extract tier name, price, and each benefit as columns.
8. If the document has a schedule/agenda, extract each time slot as a row.
9. For partner lists, extract company name and tier/type.
10. Group related data together — don't split one theme across sheets.

Output ONLY valid JSON. No markdown. No explanation. No code fences."""


# ---------------------------------------------------------------------------
# LLM clients
# ---------------------------------------------------------------------------
def call_groq(api_key: str, text: str, model: str = "llama-3.3-70b-versatile") -> tuple:
    """Call Groq API (free tier available).
    Returns: (response_text, rate_limit_info_dict or None)
    """
    import requests
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(text=text)},
            ],
            "temperature": 0.1,
            "max_tokens": 16000,
        },
        timeout=120,
    )
    resp.raise_for_status()
    # Extract rate limit headers from Groq response
    rate_info = {
        "remaining_requests": resp.headers.get("x-ratelimit-remaining-requests"),
        "remaining_tokens": resp.headers.get("x-ratelimit-remaining-tokens"),
        "limit_requests": resp.headers.get("x-ratelimit-limit-requests"),
        "limit_tokens": resp.headers.get("x-ratelimit-limit-tokens"),
        "reset_requests": resp.headers.get("x-ratelimit-reset-requests"),
        "provider": "groq",
    }
    return resp.json()["choices"][0]["message"]["content"], rate_info


def call_openai(api_key: str, text: str, model: str = "gpt-4o-mini") -> tuple:
    """Call OpenAI API."""
    import requests
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(text=text)},
            ],
            "temperature": 0.1,
            "max_tokens": 16000,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"], None


def call_gemini(api_key: str, text: str, model: str = "gemini-1.5-flash") -> tuple:
    """Call Google Gemini API (free tier — no credit card needed at aistudio.google.com)."""
    import requests
    prompt = SYSTEM_PROMPT + "\n\n" + USER_PROMPT_TEMPLATE.format(text=text)
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}",
        json={"contents": [{"parts": [{"text": prompt}]}],
              "generationConfig": {"temperature": 0.1, "maxOutputTokens": 16000}},
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    candidates = data.get("candidates", [])
    if not candidates:
        raise ValueError("Gemini returned no candidates")
    return candidates[0]["content"]["parts"][0]["text"], None


def call_anthropic(api_key: str, text: str, model: str = "claude-3-haiku-20240307") -> tuple:
    """Call Anthropic API."""
    import requests
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": USER_PROMPT_TEMPLATE.format(text=text)}],
            "max_tokens": 16000,
            "temperature": 0.1,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"], None


# ---------------------------------------------------------------------------
# JSON parser (handles markdown fences and common LLM output quirks)
# ---------------------------------------------------------------------------
def parse_llm_json(raw: str) -> dict:
    """Extract and parse JSON from LLM output (handles ```json fences etc)."""
    # Remove markdown code fences
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Fallback: rule-based sheet builder (no LLM needed)
# ---------------------------------------------------------------------------
def build_fallback_sheets(pdf_result: dict) -> list[dict]:
    """When no LLM is available, create intelligent sheets using rules."""
    pages = pdf_result["pages"]
    sections = pdf_result["sections"]
    all_text = pdf_result["all_text"]
    entities = pdf_result.get("entities", {})
    metadata = pdf_result["metadata"]
    warnings = pdf_result.get("warnings", [])

    sheets = []

    # Sheet 1: Document Info (key_value)
    sheets.append({
        "name": "Document Info",
        "type": "key_value",
        "pairs": [
            {"field": "File Name", "value": metadata["filename"]},
            {"field": "Pages", "value": str(metadata["pages"])},
            {"field": "File Size", "value": f'{metadata["file_size_mb"]:.2f} MB'},
            {"field": "Content Type", "value": metadata["content_type"].title()},
            {"field": "Total Characters", "value": f'{metadata["total_chars"]:,}'},
            {"field": "Tables Detected", "value": str(metadata["total_tables"])},
        ],
    })

    # Sheet 2: Content by Page (table)
    content_rows = []
    for p in pages:
        preview = p["text"][:500] if p["text"] else "(no text)"
        content_rows.append([p["page_num"], p["char_count"], preview])
    sheets.append({
        "name": "Content by Page",
        "type": "table",
        "headers": ["Page", "Characters", "Content Preview"],
        "rows": content_rows,
    })

    # Sheet 3: Extracted Tables (table)
    table_rows = []
    for p in pages:
        for ti, table in enumerate(p.get("tables", [])):
            for ri, row in enumerate(table):
                page_label = f"P{p['page_num']}-T{ti+1}" if ri == 0 else ""
                table_rows.append([page_label] + [str(c)[:200] for c in row])
    if table_rows:
        max_cols = max(len(r) for r in table_rows)
        headers = ["Source"] + [f"Col {i}" for i in range(1, max_cols)]
        sheets.append({
            "name": "Tables",
            "type": "table",
            "headers": headers,
            "rows": table_rows,
        })

    # Sheet 4: Quotes / Testimonials (if found)
    quotes = entities.get("quotes", [])
    if quotes:
        quote_rows = [[q] for q in quotes]
        sheets.append({
            "name": "Quotes & Testimonials",
            "type": "table",
            "headers": ["Quote"],
            "rows": quote_rows,
        })

    # Sheet 5: Pricing (if found)
    prices = entities.get("prices", [])
    if prices:
        price_rows = [[p["value"]] for p in prices]
        sheets.append({
            "name": "Pricing & Amounts",
            "type": "table",
            "headers": ["Amount"],
            "rows": price_rows,
        })

    # Sheet 6: Full Text
    sheets.append({
        "name": "Full Text",
        "type": "text",
        "content": all_text[:50000] if all_text else "(no text extracted)",
    })

    return sheets


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def analyze_with_llm(pdf_result: dict, api_key: str, provider: str = "groq") -> dict:
    """
    Send PDF text to an LLM and get structured sheet definitions back.

    Args:
        pdf_result: Output of pdf_processor.process_pdf()
        api_key: API key for the LLM provider
        provider: "groq" | "openai" | "anthropic"

    Returns:
        dict with "document_type", "summary", "sheets" keys
        On failure, returns fallback sheets.
    """
    text = pdf_result["all_text"]
    if not text or len(text.strip()) < 20:
        return {
            "document_type": "Unknown",
            "summary": "Insufficient text for analysis",
            "sheets": build_fallback_sheets(pdf_result),
        }

    # Truncate if too large (LLM context limits)
    if len(text) > 120000:
        # Keep first and last pages
        text = text[:80000] + "\n\n[... content truncated ...]\n\n" + text[-40000:]

    rate_info = None
    try:
        if provider == "groq":
            raw, rate_info = call_groq(api_key, text)
        elif provider == "openai":
            raw, _ = call_openai(api_key, text)
        elif provider == "gemini":
            raw, _ = call_gemini(api_key, text)
        elif provider == "anthropic":
            raw, _ = call_anthropic(api_key, text)
        else:
            raise ValueError(f"Unknown provider: {provider}")

        result = parse_llm_json(raw)
        if "sheets" not in result or not result["sheets"]:
            raise ValueError("No sheets in LLM response")
        result["rate_info"] = rate_info
        return result

    except Exception as e:
        logger.warning(f"LLM analysis failed: {e}. Using rule-based fallback.")
        return {
            "document_type": "Unknown (LLM unavailable)",
            "summary": f"LLM analysis failed: {e}. Using rule-based extraction.",
            "sheets": build_fallback_sheets(pdf_result),
            "rate_info": rate_info,
        }


def analyze_rule_based(pdf_result: dict) -> dict:
    """Rule-based analysis — no LLM needed, works offline."""
    return {
        "document_type": "Document",
        "summary": f"Auto-analyzed document ({pdf_result['metadata']['pages']} pages, {pdf_result['metadata']['total_tables']} tables detected)",
        "sheets": build_fallback_sheets(pdf_result),
    }
