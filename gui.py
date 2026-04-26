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
        self.root.geometry("600x300")  # Start with only search section visible (enough room for both toggles)
        
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
        
        # Search button with status indicator
        button_frame = ttk.Frame(input_frame)
        button_frame.grid(row=2, column=0, columnspan=3, pady=(20, 0))
        
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
            self.root.geometry("600x300")
        elif result_shown and not log_shown:
            # Search + Result
            self.root.geometry("600x480")
        elif not result_shown and log_shown:
            # Search + Log
            self.root.geometry("600x550")
        else:
            # All sections
            self.root.geometry("600x800")
    
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
        ref = self.doi_var.get().strip()
        if not ref:
            messagebox.showwarning("Input Required", "Please enter a DOI, title, or URL")
            return
        
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
            args=(ref, Path(self.output_var.get())),
            daemon=True
        )
        thread.start()
    
    def _search_thread(self, ref: str, output_dir: Path):
        """Background thread for searching"""
        redirector: Optional[_TextRedirector] = None
        old_stdout = None
        old_stderr = None
        browser_opened = [False]  # Use list to allow modification in nested function
        
        try:
            # Log start of search on the main thread
            self.root.after(0, self.log, f"Searching for: {ref}")

            # Verbose logging: stream stdout/stderr to the Activity Log in real time
            if self.verbose_logging.get():
                redirector = _TextRedirector(self)
                old_stdout, old_stderr = sys.stdout, sys.stderr
                sys.stdout, sys.stderr = redirector, redirector

            # Define OA callback that opens browser immediately when OA is detected
            def on_oa_detected(doi: str, oa_url: str):
                def _open():
                    self.log(f"Paper is Open Access (fast check). Opening in browser: {oa_url}")
                    self.status_var.set("Opening Open Access paper in browser...")
                    try:
                        webbrowser.open(oa_url)
                        # Update status and result immediately
                        self.result_fields['status'].set("✓ Opened in browser")
                        self.result_fields['source'].set("Open Access (Browser)")
                        # Show green checkmark immediately
                        self.status_indicator.configure(text="✓")
                        # Auto-show result section
                        if not self.result_visible.get():
                            self.toggle_result()
                        self.status_var.set("Continuing deep search...")
                        browser_opened[0] = True  # Mark that we opened the browser
                    except Exception as e:
                        self.log(f"Browser open failed: {e}")
                        self.status_var.set("Browser open failed")
                self.root.after(0, _open)

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

                self.root.after(0, _set)

            result = self.finder.find(ref, output_dir, oa_callback=on_oa_detected, meta_callback=on_meta)

            # Update UI in main thread, passing the browser_opened flag
            self.root.after(0, self._update_results, result, browser_opened[0])

        except Exception as e:
            self.root.after(0, self._search_error, str(e))
        finally:
            # Restore original stdout/stderr
            if redirector is not None and old_stdout is not None and old_stderr is not None:
                sys.stdout, sys.stderr = old_stdout, old_stderr
    
    def _update_results(self, result: DownloadResult, browser_already_opened: bool = False):
        """Update UI with search results"""
        # Re-enable search button, disable Stop
        self.search_button.configure(state='normal')
        self.stop_button.configure(state='disabled')
        self.stop_spinner()
        
        # Auto-show result section when search completes
        if not self.result_visible.get():
            self.toggle_result()
        
        # Extract metadata
        meta = result.metadata or {}
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
        
        if result.success:
            # Check if this is a browser-only success (no PDF file)
            if result.filepath is None:
                self.status_var.set("✓ Paper opened in browser")
                self.result_fields['status'].set("✓ Opened in browser")
                self.result_fields['source'].set(result.source)
                self.result_fields['file'].set("(Opened in browser)")
                self.log(f"✓ Paper successfully opened in browser via {result.source}")
            else:
                self.status_var.set("✓ Download successful")
                self.result_fields['status'].set("✓ Success")
                self.result_fields['source'].set(result.source)
                self.result_fields['file'].set(str(result.filepath))
                self.log(f"✓ Successfully downloaded from {result.source}")
                self.log(f"Saved to: {result.filepath}")
            
            # Show green checkmark
            self.status_indicator.configure(text="✓")
            
        else:
            if result.error == "Cancelled by user":
                # Graceful cancellation: don't treat as hard failure
                self.status_var.set("Search cancelled")
                self.result_fields['status'].set("Cancelled")
                self.result_fields['source'].set("None")
                self.log("Search cancelled by user.")
                return
            
            # Download failed; decide whether to open in browser based on OA status
            if is_oa:
                # Paper was already opened in browser via fast OA check
                # Don't say "failed" - the user got access to the paper!
                self.status_var.set("✓ Paper opened in browser (Open Access)")
                # Show green checkmark
                self.status_indicator.configure(text="✓")
                # Status and source were already set by on_oa_detected callback
                if not browser_already_opened:
                    # This shouldn't happen, but just in case the fast check failed
                    self.result_fields['status'].set("✓ Opened in browser")
                    self.result_fields['source'].set("Open Access (Browser)")
                    self.log(f"PDF download not available, but paper is accessible via Open Access.")
            else:
                # Not Open Access and download failed – truly failed
                self.status_var.set("✗ Download failed")
                self.result_fields['status'].set("✗ Failed")
                self.result_fields['source'].set("None")
                self.log(f"Download failed: {result.error}")
    
    def _search_error(self, error: str):
        """Handle search error"""
        self.search_button.configure(state='normal')
        self.stop_button.configure(state='disabled')
        self.stop_spinner()
        self.status_var.set("Error")
        self.log(f"Error: {error}")
        messagebox.showerror("Search Error", f"An error occurred:\n{error}")
    
    def clear_results(self):
        """Clear result fields"""
        for var in self.result_fields.values():
            var.set("")
        # Clear status indicator
        self.status_indicator.configure(text="")

    def stop_search(self):
        """Request cancellation of the current search"""
        try:
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
