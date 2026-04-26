from src.core.publishers import PublisherUtils


def test_detect_publisher_from_url_known_domains():
    utils = PublisherUtils()

    assert utils.detect_publisher(
        url="https://www.sciencedirect.com/science/article/pii/S123456789"
    ) == "elsevier"

    assert utils.detect_publisher(
        url="https://link.springer.com/article/10.1007/s12345-023-00001-0"
    ) == "springer"

    assert utils.detect_publisher(
        url="https://onlinelibrary.wiley.com/doi/10.1002/xyz1234"
    ) == "wiley"

    assert utils.detect_publisher(
        url="https://ieeexplore.ieee.org/document/1234567"
    ) == "ieee"


def test_detect_publisher_from_doi_prefix():
    utils = PublisherUtils()

    assert utils.detect_publisher(doi="10.1007/s12345-023-00001-0") == "springer"
    assert utils.detect_publisher(doi="10.1016/j.jcat.2023.01.001") == "elsevier"
    assert utils.detect_publisher(doi="10.1002/chem.202300001") == "wiley"
    assert utils.detect_publisher(doi="10.1109/5.771073") == "ieee"
    assert utils.detect_publisher(doi="10.1371/journal.pone.0000001") == "plos"
    assert utils.detect_publisher(doi="10.3390/molecules28010001") == "mdpi"


def test_generate_publisher_urls_springer_nature():
    """generate_publisher_urls() should produce plausible Springer/Nature URLs."""
    utils = PublisherUtils()
    doi = "10.1038/s41586-023-06139-9"
    article_url = "https://www.nature.com/articles/s41586-023-06139-9"

    urls = utils.generate_publisher_urls(doi=doi, article_url=article_url, publisher="springer")

    # Standard DOI resolver
    assert f"https://doi.org/{doi}" in urls

    # Derived patterns
    assert any("/pdf" in u for u in urls)
    assert any("content/pdf" in u for u in urls)

    # No duplicates
    assert len(urls) == len(set(urls))


def test_get_publisher_headers_springer_with_referer():
    utils = PublisherUtils()
    referer = "https://www.nature.com"

    headers = utils.get_publisher_headers("springer", referer=referer)

    assert headers["User-Agent"].startswith("Mozilla/")
    assert "application/pdf" in headers["Accept"]
    assert headers["Referer"] == referer
    assert headers.get("Upgrade-Insecure-Requests") == "1"


def test_get_publisher_headers_elsevier():
    utils = PublisherUtils()
    headers = utils.get_publisher_headers("elsevier")

    assert "application/pdf" in headers["Accept"]
    assert "User-Agent" in headers
    assert "Accept-Language" in headers
