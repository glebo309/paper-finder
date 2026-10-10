"""Offline contract tests: discovery must prefer abstention to wrong identity."""
import requests

from src.core.discovery import DiscoveryService


TITLE = 'Highly accurate protein structure prediction with AlphaFold'
DOI = '10.1038/s41586-021-03819-2'


def cr(title=TITLE, doi=DOI, year=2021, author='Jumper'):
    return {'title': [title], 'DOI': doi, 'author': [{'given': 'John', 'family': author}],
            'issued': {'date-parts': [[year]]}, 'container-title': ['Nature']}


def oa(title=TITLE, doi=DOI, identifier='W123'):
    return {'id': 'https://openalex.org/' + identifier, 'display_name': title,
            'doi': 'https://doi.org/' + doi if doi else None, 'publication_year': 2021,
            'authorships': [{'author': {'display_name': 'John Jumper'}}],
            'abstract_inverted_index': {'Protein': [0], 'folding': [1]},
            'best_oa_location': {'pdf_url': 'https://example.org/paper.pdf'}}


class Response:
    def __init__(self, payload, status=200, headers=None):
        self.payload, self.status_code, self.headers = payload, status, headers or {}
    def json(self):
        return self.payload


class Session:
    def __init__(self, crossref=None, openalex=None, scholar=None):
        self.calls = []
        self.payloads = {'crossref': crossref if crossref is not None else {'message': {'items': []}},
                         'openalex': openalex if openalex is not None else {'results': []},
                         'semanticscholar': scholar if scholar is not None else {'data': []}}
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        value = next(v for k, v in self.payloads.items() if k in url)
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, Response) else Response(value)


def test_rejects_first_crossref_hit_and_identifies_later_exact_title():
    session = Session(crossref={'message': {'items': [cr('A study of sea turtles', '10.1/wrong'), cr()]}})
    result = DiscoveryService(session=session).search(TITLE)
    assert result['status'] == 'matched'
    assert result['selected']['doi'] == DOI
    assert result['candidates'][0]['match_reasons']
    assert session.calls[0][1]['timeout'] > 0


def test_vague_topic_does_not_automatically_acquire_paper():
    result = DiscoveryService(session=Session(openalex={'results': [oa()]})).search('AlphaFold paper about protein folding')
    assert result['status'] == 'ambiguous'
    assert result['selected'] is None
    assert result['candidates'][0]['doi'] == DOI


def test_identical_title_different_dois_remain_ambiguous_versions():
    session = Session(crossref={'message': {'items': [cr(), cr(doi='10.1234/preprint')]}})
    result = DiscoveryService(session=session).search(TITLE)
    assert result['status'] == 'ambiguous'
    assert len(result['candidates']) == 2


def test_same_doi_merges_provenance_and_open_pdf():
    session = Session(crossref={'message': {'items': [cr()]}}, openalex={'results': [oa()]})
    result = DiscoveryService(session=session).search(TITLE)
    assert len(result['candidates']) == 1
    candidate = result['selected']
    assert set(candidate['sources']) == {'crossref', 'openalex'}
    assert candidate['pdf_urls'] == ['https://example.org/paper.pdf']
    assert candidate['abstract'] == 'Protein folding'


def test_work_without_doi_retains_real_identifier():
    result = DiscoveryService(session=Session(openalex={'results': [oa(doi=None)]})).search(TITLE)
    assert result['selected']['identifier'] == {'type': 'openalex', 'value': 'W123'}
    assert not result['selected'].get('doi')


def test_rate_limit_is_visible_and_falls_back_without_sleep():
    session = Session(openalex=Response({}, 429, {'Retry-After': '120'}), crossref={'message': {'items': [cr()]}})
    result = DiscoveryService(session=session).search(TITLE)
    assert result['status'] == 'ambiguous'
    assert result['candidates'][0]['doi'] == DOI
    assert result['errors']['openalex']['kind'] == 'rate_limited'
    assert result['errors']['openalex']['retry_after'] == '120'
    assert len([url for url, _ in session.calls if 'openalex' in url]) == 1


def test_all_failures_are_unavailable_not_no_results():
    error = requests.ConnectionError('key=SECRET do not print')
    result = DiscoveryService(session=Session(crossref=error, openalex=error, scholar=error)).search(TITLE)
    assert result['status'] == 'unavailable'
    assert 'SECRET' not in str(result)
    assert set(result['errors']) == {'openalex', 'crossref', 'semanticscholar'}


