# Legacy source audit: what actually works beyond mirrors

Audit date: 10 October 2026. This audits the older retrieval modules, not just the newly added publisher/PMC/repository path. The question is whether their many source names represent demonstrated additional retrieval of recent full texts.

The audit distinguishes a registered adapter, a reachable API/search page, a located candidate, and an identity-verified main-article PDF. Only the last counts as retrieval. A search returning HTTP 200 is not a successful paper download.

## Scope and frozen cases

Four hard cases and one available control were selected from the already frozen [26-paper recent cohort](../tests/fixtures/recent_fulltext_cohort_20261010.json), before running these adapters. The four hard cases cover Wiley, ACS, Elsevier and Nature; the control was independently verified through the newer PMC-cloud route. “Hard” means no explicitly free main PDF in the initial Europe PMC index record, not proof that the publisher or every repository is closed.

| Role | DOI | Publisher family |
|---|---|---|
| Hard | 10.1002/adma.75120 | Wiley |
| Hard | 10.1021/acsami.6c11728 | ACS |
| Hard | 10.1016/j.copbio.2026.103584 | Elsevier |
| Hard | 10.1038/s41586-026-11021-5 | Nature |
| Available control | 10.1002/advs.77789 | Wiley; verified PMC-cloud copy |

Each case runs five legacy groups separately: Open Repositories, Preprints Enhanced, International, Chinese Sources, and Deep Crawl. An isolated subprocess gets at most 25 seconds, 10 HTTP requests and a four-second timeout per request. Groups run sequentially. Figshare requests are spaced by at least 1.05 seconds and arXiv requests by 3.1 seconds. A 429 prevents subsequent requests to that host. Process-group termination bounds helpers that ignore cancellation or sleep between search retries. Output, if any, is checked with the production `verify_document_identity` function; a matching PDF header alone never counts.

Crossref and OpenAlex were excluded to respect shared API limits. Mirror domains and Telegram were excluded. No credentials, institutional browser sessions, CAPTCHA solving, or account messaging were used. The short budget tests whether the old groups are useful bounded fallbacks; it does not exhaust everything each crawler could eventually search. Preprint copies would require separate version reporting and user choice, even if their title matches a journal article.

The retained machine-readable evidence lists each case's title, publication date and DOI, every requested host/path and HTTP status/error, timeout outcomes and PDF verification. Query strings, cookies, access tokens and local account paths are omitted.

## Measured results

**The bounded legacy audit retrieved 0/4 hard papers and 0/1 available control.** There were 25 source-group runs, 180 instrumented network requests and 228.5 seconds of cumulative source time. Fifteen groups returned normally; ten exhausted their request/time budget. Budget exhaustion means incomplete search, not proof that no copy exists.

| Group | Runs | Adapter claimed a PDF | Identity-verified main PDFs | Total source time |
|---|---:|---:|---:|---:|
| Open Repositories | 5 | 2 | 0 | 33.3 s |
| Preprints Enhanced | 5 | 0 | 0 | 25.7 s |
| International | 5 | 0 | 0 | 19.1 s |
| Chinese Sources | 5 | 0 | 0 | 51.7 s |
| Deep Crawl | 5 | 0 | 0 | 98.6 s |

The two claimed repository successes were **wrong papers**, not merely unverified metadata. Dataverse returned a 2010 EPA ricin-assay report for the 2026 ACS case (832,398 bytes; title similarity 0.250), and a 2013 EPA cyclosarin-decontamination report for the Elsevier case (500,112 bytes; title similarity 0.167). Neither had the target authors or DOI in its front matter. The production identity check rejected both. The old Dataverse helper searches broadly and accepts the first PDF filename without actually checking its claimed “similar name.”

Baseline evidence: [legacy_sources_results_20261010.json](../tests/fixtures/legacy_sources_results_20261010.json). This baseline includes the first three plumbing repairs below, but predates the internal verification repair. It is retained unchanged as evidence of the false positives.

