#!/usr/bin/env python3
"""
Paper Finder - Streamlit Web Interface
Run: streamlit run streamlit_app.py --server.address 0.0.0.0
Access: http://YOUR_IP:8501
"""

import streamlit as st
from pathlib import Path
import time
from paper_finder import PaperFinder, DownloadResult

# Page config
st.set_page_config(
    page_title="Paper Finder",
    page_icon="📄",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# Custom CSS - center everything
st.markdown("""
<style>
    .main .block-container {
        max-width: 700px !important;
        margin: 0 auto !important;
        text-align: left;
    }
    /* Center all direct children */
    .main .block-container > div {
        margin-left: auto;
        margin-right: auto;
    }
    .main-title {
        font-size: 28px;
        font-weight: bold;
        margin-bottom: 30px;
        text-align: center;
    }
    .stButton>button {
        width: 100%;
    }
    .result-box {
        padding: 15px;
        border-radius: 5px;
        margin: 10px 0;
    }
    .success-box {
        background-color: #d4edda;
        border: 1px solid #c3e6cb;
    }
    .error-box {
        background-color: #f8d7da;
        border: 1px solid #f5c6cb;
    }
    section[data-testid="stSidebar"] {
        display: none;
    }
</style>
""", unsafe_allow_html=True)

# Initialize session state
if 'finder' not in st.session_state:
    st.session_state.finder = PaperFinder(silent_init=True)
if 'result' not in st.session_state:
    st.session_state.result = None
if 'searching' not in st.session_state:
    st.session_state.searching = False

# Output directory
output_dir = Path.home() / "Downloads" / "Papers"
output_dir.mkdir(parents=True, exist_ok=True)

# Title
st.markdown('<div class="main-title">Paper Finder</div>', unsafe_allow_html=True)

# Input section
st.markdown('<div class="main-title" style="font-size: 20px; margin-bottom: 10px;">Search Parameters</div>', unsafe_allow_html=True)
st.markdown('<div class="main-title" style="font-size: 14px; font-weight: normal; margin-bottom: 10px;">DOI, Title, or URL:</div>', unsafe_allow_html=True)
reference = st.text_input(
    "DOI, Title, or URL:",
    placeholder="e.g., 10.1038/nature12373 or 978-1464126116",
    label_visibility="collapsed"
)

search_button = st.button("Get Paper", type="primary", use_container_width=True)

# Search logic
if search_button and reference:
    st.session_state.searching = True
    st.session_state.result = None
    st.session_state.browser_url = None
    st.session_state.search_log = None
    
    # Show activity log during search ONLY
    status_placeholder = st.empty()
    log_expander = st.expander("Activity Log", expanded=True)
    
    status_placeholder.info(f"Searching for: {reference}")
    
    # Capture output and browser callback
    import io
    import sys
    from contextlib import redirect_stdout, redirect_stderr
    
    log_output = io.StringIO()
    captured_url = {'url': None}
    
    def browser_callback(identifier, url):
        """Capture browser URL instead of opening"""
        captured_url['url'] = url
    
    try:
        with redirect_stdout(log_output), redirect_stderr(log_output):
            result = st.session_state.finder.acquire(
                reference,
                output_dir=str(output_dir),
                browser_callback=browser_callback
            )
        
        st.session_state.result = result
        st.session_state.browser_url = captured_url['url']
        st.session_state.search_log = log_output.getvalue()
        
        # Show log in expander during search
        with log_expander:
            st.code(log_output.getvalue(), language="text")
        
        status_placeholder.empty()
        
    except Exception as e:
        st.session_state.result = None
        st.session_state.search_log = log_output.getvalue() + f"\n\nError: {str(e)}"
        with log_expander:
            st.code(st.session_state.search_log, language="text")
        status_placeholder.error(f"Error: {str(e)}")
    
    finally:
        st.session_state.searching = False

# Display results (only if we have results)
if st.session_state.result:
    result = st.session_state.result
    
    st.markdown("---")
    st.markdown("### Result")
    
    if result.success:
        if result.filepath and Path(result.filepath).exists():
            # Downloaded file
            st.markdown('<div class="result-box success-box">', unsafe_allow_html=True)
            st.markdown("**Status:** Success")
            st.markdown(f"**Source:** {result.source}")
            st.markdown(f"**Location:** `{result.filepath}`")
            st.markdown('</div>', unsafe_allow_html=True)
            
            # Download button
            with open(result.filepath, 'rb') as f:
                st.download_button(
                    label="Download PDF",
                    data=f,
                    file_name=Path(result.filepath).name,
                    mime="application/pdf",
                    use_container_width=True
                )
        else:
            # Browser-opened or link available
            st.markdown('<div class="result-box success-box">', unsafe_allow_html=True)
            st.markdown("**Status:** Success")
            st.markdown(f"**Source:** {result.source}")
            
            # Show clickable link if we captured it
            if hasattr(st.session_state, 'browser_url') and st.session_state.browser_url:
                st.markdown(f"**Link:** [{st.session_state.browser_url}]({st.session_state.browser_url})")
                st.markdown('</div>', unsafe_allow_html=True)
                
                # Copy button
                st.text_input("Direct URL:", value=st.session_state.browser_url, disabled=True)
            else:
                st.markdown("Paper found but no download link available. Check the search log.")
                st.markdown('</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="result-box error-box">', unsafe_allow_html=True)
        st.markdown("**Status:** Failed - Paper not found")
        if result.error:
            st.markdown(f"**Error:** {result.error}")
        st.markdown('</div>', unsafe_allow_html=True)

# Sidebar - Info
with st.sidebar:
    st.header("About")
    st.markdown("""
    **Paper Finder** searches 20+ sources:
    
    **Fast Sources:**
    - Sci-Hub
    - Anna's Archive
    - LibGen
    - Telegram Bots
    
    **Open Access:**
    - Unpaywall
    - PubMed Central
    - Europe PMC
    - arXiv/bioRxiv
    
    **Discovery:**
    - Google Scholar
    - International sources
    - Publisher patterns
    """)
    
    st.markdown("---")
    
    st.header("Statistics")
    
    # Show download folder
    st.write("**Download Folder:**")
    st.code(str(output_dir), language=None)
    
    # Count PDFs
    if output_dir.exists():
        pdf_count = len(list(output_dir.glob("*.pdf")))
        st.metric("Downloaded Papers", pdf_count)
    else:
        st.metric("Downloaded Papers", 0)
    
    # Button to open folder
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Open Folder", use_container_width=True):
            import subprocess
            import platform
            try:
                if platform.system() == 'Darwin':  # macOS
                    subprocess.run(['open', str(output_dir)])
                elif platform.system() == 'Windows':
                    subprocess.run(['explorer', str(output_dir)])
                else:  # Linux
                    subprocess.run(['xdg-open', str(output_dir)])
                st.success("Folder opened")
            except Exception as e:
                st.error(f"Could not open folder: {e}")
    
    with col2:
        if st.button("Refresh", use_container_width=True):
            st.rerun()

# Footer
st.markdown("---")