def test_empty_success_is_not_found():
    assert DiscoveryService(session=Session()).search(TITLE)['status'] == 'not_found'


def test_discover_mode_never_selects_even_exact_title():
    result = DiscoveryService(session=Session(openalex={'results': [oa()]})).search(TITLE, mode='discover')
    assert result['selected'] is None
    assert result['candidates']


def test_explicit_doi_never_substituted_by_another_work():
    session = Session(crossref={'message': cr(doi='10.1234/wrong')}, openalex={'results': [oa(doi='10.1234/wrong')]})
    result = DiscoveryService(session=session).search(DOI)
    assert result['selected'] is None
    assert result['candidates'] == []
    assert all('query.bibliographic' not in call['params'] for _, call in session.calls)


def test_exact_doi_accepts_only_same_identifier():
    session = Session(crossref={'message': cr()})
    result = DiscoveryService(session=session).search('https://doi.org/' + DOI)
    assert result['status'] == 'matched'
    assert result['selected']['doi'] == DOI


def test_year_and_author_disambiguate_same_titles():
    session = Session(crossref={'message': {'items': [cr(year=1999, author='Smith', doi='10.1234/other'), cr()]}})
    result = DiscoveryService(session=session).search('Jumper 2021. ' + TITLE)
    assert result['selected']['doi'] == DOI


def test_malformed_provider_does_not_abort_other_results():
    session = Session(openalex={'results': 'broken'}, crossref={'message': {'items': [cr()]}})
    result = DiscoveryService(session=session).search(TITLE)
    assert result['selected'] is None
    assert result['candidates'][0]['doi'] == DOI
    assert result['errors']['openalex']['kind'] == 'invalid_response'


def test_limit_cannot_hide_runner_up_ambiguity():
    session = Session(crossref={'message': {'items': [cr(), cr(doi='10.1234/other')]}})
    result = DiscoveryService(session=session).search(TITLE, limit=1)
    assert result['status'] == 'ambiguous'
    assert result['selected'] is None


def test_conflicting_leading_author_requires_review_even_with_exact_title():
    session = Session(crossref={'message': {'items': [cr()]}})
    result = DiscoveryService(session=session).search('Smith 2021. ' + TITLE)
    assert result['status'] == 'ambiguous'
    assert result['selected'] is None


def test_long_unrelated_prose_containing_title_is_not_an_exact_citation():
    query = 'I read a long discussion of ' + TITLE + ' but am actually looking for the earlier experiments it cites in its bibliography'
    result = DiscoveryService(session=Session(crossref={'message': {'items': [cr()]}})).search(query)
    assert result['selected'] is None


def test_timeout_is_bounded_and_keys_never_enter_url(monkeypatch):
    monkeypatch.setenv('OPENALEX_API_KEY', 'test-secret')
    session = Session(openalex=requests.Timeout('URL with secret'))
    result = DiscoveryService(session=session, providers=['openalex'], timeout=3, deadline=2).search(TITLE)
    assert result['errors']['openalex']['kind'] == 'timeout'
    url, call = session.calls[0]
    assert 0 < call['timeout'] <= 2
    assert 'test-secret' not in url and 'test-secret' not in str(call['params'])
    assert 'test-secret' not in str(result)


def test_semantic_scholar_fallback_preserves_arxiv_id():
    item = {'paperId': 'abc123', 'title': TITLE, 'externalIds': {'ArXiv': '2107.12345'},
            'authors': [{'name': 'John Jumper'}], 'year': 2021, 'openAccessPdf': {'url': 'https://arxiv.org/pdf/2107.12345'}}
    result = DiscoveryService(session=Session(scholar={'data': [item]})).search(TITLE)
    assert result['selected']['identifier'] == {'type': 'arxiv', 'value': '2107.12345'}
    assert result['selected']['pdf_urls'] == ['https://arxiv.org/pdf/2107.12345']


def test_deadline_stops_later_provider_requests(monkeypatch):
    moments = iter([0, 0, 10, 10])
    monkeypatch.setattr('src.core.discovery.time.monotonic', lambda: next(moments))
    session = Session()
    result = DiscoveryService(session=session, deadline=5).search(TITLE)
    assert len(session.calls) == 1
    assert result['errors']['crossref']['kind'] == 'deadline'
    assert result['status'] == 'not_found'


