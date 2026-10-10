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

After selecting a DOI record, **Find full-text copies** checks current indexed locations without downloading. It shows the reported manuscript version, licence, source, and any preprint alternatives or embargo. The sidebar has **Prioritize recent full-text sources** enabled by default and an optional **Unpaywall contact email**. The native desktop search panel has the same recent-source toggle; set `UNPAYWALL_EMAIL` or the configured Unpaywall email for that interface.

The web app saves documents under `~/Downloads/Papers`. Its sidebar shows the folder and saved PDF count. The activity log and verification details remain available below the result.

## Metadata-only CLI search

```bash
python3 main.py search "Jumper AlphaFold 2021" --limit 10 --save-results results.json
python3 main.py search "enzyme immobilisation porous supports" --mode discover --limit 20
python3 main.py search "10.1038/s41586-021-03819-2" --json
python3 main.py search "arXiv:1706.03762"
```

`--limit` accepts 1–50 candidates. `identify` is the default mode. Topic discovery returns a candidate list for the user to assess rather than automatically identifying one paper.

Text searches combine provider candidates, remove duplicate records for the same identity, and rank the bibliographic evidence. If any attempted provider fails, free-text results require selection instead of silently becoming an automatic match. Quota responses start shared process and persistent discovery cooldowns for that provider; other providers can still return candidates. An exact supplied DOI remains an identity constraint. Books, preprints, and URLs retain their dedicated metadata resolvers. Available providers and response times depend on API access, rate limits, and network conditions. An unavailable provider is reported separately from a successful empty search; available providers can still contribute results.

JSON contains `query`, `status`, `candidates`, `selected`, and `errors`. Multi-provider searches also expose `cache`, including provider hit ages and expiry times. Candidate records carry title, authors, year, identifiers, sources, and match reasons. Errors remain visible when a provider fails. `selected` is only populated when the resolver has enough evidence for a strong match.

## Cache and refresh

Successful nonempty provider metadata responses are cached for up to 24 hours. Empty results, errors and documents are not cached here. The SQLite metadata cache is limited to 500 entries, 20 MiB of retained payload and 1 MiB per response. Cache access fails open if its location is unavailable or corrupt.

```bash
python3 main.py search "a recently published paper title" --refresh
python3 main.py acquire "10.1038/s41586-021-03819-2" --refresh
```

`--refresh` bypasses saved metadata and updates successful cache entries, while respecting provider quotas. The browser equivalent is **Check sources again (ignore saved metadata)**. Exact book/preprint/URL resolver requests remain live; refresh propagates into DOI discovery used by those resolvers. `--from-results` always uses the saved identity and candidate order, even if `--refresh` is supplied.

Set `PAPER_FINDER_CACHE=0` to disable persistence, or `PAPER_FINDER_CACHE_DIR` to override the platform user-cache directory. On macOS the default is `~/Library/Caches/paper-finder`. Warm cached searches can still work during a provider cooldown. A refreshed search may instead report that the provider is rate-limited.

## Inspect copies without downloading

```bash
python3 main.py copies "10.1038/s41586-021-03819-2" --email you@example.org
python3 main.py copies "https://doi.org/10.1038/s41586-021-03819-2" --json
```

`copies` requires an exact DOI and calls Europe PMC, Unpaywall and OpenAlex directly; it does not run identification or construct the downloader. Unpaywall needs `--email` or `UNPAYWALL_EMAIL`; other providers remain usable without it. JSON separates `locations`, `alternatives`, `embargoed`, `closed`, and provider `errors`.

Each location reports its source, URL, version, licence when known, and availability. A repository landing page is a link, not a verified download. Submitted/preprint versions and conflicting version reports are alternatives requiring inspection, not silent substitutes for a journal version. An unknown licence does not establish reuse rights. An embargo date is reported when the source supplies it.

A missing indexed copy does not establish that no copy exists. Newly deposited manuscripts can take time to appear in these APIs. This command never downloads PDFs or claims acquisition success. It can inspect publisher HTML through bounded DOI redirects when indexes lack an eligible PDF, and checks current official PMC cloud metadata for matching open-access records.

## Acquire a selected work

```bash
python3 main.py acquire "10.1038/s41586-021-03819-2" --output downloads
python3 main.py acquire --from-results results.json --select 1 --output downloads
python3 main.py acquire --from-results results.json --select 1 --json
```

Use `search QUERY --save-results results.json` to save exactly the candidate records and order shown. Then `acquire --from-results results.json --select N` chooses candidate N from that snapshot, **without repeating metadata discovery**. Omit the reference argument when using `--from-results`. Acquisition can still contact document sources to obtain the selected work.

Snapshots use a versioned JSON envelope. Loading validates candidate identifiers, DOI consistency, title/author/year fields, URLs, and whether any automatic selection belongs to the saved candidates. Invalid or unsupported snapshots fail before the downloader is constructed. The snapshot is saved atomically and can be inspected in a text editor.

Without `--select`, acquisition proceeds only for a strong match. Ambiguous references return the candidate list without constructing the downloader. `acquire QUERY --select N` remains available for a fresh search, but its order may differ from a previous search; use a snapshot, an exact identifier, or the web interface when choosing a result you have already reviewed.

