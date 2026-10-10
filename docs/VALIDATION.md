# Validation record

Date: 2026-10-10. Local interpreter: Python 3.13.2.

## Offline checks

`python3 -m pytest -q`: **228 passed, 2 skipped**. The skipped cases are pre-existing optional tests for the absent `is_valid_title` helper. Current document identity verification has its own active tests. PyPDF2 emits one deprecation warning.

The default suite blocks unmocked requests. Coverage includes:

- Multiple metadata candidates, wrong first hits, uncertain matches, conflicting authors/years, DOI punctuation, duplicate identities and preprint distinctions.
- OpenAlex, Crossref, Semantic Scholar and semantic-search parsing, provenance, 429 responses, outages, malformed data, credentials omitted from errors and request budgets.
- Publisher HTML citation metadata, bounded page reads, redirects, documents without DOIs and refusal to invent identity from a generic page title.
- The actual CLI entry point, configuration constructor, JSON output, saved-result selection and malformed snapshot rejection.
- Streamlit AppTest: search, candidate selection, acquisition, new query and failed retry; desktop result routing and protection against concurrent searches.
- Real generated PDFs for correct documents, conflicting identifiers, citation-only matches, supplements, blank scans and corrupt files.
- Concurrent download workers, atomic publication, existing files, cancellation, exceptions, late completions and temporary-file cleanup.
- A combined production-path test from a title through two metadata providers to two PDF candidates: the wrong PDF is rejected and the correct file is verified.

`python3 -m compileall -q main.py paper_finder.py gui.py streamlit_app.py src tools` and CLI help checks passed. The initial published implementation passed hosted GitHub Actions on Python 3.11 and 3.13 ([run](https://github.com/glebo309/paper-finder/actions/runs/38053217389)). Later regression fixes are checked again before publication.

These checks establish behavior against controlled responses. They do not establish live retrieval accuracy or coverage across every source adapter. Native desktop rendering was not visually inspected in this environment; its result-routing logic is tested without opening Tk.

## Live metadata checks

The first 16-case live run found 7 of 12 target papers at rank one, with no wrong automatic selections. It exposed ranking and identifier problems that were fixed before expanding the check.

At 12:51 UTC, a 24-case run produced:

| Cohort | Target at rank one | Target in top five | Correct automatic selections | Wrong automatic selections |
| --- | --- | --- | --- | --- |
| Development cases | 10/12 | 10/12 | 5 | 0 |
| Eight independently authored cross-domain cases, first run | 8/8 | 8/8 | 2 | 0 |

The four intentionally ambiguous, contradictory or impossible development queries all required selection. Median latency was 2.59 seconds, maximum 6.62 seconds. Semantic Scholar rate limits produced 16 provider warnings; OpenAlex and Crossref still supplied results. The two retrieval misses concerned Transformer citations/descriptions and polluted index metadata. A bounded citation-title fallback was subsequently added.

**The repeat run at 12:53 UTC was materially worse.** Provider quotas were reached: OpenAlex returned HTTP 429 with a retry interval of about 40,000 seconds, and other providers also returned 429s. Eight queries became unavailable. Only 11/20 targets ranked first, and two incorrect automatic selections appeared when missing independent results left a misleading Crossref hit unchallenged. These failures were retained as regression cases. The final implementation requires selection for free-text results when an attempted provider fails, requires corroboration for short titles, and shares provider cooldowns across searches instead of repeatedly calling a throttled endpoint.

No further live benchmark was run after the quota response. The final quota-handling fixes are verified against deterministic regression cases; a post-reset live run is still needed. The earlier successful numbers describe that particular run, not a claim about the final version's general accuracy. The eight independent cases are well-known papers and are too few to establish broad accuracy, especially for obscure work.

```bash
python3 tools/benchmark_identification.py --live --output benchmark.json
```

The 24-case set reports retrieval rank separately from automatic identification and includes primary-source target references. API outages are not counted as correct abstentions. Reports keep the development and independently authored cohorts separate. Use optional provider credentials and respect retry intervals before rerunning.

## Real acquisition and interface checks

Production `PaperFinder.find_record()` downloaded and verified:

- **Attention Is All You Need** (`arXiv:1706.03762`): 2,215,244 bytes, title and eight author surnames matched.
- **BERT** (`arXiv:1810.04805`): 775,166 bytes, title and four author surnames matched.

A deliberate wrong-first test supplied the Attention PDF for BERT. It was rejected; the following BERT PDF was verified. An existing download retained its SHA-256 and a new unique filename was used. Later verifier regressions check conflicting arXiv identifiers, explicitly requested versions, real arXiv margin stamps and significant DOI punctuation.

The real CLI completed `search arxiv:1706.03762 --save-results ...` followed by `acquire --from-results ... --select 1 --json`, returning a verified local PDF with parseable JSON. A headless Chrome check exercised the running Streamlit search and selection controls against real arXiv metadata; the rendered result and download control were visually inspected. These checks contacted public metadata and open-access PDFs only, without using messaging sources.

## Remaining limits

- Heuristic scores and thresholds are not calibrated confidence probabilities. Broad live evaluation, including unfamiliar and domain-specific papers, is still required.
- PDF checking uses the first page and document metadata. OCR and cover-page recovery are not implemented, so some legitimate files need manual review.
- Existing source adapters have heterogeneous network behavior. Group deadlines stop waiting for results, but cannot forcibly kill an in-flight Python thread. Late worker output cannot replace a published file.
- Provider schemas, quotas and full-text availability can change. Some integrations require user credentials or institution access. No universal download-success claim is made.
