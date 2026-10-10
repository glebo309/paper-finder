# Validation record

Date: 2026-10-10. Local interpreter: Python 3.13.2.

## Offline checks

`python3 -m pytest -q`: **168 passed, 2 skipped**. The skipped cases are pre-existing optional tests for the absent `is_valid_title` helper. Current document identity verification has its own active tests. PyPDF2 emits one deprecation warning.

The default suite blocks unmocked requests. Coverage includes:

- Multiple metadata candidates, wrong first hits, uncertain matches, conflicting authors/years, DOI punctuation, duplicate identities and preprint distinctions.
- OpenAlex, Crossref, Semantic Scholar and semantic-search parsing, provenance, 429 responses, outages, malformed data, credentials omitted from errors and request budgets.
- Publisher HTML citation metadata, bounded page reads, redirects, documents without DOIs and refusal to invent identity from a generic page title.
- The actual CLI entry point, configuration constructor, JSON output, saved-result selection and malformed snapshot rejection.
- Streamlit AppTest: search, candidate selection, acquisition, new query and failed retry; desktop result routing and protection against concurrent searches.
- Real generated PDFs for correct documents, conflicting identifiers, citation-only matches, supplements, blank scans and corrupt files.
- Concurrent download workers, atomic publication, existing files, cancellation, exceptions, late completions and temporary-file cleanup.
- A combined production-path test from a title through two metadata providers to two PDF candidates: the wrong PDF is rejected and the correct file is verified.

`python3 -m compileall -q main.py paper_finder.py gui.py streamlit_app.py src tools` and CLI help checks passed. GitHub Actions is configured for Python 3.11 and 3.13; a hosted CI run has not yet been verified.

These checks establish behavior against controlled responses. They do not establish live retrieval accuracy or coverage across every source adapter. Native desktop rendering was not visually inspected in this environment; its result-routing logic is tested without opening Tk.

## Live check

A four-case metadata-only benchmark was executed. All four cases were **unavailable**, with 12 provider network errors. There were no successful live responses from which to calculate search accuracy. No documents were downloaded during this check.

Run the complete live smoke set on a network-connected machine:

```bash
python3 tools/benchmark_identification.py --live --output benchmark.json
```

The 16-case set reports retrieval rank separately from automatic identification. API outages are not counted as correct abstentions. It is a curated smoke set, not a broad or independently held-out evaluation.

## Remaining limits

- Heuristic scores and thresholds are not calibrated confidence probabilities. Broad live evaluation, including unfamiliar and domain-specific papers, is still required.
- PDF checking uses the first page and document metadata. OCR and cover-page recovery are not implemented, so some legitimate files need manual review.
- Existing source adapters have heterogeneous network behavior. Group deadlines stop waiting for results, but cannot forcibly kill an in-flight Python thread. Late worker output cannot replace a published file.
- Provider schemas, quotas and full-text availability can change. Some integrations require user credentials or institution access. No universal download-success claim is made.