After that fourth repair, a separate targeted rerun of the two false positives rejected and deleted both PDFs inside Open Repositories, continued to the next strategy, and correctly returned failure: **0 false success claims, 0 retained PDF bytes, 0 verified PDFs**, in 20.7 seconds. [Follow-up evidence](../tests/fixtures/legacy_sources_followup_20261010.json). This is an error-handling improvement, not an increased retrieval count. Preprints Enhanced has the same regression-tested internal continuation behavior; this cohort supplied no live preprint PDF on which to demonstrate it.

Google returned 429 during the baseline and was suppressed afterward. The separate follow-up directory accidentally did not inherit that local cooldown, producing one further search attempt before 429 was latched there too. No additional Google probes were made. The report retains those responses rather than masking them. A production race needs one shared host-rate-limit policy across strategies and operations, not per-group rate limits.

The OA control's published PDF had already been verified through the newer PMC-cloud path (17 pages, 3,020,084 bytes), while all five older groups missed it in this audit. That is a demonstrated improvement over these legacy groups. **No additional verified hard-paper retrieval from these legacy groups was demonstrated**, and mirror-only performance was not measured here.

## Runtime registration versus usable retrieval

The registry initially advertised 22 source labels. Several labels wrap multiple searches; others are disabled or unconfigured. Therefore neither 22 labels nor the number of domains in a module is a tested coverage figure.

| Group or source | Code actually reached / configuration | Limitation found |
|---|---|---|
| Open Repositories | Zenodo, Figshare, OSF Storage, affiliation hunt, Harvard Dataverse, Google DSpace/EPrints search | OSF `/v2/search/` returned 404. The affiliation hunt depends on Crossref and old CORE API-v2 code. Broad repository matches can be data or supplements rather than the article. |
| Preprints Enhanced | Crossref relations, arXiv, bioRxiv/medRxiv, Europe PMC, ChemRxiv, SSRN, OSF, HAL, CORE | Sequential fan-out spends its budget before later providers. Several HTML sites returned 403. Author manuscripts/preprints need explicit version handling. Old Europe PMC code constructs a PDF path; this differs from the newer verified cloud API route. |
| International | Baidu Scholar, CyberLeninka, SID, KISS, Dialnet, HAL, SciELO | Mixed HTML scraping and API searches. KISS search returned 404. `search_cnki_mirror` is an empty helper and is not called by this dispatcher. |
| Chinese Sources | CNKI, Wanfang, Baidu university search | CNKI TLS failure in this environment; English title searches do not demonstrate Chinese-language coverage. VIP search exists in the module but is not invoked by the main entry point. |
| Deep Crawl | Search engines → preprint/repository pages → author pages/profiles | Extensive serial searches, retries and sleeps; a bounded run may not reach the author stage. Affiliation-domain mapping is small and mostly hardcoded. |
| Multi-language | Registered wrapper immediately returns `False` | Translation/search code below that return is unreachable. It was not secretly enabled for this audit. |
| CORE.ac.uk | API-v3 adapter checks `CORE_API_KEY` | No key was present in the audited environment, so this source skips. Legacy helper code separately contains API-v2 URLs; that does not make the configured v3 source available. |
| Semantic Scholar | Real graph API adapter with OA PDF and arXiv fallbacks | No new live probe in this audit; not counted as working or failing. Existing implementation and registration alone cannot establish recent-paper retrieval. |
| Telegram | Previously dynamically registered even without usable credentials | Excluded from this audit. Registry presence does not establish login, authorization, configured bots, or responses. |

## Four reproducible adapter bugs repaired

These were tested to fail before implementation and pass afterward:

1. **Figshare search/detail mismatch.** The old adapter searched for `files` in the lightweight search result before fetching article detail. A valid minimal search record therefore never reached its files. It now requests detail after a title match, then checks detail metadata and PDF files. This matches [Figshare's documented lightweight-list versus complete-detail representations](https://docs.figshare.com/v2/).
2. **CyberLeninka tuple mismatch.** Its search returns `(URL, title)` pairs; the dispatcher passed the whole tuple as a URL. It now passes the URL string.
3. **Deep Crawl author-field mismatch.** Canonical records use `authors`; the crawler only checked `author` and raw Crossref authors. It now consumes the canonical plural field as well, allowing the author stage to receive the supplied names.

4. **Wrong-first PDF terminated an entire group.** Both Open Repositories and Preprints Enhanced now apply the shared identity verifier before returning success. A wrong or unverifiable PDF is removed and the group continues to its next strategy. A wrong-first/valid-second regression test covers each module. The top-level pipeline still verifies every winning candidate independently.

Regression tests: [test_legacy_source_repairs.py](../tests/unit/test_legacy_source_repairs.py). These fixes establish correct data plumbing. They are not evidence that any particular live paper was retrieved.

## What would add actual value

The old architecture repeatedly searches HTML pages and treats many failures as “nothing found.” It lacks a shared crawl budget, source-health reporting and consistent copy-version evidence. Several groups try similar providers again. Provider ordering can prevent a useful late repository API from being reached at all.

The useful direction is direct, documented repository APIs, exact DOI relationships, authoritative manuscript/version metadata, and clear access/recovery actions. Keep author-page searches as bounded fallbacks. Do not replace a unavailable journal article with a loosely matched preprint or supplement. Prefer a few sources with demonstrated correct PDFs over dozens of unvalidated scraper labels.

This audit does not run Sci-Hub or Anna's Archive, so it cannot measure a paired win over mirror-only retrieval. It can measure additional public-source retrieval and compare the old adapters with the already verified newer PMC-cloud route. Any claim that the project now obtains papers absent from both mirrors requires a separate paired comparison with recorded mirror outcomes; source count is not that evidence.

## Current scheduling and stopping work

The audit above used separate sequential subprocesses to measure each legacy group; those historical results are unchanged. The normal paper pipeline now submits all enabled registered sources to a single acquisition race, alongside eligible direct URLs from the selected record. Recent-source mode adds six independent jobs: Europe PMC, OpenAlex, Unpaywall, publisher metadata, HAL and Zenodo. Sources no longer wait behind serial tiers. Legacy adapters may still search their own internal provider lists sequentially, as described in the audit table.

Only the first identity-verified main PDF wins. Metadata results, browser navigation and unverified links cannot end the race successfully. Known preprint or conflicting-version alternatives require selection but never stop independent routes. In recent-source mode, unclassified and unknown-version copies must provide the requested identifier; classified accepted and published versions retain the existing title-and-author verification path.

The default operation-wide deadline is `pipeline.method_timeout: 45`. Setting `pipeline.parallel_execution: false` opts out of parallel scheduling and runs the same jobs sequentially within that deadline. Each operation has its own cancellation state; losing workers cannot publish over the winner. Cooperative cancellation stops new requests and checks streamed work, but a running HTTP request may finish up to its network timeout. Python threads cannot forcibly terminate arbitrary legacy helpers; the isolated audit subprocesses above used hard process termination for that reason.

The CLI `sources` command and browser **Search sources and configuration** expander report local availability and prerequisites without probing services. Configuration is not evidence of successful retrieval. Alternative manuscripts can be saved with `copies --save-alternatives FILE` and explicitly selected with `acquire --from-results FILE --select N`, or chosen with **Select this manuscript** in the browser. See [the usage guide](SEARCH.md).

These scheduling changes do not increase the recorded retrieval results by themselves: the recent cohort remains **4/26 automated verified PDFs**, and the bounded legacy audit remains **0/4 hard papers**. A new measured acquisition run would be needed to claim a higher retrieval rate.

The follow-up implementation now includes `CancellableSession` and interruptible sleeps in `src/core/cancellation.py`, wired into 13 older acquisition modules plus the shared acquisition-source base. Sessions created inside a worker retain that operation's event for nested calls; a binding helper propagates it to nested executor tasks. Cancellation closes streamed responses and escapes legacy retry handlers using a dedicated cancellation signal. Bare handlers that swallowed this signal in the audited adapters were narrowed to ordinary exceptions. The common source base also verifies each candidate before returning, so CORE-style adapters can continue after a wrong first PDF. Tests cover pre-request cancellation, response/stream cleanup, nested-worker propagation, retry interruption, and wrong-first/valid-second continuation. Running socket reads still depend on their configured timeout; there is no claim of force-killing arbitrary threads.
