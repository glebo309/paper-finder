"""Combine indexed copies with direct repository searches without losing versions."""
from copy import deepcopy


def merge_access_reports(*reports):
    result = {'locations': [], 'alternatives': [], 'embargoed': [], 'closed': [], 'errors': {}}
    groups = ('locations', 'alternatives', 'embargoed', 'closed')
    for report in reports:
        for key in ('doi', 'publisher_access'):
            if report.get(key) is not None:
                result[key] = deepcopy(report[key])
        result['errors'].update(deepcopy(report.get('errors') or {}))
        for group in groups:
            for location in report.get(group, []):
                item = deepcopy(location)
                if item not in result[group]:
                    result[group].append(item)
    def url(item):
        return item.get('pdf_url') or item.get('url') or item.get('landing_page_url')
    alternatives = {url(item): item for item in result['alternatives'] if url(item)}
    retained = []
    for item in result['locations']:
        other = alternatives.get(url(item))
        if other is not None:
            if item.get('version') not in (None, 'unknown', other.get('version')):
                other['version'] = 'conflicting'
            other['requires_selection'] = True
            other['downloadable'] = False
        elif item.get('requires_selection') or item.get('version') in ('submittedVersion', 'conflicting'):
            item['requires_selection'] = True
            result['alternatives'].append(item)
        else:
            retained.append(item)
    result['locations'] = retained
    result['status'] = ('found' if retained else 'alternatives' if result['alternatives']
                        else 'unavailable' if result['errors'] else 'not_found')
    return result


def discover_access_options(record, *, session=None, email=None, recent=None, repositories=None):
    """Fresh index/publisher evidence plus bounded direct HAL/Zenodo evidence.

    This only returns metadata and links. Independent source failures remain
    visible and do not discard results from another source.
    """
    if recent is None:
        from .recent_open_access import RecentOpenAccessDiscovery
        recent = RecentOpenAccessDiscovery(session=session, email=email)
    if repositories is None:
        from .repository_discovery import RepositoryDiscovery
        repositories = RepositoryDiscovery(session=session)
    doi = record.get('doi') or (record.get('identifier') or {}).get('value')
    reports = []
    for name, lookup in (('indexes', lambda: recent.discover(doi)),
                         ('repositories', lambda: repositories.discover(record))):
        try:
            reports.append(lookup())
        except Exception:
            reports.append({'errors': {name: {'kind': 'error', 'message': 'Source discovery failed.'}}})
    return merge_access_reports(*reports)