By default, `acquire` checks current full-text locations first for DOI records, then tries classified copies and eligible URLs from the selected record before the remaining acquisition adapters. Use `--skip-recent-sources` to omit the current-copy stage. `--email CONTACT` supplies the Unpaywall address for that stage. Available published or accepted manuscript locations can be tried automatically; submitted versions and version conflicts remain alternatives. Embargoed and closed locations are not promoted to downloadable copies. If known preprint or conflicting-version alternatives exist and no eligible copy verifies, recent mode stops for inspection rather than invoking legacy sources that cannot preserve version evidence. Otherwise legacy copies can remain version-unknown even when their identity verifies. Every retrieved PDF still passes the same identity checks.

`--config FILE` uses a YAML configuration file; the default is `config.yaml` when present. Output paths accept `~`. CLI progress goes to stderr, keeping `--json` stdout parseable. Ordinary acquisition captures document links instead of opening a browser. The explicit `--watch-downloads` mode opens the selected publisher or configured library proxy in your default browser.

Results distinguish:

- **verified**: a local document passed the identity checks.
- **located**: a document link was found, but no verified local PDF was saved.
- **unverifiable**: a document could not be checked, for example because a scan has no extractable text. Any retained review path is shown explicitly.
- **mismatch**: retrieved content does not match the selected work.
- **ambiguous**: identification needs an explicit selection or a more specific reference.
- **not_found / unavailable / failed / error**: no result, unavailable metadata services, unsuccessful acquisition, or an operational error.

A link alone is not reported as a successful download. Verification evidence is included in acquisition JSON when available.

## Finish a browser download

In the web app, select the matching paper, expand **Finish a browser download**, confirm the browser download folder, and click **Watch for browser PDF** before opening the publisher and saving its PDF. The page checks for new stable PDFs every two seconds and displays progress; **Stop watching** cancels. Keep the page open. A new search or selection cancels the previous watch. For an existing file or a browser on another computer, upload the PDF and click **Verify and save browser PDF** instead. The selected title and identifier remain the verification target. The app accepts files up to 100 MB, verifies a temporary copy, and saves only matching documents. Original files are preserved and existing output files are never overwritten.

In the desktop app, **Watch browser download** asks for your download folder, opens the publisher and waits for a matching PDF. **Stop** cancels. The result panel also retains **Open publisher** and **Import browser PDF**. For an ambiguous search, the chooser also has **Use browser / import instead**, so you can select the intended identity without starting another download attempt.

```bash
python3 main.py acquire --from-results results.json --select 1 \
  --local-pdf ~/Downloads/article.pdf --output downloads --json
```

Start the browser and watch its download folder directly from the CLI:

```bash
python3 main.py acquire --from-results results.json --select 1 \
  --watch-downloads ~/Downloads --watch-timeout 300 --output downloads --json
```

The watcher snapshots the folder before opening the browser, checks only new or changed stable PDFs, and ignores incomplete, oversized and nonmatching files. It never deletes browser downloads. `Ctrl+C` cancels; timeout and cancellation are reported as unsuccessful results. `--watch-downloads` and `--local-pdf` are mutually exclusive. Progress goes to stderr and JSON stays on stdout.

### Institutional browser access

Use your institution's sign-in on the publisher page or its official VPN. SWITCH edu-ID is one supported browser sign-in system; Paper Finder does not integrate with or store university credentials. Eduroam is network access, not a journal subscription service.

In the web sidebar, **University / library access** provides optional official login and proxy URLs. Desktop has **Institution settings** and **Open library login**. Session edits stay in the app; persistent defaults can be set in the `institutional` section of `config.yaml`:

```yaml
institutional:
  label: "University Library"
  login_url: "https://library.example/access"
  proxy_template: "https://proxy.example/login?url={url}"
```

Replace these example addresses with your library's published URLs, or leave them empty. `PAPER_FINDER_LIBRARY_LABEL`, `PAPER_FINDER_LIBRARY_LOGIN` and `PAPER_FINDER_LIBRARY_PROXY` override config defaults. The web app also reads configured defaults; sidebar edits apply to the current session. `{url}` must occur exactly once in the proxy's path or query and is replaced with the encoded article URL. Credentials in URLs and non-HTTP(S) URLs are rejected.

With CLI watching, `--proxy-template` overrides the template for that operation, and `--open-library-login` also opens the configured access page. The normal browser handles affiliation checks and sign-in. The tool cannot guarantee subscription access, and successful institutional login has not been tested against a university account.

The snapshot form makes no network requests. Without a snapshot, the reference still needs metadata identification before importing. `Browser/local PDF` is the reported source; identity verification does not by itself establish the manuscript version. Incorrect and unverifiable files are not added to the library.

## Exit codes and scripting

| Exit | Meaning |
| --- | --- |
| `0` | Search returned candidates, `copies` found locations or alternatives, or acquisition returned a verified document |
| `1` | No search results, providers unavailable, acquisition incomplete, or operational failure |
| `2` | Acquisition needs a selection, a selection is out of range, or command syntax is invalid |

`copies` exit `0` means links were found, not that a PDF was downloaded or verified. Search can exit `0` with `status: ambiguous`: metadata search succeeded, but no identity was chosen. Check `status` and `selected` before using the result in an automated acquisition workflow. Argument parsing errors use normal argparse stderr output; runtime search/acquisition errors respect `--json`.

## Interface regression checks

```bash
python3 -m pytest tests/unit/test_cli.py tests/unit/test_search_ui.py -q
```

These tests run the actual CLI entry point with deterministic metadata responses, exercise the real configured constructor, verify ambiguity stops acquisition, check clean JSON and located-link outcomes, check stable saved-result selection and invalid snapshot rejection, and run the Streamlit app through search, selection, acquisition, and a fresh search using Streamlit's `AppTest`. Network downloads are mocked.
