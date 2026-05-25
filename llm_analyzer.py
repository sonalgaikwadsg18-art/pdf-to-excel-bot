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
SYSTEM_PROMPT = """You are a world-class data analyst. Your output must match the quality of a meticulous human analyst who spends hours organizing a document into a professional Excel workbook.

RULES (EVERY output MUST follow):
1. NEVER create generic dump-sheets like "Full Text", "Raw Data", "Content by Page", "Summary", "Raw Tables". These are LAZY outputs that a beginner would create.
2. ALWAYS organize data thematically. Each sheet should answer a specific question a reader would have about the document.
3. First understand the DOCUMENT'S PURPOSE, then create sheets that serve that purpose.
4. Extract EVERY data point. If there are 156 attendees, include all 156 rows. Do NOT summarize/truncate.
5. Sheet names must be DESCRIPTIVE and PROFESSIONAL. Use title case. Examples: "Event Overview", "Partner Benefits", "Pricing Matrix", "Attendee Directory".
6. For any table with 3+ rows, include ALL rows. Never sample or truncate.
7. Markdown/formatted text within cells should be preserved as-is.

THINK STEP-BY-STEP before outputting JSON:
Step 1 - Identify document type (event kit, research report, invoice, contract, brochure, annual report, catalog, etc.)
Step 2 - Identify who the intended reader is and what they care about
Step 3 - List every distinct theme/topic/section in the document
Step 4 - For each theme, decide what data to extract (columns, rows, key-value pairs)
Step 5 - Check: did I miss any data? Are there numbers, names, dates, prices I skipped?
Step 6 - Output the JSON

IMPORTANT — What "thematic sheets" look like (real examples):
For a SPONSORSHIP/PARTNER KIT (like a conference prospectus):
- "Event Overview" → date, location, attendees, format, highlights
- "Key Differentiators" → what makes this event unique
- "Partner Benefits" → benefit name, description, tier availability
- "Sponsorship Levels" → tier name, price, each benefit as columns
- "Testimonials" → quote, person name, title, company
- "Partner Directory" → company name, tier/level (all rows)
- "Sample Schedule" → time, session, details
- "Attendee Directory" → name, title, organization, location (all rows)
- "Event Snapshot" → key stats and metrics as key-value pairs

For an INVOICE:
- "Invoice Summary" → invoice number, date, vendor, amount
- "Line Items" → item description, quantity, unit price, total
- "Payment Terms" → terms, due date, late fees

For a RESEARCH REPORT:
- "Executive Summary" → key findings as key-value pairs
- "Methodology" → sample size, date range, method
- "Data Tables" → all numeric tables with full data
- "Key Findings" → each finding with supporting data

For a BROCHURE/CATALOG:
- "Product Overview" → product name, category, description
- "Specifications" → features and specs as key-value per product
- "Pricing" → product name, SKU, price, availability
- "Contact Info" → address, phone, email, website"""

USER_PROMPT_TEMPLATE = """I extracted all text from a PDF document. Please analyze it.

--- DOCUMENT TEXT ---
{text}
--- END ---

Follow this thinking process BEFORE outputting JSON:
1. What type of document is this? (event kit, invoice, report, contract, catalog, brochure, etc.)
2. Who is the intended reader?
3. What questions would that reader want answered?
4. What themes/sections do I see?
5. For each theme, what data columns would a human create?

Then output ONLY valid JSON with this exact schema:

{{
  "document_type": "one-line document type identification",
  "summary": "one-sentence summary of what this document is and who it's for",
  "sheets": [
    {{
      "name": "Thematic Sheet Name (title case, descriptive)",
      "type": "table",
      "headers": ["Column1", "Column2", "Column3"],
      "rows": [
        ["value1", "value2", "value3"],
        ["value4", "value5", "value6"]
      ]
    }}
  ]
}}

SHEET TYPES:
- "table": Tabular data with headers and rows (for lists, directories, pricing grids, schedules, comparisons)
- "key_value": Pairs like {{"field": "Name", "value": "John"}} (for metadata, specs, properties, overviews)
- "text": Single content block (for prose, descriptions, terms)

CRITICAL REQUIREMENTS (check each before outputting):
- [ ] Each sheet is THEMATIC (groups related information together)
- [ ] No sheet is a generic dump (no "Full Text", "Raw Data", "All Content", "Content by Page")
- [ ] EVERY sheet MUST have data. NEVER create empty sheets with 0 rows/0 pairs.
- [ ] If you cannot extract actual data for a topic, SKIP that sheet entirely.
- [ ] Every data point in the document is captured somewhere — do not skip names, prices, dates, stats
- [ ] Large lists (attendees, partners, products, items) have ALL rows, not truncated
- [ ] Quotes include: quote text, person name, their title, organization
- [ ] Pricing includes: tier/level name, price, each benefit/feature as a column
- [ ] Schedules include: time, session, speaker/location, description
- [ ] Contact info includes: name, title, organization, email, phone, address

Output ONLY valid JSON. No markdown. No code fences. No explanations outside JSON."""


# ---------------------------------------------------------------------------
# LLM clients
# ---------------------------------------------------------------------------
def call_groq(api_key: str, text: str, model: str = "llama-3.3-70b-versatile") -> tuple:
    """Call Groq API (free tier available, 12K TPM limit).
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
            "max_tokens": 6000,
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
    raw = raw.strip()
    # Remove markdown code fences
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()
    # Fix common LLM issues: trailing commas before ] or }
    raw = re.sub(r",\s*]", "]", raw)
    raw = re.sub(r",\s*}", "}", raw)
    # Fix unescaped control characters (common in extracted text)
    raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", raw)
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
    # --- Page-aware truncation for Groq free tier (12K TPM limit) ---
    text = pdf_result["all_text"]

    if not text or len(text.strip()) < 20:
        return {
            "document_type": "Unknown",
            "summary": "Insufficient text for analysis",
            "sheets": build_fallback_sheets(pdf_result),
        }

    # Mild truncation: stay within Groq free tier 12K TPM limit
    # Budget: ~15K text chars (3750 tok) + prompt (1250 tok) + output (5000 tok) = 10000 ✓
    if len(text) > 20000:
        text = text[:15000] + "\n\n[... content truncated ...]\n\n" + text[-5000:]

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

        # Post-process: remove empty sheets (0 rows, 0 pairs, 0 content)
        valid_sheets = []
        for s in result["sheets"]:
            stype = s.get("type", "")
            if stype == "table" and len(s.get("rows", [])) > 0:
                valid_sheets.append(s)
            elif stype == "key_value" and len(s.get("pairs", [])) > 0:
                valid_sheets.append(s)
            elif stype == "text" and len(s.get("content", "").strip()) > 0:
                valid_sheets.append(s)
        result["sheets"] = valid_sheets

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
