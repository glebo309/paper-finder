# Search, compare, and acquire

Paper Finder separates identifying a work from obtaining its document. You can search metadata without contacting download sources, inspecting local acquisition caches, or opening a browser.

## Install and start

From the repository directory:

```bash
python3 -m pip install -r requirements.txt
python3 main.py search "Highly accurate protein structure prediction with AlphaFold"
```

For the web interface:

```bash
python3 -m streamlit run streamlit_app.py
```

Enter a title, author/year citation, description, DOI, ISBN, arXiv ID, or URL. Choose **One particular paper** to identify a work, or **Papers about a topic** to browse related work. The candidate cards show publication details, provenance, and match reasons. Bibliographic match scores are heuristics, not confidence probabilities. Conflicting index metadata is highlighted. Expand **Inspect indexed repository records** to inspect original locations, including arXiv, when the primary DOI or publication year appears questionable.

Click **Select this paper**, review the selected title, then **Download selected paper**. Merely searching or selecting never starts acquisition. A new search clears the previous selection and download result.

The web app saves documents under `~/Downloads/Papers`. Its sidebar shows the folder and saved PDF count. The activity log and verification details remain available below the result.

## Metadata-only CLI search

```bash
python3 main.py search "Jumper AlphaFold 2021" --limit 10 --save-results results.json
python3 main.py search "enzyme immobilisation porous supports" --mode discover --limit 20
python3 main.py search "10.1038/s41586-021-03819-2" --json
python3 main.py search "arXiv:1706.03762"
```

`--limit` accepts 1–50 candidates. `identify` is the default mode. Topic discovery returns a candidate list for the user to assess rather than automatically identifying one paper.

Text searches combine provider candidates, remove duplicate records for the same identity, and rank the bibliographic evidence. If any attempted provider fails, free-text results require selection instead of silently becoming an automatic match. Quota responses start a shared in-memory cooldown for that provider; other providers can still return candidates. An exact supplied DOI remains an identity constraint. Books, preprints, and URLs retain their dedicated metadata resolvers. Available providers and response times depend on API access, rate limits, and network conditions. An unavailable provider is reported separately from a successful empty search; available providers can still contribute results.

JSON contains `query`, `status`, `candidates`, `selected`, and `errors`. Candidate records carry title, authors, year, identifiers, sources, and match reasons. Errors remain visible when a provider fails. `selected` is only populated when the resolver has enough evidence for a strong match.

## Acquire a selected work

```bash
python3 main.py acquire "10.1038/s41586-021-03819-2" --output downloads
python3 main.py acquire --from-results results.json --select 1 --output downloads
python3 main.py acquire --from-results results.json --select 1 --json
```

Use `search QUERY --save-results results.json` to save exactly the candidate records and order shown. Then `acquire --from-results results.json --select N` chooses candidate N from that snapshot, **without repeating metadata discovery**. Omit the reference argument when using `--from-results`. Acquisition can still contact document sources to obtain the selected work.

Snapshots use a versioned JSON envelope. Loading validates candidate identifiers, DOI consistency, title/author/year fields, URLs, and whether any automatic selection belongs to the saved candidates. Invalid or unsupported snapshots fail before the downloader is constructed. The snapshot is saved atomically and can be inspected in a text editor.

Without `--select`, acquisition proceeds only for a strong match. Ambiguous references return the candidate list without constructing the downloader. `acquire QUERY --select N` remains available for a fresh search, but its order may differ from a previous search; use a snapshot, an exact identifier, or the web interface when choosing a result you have already reviewed.

`--config FILE` uses a YAML configuration file; the default is `config.yaml` when present. Output paths accept `~`. CLI progress goes to stderr, keeping `--json` stdout parseable. The CLI captures document links instead of opening a browser automatically.

Results distinguish:

- **verified**: a local document passed the identity checks.
- **located**: a document link was found, but no verified local PDF was saved.
- **unverifiable**: a document could not be checked, for example because a scan has no extractable text. Any retained review path is shown explicitly.
- **mismatch**: retrieved content does not match the selected work.
- **ambiguous**: identification needs an explicit selection or a more specific reference.
- **not_found / unavailable / failed / error**: no result, unavailable metadata services, unsuccessful acquisition, or an operational error.

A link alone is not reported as a successful download. Verification evidence is included in acquisition JSON when available.

## Exit codes and scripting

| Exit | Meaning |
| --- | --- |
| `0` | Search returned candidates, or acquisition returned a verified document |
| `1` | No search results, providers unavailable, acquisition incomplete, or operational failure |
| `2` | Acquisition needs a selection, a selection is out of range, or command syntax is invalid |

Search can exit `0` with `status: ambiguous`: metadata search succeeded, but no identity was chosen. Check `status` and `selected` before using the result in an automated acquisition workflow. Argument parsing errors use normal argparse stderr output; runtime search/acquisition errors respect `--json`.

## Interface regression checks

```bash
python3 -m pytest tests/unit/test_cli.py tests/unit/test_search_ui.py -q
```

These tests run the actual CLI entry point with deterministic metadata responses, exercise the real configured constructor, verify ambiguity stops acquisition, check clean JSON and located-link outcomes, check stable saved-result selection and invalid snapshot rejection, and run the Streamlit app through search, selection, acquisition, and a fresh search using Streamlit's `AppTest`. Network downloads are mocked.
