# Validation record

Date: 2026-10-10. Local interpreter: Python 3.13.2.

## Offline checks

`python3 -m pytest -q`: **554 passed, 2 skipped** (local regression run including parallel acquisition, cooperative cancellation, repository discovery, browser watching and institutional settings). The skipped cases are pre-existing optional tests for the absent `is_valid_title` helper. Current document identity verification has its own active tests. PyPDF2 emits one deprecation warning.

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

These checks establish behavior against controlled responses. They do not establish live retrieval accuracy or coverage across every source adapter. Desktop result-routing logic is tested without opening Tk; a separate native Tk check confirmed the new recent-source checkbox is visible, enabled and within the window bounds. A headless Chrome inspection confirmed the refreshed browser controls without app exceptions.

## Live metadata checks

The first 16-case live run found 7 of 12 target papers at rank one, with no wrong automatic selections. It exposed ranking and identifier problems that were fixed before expanding the check.

At 12:51 UTC, a 24-case run produced:

| Cohort | Target at rank one | Target in top five | Correct automatic selections | Wrong automatic selections |
| --- | --- | --- | --- | --- |
| Development cases | 10/12 | 10/12 | 5 | 0 |
| Eight independently authored cross-domain cases, first run | 8/8 | 8/8 | 2 | 0 |

The four intentionally ambiguous, contradictory or impossible development queries all required selection. Median latency was 2.59 seconds, maximum 6.62 seconds. Semantic Scholar rate limits produced 16 provider warnings; OpenAlex and Crossref still supplied results. The two retrieval misses concerned Transformer citations/descriptions and polluted index metadata. A bounded citation-title fallback was subsequently added.

**The repeat run at 12:53 UTC was materially worse.** Provider quotas were reached: OpenAlex returned HTTP 429 with a retry interval of about 40,000 seconds, and other providers also returned 429s. Eight queries became unavailable. Only 11/20 targets ranked first, and two incorrect automatic selections appeared when missing independent results left a misleading Crossref hit unchallenged. These failures were retained as regression cases. The final implementation requires selection for free-text results when an attempted provider fails, requires corroboration for short titles, and shares provider cooldowns across searches instead of repeatedly calling a throttled endpoint.

No further broad identification benchmark was run after the quota response; the separate recent full-text check below uses Europe PMC and the official PMC cloud dataset. The final quota-handling fixes are verified against deterministic regression cases; a post-reset live run is still needed. The earlier successful numbers describe that particular run, not a claim about the final version's general accuracy. The eight independent cases are well-known papers and are too few to establish broad accuracy, especially for obscure work.

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

## Recent full-text acquisition, 10 October 2026

At 13:13 UTC, the opt-in recent-paper benchmark ran all three cases with actual PDF downloads enabled. It queried Europe PMC and, for an exact-DOI record with an open-access PMCID, the official PMC cloud dataset. OpenAlex and Semantic Scholar were not queried during their cooldowns. No legacy acquisition routes or messaging services were used.

| Paper / DOI | First-publication date | Actual result |
| --- | --- | --- |
| Thiamine Diphosphate-Dependent Biocatalysis in the 21st Century / `10.1002/chem.71699` | 2026-09-23 | No open full-text copy located by these providers; publisher landing page retained. |
| Engineering the Enzyme-Support Interface / `10.1021/acsami.6c14068` | 2026-09-14 | No open full-text copy located by these providers; publisher landing page retained. |
| Next-Generation Manufacturing: The Evolving Role of Biocatalysis in AstraZeneca / `10.1002/cbic.70489` | 2026-09-01 | Published version downloaded and verified, CC BY, 14 pages, 1,254,342 bytes. |

**Result: 1/3 verified, including the available control; 0/2 hard cases acquired.** This is a curated smoke test, not a representative success-rate estimate. Failure to find an open copy in these providers does not prove that no copy exists elsewhere. At this stage both hard cases remained unresolved; a later ordinary-browser check below recovered one of them.