def test_doi_url_tracking_query_is_not_part_of_identifier():
    session = Session(crossref={'message': cr()})
    result = DiscoveryService(session=session).search('https://doi.org/' + DOI + '?utm_source=reader#references')
    assert result['selected']['doi'] == DOI


def test_diacritics_do_not_prevent_exact_title_matching():
    title = 'Über die Wirkung der Enzyme auf Proteine'
    session = Session(crossref={'message': {'items': [cr(title=title)]}})
    result = DiscoveryService(session=session).search('Uber die Wirkung der Enzyme auf Proteine')
    assert result['status'] == 'matched'
    assert 'Exact normalized title' in result['selected']['match_reasons']


def test_close_publication_year_discrepancy_requires_review_not_silent_match():
    session = Session(crossref={'message': {'items': [cr()]}})
    result = DiscoveryService(session=session).search('Jumper 2020. ' + TITLE)
    assert result['selected'] is None
    assert any('year' in reason.lower() for reason in result['candidates'][0]['match_reasons'])


class SemanticSession(Session):
    def __init__(self, semantic, **kwargs):
        super().__init__(**kwargs)
        self.semantic = semantic
    def get(self, url, **kwargs):
        if 'search.semantic' in kwargs.get('params', {}):
            self.calls.append((url, kwargs))
            return Response(self.semantic)
        return super().get(url, **kwargs)


def test_semantic_fallback_keeps_meaning_match_above_literal_word_overlap(monkeypatch):
    monkeypatch.setattr('src.core.discovery._SEMANTIC_NEXT_ALLOWED', 0, raising=False)
    query = 'paper about computers working out how proteins fold'
    literal = oa(title='Computers in the protein laboratory', doi='10.1234/literal', identifier='W124')
    session = SemanticSession({'results': [oa(), literal]}, openalex={'results': [literal]})
    result = DiscoveryService(session=session).search(query)
    assert result['candidates'][0]['doi'] == DOI
    assert result['selected'] is None
    calls = [kw['params'] for _, kw in session.calls if 'search.semantic' in kw['params']]
    assert len(calls) == 1
    assert 'search' not in calls[0]
    assert result['candidates'][0]['source_ranks']['openalex_semantic'] == 1


def test_no_semantic_request_after_openalex_rate_limit():
    session = SemanticSession({'results': [oa()]}, openalex=Response({}, 429))
    result = DiscoveryService(session=session).search('paper about protein folding')
    assert not any('search.semantic' in kw['params'] for _, kw in session.calls)
    assert result['errors']['openalex']['kind'] == 'rate_limited'


def test_semantic_requests_respect_one_per_second_without_sleep(monkeypatch):
    monkeypatch.setattr('src.core.discovery._SEMANTIC_NEXT_ALLOWED', 0, raising=False)
    monkeypatch.setattr('src.core.discovery.time.monotonic', lambda: 100)
    session = SemanticSession({'results': [oa()]})
    service = DiscoveryService(session=session)
    service.search('protein shapes', mode='discover')
    result = service.search('protein shapes', mode='discover')
    assert len([kw for _, kw in session.calls if 'search.semantic' in kw['params']]) == 1
    assert result['errors']['openalex_semantic']['kind'] == 'rate_limited'


def test_semantic_only_exact_title_still_requires_selection(monkeypatch):
    monkeypatch.setattr('src.core.discovery._SEMANTIC_NEXT_ALLOWED', 0)
    session = SemanticSession({'results': [oa()]})
    result = DiscoveryService(session=session).search(TITLE)
    assert result['selected'] is None
    assert result['status'] == 'ambiguous'


def test_semantic_retry_after_blocks_followup_call(monkeypatch):
    monkeypatch.setattr('src.core.discovery._SEMANTIC_NEXT_ALLOWED', 0)
    now = [100]
    monkeypatch.setattr('src.core.discovery.time.monotonic', lambda: now[0])
    class LimitedSession(Session):
        def get(self, url, **kwargs):
            if 'search.semantic' in kwargs.get('params', {}):
                self.calls.append((url, kwargs))
                return Response({}, 429, {'Retry-After': '120'})
            return super().get(url, **kwargs)
    session = LimitedSession()
    service = DiscoveryService(session=session)
    service.search('protein shapes', mode='discover')
    now[0] += 5
    service.search('protein shapes', mode='discover')
    assert len([kw for _, kw in session.calls if 'search.semantic' in kw['params']]) == 1


