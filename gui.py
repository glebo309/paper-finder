#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Paper Finder GUI

Graphical interface for the Paper Finder system.
Provides an intuitive way to search for and download academic papers.
"""

import sys
import threading
from pathlib import Path
from typing import Optional
import webbrowser

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import requests
import os

from paper_finder import PaperFinder, DownloadResult
from src.core.config import load_config, set_config


class _TextRedirector:
    """Redirect stdout/stderr to the GUI log in a thread-safe way."""

    def __init__(self, gui: "PaperFinderGUI") -> None:
        self.gui = gui

    def write(self, message: str) -> None:
        if not message:
            return
        self.gui.root.after(0, self.gui.log, message.rstrip("\n"))

    def flush(self) -> None:  # required for file-like interface
        pass


class PaperFinderGUI:
    """Main GUI application for Paper Finder"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Paper Finder - Academic PDF Download")
        self.root.geometry("600x340")  # Start with only search section visible (enough room for both toggles)
        
        # Configure style
        self.setup_style()
        
        # Load and set global configuration
        config_path = Path('config.yaml')
        if config_path.exists():
            try:
                config = load_config(str(config_path))
                set_config(config)  # Set as global config
            except Exception as e:
                print(f"Warning: Could not load config.yaml: {e}")
        
        # Initialize finder (silent mode for fast GUI startup)
        # Config is now loaded globally via set_config
        self.finder = PaperFinder(silent_init=True)
        
        # Verbose logging flag
        self.verbose_logging = tk.BooleanVar(value=True)  # Default to True for visibility
        self.logging_silenced = False
        
        # Spinner state
        self.spinner_active = False
        self.spinner_frame = 0
        
        # Timer state
        self.search_start_time = None
        self.timer_job = None
        
        # Build interface
        self.build_interface()
        
        # Center window
        self.center_window()
    
    def setup_style(self):
        """Configure application style"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # Configure colors
        bg_color = '#f0f0f0'
        self.root.configure(bg=bg_color)
        
        style.configure('Title.TLabel', font=('Helvetica', 16, 'bold'))
        style.configure('Status.TLabel', font=('Helvetica', 10))
    
    def build_interface(self):
        """Build the user interface"""
        # Main container
        main_frame = ttk.Frame(self.root, padding="20")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        
        # Title
        title_label = ttk.Label(
            main_frame, 
            text="Paper Finder", 
            style='Title.TLabel'
        )
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        
        # Input section
        self.build_input_section(main_frame)
        
        # Output section  
        self.build_output_section(main_frame)
        
        # Log section
        self.build_log_section(main_frame)
        
        # Status bar
        self.build_status_bar()
    
    def build_input_section(self, parent):
        """Build the input section"""
        input_frame = ttk.LabelFrame(parent, text="Search Parameters", padding="10")
        input_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
        input_frame.columnconfigure(1, weight=1)
        
        # DOI/Title/URL input
        ttk.Label(input_frame, text="DOI, Title, or URL:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        self.doi_var = tk.StringVar()
        doi_entry = ttk.Entry(input_frame, textvariable=self.doi_var, width=50)
        doi_entry.grid(row=0, column=1, sticky=(tk.W, tk.E))
        doi_entry.bind('<Return>', lambda e: self.search())
        
        # Output directory
        ttk.Label(input_frame, text="Save to:").grid(row=1, column=0, sticky=tk.W, padx=(0, 10), pady=(10, 0))
        self.output_var = tk.StringVar(value=str(Path.home() / "Downloads"))
        output_entry = ttk.Entry(input_frame, textvariable=self.output_var)
        output_entry.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=(10, 0))
        
        browse_btn = ttk.Button(
            input_frame, 
            text="…",  # single ellipsis, more compact
            command=self.browse_output,
            width=2
        )
        browse_btn.grid(row=1, column=2, padx=(6, 0), pady=(10, 0))
        
        self.recent_sources = tk.BooleanVar(value=True)
        ttk.Checkbutton(input_frame, text="Prioritize recent full-text sources",
                        variable=self.recent_sources).grid(
                            row=2, column=0, columnspan=3, sticky=tk.W, pady=(12, 0))

        # Search button with status indicator
        button_frame = ttk.Frame(input_frame)
        button_frame.grid(row=3, column=0, columnspan=3, pady=(12, 0))
        
        self.search_button = ttk.Button(
            button_frame, 
            text="Get Paper", 
            command=self.search
        )
        self.search_button.grid(row=0, column=0)
        
        # Stop button to cancel ongoing search
        self.stop_button = ttk.Button(
            button_frame,
            text="Stop",
            command=self.stop_search,
            state='disabled'
        )
        self.stop_button.grid(row=0, column=1, padx=(10, 0))
        
        # Visual status indicator (green checkmark when found)
        self.status_indicator = ttk.Label(
            button_frame,
            text="",
            font=('Helvetica', 16),
            foreground="green"
        )
        self.status_indicator.grid(row=0, column=2, padx=(10, 0))
    
    def build_output_section(self, parent):
        """Build the output section with collapsible behavior"""
        # Wrapper for result section
        self.result_container = ttk.Frame(parent)
        self.result_container.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(5, 0))
        self.result_container.columnconfigure(0, weight=1)
        
        # Shared toggle row for Result and Activity Log
        toggle_bar = ttk.Frame(self.result_container)
        toggle_bar.grid(row=0, column=0, sticky=(tk.W, tk.E))
        toggle_bar.columnconfigure(0, weight=0)
        toggle_bar.columnconfigure(1, weight=1)
        toggle_bar.columnconfigure(2, weight=0)
        toggle_bar.columnconfigure(3, weight=0)
        
        # Result toggle
        self.result_visible = tk.BooleanVar(value=False)
        self.result_toggle_btn = ttk.Label(toggle_bar, text="▼")
        self.result_toggle_btn.grid(row=0, column=0, sticky=tk.W, padx=(5, 2))
        self.result_toggle_btn.bind('<Button-1>', lambda e: self.toggle_result())
        ttk.Label(toggle_bar, text="Result", font=('Helvetica', 10, 'bold')).grid(row=0, column=1, sticky=tk.W)

        # Log toggle (reused in build_log_section)
        self.log_visible = tk.BooleanVar(value=False)
        self.log_toggle_btn = ttk.Label(toggle_bar, text="▼")
        self.log_toggle_btn.grid(row=0, column=2, sticky=tk.W, padx=(20, 2))
        self.log_toggle_btn.bind('<Button-1>', lambda e: self.toggle_log())
        ttk.Label(toggle_bar, text="Activity Log", font=('Helvetica', 10, 'bold')).grid(row=0, column=3, sticky=tk.W)

        # Actual result frame (initially hidden)
        output_frame = ttk.LabelFrame(self.result_container, text="Result", padding="10")
        self.output_frame = output_frame
        output_frame.columnconfigure(1, weight=1)
        
        # Result fields
        self.result_fields = {}
        fields = [
            ('Status:', 'status'),
            ('Source:', 'source'),
            ('Title:', 'title'),
            ('Author:', 'author'),
            ('File:', 'file'),
        ]
        
        for i, (label, key) in enumerate(fields):
            ttk.Label(output_frame, text=label).grid(row=i, column=0, sticky=tk.W, padx=(0, 10), pady=2)
            var = tk.StringVar()
            self.result_fields[key] = var
            
            if key == 'file':
                # Make file path clickable
                label_widget = ttk.Label(
                    output_frame, 
                    textvariable=var,
                    foreground='blue',
                    cursor='hand2'
                )
                label_widget.grid(row=i, column=1, sticky=(tk.W, tk.E), pady=2)
                label_widget.bind('<Button-1>', self.open_file)
            else:
                ttk.Label(output_frame, textvariable=var).grid(row=i, column=1, sticky=(tk.W, tk.E), pady=2)
    
        handoff = ttk.Frame(output_frame)
        handoff.grid(row=5, column=0, columnspan=2, sticky=tk.W, pady=(12, 0))
        self.publisher_button = ttk.Button(handoff, text="Open publisher", command=self.open_publisher, state='disabled')
        self.publisher_button.grid(row=0, column=0)
        self.import_pdf_button = ttk.Button(handoff, text="Import browser PDF", command=self.import_browser_pdf, state='disabled')
        self.import_pdf_button.grid(row=0, column=1, padx=(10, 0))
        self.watch_download_button = ttk.Button(handoff, text='Watch browser download', command=self.watch_browser_download, state='disabled')
        self.watch_download_button.grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(8, 0))
        ttk.Button(handoff, text='Institution settings', command=self.institution_settings).grid(row=2, column=0, sticky=tk.W, pady=(8, 0))
        ttk.Button(handoff, text='Open library login', command=self.open_library_login).grid(row=2, column=1, padx=(10, 0), pady=(8, 0))

    def build_log_section(self, parent):
        """Build the log section (content only, header is in toggle bar)"""
        # Wrapper frame for log content
        self.log_container = ttk.Frame(parent)
        self.log_container.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(5, 10))
        self.log_container.columnconfigure(0, weight=1)
        self.log_container.rowconfigure(0, weight=1)
        parent.rowconfigure(3, weight=1)

        # Actual log frame (no extra "Activity Log" header here)
        self.log_frame = ttk.Frame(self.log_container, padding="10")
        self.log_frame.columnconfigure(0, weight=1)
        self.log_frame.rowconfigure(0, weight=1)

        # Log text area
        self.log_text = scrolledtext.ScrolledText(
            self.log_frame,
            height=10,
            wrap=tk.WORD,
            font=('Courier', 9)
        )
        self.log_text.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Bottom controls: verbose toggle and clear button
        controls_frame = ttk.Frame(self.log_frame)
        controls_frame.grid(row=1, column=0, pady=(10, 0), sticky=tk.W)
        
        verbose_check = ttk.Checkbutton(
            controls_frame,
            text="Show full process log",
            variable=self.verbose_logging
        )
        verbose_check.grid(row=0, column=0, sticky=tk.W, padx=(0, 20))
        
        ttk.Button(
            controls_frame,
            text="Clear Log",
            command=self.clear_log
        ).grid(row=0, column=1, sticky=tk.W)
    
    def build_status_bar(self):
        """Build the status bar"""
        status_frame = ttk.Frame(self.root)
        status_frame.grid(row=1, column=0, sticky=(tk.W, tk.E))
        status_frame.columnconfigure(0, weight=1)  # Left side expands
        
        self.status_var = tk.StringVar(value="Ready")
        status_label = ttk.Label(
            status_frame,
            textvariable=self.status_var,
            style='Status.TLabel'
        )
        status_label.grid(row=0, column=0, padx=10, pady=5, sticky=tk.W)
        
        # Timer on the right side
        self.timer_var = tk.StringVar(value="")
        timer_label = ttk.Label(
            status_frame,
            textvariable=self.timer_var,
            style='Status.TLabel'
        )
        timer_label.grid(row=0, column=1, padx=10, pady=5, sticky=tk.E)
    
    def toggle_result(self):
        """Show/hide the Result section and resize window"""
        if self.result_visible.get():
            # Hide
            self.output_frame.grid_remove()
            self.result_toggle_btn.configure(text="▼")
            self.result_visible.set(False)
        else:
            # Show
            self.output_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(5, 0))
            self.result_toggle_btn.configure(text="▲")
            self.result_visible.set(True)
        
        # Resize based on what's visible
        self._resize_window()
    
    def toggle_log(self):
        """Show/hide the Activity Log section and resize window"""
        if self.log_visible.get():
            # Hide
            self.log_frame.grid_remove()
            self.log_toggle_btn.configure(text="▼")
            self.log_visible.set(False)
        else:
            # Show
            self.log_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(5, 0))
            self.log_toggle_btn.configure(text="▲")
            self.log_visible.set(True)
            # Force update to ensure log text is visible
            self.root.update_idletasks()
        
        # Resize based on what's visible
        self._resize_window()
    
    def _resize_window(self):
        """Resize window based on which sections are visible"""
        result_shown = self.result_visible.get()
        log_shown = self.log_visible.get()
        
        if not result_shown and not log_shown:
            # Only search section (both toggles visible)
            self.root.geometry("600x340")
        elif result_shown and not log_shown:
            # Search + Result
            self.root.geometry("600x650")
        elif not result_shown and log_shown:
            # Search + Log
            self.root.geometry("600x590")
        else:
            # All sections
            self.root.geometry("600x970")
    
    def center_window(self):
        """Center the window on screen"""
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')
    
    def browse_output(self):
        """Browse for output directory"""
        directory = filedialog.askdirectory(
            title="Select Output Directory",
            initialdir=self.output_var.get()
        )
        if directory:
            self.output_var.set(directory)
    
    def search(self):
        """Search for and download paper.

        The engine (paper_finder) controls if/when the browser is opened,
        based on whether the paper is actually Open Access.
        """
        if getattr(self, "_search_active", False):
            return
        ref = self.doi_var.get().strip()
        if not ref:
            messagebox.showwarning("Input Required", "Please enter a DOI, title, or URL")
            return
        
        self._search_active = True
        self._search_id = getattr(self, "_search_id", 0) + 1
        self.logging_silenced = False
        # Clear previous results
        self.clear_results()
        self.status_var.set("Searching...")
        self.start_spinner()
        
        # Start timer
        import time
        self.search_start_time = time.time()
        self.update_timer()

        # Disable search button, enable Stop
        self.search_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        
        # Run search in background thread (full pipeline)
        # Pass raw reference - finder.find() will handle DOI extraction/resolution
        thread = threading.Thread(
            target=self._search_thread,
            args=(ref, Path(self.output_var.get()), self.recent_sources.get()),
            daemon=True
        )
        thread.start()
    
    def _search_thread(self, ref: str, output_dir: Path, recent_sources=True):
        """Background thread for searching"""
        request_id = getattr(self, "_search_id", 0)
        def post(callback, *args):
            def dispatch():
                if getattr(self, "_search_id", 0) == request_id:
                    callback(*args)
            self.root.after(0, dispatch)
        redirector: Optional[_TextRedirector] = None
        old_stdout = None
        old_stderr = None
        browser_opened = [False]  # Use list to allow modification in nested function
        
        try:
            # Log start of search on the main thread
            post(self.log, f"Searching for: {ref}")

            # Verbose logging: stream stdout/stderr to the Activity Log in real time
            if self.verbose_logging.get():
                redirector = _TextRedirector(self)
                old_stdout, old_stderr = sys.stdout, sys.stderr
                sys.stdout, sys.stderr = redirector, redirector

            # A located article is not a verified download. Keep its URL in the log.
            def on_oa_detected(identifier: str, url: str):
                post(self.log, f"Article link found: {url}")

            # Metadata callback: update title/author in Results section as soon as paper is identified
            def on_meta(meta: dict):
                title = meta.get("title", "")
                authors = meta.get("authors", [])
                author_str = ""
                if authors:
                    # Show first 2-3 authors and last author
                    if isinstance(authors, list) and len(authors) > 0:
                        if len(authors) <= 3:
                            author_str = ', '.join(authors)
                        else:
                            # First 2-3 + last
                            first_authors = authors[:3]
                            last_author = authors[-1]
                            if last_author not in first_authors:
                                author_str = ', '.join(first_authors) + f', ... {last_author}'
                            else:
                                author_str = ', '.join(first_authors)
                    else:
                        author_str = str(authors)

                def _set():
                    if title:
                        self.result_fields['title'].set(title)
                    if author_str:
                        self.result_fields['author'].set(author_str)

                post(_set)

            if isinstance(ref, dict):
                result = self.finder.find_record(ref, output_dir, oa_callback=on_oa_detected, meta_callback=on_meta,
                                                      recent_sources=recent_sources)
            else:
                result = self.finder.find(ref, output_dir, oa_callback=on_oa_detected, meta_callback=on_meta,
                                                      recent_sources=recent_sources)

            # Update UI in main thread, passing the browser_opened flag
            post(self._update_results, result, browser_opened[0])

        except Exception as e:
            post(self._search_error, str(e))
        finally:
            # Restore original stdout/stderr
            if redirector is not None and old_stdout is not None and old_stderr is not None:
                sys.stdout, sys.stderr = old_stdout, old_stderr
    
    def _update_results(self, result: DownloadResult, browser_already_opened: bool = False):
        """Update UI with search results"""
        self._search_active = False
        # Re-enable search button, disable Stop
        self.search_button.configure(state='normal')
        self.stop_button.configure(state='disabled')
        self.stop_spinner()
        
        # Auto-show result section when search completes
        if not self.result_visible.get():
            self.toggle_result()
        
        # Extract metadata
        meta = result.metadata or {}
        self._set_handoff_record(meta if getattr(result, "status", "") != "ambiguous" else None)
        title = meta.get('title', '')
        authors = meta.get('authors', [])
        is_oa = bool(meta.get('is_oa'))
        
        # Update title and author in result fields (if not already set by callback)
        if title and not self.result_fields['title'].get():
            self.result_fields['title'].set(title)
        if authors and not self.result_fields['author'].get():
            # Show first 2-3 authors and last author
            if isinstance(authors, list) and len(authors) > 0:
                if len(authors) <= 3:
                    author_str = ', '.join(authors)
                else:
                    # First 2-3 + last
                    first_authors = authors[:3]
                    last_author = authors[-1]
                    if last_author not in first_authors:
                        author_str = ', '.join(first_authors) + f', ... {last_author}'
                    else:
                        author_str = ', '.join(first_authors)
            else:
                author_str = str(authors)
            self.result_fields['author'].set(author_str)
        
        candidates = meta.get('candidates', [])
        if getattr(result, 'status', '') == 'ambiguous' and candidates:
            self.status_var.set("Choose the paper you meant")
            self.result_fields['status'].set("Needs selection")
            self._show_candidates(candidates)
            return
        status = getattr(result, 'status', '') or ('verified' if result.success else 'not_found')
        labels = {
            'verified': 'Verified download', 'unverifiable': 'Saved, identity unverified' if result.filepath else 'Document identity unverified',
            'mismatch': 'Document does not match', 'located': 'Article link found, no verified download',
            'cancelled': 'Search cancelled', 'unavailable': 'Search providers unavailable',
            'not_found': 'No verified download found',
        }
        label = labels.get(status, status.replace('_', ' ').capitalize())
        self.status_var.set(label)
        self.result_fields['status'].set(label)
        self.result_fields['source'].set(result.source or "None")
        self.result_fields['file'].set(str(result.filepath) if result.filepath else "")
        self.status_indicator.configure(text="OK" if result.success else "")
        self.log(label)
        if result.error:
            self.log(result.error)
        if result.filepath:
            self.log(f"Saved to: {result.filepath}")

    def _show_candidates(self, candidates):
        """Offer real records for explicit selection on the Tk main thread."""
        window = tk.Toplevel(self.root)
        window.title("Choose a paper")
        window.geometry("900x480")
        window.transient(self.root)
        ttk.Label(window, text="Several papers may match. Select the one you want to download.",
                  padding=12).pack(anchor='w')
        columns = ('title', 'authors', 'year', 'source')
        table = ttk.Treeview(window, columns=columns, show='headings', selectmode='browse')
        for key, width in zip(columns, (420, 220, 65, 140)):
            table.heading(key, text=key.capitalize())
            table.column(key, width=width, minwidth=50)
        for index, record in enumerate(candidates):
            table.insert('', 'end', iid=str(index), values=(record.get('title', ''),
                         ', '.join(record.get('authors', [])[:3]), record.get('year') or '',
                         ', '.join(record.get('sources', []))))
        table.pack(fill='both', expand=True, padx=12)
        details = tk.StringVar(value="Select a result to see the match evidence.")
        ttk.Label(window, textvariable=details, wraplength=850, padding=12).pack(anchor='w')
        def select(_event=None):
            selection = table.selection()
            if selection:
                record = candidates[int(selection[0])]
                details.set(record.get('title', '') + "\n" + '; '.join(record.get('match_reasons', []))
                            + "\n" + str((record.get('identifier') or {}).get('value', '')))
                download.configure(state='normal')
                browser_handoff.configure(state='normal')
        def acquire():
            selection = table.selection()
            if not selection:
                return
            record = candidates[int(selection[0])]
            window.destroy()
            self._search_active = True
            self._search_id = getattr(self, "_search_id", 0) + 1
            self.clear_results()
            self.search_button.configure(state='disabled')
            self.stop_button.configure(state='normal')
            self.status_var.set("Downloading selected paper...")
            self.start_spinner()
            threading.Thread(target=self._search_thread,
                             args=(record, Path(self.output_var.get()), self.recent_sources.get()), daemon=True).start()
        def use_browser():
            selection = table.selection()
            if not selection:
                return
            record = candidates[int(selection[0])]
            window.destroy()
            self.clear_results()
            self._update_results(DownloadResult(False, status='located', metadata=record,
                error='Open the publisher page, download through your browser access, then import the PDF for verification.'))
        buttons = ttk.Frame(window, padding=12)
        buttons.pack(fill='x')
        download = ttk.Button(buttons, text="Download selected paper", command=acquire, state='disabled')
        download.pack(side='right')
        browser_handoff = ttk.Button(buttons, text='Use browser / import instead', command=use_browser, state='disabled')
        browser_handoff.pack(side='right', padx=8)
        ttk.Button(buttons, text="Cancel", command=window.destroy).pack(side='right', padx=8)
        table.bind('<<TreeviewSelect>>', select)
        window.grab_set()

    def _search_error(self, error: str):
        """Handle search error"""
        self._search_active = False
        self.search_button.configure(state='normal')
        self.stop_button.configure(state='disabled')
        self.stop_spinner()
        self.status_var.set("Error")
        self.log(f"Error: {error}")
        messagebox.showerror("Search Error", f"An error occurred:\n{error}")
    
    def _set_handoff_record(self, record):
        valid = isinstance(record, dict) and bool(record.get('title')) and bool((record.get('identifier') or {}).get('value'))
        self._handoff_record = dict(record) if valid else None
        state = 'normal' if valid and not getattr(self, '_search_active', False) else 'disabled'
        for name in ('publisher_button', 'import_pdf_button', 'watch_download_button'):
            button = getattr(self, name, None)
            if button is not None:
                button.configure(state=state)

    def _institutional_settings(self):
        from src.acquisition.institutional_access import load_institutional_settings
        settings = getattr(self, '_institution_settings', None)
        return settings if settings is not None else load_institutional_settings(getattr(getattr(self, 'finder', None), 'config', None))

    def institution_settings(self):
        from src.acquisition.institutional_access import InstitutionalAccessSettings, validate_proxy_template, validate_login_url
        try:
            current = self._institutional_settings()
        except ValueError as exc:
            messagebox.showerror('Institution settings', str(exc))
            current = InstitutionalAccessSettings()
        window = tk.Toplevel(self.root)
        window.title('Institution settings')
        window.geometry('650x260')
        window.transient(self.root)
        fields = {}
        for row, (key, label) in enumerate((('label', 'Library name'), ('login_url', 'Official sign-in URL'), ('proxy_template', 'Official proxy template ({url})'))):
            ttk.Label(window, text=label).grid(row=row, column=0, sticky=tk.W, padx=12, pady=8)
            fields[key] = tk.StringVar(value=getattr(current, key))
            ttk.Entry(window, textvariable=fields[key], width=48).grid(row=row, column=1, padx=12, pady=8, sticky=(tk.W, tk.E))
        ttk.Label(window, text='Use your library’s published URLs. Sign in in the browser. Settings apply to this session; no passwords or cookies are stored.', wraplength=610).grid(row=3, column=0, columnspan=2, padx=12, pady=8)
        def save():
            try:
                self._institution_settings = InstitutionalAccessSettings(label=fields['label'].get().strip(),
                    login_url=validate_login_url(fields['login_url'].get()),
                    proxy_template=validate_proxy_template(fields['proxy_template'].get()))
            except ValueError as exc:
                messagebox.showerror('Institution settings', str(exc), parent=window)
                return
            window.destroy()
        ttk.Button(window, text='Apply', command=save).grid(row=4, column=1, sticky=tk.E, padx=12, pady=8)
        window.columnconfigure(1, weight=1)
        window.grab_set()

    def open_library_login(self):
        try:
            settings = self._institutional_settings()
            if settings.login_url:
                webbrowser.open(settings.login_url)
            else:
                messagebox.showinfo('Library sign-in', 'Add your library’s official sign-in URL in Institution settings.')
        except ValueError as exc:
            messagebox.showerror('Library sign-in', str(exc))

    def open_publisher(self):
        """Open only on an explicit click, using the record or configured proxy."""
        from src.acquisition.institutional_access import browser_access_url
        record = getattr(self, '_handoff_record', None)
        if not record or getattr(self, '_search_active', False):
            return
        try:
            settings = self._institutional_settings()
            webbrowser.open(browser_access_url(record, proxy_template=settings.proxy_template))
        except ValueError as exc:
            messagebox.showerror('Open publisher', str(exc))

    def watch_browser_download(self):
        from src.acquisition.browser_handoff import BrowserDownloadWatcher
        from src.acquisition.institutional_access import browser_access_url
        record = getattr(self, '_handoff_record', None)
        if not record or getattr(self, '_search_active', False):
            return
        folder = filedialog.askdirectory(title='Choose your browser download folder', initialdir=str(Path.home() / 'Downloads'))
        if not folder:
            return
        try:
            settings = self._institutional_settings()
            url = browser_access_url(record, proxy_template=settings.proxy_template)
            watcher = BrowserDownloadWatcher(record, folder, self.output_var.get(), timeout=300)
        except ValueError as exc:
            messagebox.showerror('Browser download watch', str(exc))
            return
        if watcher.finished:
            self._update_results(watcher.poll())
            return
        self._browser_watcher = watcher
        self._search_active = True
        self._search_id = getattr(self, '_search_id', 0) + 1
        self._set_handoff_record(record)
        self.search_button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.status_var.set('Waiting for browser PDF. Use Stop to cancel.')
        webbrowser.open(url)
        threading.Thread(target=self._watch_browser_thread, args=(watcher, self._search_id), daemon=True).start()

    def _watch_browser_thread(self, watcher, request_id):
        import time
        previous = None
        while True:
            result = watcher.poll()
            message = watcher.message
            if result is not None:
                def finish(result=result):
                    if getattr(self, '_search_id', 0) == request_id:
                        self._update_results(result)
                self.root.after(0, finish)
                return
            if message != previous:
                def update(message=message):
                    if getattr(self, '_search_id', 0) == request_id:
                        self.status_var.set(message)
                self.root.after(0, update)
                previous = message
            time.sleep(.75)

    def import_browser_pdf(self):
        """Choose a local browser download; verification and copying stay offline."""
        record = getattr(self, '_handoff_record', None)
        if not record or getattr(self, '_search_active', False):
            return
        source = filedialog.askopenfilename(title='Import browser-downloaded PDF', filetypes=[('PDF documents', '*.pdf')])
        if not source:
            return
        self._search_active = True
        self._search_id = getattr(self, '_search_id', 0) + 1
        self._set_handoff_record(record)
        self.search_button.configure(state='disabled')
        self.stop_button.configure(state='disabled')
        self.status_var.set('Verifying browser PDF...')
        threading.Thread(target=self._import_pdf_thread,
            args=(dict(record), source, self.output_var.get(), self._search_id), daemon=True).start()

    def _import_pdf_thread(self, record, source, output_dir, request_id):
        from src.acquisition.local_import import import_local_pdf
        try:
            result = import_local_pdf(record, source, output_dir)
        except Exception as exc:
            result = DownloadResult(False, status='error', error=str(exc), metadata=record)
        def finish():
            if getattr(self, '_search_id', 0) == request_id:
                self._update_results(result)
        self.root.after(0, finish)

    def clear_results(self):
        """Clear result fields"""
        self._set_handoff_record(None)
        for var in self.result_fields.values():
            var.set("")
        # Clear status indicator
        self.status_indicator.configure(text="")

    def stop_search(self):
        """Request cancellation of the current search"""
        try:
            watcher = getattr(self, '_browser_watcher', None)
            if watcher is not None and not watcher.finished:
                watcher.cancel()
                self.status_var.set('Cancelling browser watch...')
                self.stop_button.configure(state='disabled')
                return
            if hasattr(self, 'finder') and self.finder is not None:
                # Debug log so we can verify Stop is actually being invoked
                self.log("[GUI] Stop button pressed - calling finder.request_cancel()")
                self.finder.request_cancel()
                self.status_var.set("Cancelling search...")
                self.log("Cancellation requested by user...")
                # Visually indicate that we're stopping
                self.stop_button.configure(state='disabled')
                self.stop_spinner()
        except Exception:
            # Best-effort; errors here should not crash the GUI
            pass
    
    def open_file(self, event):
        """Open the downloaded file"""
        filepath = self.result_fields['file'].get()
        if filepath and Path(filepath).exists():
            webbrowser.open(f"file://{filepath}")
    
    def clear_log(self):
        """Clear the log text"""
        self.log_text.delete(1.0, tk.END)
    
    def start_spinner(self):
        """Start the search spinner"""
        self.spinner_active = True
        self.spinner_frame = 0
        self._animate_spinner()
    
    def stop_spinner(self):
        """Stop the search spinner"""
        self.spinner_active = False
        self.stop_timer()
    
    def _animate_spinner(self):
        """Animate the spinner in status bar"""
        if not self.spinner_active:
            return
        
        frames = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
        current_text = self.status_var.get()
        
        # Remove old spinner if present
        for frame in frames:
            current_text = current_text.replace(frame + ' ', '')
        
        # Add new spinner
        spinner = frames[self.spinner_frame % len(frames)]
        self.status_var.set(f"{spinner} {current_text}")
        
        self.spinner_frame += 1
        self.root.after(100, self._animate_spinner)
    
    def log(self, message: str):
        """Add message to log"""
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.see(tk.END)
    
    def update_timer(self):
        """Update the realtime timer display"""
        if self.search_start_time is not None:
            import time
            elapsed = time.time() - self.search_start_time
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            
            if minutes > 0:
                self.timer_var.set(f"⏱ {minutes}m {seconds}s")
            else:
                self.timer_var.set(f"⏱ {seconds}s")
            
            # Schedule next update
            self.timer_job = self.root.after(1000, self.update_timer)
    
    def stop_timer(self):
        """Stop the timer"""
        if self.timer_job:
            self.root.after_cancel(self.timer_job)
            self.timer_job = None
        
        # Show final time
        if self.search_start_time is not None:
            import time
            elapsed = time.time() - self.search_start_time
            minutes = int(elapsed // 60)
            seconds = int(elapsed % 60)
            
            if minutes > 0:
                self.timer_var.set(f"✓ {minutes}m {seconds}s")
            else:
                self.timer_var.set(f"✓ {seconds}s")
            
            self.search_start_time = None
    
    def run(self):
        """Run the application"""
        self.root.mainloop()


def main():
    """Main entry point"""
    app = PaperFinderGUI()
    app.run()


if __name__ == '__main__':
    main()