The verified control came from [NLM PMC Article Datasets](https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/), `PMC13572967`, version 1. Its [cloud metadata](https://pmc-oa-opendata.s3.amazonaws.com/metadata/PMC13572967.1.json) confirmed the requested DOI, PMCID, published-version status and CC BY license. The production PDF verifier matched its first-page heading exactly and corroborated the author surname Rodriguez. A separate inspection confirmed the 14-page PDF's title and author list. Its MD5 matched the checksum in the official metadata: `b666873af408e4dc47ef236005242dfc`. SHA-256: `7bf325265528b4623189b122f5189f1487220cf4807b6ccbe154834413133b8d`.

The control's metadata lookup took 0.748 seconds, download and verification 1.539 seconds, and total case processing 2.387 seconds. The three-case run recorded no provider errors. Its remaining HTML landing-page probe returned no usable PDF advertisement; success came from the explicit PDF URL in cloud metadata.

This check uncovered a real upstream migration. The old `oa.fcgi` endpoint returned 404 because the [PMC OA Web Service was discontinued on 25 August 2026](https://pmc.ncbi.nlm.nih.gov/tools/oa-service/). The earlier Europe PMC browser PDF link returned 403 in this environment. The implementation now lists actual article-version metadata in the [documented public cloud structure](https://pmc-oa-opendata.s3.amazonaws.com/README.txt), verifies DOI and PMCID, and retrieves the main PDF URL advertised there. It does not infer PDF filenames, extract supplementary files, or attempt to bypass the rejected browser request.


A final repeat with publisher fallback enabled produced the same **1/3 verified PDFs and 0/2 hard-case recoveries**. Both hard cases returned publisher HTTP 403, now recorded separately from missing indexed copies. The Wiley landing page publicly labels the ThDP article open access, so its index's closed-location flag is not a reliable statement of current publisher access. The final report is `/private/tmp/paper-finder-recent-final.json`; PDFs remain in temporary storage. The default repeat command below includes this bounded publisher check.

The earlier cloud-only local report is `/private/tmp/paper-finder-recent-cloud-results.json`; its downloaded control is under `/private/tmp/paper-finder-recent-cloud-verified/`. To repeat with explicit temporary output storage:

```bash
python3 tools/benchmark_recent_fulltext.py --live --download \
  --download-dir /tmp/paper-finder-recent-check \
  --output /tmp/paper-finder-recent-results.json
```

## Difficult publisher PDF recovered through an ordinary browser

A later Chrome guest-browser check downloaded the ThDP paper (`10.1002/chem.71699`) from Wiley's regular PDF interface: **2,995,918 bytes, 15 pages**. This was a real full-text recovery, distinct from the automated HTTP benchmark above, whose publisher requests returned 403. The API benchmark's 1/3 result is retained; it must not be presented as if the browser recovery were an automated API success. Across these separate checks, the available control and one difficult paper were obtained; the ACS peroxygenase paper remains unresolved.

The initial local verifier incorrectly rejected the correct Wiley PDF. PyPDF2 extracted its title and author names with missing word spaces, while the metadata contained an exact article DOI under `/WPS-ARTICLEDOI`. Regression fixtures now cover this extraction pattern. Verification permits an exact compact title in the first-page heading only with independent corroboration from an exact article identifier or a complete author name. The article DOI metadata key is recognized; the journal DOI and arbitrary subjects are not used as article identity. Matching metadata cannot override a conflicting printed DOI or an unrelated heading. Glued supplementary headings, body citations and title-only matches remain rejected.

The downloaded PDF now verifies through its compact first-page title, all three expected author names (Lanza, Bjarnesen and Muller), and the exact article DOI. Its conventional word-token title score remains visible as 0.125, with `compact_title_match: true`; no confidence percentage is invented. SHA-256: `0b16b784f58265eb1a4ba88a71c8da14fb62048e8af535150cef2c59414496ef`.

The local evidence is `/private/tmp/paper-finder-thdp-browser-verification.json`; the downloaded document is `/private/tmp/paper-finder-thdp-2026-browser.pdf`. The document was not added to the repository. The real CLI then imported it offline using a saved selection and `--local-pdf`, returning `verified` and saving a copy under `~/Downloads/Papers/10.1002_chem.71699.pdf`. Browser handoff controls were also inspected in the running web app and native desktop UI. Browser-assisted recovery is not yet proof of unattended, cross-publisher acquisition coverage.

## Browser download watching and institutional settings

The browser, desktop and CLI now expose a bounded download-folder watcher. It snapshots existing files before waiting, requires stable PDF observations, verifies the selected identity, and publishes only a matching copy. Tests cover wrong PDFs followed by the correct one, partial downloads, symlinks, oversized files, existing files, timeouts and cancellation during verification before publication. A new browser search or candidate selection cancels the old watch. Streamlit AppTest exercises start, progress, cancellation, successful completion, configuration defaults and invalid proxy settings.

An offline integration check placed the **actual previously downloaded Wiley paper** in an isolated watched folder after the snapshot. The first poll waited; the second verified and imported the 15-page, 2,995,918-byte PDF. The original and watched download remained intact, and all three files had the previously recorded SHA-256. This tests the watcher with a real publisher PDF; it is not a new browser retrieval or an additional benchmark success. Local evidence: `/private/tmp/paper-finder-real-watcher-verification.json`.

The desktop's five recovery controls were checked in native Tk and fit within its 600 x 650 result view. The updated browser interaction is covered by Streamlit AppTest. A fresh screenshot inspection could not run because the native browser automation connection was unavailable.

Generic institutional settings accept an official library access URL and a proxy template with one encoded article URL placeholder. Configuration files, environment values and visible app controls are supported. Credentials and cookies stay in the ordinary browser. No university account was used to test authenticated access; successful account-specific access remains unverified. Eduroam is network connectivity, not a universal entitlement to subscribed journals.

See [the expanded recent-paper benchmark](RECENT_BENCHMARK.md) for the fixed cohort, automated failures and separately recorded publisher follow-ups.

## Parallel acquisition and repository audit, 10 October 2026

The normal selected-paper entry point now starts eligible direct links, every enabled registered route, and six independent recent-source jobs in the same race. A seven-party barrier regression requires the legacy route and all six discovery jobs to enter before any can continue. Other tests verify wrong-first/correct-second downloads, cross-provider manuscript conflicts, stale access labels, cancellation during verification, interruption of retries and HTTP streams, and a new operation starting while an old worker exits. Only a verified winner is published; losing and unverified race candidates are removed. Linux CI exposed a completion-order edge case: a winner could hide an already-decided rejection while its worker cleaned up. Three deterministic regressions now cover that order. A bounded 50 ms cleanup grace period preserves completed outcomes without waiting for stalled network requests.

A live production-entry-point check enabled the six public discovery jobs and disabled all legacy registry routes. It downloaded and verified `10.1002/cbic.70489` through Europe PMC's official PMC cloud location in **2.729 seconds**: **1,254,342 bytes, 14 pages**, published version, CC BY, exact DOI confirmed. The process exited normally in 3.009 seconds. A second control, `10.1016/j.coelec.2023.101346`, had an exact-DOI HAL location but its download was unverifiable; no PDF was retained. That process exited in 4.622 seconds. OpenAlex cooldowns were honored; Unpaywall remained unconfigured; no browser or messaging service was used. These controls do not estimate difficult-paper retrieval performance. Evidence: [live race report](../tests/fixtures/acquisition_race_live_20261010.json).

The separately bounded legacy audit acquired **0/4 difficult papers and 0/1 available control**. Two repository candidates were unrelated Dataverse PDFs, correctly rejected. Repository and preprint adapters now continue after those mismatches instead of returning early. Full results, endpoint failures, test budgets and limitations are in [DEEP_SOURCES.md](DEEP_SOURCES.md). The prior frozen automated benchmark remains **4/26 verified, 0/21 hard cases**; neither the race implementation nor these controls establish an improvement to that count.

Configured sources are now visible with `python3 main.py sources` and in the browser source inventory. The CLI can save repository alternatives for explicit selection, and the browser provides a manuscript selection button. Source availability labels describe configuration, not proven live success. An identifier match establishes paper identity; copies without version provenance remain version-unknown.

## Remaining limits

- Heuristic scores and thresholds are not calibrated confidence probabilities. Broad live evaluation, including unfamiliar and domain-specific papers, is still required.
- PDF checking uses the first page and document metadata. OCR and cover-page recovery are not implemented, so some legitimate files need manual review.
- Existing source adapters have heterogeneous network behavior. Group deadlines stop waiting for results, but cannot forcibly kill an in-flight Python thread. Late worker output cannot replace a published file.
- Provider schemas, quotas and full-text availability can change. Some integrations require user credentials or institution access. No universal download-success claim is made.