def test_conflicting_author_after_title_requires_review():
    result = DiscoveryService(session=Session(crossref={'message': {'items': [cr()]}})).search(TITLE + '. Smith (2021)')
    assert result['selected'] is None


def test_citation_journal_after_title_is_not_mistaken_for_wrong_author():
    result = DiscoveryService(session=Session(crossref={'message': {'items': [cr()]}})).search(TITLE + '. Nature (2021)')
    assert result['selected']['doi'] == DOI


def test_semantic_rank_cannot_bury_strong_partial_citation(monkeypatch):
    monkeypatch.setattr('src.core.discovery._SEMANTIC_NEXT_ALLOWED', 0)
    related = oa('Protein structure predictions to atomic accuracy with AlphaFold', '10.1234/commentary')
    related['publication_year'] = 2022
    related['authorships'] = [{'author': {'display_name': 'Other Author'}}]
    session = SemanticSession({'results': [related]}, openalex={'results': [oa()]})
    result = DiscoveryService(session=session).search('protein structure prediction AlphaFold Jumper 2021')
    assert result['selected'] is None
    assert result['candidates'][0]['doi'] == DOI


def test_exact_homonyms_keep_lexical_first_hit_visible_without_automatic_choice(monkeypatch):
    monkeypatch.setattr('src.core.discovery._SEMANTIC_NEXT_ALLOWED', 0)
    original = oa('Attention Is All You Need', '10.1234/original')
    unrelated = oa('Attentionlet Is All You Need', '10.1234/commentary')
    homonym = oa('Attention Is All You Need', '10.1234/homonym')
    session = SemanticSession({'results': [unrelated, homonym]}, openalex={'results': [original, homonym]})
    result = DiscoveryService(session=session).search('Attention Is All You Need')
    assert result['selected'] is None
    assert result['candidates'][0]['doi'] == '10.1234/original'


def test_openalex_preserves_arxiv_locations_and_flags_unattributed_doi_cluster():
    record = oa('Attention Is All You Need', '10.1234/mirror')
    record['primary_location'] = {'source': None, 'landing_page_url': 'https://doi.org/10.1234/mirror'}
    record['locations'] = [
        {'doi': 'https://doi.org/10.1234/mirror'},
        {'doi': 'https://doi.org/10.1234/other-mirror'},
        {'landing_page_url': 'http://arxiv.org/abs/1706.03762v5', 'pdf_url': 'https://arxiv.org/pdf/1706.03762'},
    ]
    result = DiscoveryService(session=Session(openalex={'results': [record]}), providers=['openalex']).search('Attention Is All You Need')
    candidate = result['candidates'][0]
    assert candidate['arxiv_ids'] == ['1706.03762']
    assert candidate['metadata_warnings']
    assert 'http://arxiv.org/abs/1706.03762v5' in candidate['record_urls']
    assert result['selected'] is None


def test_preprint_submission_year_supports_citation_without_replacing_publication_year(monkeypatch):
    monkeypatch.setattr('src.core.discovery._SEMANTIC_NEXT_ALLOWED', 0)
    title = 'Attention Is All You Need'
    original = oa(title, '10.1234/indexed-mirror')
    original.update(publication_year=2025, authorships=[{'author': {'display_name': 'Ashish Vaswani'}}],
                    locations=[{'landing_page_url': 'https://arxiv.org/abs/1706.03762'}])
    mirror = cr(title, '10.1234/other-mirror', year=2025, author='Vaswani')
    result = DiscoveryService(session=Session(openalex={'results': [original]}, crossref={'message': {'items': [mirror]}})).search('Vaswani 2017. ' + title)
    candidate = result['candidates'][0]
    assert candidate['doi'] == '10.1234/indexed-mirror'
    assert candidate['year'] == 2025
    assert candidate['preprint_years'] == [2017]
    assert 'Preprint submission year matches' in candidate['match_reasons']
    assert result['selected'] is None


