# Paper Finder - Comprehensive Benchmark Report

**Generated**: 2025-12-06 14:42:33

## Summary Statistics

**Total Tests**: 29
**Successes**: 22 (75.9%)
**Failures**: 7 (24.1%)
**Total Time**: 573.2s
**Average Time**: 19.8s per test

## Results by Category

- **Biology - Classic**: 2/3 (67% success, avg 34.2s)
- **Biotechnology - Recent**: 2/2 (100% success, avg 24.7s)
- **Book - Biology**: 1/1 (100% success, avg 7.4s)
- **Book - Philosophy**: 2/2 (100% success, avg 7.1s)
- **Chemistry - Classic**: 2/3 (67% success, avg 37.2s)
- **Chemistry - Edge Case**: 1/1 (100% success, avg 2.1s)
- **Edge Case**: 0/2 (0% success, avg 52.8s)
- **Edge Case - URL Input**: 1/1 (100% success, avg 1.0s)
- **Open Access - Biology**: 1/1 (100% success, avg 1.6s)
- **Open Access - Education**: 1/1 (100% success, avg 0.6s)
- **Open Access - Education Tech**: 1/1 (100% success, avg 0.6s)
- **Open Access - Health**: 1/1 (100% success, avg 0.6s)
- **Philosophy - Recent**: 1/2 (50% success, avg 51.0s)
- **Physics - Classic**: 2/2 (100% success, avg 0.8s)
- **Preprint - AI/ML**: 1/1 (100% success, avg 0.5s)
- **Preprint - Computer Science**: 1/1 (100% success, avg 1.6s)
- **Preprint - Virology**: 0/1 (0% success, avg 65.4s)
- **Recent Paywalled - Biology**: 2/3 (67% success, avg 1.5s)

## Analysis

### Expected Successes
- 17 tests succeeded as expected

### Expected Failures
- 4 tests failed as expected

### Unexpected Results
- ⚠️  8 unexpected results:
  - `biorxiv_covid`: Expected success, got failure
  - `chem_grubbs`: Expected success, got failure
  - `bio_pcr`: Expected success, got failure
  - `phil_political`: Expected failure, got success
  - `recent_nature_2024`: Expected failure, got success
  - `recent_cell_2024`: Expected failure, got success
  - `biotech_methods`: Expected failure, got success
  - `biotech_review`: Expected failure, got success

## Detailed Results

### oa_plos_biology - ✅ PASS

- **Reference**: `10.1371/journal.pone.0134116`
- **Category**: Open Access - Biology
- **Source**: Open Access (Browser)
- **Time**: 1.6s

### oa_plos_education - ✅ PASS

- **Reference**: `10.1371/journal.pone.0286208`
- **Category**: Open Access - Education
- **Source**: Open Access (Browser)
- **Time**: 0.6s

### oa_plos_technology - ✅ PASS

- **Reference**: `10.1371/journal.pone.0286112`
- **Category**: Open Access - Education Tech
- **Source**: Open Access (Browser)
- **Time**: 0.6s

### oa_plos_health - ✅ PASS

- **Reference**: `10.1371/journal.pone.0284420`
- **Category**: Open Access - Health
- **Source**: Open Access (Browser)
- **Time**: 0.6s

### arxiv_cs - ✅ PASS

- **Reference**: `10.48550/arXiv.2006.11239`
- **Category**: Preprint - Computer Science
- **Source**: arXiv Direct
- **Time**: 1.6s
- **File**: `arxiv_2006.11239.pdf`

### arxiv_physics - ✅ PASS

- **Reference**: `10.48550/arXiv.1706.03762`
- **Category**: Preprint - AI/ML
- **Source**: arXiv Direct
- **Time**: 0.5s
- **File**: `arxiv_1706.03762.pdf`

### biorxiv_covid - ❌ FAIL

- **Reference**: `10.1101/2020.12.08.416727`
- **Category**: Preprint - Virology
- **Source**: Unknown
- **Time**: 65.4s
- **Error**: All acquisition methods failed

### chem_woodward_hoffmann - ✅ PASS

- **Reference**: `10.1021/ja01080a054`
- **Category**: Chemistry - Classic
- **Source**: SciHub
- **Time**: 1.1s
- **File**: `10.1021_ja01080a054.pdf`

### chem_hammond - ✅ PASS

- **Reference**: `10.1021/ja01616a027`
- **Category**: Chemistry - Classic
- **Source**: SciHub
- **Time**: 0.8s
- **File**: `10.1021_ja01616a027.pdf`

### chem_grubbs - ❌ FAIL

