# Paper Finder

Find an academic work from a title, citation, remembered description or identifier, compare the candidates, then retrieve and verify its PDF.

Paper Finder has a browser interface, a desktop interface and a command line. Searching metadata does not start downloads. Ambiguous matches remain available for selection instead of silently becoming the first search result's DOI.

## Quick start

Python 3.11 or newer is recommended. From the repository directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run streamlit_app.py
```

The browser interface offers **One particular paper** and **Papers about a topic**. Search, review the title, authors, year and match evidence, select a record, then click **Download selected paper**. Downloads go to `~/Downloads/Papers`.

For the Tk desktop interface:

```bash
python main.py gui
```

The desktop interface searches and acquires strong matches directly. Uncertain matches open a candidate chooser. It requires a Python installation with Tk support.

## Command line

Search without downloading:

```bash
python main.py search "Jumper AlphaFold 2021" --save-results results.json
python main.py search "enzyme immobilisation porous supports" --mode discover
python main.py search "10.1038/s41586-021-03819-2" --json
```

Acquire exactly the candidate you reviewed:

```bash
python main.py acquire --from-results results.json --select 1 --output downloads
```

Or use an exact identifier:

```bash
python main.py acquire "10.1038/s41586-021-03819-2" --output downloads
```

A saved result snapshot preserves candidate identity and order. Acquisition from a snapshot does not repeat discovery. Without explicit selection, uncertain searches stop before contacting download sources.

See [the usage guide](docs/SEARCH.md) for JSON output, exit codes, configuration and result states.

## How identification works

1. **Retrieve candidates.** OpenAlex and Crossref provide metadata; Semantic Scholar provides an additional search path. ISBNs and arXiv IDs retain dedicated resolvers.
2. **Compare evidence.** Candidate records retain identifiers, title, authors, publication year, provenance and available full-text locations. Matching uses bibliographic evidence, handles punctuation and accents, and checks author/year conflicts.
3. **Search by meaning when useful.** Uncertain descriptions and topic discovery can use OpenAlex semantic search. A bounded citation fallback searches an explicitly supplied title separately while retaining the original author/year checks. Provider ranks are combined with bibliographic evidence; citations and popularity alone never establish identity.
4. **Keep uncertainty visible.** Close alternatives, vague queries and semantic-only evidence require selection. Displayed scores are heuristic evidence scores, not calibrated confidence percentages.
5. **Preserve identity.** Different DOIs remain separate, including preprints and journal versions. A failed explicit DOI lookup never silently changes into another work. Canonical arXiv links remain available when an index groups a paper with later reposts; metadata conflicts and retracted records require review.

Provider timeouts, rate limits and malformed responses are reported separately from an empty search. Search has a shared request budget. Optional credentials are read from the environment:

| Variable | Purpose |
| --- | --- |
| `OPENALEX_API_KEY` | OpenAlex access and account quota |
| `CROSSREF_MAILTO` | Contact address for Crossref requests |
| `SEMANTIC_SCHOLAR_API_KEY` | Semantic Scholar API access |
| `UNPAYWALL_EMAIL` | Contact address for Unpaywall acquisition |
| `CORE_API_KEY` | Optional CORE acquisition adapter |

Provider access policies can change. See [OpenAlex authentication](https://help.openalex.org/api/authentication/), [semantic search](https://help.openalex.org/api/semantic-search/), [Crossref's API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) and [Semantic Scholar's API](https://api.semanticscholar.org/api-docs).

## Acquisition and verification

The selected record's discovered PDF locations are tried first. For DOI records, the existing acquisition adapters provide further paths through Unpaywall, PMC, Europe PMC, repositories, publisher pages, preprints, CORE, and the project's existing mirror and book integrations. These adapters remain available; their coverage is not a promise that every source currently works. Source configuration remains in `src/core/config.py` and optional `config.yaml`.

Sources write to isolated temporary files. Only a verified winner is published, and existing files are preserved. A wrong file does not win because it arrived first. Direct discovered downloads have a size limit, a five-location limit and a shared time budget. Acquisition groups have deadlines and cancellation checks. Running source threads cannot be forcibly killed; late workers cannot overwrite the result and clean up their temporary files when they finish.

Verification examines actual PDF metadata and first-page front matter. It compares title, authors and exact identifiers, rejects contradictory identifiers and supplementary-material headings, and excludes body/reference-list matches. A DOI appearing only in a bibliography is insufficient.

| State | Meaning |
| --- | --- |
| `verified` | A local PDF passed document identity checks |
| `located` | A landing/document link is available, without a verified local download |
| `unverifiable` | The available evidence is insufficient; any retained file needs review |
| `mismatch` | Retrieved content contradicts the selected work |
| `ambiguous` | Choose between candidate records before acquisition |
| `unavailable` | Required metadata providers could not be reached |
| `cancelled` | The operation was cancelled |

`success` is true only for a verified local PDF. Opening a page does not count as a completed download. Scans, unusual cover pages and incomplete metadata can remain unverified; OCR is not implemented. Identity checking is a conservative heuristic, not a proof of document authenticity.

## Python API

```python
from src.core.discovery import DiscoveryService
from paper_finder import PaperFinder

search = DiscoveryService().search("Highly accurate protein structure prediction with AlphaFold")
if search["status"] == "matched":
    result = PaperFinder(silent_init=True).find_record(search["selected"], output_dir="downloads")
    print(result.status, result.filepath, result.verification)
else:
    for candidate in search["candidates"]:
        print(candidate["title"], candidate["year"], candidate["match_reasons"])
```

Legacy `PaperFinder.find()` and `acquire()` use the same identification policy. `PaperFinder(config=..., silent_init=True)` accepts an explicit configuration. The existing Telegram interface can use the shared engine; the candidate-selection UI described here is implemented in the CLI, browser and desktop interfaces.

## Tests and benchmarks

```bash
python -m pytest -q
```

The default suite is offline. It covers ranking and provider errors, actual CLI commands, Streamlit interactions, selected-record handoff, real generated PDF fixtures, cancellation, temporary-file cleanup, atomic publication and overwrite races. HTTP requests are blocked unless mocked. GitHub Actions is configured to run it on Python 3.11 and 3.13.

Run the separate metadata-only benchmark with an explicit live flag:

```bash
python tools/benchmark_identification.py
python tools/benchmark_identification.py --live --output benchmark.json
```

It includes 24 curated title, citation, typo, description, ambiguous and impossible cases across several disciplines. The report separates development cases from eight independently authored cases first run after the initial ranking changes. Reports distinguish top-one/top-five retrieval, correct and wrong automatic selections, abstentions, provider outages and latency. It never downloads papers. These smoke cases are not a representative accuracy estimate.

The older scripts under `tests/` outside `tests/unit/` are manual integration/download experiments and are not included in the default test run.

## Development status

This is an early-stage project with offline regression tests, live metadata checks, real open-access PDF acquisition checks and CI on Python 3.11 and 3.13. See [the validation record](docs/VALIDATION.md) for measured results and limitations. These small curated checks do not establish broad retrieval accuracy or universal download coverage. Existing screenshots in `resources/` show the earlier interfaces.

Use configured sources in accordance with their terms and the access rights available to you. Local configuration, credentials, sessions, generated PDFs and benchmark outputs should not be committed.
