from leadfinder.services.amazon.amazon_url_parser import (
    extract_asin,
    is_amazon_url,
    normalize_amazon_book_url,
)


def test_extracts_asin_from_dp():
    assert extract_asin("https://www.amazon.com/dp/B0ABCDEF12/ref=something") == "B0ABCDEF12"


def test_extracts_asin_from_gp_product():
    assert extract_asin("https://amazon.co.uk/gp/product/B012345678?tag=x") == "B012345678"


def test_normalizes_amazon_url():
    assert normalize_amazon_book_url("https://amazon.com/gp/product/B012345678/ref=abc") == "https://www.amazon.com/dp/B012345678"
    assert normalize_amazon_book_url("https://amazon.com/dp/B012345678", "tag-20") == "https://www.amazon.com/dp/B012345678?tag=tag-20"


def test_preserves_supported_marketplace_when_normalizing():
    assert normalize_amazon_book_url("https://smile.amazon.co.uk/gp/product/B012345678") == "https://www.amazon.co.uk/dp/B012345678"


def test_rejects_non_amazon_url():
    assert not is_amazon_url("https://example.com/dp/B012345678")
    assert not is_amazon_url("https://amazon.com.evil.example/dp/B012345678")
    assert not is_amazon_url("https://notamazon.com/dp/B012345678")


def test_does_not_rewrite_non_amazon_product_path():
    url = "https://example.com/dp/B012345678"
    assert normalize_amazon_book_url(url) == url


def test_parser_does_not_fetch_amazon_page(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Network fetch should not happen")

    monkeypatch.setattr("requests.get", fail)
    assert extract_asin("https://www.amazon.com/dp/B0ABCDEF12") == "B0ABCDEF12"
