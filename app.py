"""
PDF -> Excel Bot v2 — Streamlit Web App
Default Smart Mode with built-in Groq API key via Streamlit Secrets.
No key prompt needed. Just upload and download.
"""
import io
import os
import streamlit as st

st.set_page_config(page_title="PDF -> Excel Bot", page_icon=":page_facing_up:", layout="centered")

from pdf_processor import process_pdf, PDFProcessingError
from llm_analyzer import analyze_with_llm, analyze_rule_based
from excel_builder import build_workbook

MAX_UPLOAD_MB = 200

# ---------------------------------------------------------------------------
# API key resolution: Streamlit Secrets -> env var -> None
# ---------------------------------------------------------------------------
DEFAULT_GROQ_KEY = None
try:
    DEFAULT_GROQ_KEY = st.secrets.get("GROQ_API_KEY")
except Exception:
    pass
if not DEFAULT_GROQ_KEY:
    DEFAULT_GROQ_KEY = os.environ.get("GROQ_API_KEY")

DEFAULT_PROVIDER = "groq"

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
for key in ["excel_bytes", "filename", "analysis", "rate_limit"]:
    if key not in st.session_state:
        st.session_state[key] = None

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### :gear: Mode")

    if DEFAULT_GROQ_KEY:
        smart_label = "Smart (LLM) — AI analysis (recommended)"
        basic_label = "Basic (rules) — no AI"
        default_index = 0
    else:
        smart_label = "Smart (LLM) — requires API key"
        basic_label = "Basic (rules) — no key needed"
        default_index = 1

    mode = st.radio("Analysis mode:", [smart_label, basic_label], index=default_index)
    use_llm = mode.startswith("Smart")

    api_key = DEFAULT_GROQ_KEY if use_llm else ""
    api_provider_clean = DEFAULT_PROVIDER

    if use_llm and not api_key:
        st.warning("No API key configured. Add GROQ_API_KEY to Streamlit Secrets.")
        st.markdown("Or get a free key at [console.groq.com](https://console.groq.com)")

    if use_llm and api_key:
        st.success(":white_check_mark: AI mode ready — Groq key configured")

    st.markdown("---")
    st.markdown("### :information_source: How it works")
    if use_llm and api_key:
        st.markdown(
            "1. Upload any PDF\n"
            "2. AI reads & understands document structure\n"
            "3. Creates themed sheets (just like manual work)\n"
            "4. Download formatted Excel"
        )
    else:
        st.markdown(
            "1. Upload any PDF\n"
            "2. Rules extract text & tables\n"
            "3. Creates organized sheets\n"
            "4. Download Excel"
        )

    st.markdown("---")
    st.markdown("### :shield: Free & Private")
    st.markdown(
        "- No account needed\n"
        "- Files processed in memory (not stored)\n"
        "- Powered by Groq free tier"
        if DEFAULT_GROQ_KEY else
        "- No account needed\n"
        "- Files processed in memory (not stored)"
    )

    st.markdown("---")
    st.markdown("### :fuel_pump: Groq API Quota")
    rl = st.session_state.rate_limit
    if rl and rl.get("remaining_requests") is not None:
        try:
            rem = int(rl["remaining_requests"])
            lim = int(rl.get("limit_requests", 14400))
            pct = max(0, int(rem / lim * 100)) if lim else 0
            bar_color = "green" if pct > 30 else ("orange" if pct > 10 else "red")
            st.markdown(f"**Requests remaining:** {rem:,} / {lim:,}")
            st.markdown(
                f"<div style='width:100%; height:10px; background:#eee; border-radius:5px;'>"
                f"<div style='width:{pct}%; height:10px; background:{bar_color}; border-radius:5px;'></div></div>",
                unsafe_allow_html=True,
            )
            if rl.get("remaining_tokens"):
                st.caption(f"Tokens remaining: {int(rl['remaining_tokens']):,}")
        except (ValueError, TypeError):
            st.caption("Usage data pending...")
    elif DEFAULT_GROQ_KEY:
        st.caption("Upload a PDF to see usage")
    else:
        st.caption("No API key configured")

# ---------------------------------------------------------------------------
# Main UI
# ---------------------------------------------------------------------------
st.markdown(
    "<h1 style='color: #1F3864;'>:page_facing_up: :arrow_right: :bar_chart: PDF to Excel Bot</h1>",
    unsafe_allow_html=True,
)
st.markdown(
    "<p style='color: #666; font-size: 1.1em;'>"
    "Upload any PDF. Get a professionally structured Excel workbook."
    + (" AI-powered document understanding." if api_key else " Rule-based extraction.")
    + "</p>",
    unsafe_allow_html=True,
)
st.divider()

