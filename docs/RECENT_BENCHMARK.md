# Recent full-text benchmark

On 10 October 2026, the frozen 26-paper cohort produced **4 verified PDFs out of 26** using the automated public-source route. This includes **0/21 index-hard papers** and **4/5 indexed-available controls**. Browser recovery was not part of this run. These results do not support a claim that difficult recent papers are generally solved.

## Cohort frozen before downloading

The [cohort fixture](../tests/fixtures/recent_fulltext_cohort_20261010.json) was frozen before the first download attempt. Its SHA-256 is `872ccaaf4a625ad7c706e679c7e0606372b2716a011255a466790a6497fb2e61`. It contains 26 distinct journal DOIs first published between 1 September and 1 October 2026. Selection permitted dates through 10 October; the selected records happened to end on 1 October.

Three fixed Europe PMC queries sampled the first 40 relevance-ranked MED records each: chemistry/biocatalysis, enzyme engineering, and structural/molecular biology. Within each ordered result set, selection required a unique DOI and a first-publication date in the window, then took seven index-hard records. The three strata also contributed two, two, and one indexed-available controls. The three earlier development cases were excluded. Exact queries, source links, retrieval ranks, initial access observations, and timestamps are stored with each case.

Here, **index-hard** means that the initial Europe PMC core record advertised no explicitly free main PDF. It does not mean paywalled, unavailable, or intrinsically difficult. Controls were selected because the index advertised a free PDF, before trying to download it. No case was replaced after observing its outcome.

This is a deliberately challenging, biomedical-indexed convenience sample. Relevance ordering, English topic terms, a narrow date window, and fixed hard/control quotas bias it. It is not a representative acquisition-rate estimate and does not cover all academic disciplines.

## Automated baseline

The [published result snapshot](../tests/fixtures/recent_fulltext_results_20261010.json) preserves all 26 outcomes, source/version/license evidence, timings, provider errors, and verification details. PDFs remain in temporary local storage and are not distributed with the repository.

| Stratum | Papers | Verified PDFs |
| --- | ---: | ---: |
| Chemistry / biocatalysis | 9 | 1 |
| Enzyme engineering | 9 | 2 |
| Structural / molecular biology | 8 | 1 |
| Total | 26 | 4 |

All four verified documents came from the official PMC cloud dataset, reported as published versions under CC BY. They total 25,626,291 bytes and 55 pages. The production verifier checked the files; a second inspection confirmed PDF page counts and generated SHA-256 hashes. Summed case processing time was 23.799 seconds.