- **Reference**: `10.1021/ja00506a050`
- **Category**: Chemistry - Classic
- **Source**: Unknown
- **Time**: 109.8s
- **Error**: All acquisition methods failed

### chem_messy_input - ✅ PASS

- **Reference**: `ja01080a054https://pubs.acs.org/doi/10.1021/ja01080a054`
- **Category**: Chemistry - Edge Case
- **Source**: SciHub
- **Time**: 2.1s
- **File**: `10.1021_ja01080a054.pdf`

### bio_watson_crick - ✅ PASS

- **Reference**: `10.1038/171737a0`
- **Category**: Biology - Classic
- **Source**: SciHub
- **Time**: 0.7s
- **File**: `10.1038_171737a0.pdf`

### bio_krebs_cycle - ✅ PASS

- **Reference**: `10.1042/bj0320108`
- **Category**: Biology - Classic
- **Source**: Open Access (Browser)
- **Time**: 0.6s

### bio_pcr - ❌ FAIL

- **Reference**: `10.1126/science.2448875`
- **Category**: Biology - Classic
- **Source**: Unknown
- **Time**: 101.4s
- **Error**: All acquisition methods failed

### physics_dirac - ✅ PASS

- **Reference**: `10.1098/rspa.1928.0023`
- **Category**: Physics - Classic
- **Source**: Open Access (Browser)
- **Time**: 1.0s

### physics_einstein - ✅ PASS

- **Reference**: `10.1002/andp.19053220607`
- **Category**: Physics - Classic
- **Source**: Open Access (Browser)
- **Time**: 0.6s

### phil_ethics - ❌ FAIL

- **Reference**: `10.1111/josp.12535`
- **Category**: Philosophy - Recent
- **Source**: Unknown
- **Time**: 101.0s
- **Error**: All acquisition methods failed

### phil_political - ✅ PASS

- **Reference**: `10.1111/jopp.70000`
- **Category**: Philosophy - Recent
- **Source**: Open Access (Browser)
- **Time**: 1.1s

### recent_nature_2024 - ✅ PASS

- **Reference**: `10.1038/s41586-024-07487-w`
- **Category**: Recent Paywalled - Biology
- **Source**: Open Access (Browser)
- **Time**: 0.6s

### recent_science_2024 - ❌ FAIL

- **Reference**: `10.1126/science.adl2520`
- **Category**: Recent Paywalled - Biology
- **Source**: Unknown
- **Time**: 0.6s
- **Error**: DOI not found in Crossref/doi.org: 10.1126/science.adl2520

### recent_cell_2024 - ✅ PASS

- **Reference**: `10.1016/j.cell.2024.07.027`
- **Category**: Recent Paywalled - Biology
- **Source**: SciHub
- **Time**: 3.3s
- **File**: `10.1016_j.cell.2024.07.027.pdf`

### book_kuhn - ✅ PASS

- **Reference**: `978-0226458083`
- **Category**: Book - Philosophy
- **Source**: Anna's Archive (Book Browser)
- **Time**: 7.2s

### book_popper - ✅ PASS

- **Reference**: `978-0415278447`
- **Category**: Book - Philosophy
- **Source**: Anna's Archive (Book Browser)
- **Time**: 7.0s

### book_darwin - ✅ PASS

- **Reference**: `978-0451529060`
- **Category**: Book - Biology
- **Source**: Anna's Archive (Book Browser)
- **Time**: 7.4s

### biotech_methods - ✅ PASS

- **Reference**: `10.1038/s41592-024-02591-1`
- **Category**: Biotechnology - Recent
- **Source**: Crossref Direct
- **Time**: 48.2s
- **File**: `10.1038_s41592-024-02591-1.pdf`

### biotech_review - ✅ PASS

- **Reference**: `10.1038/s41587-024-02508-5`
- **Category**: Biotechnology - Recent
- **Source**: Open Access (Browser)
- **Time**: 1.1s

### invalid_doi - ❌ FAIL

- **Reference**: `10.1234/FAKE.DOI.12345`
- **Category**: Edge Case
- **Source**: Unknown
- **Time**: 0.6s
- **Error**: DOI not found in Crossref/doi.org: 10.1234/FAKE.DOI.12345

### malformed_doi - ❌ FAIL

- **Reference**: `not-a-doi-at-all`
- **Category**: Edge Case
- **Source**: Unknown
- **Time**: 105.1s
- **Error**: All acquisition methods failed

### doi_with_url - ✅ PASS

- **Reference**: `https://doi.org/10.1371/journal.pone.0134116`
- **Category**: Edge Case - URL Input
- **Source**: Open Access (Browser)
- **Time**: 1.0s
