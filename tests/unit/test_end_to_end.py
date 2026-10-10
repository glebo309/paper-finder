"""Production metadata-to-PDF path with deterministic HTTP boundary fixtures."""
from unittest.mock import Mock
from paper_finder import PaperFinder
from src.core.config import Config
from src.core.identity import IdentityResolver
from test_document_identity import pdf, TARGET


def test_phrase_to_merged_identity_to_correct_pdf(tmp_path):
    wrong = pdf(tmp_path, 'A different article\nJane Smith\nAbstract\nOther results').read_bytes()
    correct = pdf(tmp_path, TARGET['title'] + '\nJohn Jumper\nAbstract\nMain results').read_bytes()
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        response = Mock(status_code=200, headers={})
        if url == 'https://api.openalex.org/works':
            response.json.return_value = {'results': [{
                'id': 'https://openalex.org/W123', 'doi': 'https://doi.org/' + TARGET['doi'],
                'title': TARGET['title'], 'publication_year': 2021,
                'authorships': [{'author': {'display_name': 'John Jumper'}}],
                'locations': [{'pdf_url': 'https://example.org/wrong.pdf'}, {'pdf_url': 'https://example.org/right.pdf'}]
            }]}
        elif url == 'https://api.crossref.org/works':
            response.json.return_value = {'message': {'items': [{
                'DOI': TARGET['doi'], 'title': [TARGET['title']],
                'author': [{'given': 'John', 'family': 'Jumper'}],
                'published': {'date-parts': [[2021]]}
            }]}}
        elif url == 'https://example.org/wrong.pdf':
            response.iter_content.return_value = [wrong]
        elif url == 'https://example.org/right.pdf':
            response.iter_content.return_value = [correct]
        else:
            raise AssertionError('Unexpected endpoint: ' + url)
        return response
    config = Config()
    config.cache.enabled = False
    finder = PaperFinder(config=config, silent_init=True)
    finder.session = Mock(headers={}, get=Mock(side_effect=get))
    finder.identity_resolver = IdentityResolver(finder.session)
    result = finder.find(TARGET['title'], tmp_path)
    assert result.success and result.status == 'verified'
    assert result.metadata['doi'] == TARGET['doi']
    assert set(result.metadata['sources']) == {'openalex', 'crossref'}
    assert result.filepath.read_bytes() == correct
    assert result.attempts['https://example.org/wrong.pdf'] == 'mismatch'
    assert calls == ['https://api.openalex.org/works', 'https://api.crossref.org/works',
                     'https://example.org/wrong.pdf', 'https://example.org/right.pdf']
    assert not list(tmp_path.glob('.paperfinder-*'))