def test_balanced_angle_brackets_in_structured_doi_are_not_truncated():
    doi = '10.1002/(SICI)1099-0690(199812)1998:12<2501::AID-EJOC2501>3.0.CO;2-X'
    result = DiscoveryService(session=Session(crossref={'message': cr(doi=doi)}), providers=['crossref']).search('https://doi.org/' + doi)
    assert result['selected']['doi'] == doi.lower()


def test_descriptive_ranking_uses_bounded_citation_prior_without_automatic_identification(monkeypatch):
    monkeypatch.setattr('src.core.discovery._SEMANTIC_NEXT_ALLOWED', 0)
    original = oa()
    original['cited_by_count'] = 40000
    related = oa('Applying and improving AlphaFold at CASP14', '10.1234/related')
    related['cited_by_count'] = 400
    query = 'DeepMind paper by Jumper in 2021 that predicted protein structures at near experimental accuracy in CASP14'
    session = SemanticSession({'results': [related]}, openalex={'results': [original]})
    result = DiscoveryService(session=session).search(query)
    assert result['candidates'][0]['doi'] == DOI
    assert result['selected'] is None


class CitationSession(Session):
    def __init__(self, title, rows, **kwargs):
        super().__init__(**kwargs)
        self.title, self.rows = title, rows
    def get(self, url, **kwargs):
        if 'openalex' in url and kwargs.get('params', {}).get('search') == self.title:
            self.calls.append((url, kwargs))
            return Response({'results': self.rows})
        return super().get(url, **kwargs)


def test_citation_relaxation_extracts_title_and_retains_original_evidence():
    title = 'Structural rules governing selective enzyme catalysis'
    item = oa(title, '10.1234/catalysis')
    item.update(publication_year=2019, authorships=[{'author': {'display_name': 'Jane Smith'}}])
    session = CitationSession(title, [item])
    result = DiscoveryService(session=session, providers=['openalex']).search(
        'Smith et al. (2019). Structural rules governing selective enzyme catalysis. Journal of Catalysis 80, 12-18.')
    assert result['selected']['doi'] == '10.1234/catalysis'
    assert result['selected']['source_ranks']['openalex_citation'] == 1
    assert 'Publication year matches' in result['selected']['match_reasons']
    assert len(session.calls) == 2


def test_quoted_title_relaxation_does_not_discard_conflicting_author():
    session = CitationSession(TITLE, [oa()])
    result = DiscoveryService(session=session, providers=['openalex']).search('Smith (2021). "' + TITLE + '".')
    assert result['selected'] is None
    assert result['candidates'][0]['doi'] == DOI
    assert any('author conflicts' in reason for reason in result['candidates'][0]['match_reasons'])
    assert len([call for _, call in session.calls if call['params'].get('search') == TITLE]) == 1


def test_citation_relaxation_uses_shared_deadline(monkeypatch):
    moments = iter([0, 0, 5])
    monkeypatch.setattr('src.core.discovery.time.monotonic', lambda: next(moments))
    session = CitationSession(TITLE, [oa()])
    result = DiscoveryService(session=session, providers=['openalex'], deadline=3).search('Jumper (2021). ' + TITLE + '.')
    assert len(session.calls) == 1
    assert result['errors']['openalex_citation']['kind'] == 'deadline'


def test_description_without_clear_citation_does_not_guess_a_title():
    query = 'DeepMind paper by Jumper in 2021 that predicted protein structures'
    session = CitationSession('that predicted protein structures', [oa()])
    DiscoveryService(session=session, providers=['openalex']).search(query)
    assert all(call['params'].get('search', query) == query for _, call in session.calls)


def test_exact_doi_retracted_work_still_requires_manual_review():
    item = oa()
    item['is_retracted'] = True
    result = DiscoveryService(session=Session(openalex={'results': [item]}), providers=['openalex']).search(DOI)
    assert result['selected'] is None
    assert 'Retracted work: manual review required' in result['candidates'][0]['match_reasons']


def test_exact_doi_retains_metadata_conflict_warnings():
    item = oa()
    item['locations'] = [{'doi': 'https://doi.org/' + DOI}, {'doi': 'https://doi.org/10.1234/mirror'},
                         {'landing_page_url': 'https://arxiv.org/abs/1706.03762'}]
    result = DiscoveryService(session=Session(openalex={'results': [item]}), providers=['openalex']).search(DOI)
    assert result['selected'] is None
    assert result['candidates'][0]['metadata_warnings'][0] in result['candidates'][0]['match_reasons']