# ---------------------------------------------------------------------------
# File upload
# ---------------------------------------------------------------------------
uploaded_file = st.file_uploader("Choose a PDF file", type=["pdf"], help=f"Max: {MAX_UPLOAD_MB} MB")

if uploaded_file is not None:
    file_bytes = uploaded_file.read()
    filename = uploaded_file.name
    file_size_mb = len(file_bytes) / (1024 * 1024)

    if file_size_mb > MAX_UPLOAD_MB:
        st.error(f"File too large ({file_size_mb:.1f} MB). Max: {MAX_UPLOAD_MB} MB.")
        st.stop()

    if not filename.lower().endswith(".pdf"):
        st.error("Only PDF files supported.")
        st.stop()

    if use_llm and not api_key:
        st.error("Smart mode requires a Groq API key. Add GROQ_API_KEY to Streamlit Secrets, or switch to Basic mode.")
        st.stop()

    mode_label = "Smart (LLM)" if use_llm else "Basic (rules)"
    with st.spinner("Step 1/2: Extracting text from PDF..."):
        try:
            pdf_result = process_pdf(file_bytes, filename)
        except PDFProcessingError as e:
            st.error(f":x: {e}")
            st.stop()
        except Exception as e:
            st.error(f":x: Unexpected error: {e}")
            st.stop()

    for w in pdf_result.get("warnings", []):
        st.warning(w)

    if use_llm:
        with st.spinner("Step 2/2: AI analyzing document structure (15-30 sec)..."):
            try:
                analysis = analyze_with_llm(pdf_result, api_key, api_provider_clean)
                st.session_state.rate_limit = analysis.get("rate_info")
            except Exception as e:
                st.error(f"AI analysis failed: {e}. Falling back to rules.")
                analysis = analyze_rule_based(pdf_result)
    else:
        with st.spinner("Step 2/2: Analyzing document structure..."):
            analysis = analyze_rule_based(pdf_result)

    excel_buf = build_workbook(analysis)
    st.session_state.excel_bytes = excel_buf.getvalue()
    st.session_state.filename = filename
    st.session_state.analysis = analysis

    sheets = analysis.get("sheets", [])
    st.success(f":white_check_mark: Done! {len(sheets)} sheets created.")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Pages", pdf_result["metadata"]["pages"])
    with col2:
        st.metric("Sheets Created", len(sheets))
    with col3:
        st.metric("Tables Found", pdf_result["metadata"]["total_tables"])
    with col4:
        st.metric("Mode", "Smart AI" if use_llm else "Basic Rules")

    with st.expander(":book: Preview Excel sheets", expanded=True):
        st.markdown(f"**{analysis.get('document_type', 'Document')}**")
        st.markdown(f"*{analysis.get('summary', '')}*")
        for s in sheets:
            name = s.get("name", "?")
            stype = s.get("type", "?")
            count = max(len(s.get("rows", [])), len(s.get("pairs", [])), 1 if s.get("content") else 0)
            st.markdown(f"- :bar_chart: **{name}** ({stype}, {count} items)")

    excel_filename = filename.rsplit(".", 1)[0] + "_structured.xlsx"
    st.divider()
    st.download_button(
        label=":inbox_tray: DOWNLOAD EXCEL",
        data=st.session_state.excel_bytes,
        file_name=excel_filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
        type="primary",
    )
    st.caption(f"{excel_filename} | {len(st.session_state.excel_bytes) / 1024:.1f} KB")

else:
    st.info("Upload a PDF above to get started.")
    st.markdown("### :sparkles: What makes this different?")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**:rocket: AI Mode** (default — key pre-configured)")
        st.markdown(
            "- AI reads & understands document structure\n"
            "- Creates themed sheets (Testimonials, Pricing, Directory...)\n"
            "- Same quality as manual human work\n"
            "- Powered by Groq (free tier)"
        )
    with col2:
        st.markdown("**:zap: Basic Mode** (no AI)")
        st.markdown(
            "- Rule-based extraction\n"
            "- Detects tables, quotes, prices\n"
            "- Creates organized sheets\n"
            "- Works without any API key"
        )
