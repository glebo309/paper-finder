# Paper Finder

Find an academic work from a title, citation, remembered description or identifier, compare the candidates, then retrieve and verify its PDF.

The current development focus is recently published, difficult-to-obtain full text: checking fresh publisher and repository locations, keeping manuscript versions explicit, and verifying the actual downloaded paper.

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

The desktop interface searches and acquires strong matches directly. Uncertain matches open a candidate chooser. **Prioritize recent full-text sources** is enabled by default and can be toggled in the search panel. It requires a Python installation with Tk support.

## Command line

Search without downloading:

```bash
python main.py search "Jumper AlphaFold 2021" --save-results results.json
python main.py search "enzyme immobilisation porous supports" --mode discover
python main.py search "10.1038/s41586-021-03819-2" --json
python main.py search "a recently published paper title" --refresh
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

Inspect current full-text locations without downloading:

```bash
python main.py copies "10.1038/s41586-021-03819-2" --email you@example.org
```

This shows source, version, licence when known, and any preprint alternatives or embargo information. The contact email enables Unpaywall; Europe PMC and OpenAlex can be queried without it. `acquire` checks these current locations by default after the selected record's existing PDF links, before older fallback adapters. Use `--skip-recent-sources` to disable that stage or `--email` to provide a contact address.

See [the usage guide](docs/SEARCH.md) for JSON output, exit codes, configuration and result states.

## How identification works

1. **Retrieve candidates.** OpenAlex, Crossref and Europe PMC provide metadata; Semantic Scholar and a bounded arXiv title/citation fallback provide additional search paths. ISBNs and arXiv IDs retain dedicated resolvers.
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

## Cached metadata and freshness

Successful nonempty discovery responses are cached locally for up to 24 hours. The cache is bounded to 500 entries and 20 MiB of metadata payload, with a 1 MiB per-response limit. It contains no PDFs or API credentials. Empty results and provider errors are never cached. Search JSON exposes cache hits, their ages and expiry times.

Use `search --refresh` or `acquire --refresh` to check the indexes again. In the browser, select **Check sources again (ignore saved metadata)**. Refresh still respects provider cooldowns, including persisted discovery rate limits; it cannot bypass a provider's quota. Saved candidate snapshots remain fixed when acquired with `--from-results`.

Set `PAPER_FINDER_CACHE=0` to disable this cache or `PAPER_FINDER_CACHE_DIR` to choose its directory. The default is `~/Library/Caches/paper-finder` on macOS, the user cache directory on Linux, and the local application-data cache on Windows. Unwritable, corrupt or locked caches do not stop searches.

## Acquisition and verification

With **Prioritize recent full-text sources** enabled, DOI acquisition first checks Europe PMC, Unpaywall and OpenAlex for current copies. Exact open-access PMC records also use NLM's current public cloud dataset. When no eligible PDF is indexed, a bounded publisher check follows the DOI and reads the publisher's own access metadata; a denied request is reported as blocked rather than proof of closed access. Classified copies are tried before eligible unclassified URLs from the selected record. Available publisher and accepted-manuscript locations are eligible; submitted versions and conflicting version reports are kept as alternatives for inspection. Embargoed and closed locations are shown separately. A missing licence is reported as unknown, not inferred from free access. This stage makes bounded checks of repository landing pages when no direct PDF URL is indexed.

The browser's **Find full-text copies** button and the CLI `copies` command inspect this information without starting a download. Newly deposited work may not yet be indexed, and publisher or institutional access may still be necessary. Version labels come from providers and do not replace verification of the PDF itself.

For DOI records, the existing acquisition adapters provide further paths through Unpaywall, PMC, Europe PMC, repositories, publisher pages, preprints, CORE, and the project's existing mirror and book integrations. If known preprint or conflicting-version alternatives exist and no eligible copy verifies, recent mode stops for inspection instead of handing the request to version-blind legacy sources. Otherwise a legacy download can verify identity while its manuscript version remains unknown. These adapters remain available; their coverage is not a promise that every source currently works. Source configuration remains in `src/core/config.py` and optional `config.yaml`.

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

## When the browser can download a paper

A publisher can serve an article to your ordinary browser while denying automated HTTP requests. After selecting the paper, use **Finish a browser download** in the web interface: open the publisher, download its PDF, then upload that file and click **Verify and save browser PDF**. The desktop equivalent is **Open publisher** followed by **Import browser PDF**.

The CLI can import a saved browser download against your selected metadata:

```bash
python main.py acquire --from-results results.json --select 1 \
  --local-pdf ~/Downloads/article.pdf --output downloads --json
```

With `--from-results`, importing is entirely offline. Only a matching PDF is copied into the output library; the original and existing files stay intact. This is browser-assisted retrieval, not unattended downloading or a guarantee of institutional access. An imported copy's manuscript version remains unknown unless separately established.

## Python API

```python
from src.core.discovery import DiscoveryService
from paper_finder import PaperFinder

search = DiscoveryService().search("Highly accurate protein structure prediction with AlphaFold")
if search["status"] == "matched":
    result = PaperFinder(silent_init=True).find_record(search["selected"], output_dir="downloads", recent_sources=True)
    print(result.status, result.filepath, result.verification)
else:
    for candidate in search["candidates"]:
        print(candidate["title"], candidate["year"], candidate["match_reasons"])
```

For library callers, `find()` and `find_record()` accept `recent_sources=True` and an optional `contact_email`; recent-source expansion remains opt-in at the Python API level for compatibility. Legacy `PaperFinder.find()` and `acquire()` use the same identification policy. `PaperFinder(config=..., silent_init=True)` accepts an explicit configuration. The existing Telegram interface can use the shared engine; the candidate-selection UI described here is implemented in the CLI, browser and desktop interfaces.

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

For recent full-text acquisition, run the separate opt-in check:

```bash
python tools/benchmark_recent_fulltext.py
python tools/benchmark_recent_fulltext.py --live --download \
  --download-dir /tmp/paper-finder-recent --output /tmp/recent-results.json
```

This uses Europe PMC, official PMC cloud records and a bounded publisher fallback. It requires a real PDF and identity verification to count success. The automated three-paper check yields one verified open-access control and zero of the two harder cases. A separate ordinary-browser check subsequently recovered and verified one hard case; that assisted result is recorded separately. This is a small failure-finding sample, not a coverage estimate. See [validation](docs/VALIDATION.md).

The older scripts under `tests/` outside `tests/unit/` are manual integration/download experiments and are not included in the default test run.

## Development status

This is an early-stage project with offline regression tests, live metadata checks, real open-access PDF acquisition checks and CI on Python 3.11 and 3.13. See [the validation record](docs/VALIDATION.md) for measured results and limitations. These small curated checks do not establish broad retrieval accuracy or universal download coverage. Existing screenshots in `resources/` show the earlier interfaces.

Use configured sources in accordance with their terms and the access rights available to you. Local configuration, credentials, sessions, generated PDFs and benchmark outputs should not be committed.