def test_component_exact_title_is_not_automatically_a_paper():
    item = cr('Neural network architecture with recurrent attention', '10.1234/article/fig1')
    item['type'] = 'component'
    result = DiscoveryService(session=Session(crossref={'message': {'items': [item]}}), providers=['crossref']).search(item['title'][0])
    assert result['selected'] is None
    assert result['candidates'][0]['record_type'] == 'component'
    assert any('standalone paper' in reason for reason in result['candidates'][0]['match_reasons'])


def test_components_do_not_crowd_out_papers_in_descriptive_results(monkeypatch):
    monkeypatch.setattr('src.core.discovery._SEMANTIC_NEXT_ALLOWED', 0)
    component = oa('Protein structure prediction diagram', '10.1234/article/fig1')
    component['type'] = 'paratext'
    session = SemanticSession({'results': [component, oa()]})
    result = DiscoveryService(session=session).search('paper about protein folding')
    assert result['candidates'][0]['doi'] == DOI
    assert result['selected'] is None


def test_citation_rate_limit_does_not_trigger_another_openalex_request(monkeypatch):
    monkeypatch.setattr('src.core.discovery._SEMANTIC_NEXT_ALLOWED', 0)
    class LimitedCitationSession(Session):
        def get(self, url, **kwargs):
            if kwargs.get('params', {}).get('search') == TITLE:
                self.calls.append((url, kwargs))
                return Response({}, 429, {'Retry-After': '30'})
            return super().get(url, **kwargs)
    session = LimitedCitationSession()
    result = DiscoveryService(session=session, providers=['openalex']).search('Jumper (2021). ' + TITLE + '.')
    assert result['errors']['openalex_citation']['kind'] == 'rate_limited'
    assert len(session.calls) == 2


def test_degraded_independent_providers_cannot_auto_select_text_match():
    session = Session(openalex=Response({}, 429), crossref={'message': {'items': [cr()]}},
                      scholar=Response({}, 429))
    result = DiscoveryService(session=session).search(TITLE)
    assert result['selected'] is None
    assert result['status'] == 'ambiguous'
    assert result['candidates'][0]['doi'] == DOI
    assert any('semanticscholar' in url for url, _ in session.calls)


def test_exact_doi_can_resolve_despite_independent_provider_outage():
    session = Session(openalex=Response({}, 429), crossref={'message': cr()})
    result = DiscoveryService(session=session).search(DOI)
    assert result['selected']['doi'] == DOI
    assert result['errors']['openalex']['kind'] == 'rate_limited'


def test_three_word_topic_title_is_not_automatic_identification():
    item = cr('Protein structure prediction', '10.1234/reference-entry')
    result = DiscoveryService(session=Session(crossref={'message': {'items': [item]}}), providers=['crossref']).search('protein structure prediction')
    assert result['status'] == 'ambiguous'
    assert result['selected'] is None


def test_short_title_can_be_identified_with_matching_author_and_year():
    item = cr('Protein structure prediction', '10.1234/reference-entry')
    result = DiscoveryService(session=Session(crossref={'message': {'items': [item]}}), providers=['crossref']).search('Jumper (2021). Protein structure prediction.')
    assert result['selected']['doi'] == '10.1234/reference-entry'


def test_provider_cooldown_shared_across_services_without_retrying_http(monkeypatch):
    from src.core.provider_limits import ProviderCooldowns
    import src.core.discovery as discovery
    monkeypatch.setattr(discovery, 'provider_cooldowns', ProviderCooldowns(), raising=False)
    monkeypatch.setattr(discovery.time, 'monotonic', lambda: 100)
    session = Session(openalex=Response({}, 429, {'Retry-After': '40000'}))
    first = DiscoveryService(session=session, providers=['openalex']).search(TITLE)
    second = DiscoveryService(session=session, providers=['openalex']).search(TITLE)
    assert len(session.calls) == 1
    assert first['status'] == second['status'] == 'unavailable'
    assert second['errors']['openalex']['retry_after'] == '40000'
    assert 'cooling down' in second['errors']['openalex']['message']
