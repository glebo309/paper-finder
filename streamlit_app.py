#!/usr/bin/env python3
"""Browse candidate metadata, select the right work, then acquire its document.

Run: streamlit run streamlit_app.py
"""
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

from src.cli.search_helpers import begin_search, search_reference, select_candidate

st.set_page_config(page_title="Paper Finder", page_icon="📄", layout="centered")
st.title("Paper Finder")
st.caption("Find the right paper first. Compare the evidence, then download your selection.")

for key, default in {
    "query": "", "search_result": None, "selected_record": None,
    "result": None, "browser_url": None, "search_log": "",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

output_dir = Path.home() / "Downloads" / "Papers"
with st.form("paper_search"):
    reference = st.text_input("Title, citation, description, DOI, ISBN, arXiv ID, or URL", placeholder="The AlphaFold protein structure paper by Jumper, 2021")
    mode_label = st.radio("What are you looking for?", ["One particular paper", "Papers about a topic"], horizontal=True)
    limit = st.slider("Maximum candidates", min_value=5, max_value=30, value=10, step=5)
    submitted = st.form_submit_button("Find candidates", type="primary")

if submitted:
    begin_search(st.session_state, reference.strip())
    if not reference.strip():
        st.warning("Enter a reference or a topic to search.")
    else:
        log = io.StringIO()
        try:
            with st.spinner("Searching and comparing metadata…"), redirect_stdout(log), redirect_stderr(log):
                st.session_state.search_result = search_reference(reference, limit=limit, mode="identify" if mode_label == "One particular paper" else "discover")
        except Exception as exc:
            st.error(f"Search failed: {exc}")
        st.session_state.search_log = log.getvalue()

search = st.session_state.search_result
if search:
    st.subheader(f"Results for: {search['query']}")
    status = search.get("status")
    if status == "matched":
        st.success("A strong match was found. Review its details and select it below.")
    elif status == "ambiguous":
        st.info("Choose the intended paper below. No document has been downloaded.")
    elif status == "unavailable":
        st.error("Search providers could not be reached. Try again later.")
    else:
        st.warning("No matching metadata was found. Try an author, a year, a fuller title, or an identifier.")
    if search.get("errors"):
        with st.expander("Search provider warnings"):
            for provider, error in search["errors"].items():
                st.text(f"{provider}: {error}")
    for index, record in enumerate(search.get("candidates", [])):
        with st.container(border=True):
            st.subheader(f"{index + 1}. {record.get('title') or 'Untitled record'}")
            authors = record.get("authors") or []
            st.write(", ".join(str(author) for author in authors[:8]) or "Authors unavailable")
            if len(authors) > 8:
                st.caption(f"and {len(authors) - 8} more authors")
            st.caption(" · ".join(str(value) for value in (record.get("year"), record.get("journal")) if value) or "Publication details unavailable")
            identifier = record.get("identifier") or {}
            st.text(record.get("doi") or identifier.get("value", "No identifier available"))
            st.caption("Sources: " + ", ".join(record.get("sources") or [record.get("metadata_source") or "unknown"]))
            if record.get("match_reasons"):
                st.write("Why it appeared: " + "; ".join(record["match_reasons"]))
            if record.get("score") is not None:
                st.caption(f"Ranking score: {record['score']:.1f}/100. This is a heuristic, not a probability.")
            if record.get("abstract"):
                with st.expander("Abstract"):
                    st.text(record["abstract"])
            url = record.get("url") or ("https://doi.org/" + record["doi"] if record.get("doi") else None)
            if url and urlparse(url).scheme in ("http", "https"):
                st.link_button("View record", url)
            if st.button("Select this paper", key=f"select_{index}"):
                select_candidate(st.session_state, index)

selected = st.session_state.selected_record
if selected:
    st.divider()
    st.subheader("Selected paper")
    st.write(selected.get("title") or selected.get("identifier", {}).get("value"))
    if st.button("Download selected paper", type="primary"):
        st.session_state.result = None
        st.session_state.browser_url = None
        log = io.StringIO()
        captured_url = {"url": None}

        def browser_callback(identifier, url):
            captured_url["url"] = url

        try:
            with st.spinner("Looking for the selected document and checking its identity…"), redirect_stdout(log), redirect_stderr(log):
                from paper_finder import PaperFinder
                finder = PaperFinder(silent_init=True)
                output_dir.mkdir(parents=True, exist_ok=True)
                st.session_state.result = finder.find_record(selected, output_dir=str(output_dir), browser_callback=browser_callback)
            st.session_state.browser_url = captured_url["url"]
        except Exception as exc:
            st.error(f"Acquisition failed: {exc}")
        st.session_state.search_log = log.getvalue()

result = st.session_state.result
if result:
    st.divider()
    status = getattr(result, "status", "")
    if result.success and result.filepath and Path(result.filepath).is_file():
        st.success(f"Document downloaded and verified. Source: {result.source}")
        st.caption(str(result.filepath))
        with open(result.filepath, "rb") as document:
            st.download_button("Save PDF", data=document, file_name=Path(result.filepath).name, mime="application/pdf")
    elif status == "unverifiable":
        st.warning("A file was retrieved, but its identity could not be verified. Review it before using it.")
        if result.filepath:
            st.caption(f"Review file: {result.filepath}")
    elif status == "mismatch":
        st.error("The retrieved document does not match the selected paper.")
    elif status == "located" or st.session_state.browser_url:
        st.info("A document link was found. No verified PDF was saved.")
    else:
        st.error(result.error or "No verified document could be acquired.")
    if result.error and status in ("located", "unverifiable", "mismatch"):
        st.caption(result.error)
    url = st.session_state.browser_url
    if url and urlparse(url).scheme in ("http", "https"):
        st.link_button("Open document link", url)
    verification = getattr(result, "verification", None)
    if verification:
        with st.expander("Document verification"):
            st.json(verification)

if st.session_state.search_log:
    with st.expander("Activity log"):
        st.code(st.session_state.search_log, language="text")

with st.sidebar:
    st.header("Downloads")
    st.code(str(output_dir), language=None)
    st.metric("Saved PDFs", len(list(output_dir.glob("*.pdf"))) if output_dir.exists() else 0)
    if st.button("Open download folder"):
        import platform
        import subprocess
        output_dir.mkdir(parents=True, exist_ok=True)
        command = {"Darwin": "open", "Windows": "explorer"}.get(platform.system(), "xdg-open")
        try:
            subprocess.run([command, str(output_dir)], check=True)
        except Exception as exc:
            st.error(f"Could not open folder: {exc}")
    st.caption("Search only reads metadata. Acquisition starts only when you click Download selected paper.")