| DOI | Pages | Bytes | SHA-256 |
| --- | ---: | ---: | --- |
| [10.3390/biology15181652](https://doi.org/10.3390/biology15181652) | 18 | 18,364,747 | `8de4289186f37be79b6237fbe0ce961ee861ad983a1c280e4a3dad189732df96` |
| [10.1002/advs.77789](https://doi.org/10.1002/advs.77789) | 17 | 3,020,084 | `95e6a1f1cbc90bbca7d78d6144e91edf4b1bf401e93e4b77e943471c97eea42b` |
| [10.1002/cbic.70537](https://doi.org/10.1002/cbic.70537) | 8 | 845,964 | `8cd6745241eb68b5c86754f2bf79a32290035aa332bec2371a9b8180c1226f6c` |
| [10.3389/fmicb.2026.1873698](https://doi.org/10.3389/fmicb.2026.1873698) | 12 | 3,395,496 | `fbaf73335df068f284b480e0b4f7433248d907d3a5378412a08e3471854f80f7` |

## What failed

Ten hard cases encountered publisher HTTP 403: Wiley, ACS, RSC, and ASM. Nine Elsevier cases reached an article linking hub without recognized article access metadata. One Nature case reached an article page whose nested metadata was not recognized; another stopped at the then three-request redirect budget. No hard case yielded a verified PDF in the baseline. An HTTP block or unrecognized metadata is not proof that the article is closed.

The failed control, `10.1002/cbic.70492`, advertised a Europe PMC PDF but that URL returned HTTP 403. A follow-up official cloud lookup for its confirmed PMCID `PMC13529271` returned HTTP 200 with `KeyCount=0`. Consequently, relaxing the index OA flag alone would not have recovered this control from the cloud at that time.

| DOI | First publication | Cohort | Baseline outcome |
| --- | --- | --- | --- |
| [10.1002/adma.75120](https://doi.org/10.1002/adma.75120) | 2026-09-24 | hard | Publisher HTTP block |
| [10.1002/anie.9389619](https://doi.org/10.1002/anie.9389619) | 2026-09-08 | hard | Publisher HTTP block |
| [10.1016/j.copbio.2026.103584](https://doi.org/10.1016/j.copbio.2026.103584) | 2026-09-22 | hard | No verified PDF observed |
| [10.1021/acsami.6c11728](https://doi.org/10.1021/acsami.6c11728) | 2026-09-01 | hard | Publisher HTTP block |
| [10.1039/d6ob00991c](https://doi.org/10.1039/d6ob00991c) | 2026-09-16 | hard | Publisher HTTP block |
| [10.1021/jacs.6c08848](https://doi.org/10.1021/jacs.6c08848) | 2026-09-01 | hard | Publisher HTTP block |
| [10.1002/cbic.70492](https://doi.org/10.1002/cbic.70492) | 2026-09-01 | available_control | Indexed PDF HTTP block |
| [10.1016/j.bioorg.2026.110521](https://doi.org/10.1016/j.bioorg.2026.110521) | 2026-09-18 | hard | No verified PDF observed |
| [10.3390/biology15181652](https://doi.org/10.3390/biology15181652) | 2026-09-18 | available_control | Verified PDF |
| [10.1002/cbic.70508](https://doi.org/10.1002/cbic.70508) | 2026-09-01 | hard | Publisher HTTP block |
| [10.1016/j.foodchem.2026.150886](https://doi.org/10.1016/j.foodchem.2026.150886) | 2026-09-01 | hard | No verified PDF observed |
| [10.1021/acs.jafc.6c08020](https://doi.org/10.1021/acs.jafc.6c08020) | 2026-09-01 | hard | Publisher HTTP block |
| [10.1021/acs.jafc.6c09373](https://doi.org/10.1021/acs.jafc.6c09373) | 2026-09-01 | hard | Publisher HTTP block |
| [10.1002/advs.77789](https://doi.org/10.1002/advs.77789) | 2026-09-27 | available_control | Verified PDF |
| [10.1002/cbic.70537](https://doi.org/10.1002/cbic.70537) | 2026-09-01 | available_control | Verified PDF |
| [10.1016/j.tibtech.2026.08.011](https://doi.org/10.1016/j.tibtech.2026.08.011) | 2026-09-09 | hard | No verified PDF observed |
| [10.1016/j.micres.2026.128741](https://doi.org/10.1016/j.micres.2026.128741) | 2026-09-23 | hard | No verified PDF observed |
| [10.1002/smll.75979](https://doi.org/10.1002/smll.75979) | 2026-09-27 | hard | Publisher HTTP block |
| [10.1128/jvi.01168-26](https://doi.org/10.1128/jvi.01168-26) | 2026-09-09 | hard | Publisher HTTP block |
| [10.1038/s41586-026-11021-5](https://doi.org/10.1038/s41586-026-11021-5) | 2026-09-16 | hard | No verified PDF observed |
| [10.1016/j.jbc.2026.113599](https://doi.org/10.1016/j.jbc.2026.113599) | 2026-09-23 | hard | No verified PDF observed |
| [10.1038/s41594-026-01890-9](https://doi.org/10.1038/s41594-026-01890-9) | 2026-09-16 | hard | No verified PDF observed |
| [10.1016/j.jsb.2026.108378](https://doi.org/10.1016/j.jsb.2026.108378) | 2026-09-26 | hard | No verified PDF observed |
| [10.1016/j.str.2026.08.016](https://doi.org/10.1016/j.str.2026.08.016) | 2026-09-22 | hard | No verified PDF observed |
| [10.1016/j.bbrc.2026.154679](https://doi.org/10.1016/j.bbrc.2026.154679) | 2026-10-01 | hard | No verified PDF observed |
| [10.3389/fmicb.2026.1873698](https://doi.org/10.3389/fmicb.2026.1873698) | 2026-09-16 | available_control | Verified PDF |

## Follow-up fixes, separate from the frozen baseline

The Elsevier linking-hub HTML explicitly supplied a standard meta refresh redirect. The publisher reader now follows that advertised HTTP(S) target without executing JavaScript or submitting forms, within five total requests and the existing shared time/size budgets. Tests cover malformed redirects, unsafe schemes, embedded credentials, and loops. A targeted live follow-up for `10.1016/j.copbio.2026.103584` reached the advertised ScienceDirect article and received HTTP 403. This improved the diagnosis; it did not recover a PDF.

The Nature redirect chain required five ordinary requests. Its article HTML contained a DOI-confirmed `ScholarlyArticle` under `WebPage.mainEntity`, with `isAccessibleForFree: true`, a CC BY license, and an advertised main PDF URL. The metadata reader now inspects that bounded nested entity without inheriting access flags from the enclosing website. This is a separate, benchmark-informed correction; the original 4/26 baseline is retained. The targeted follow-up did locate the publisher-advertised PDF and its CC BY declaration, but the actual download hit the 45-second direct-download budget and returned `TimeoutError` (46.537 seconds total case time). **No verified PDF was saved.** This improves access discovery, not the verified retrieval count. The [separate follow-up snapshot](../tests/fixtures/recent_fulltext_followup_20261010.json) preserves that outcome; automated verified retrieval remains 4/26 in the baseline.

## Reproduce

```bash
python3 tools/benchmark_recent_fulltext.py \
  --cases tests/fixtures/recent_fulltext_cohort_20261010.json \
  --live --download --progress \
  --download-dir /tmp/paper-finder-recent-expanded \
  --output /tmp/paper-finder-recent-expanded.json
```

Without `--live`, the command only prints cases. With `--live` alone, it queries access metadata but does not download documents. `--download` requires an explicit temporary output directory. Progress checkpoints preserve completed cases; the final report includes the cohort hash.

This run used Europe PMC, DOI-confirmed PMC cloud copies, and conditional publisher metadata. OpenAlex and Crossref were not used, and no unavailable-provider requests were added to improve the count. The direct PDF coordinator validates identity and bounds downloads. No legacy messaging services, unofficial mirrors, institution credentials, or browser sessions were used. Browser-assisted recovery must be measured and reported separately.

API and markup references: [Europe PMC core metadata](https://europepmc.org/RestfulWebService), [PMC Article Datasets](https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/), [HTML refresh directives](https://html.spec.whatwg.org/multipage/semantics.html#attr-meta-http-equiv-refresh), and [Schema.org access declarations](https://schema.org/isAccessibleForFree).
