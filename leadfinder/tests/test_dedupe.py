from leadfinder.services.pipeline.dedupe import dedupe_book_candidates


def test_same_title_author_with_punctuation_dedupes():
    candidates = [
        {"title": "The Moonlit Bunny Adventure!", "author_name": "Avery Moon"},
        {"title": "The Moonlit Bunny Adventure", "author_name": "Avery Moon"},
    ]
    assert len(dedupe_book_candidates(candidates)) == 1


def test_same_asin_dedupes():
    candidates = [
        {"title": "A", "author_name": "One", "asin": "B012345678"},
        {"title": "Different", "author_name": "Two", "asin": "B012345678"},
    ]
    assert len(dedupe_book_candidates(candidates)) == 1


def test_different_authors_do_not_merge():
    candidates = [
        {"title": "A Shared Title", "author_name": "One"},
        {"title": "A Shared Title", "author_name": "Two"},
    ]
    assert len(dedupe_book_candidates(candidates)) == 2
