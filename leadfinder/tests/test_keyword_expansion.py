import pytest
from leadfinder.services.pipeline.run_research import _keyword_variants, discovery_queries

def test_specific_keyword_no_expansion():
    # A specific book/topic like "children of time" should not trigger generic children's picture book expansion
    variants = _keyword_variants("children of time")
    assert variants == ["children of time"]

    variants_dune = _keyword_variants("children of dune")
    assert variants_dune == ["children of dune"]

def test_generic_children_expansion():
    # Searching for just "children" should expand to standard children/kids book searches
    variants = _keyword_variants("children")
    assert "children" in variants
    assert "children picture book" in variants
    assert "kids picture book" in variants

def test_generic_illustration_expansion():
    # Searching for "illustration" should expand to illustration searches
    variants = _keyword_variants("illustration")
    assert "illustration" in variants
    assert "children picture book illustrator" in variants
    assert "children book illustrator" in variants

def test_children_books_illustration_expands_to_product_focused_queries():
    variants = _keyword_variants("Children books illustration")
    queries = discovery_queries("Children books illustration")

    assert "children picture book illustrator" in variants
    assert "illustrated children picture book" in variants
    assert 'site:amazon.com/dp "children picture book illustrator"' in queries
    assert "amazon.com/dp children picture book illustrator by" in queries

def test_plural_handling():
    # Plurals should add the singular form and expand if it matches the generic terms
    variants = _keyword_variants("children's books")
    assert "children's books" in variants
    assert "children's book" in variants
    assert "children picture book" in variants
    assert "kids picture book" in variants

def test_discovery_queries_format():
    # Check that discovery queries are formatted with the terms properly
    queries = discovery_queries("children of time")
    
    # We expect exactly these queries targeting only "children of time" without any extra keywords added
    expected = [
        'site:amazon.com "children of time"',
        'amazon "children of time"',
        '"children of time" "amazon.com/dp"',
        'children of time'
    ]
    assert queries == expected
