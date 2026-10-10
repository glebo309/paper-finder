"""Shared metadata-only search and explicit UI selection state."""
import re


def _dedicated_reference(query):
    """Keep exact book/preprint/URL resolution separate from free-text search."""
    query = query.strip()
    return bool(
        re.fullmatch(r"https?://\S+", query, re.I)
        or re.fullmatch(r"(?:arxiv:\s*)?(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})(?:v\d+)?", query, re.I)
        or re.fullmatch(r"(?:ISBN(?:-1[03])?:?\s*)?(?:[\dXx][ -]?){10,13}", query)
    )


def search_reference(query, limit=10, mode="identify", refresh=False):
    """Return candidates without constructing an acquisition engine."""
    query = query.strip()
    if mode == "identify" and _dedicated_reference(query):
        from src.core.identity import IdentityResolver
        resolver = IdentityResolver(refresh=True) if refresh else IdentityResolver()
        record = resolver.resolve(query)
        valid = bool(record.get("identifier", {}).get("value") and record.get("title") and not record.get("error"))
        if valid:
            if isinstance(record.get("year"), str):
                record["publication_date"] = record["year"]
                year = re.search(r"\b([12]\d{3})\b", record["year"])
                record["year"] = int(year.group(1)) if year else None
            record.setdefault("sources", [record.get("metadata_source", "identifier")])
            record.setdefault("match_reasons", ["Resolved the supplied identifier or URL"])
        errors = dict(record.get("provider_errors") or {})
        if record.get("error"):
            errors["identity"] = record["error"]
        status = "matched" if valid else record.get("status", "not_found")
        return {"query": query, "status": status, "candidates": [record] if valid else record.get("candidates", []), "selected": record if valid else None, "errors": errors}
    from src.core.discovery import DiscoveryService
    return DiscoveryService(refresh=refresh).search(query, limit=limit, mode=mode)


def begin_search(state, query):
    state["query"] = query
    for key in ("search_result", "selected_record", "result", "browser_url", "access_options"):
        state[key] = None
    state["search_log"] = ""


def select_candidate(state, index):
    state["selected_record"] = state["search_result"]["candidates"][index]
    state["access_options"] = None
    state["result"] = None
    state["browser_url"] = None
    state["search_log"] = ""


def _validate_snapshot(snapshot):
    """Validate the portable metadata envelope before any acquisition is started."""
    from urllib.parse import urlsplit
    if not isinstance(snapshot, dict) or type(snapshot.get("version")) is not int or snapshot["version"] != 1:
        raise ValueError("Unsupported results snapshot version; expected version 1.")
    result = snapshot.get("result")
    if not isinstance(result, dict) or not isinstance(result.get("query"), str):
        raise ValueError("Results snapshot must contain a query and result object.")
    if result.get("status") not in {"matched", "ambiguous", "not_found", "unavailable"}:
        raise ValueError("Invalid results snapshot status.")
    candidates = result.get("candidates")
    if not isinstance(candidates, list) or len(candidates) > 50:
        raise ValueError("Results snapshot must contain at most 50 candidate records.")
    if not isinstance(result.get("errors", {}), dict):
        raise ValueError("Results snapshot errors must be an object.")
    identifier_patterns = {
        "doi": r"10\.\d{4,9}/[^\s]+",
        "biorxiv": r"10\.1101/[^\s]+",
        "medrxiv": r"10\.1101/[^\s]+",
        "arxiv": r"(?:\d{4}\.\d{4,5}|[a-z.-]+/\d{7})(?:v\d+)?",
        "isbn": r"(?:\d[ -]?){9}[\dXx]|(?:\d[ -]?){12}\d",
        "openalex": r"W\d+",
        "semanticscholar": r"[a-fA-F0-9]{40}",
        "pmid": r"\d+",
    }

    def valid_http(value):
        return isinstance(value, str) and urlsplit(value).scheme in ("http", "https") and bool(urlsplit(value).netloc)

    for index, record in enumerate(candidates, 1):
        if not isinstance(record, dict) or not isinstance(record.get("title"), str) or not record["title"].strip():
            raise ValueError(f"Candidate {index} needs a title.")
        identifier = record.get("identifier")
        if not isinstance(identifier, dict) or not isinstance(identifier.get("value"), str):
            raise ValueError(f"Candidate {index} needs a canonical identifier.")
        kind, value = identifier.get("type"), identifier["value"]
        if kind == "url":
            valid = valid_http(value)
        elif kind == "title":
            valid = value == record["title"]
        else:
            pattern = identifier_patterns.get(kind)
            valid = pattern is not None and bool(re.fullmatch(pattern, value, re.I))
        if not valid:
            raise ValueError(f"Candidate {index} has an invalid canonical identifier.")
        doi = record.get("doi")
        if doi is not None and (not isinstance(doi, str) or not re.fullmatch(identifier_patterns["doi"], doi, re.I)):
            raise ValueError(f"Candidate {index} has an invalid DOI.")
        if doi and kind in {"doi", "biorxiv", "medrxiv"} and doi.casefold() != value.casefold():
            raise ValueError(f"Candidate {index} has conflicting DOI identifiers.")
        if not isinstance(record.get("authors", []), list) or any(not isinstance(author, str) for author in record.get("authors", [])):
            raise ValueError(f"Candidate {index} authors must be a list of names.")
        if record.get("year") is not None and (type(record["year"]) is not int or not 1000 <= record["year"] <= 2200):
            raise ValueError(f"Candidate {index} has an invalid publication year.")
        for field in ("sources", "match_reasons", "pdf_urls"):
            values = record.get(field, [])
            if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
                raise ValueError(f"Candidate {index} {field} must be a list of strings.")
        if record.get("url") and not valid_http(record["url"]):
            raise ValueError(f"Candidate {index} has an invalid record URL.")
        if any(not valid_http(url) for url in record.get("pdf_urls", [])):
            raise ValueError(f"Candidate {index} has an invalid PDF URL.")
    selected = result.get("selected")
    if selected is not None and (result["status"] != "matched" or selected not in candidates):
        raise ValueError("Selected snapshot record must be a matched candidate from this snapshot.")
    if result["status"] == "matched" and selected is None:
        raise ValueError("Matched results snapshot needs a selected candidate.")
    return result


def save_results(path, result):
    """Atomically save exactly the candidate order shown to the user."""
    import json
    import os
    from pathlib import Path
    import tempfile
    envelope = {"version": 1, "result": result}
    _validate_snapshot(envelope)
    destination = Path(path).expanduser()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent, prefix=".paper-results-", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(envelope, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_results(path):
    """Load a versioned snapshot; never perform metadata or network lookups."""
    import json
    from pathlib import Path
    with Path(path).expanduser().open("r", encoding="utf-8") as handle:
        data = handle.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise ValueError("Results snapshot exceeds the 5 MB size limit.")
    return _validate_snapshot(json.loads(data))
