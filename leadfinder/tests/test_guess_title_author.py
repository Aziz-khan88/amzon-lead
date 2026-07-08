from __future__ import annotations

import pytest
from leadfinder.services.pipeline.run_research import guess_title_author

def test_guess_title_author_step_by_step():
    title = "Children's Book Illustration: Step by Step Techniques"
    snippet = "Children's Book Illustration: Step by Step Techniques, a Unique Guide from the Masters Paperback – January 1, 1998 by Jill Bossert (Author) 4.0 4.0 out of 5 stars (17)"
    cleaned, author, conf = guess_title_author(title, snippet)
    
    assert cleaned == "Children's Book Illustration: Step by Step Techniques"
    assert author == "Jill Bossert"
    assert conf == 0.8

def test_guess_title_author_concatenated_titles():
    title = "Writing with Pictures: How to Write and Illustrate Children's ...Amazon.com: Picture BooksChildren's Book Illustration and Design: Cummins, Julie ..."
    snippet = "May 1, 1997  Picture Book Perfection: How to Successfully Write a Picture Book That Sells to Publishers (and Readers) Picture Book Perfection: How to Successfully Write a P The Wild Robot on the Island: An Illustrated Picture Book Adaptation of The Wild Robot by Peter Brown Hardcover Ages: 5 - 10 years Jan 1, 1998  From Booklist The sumptuous color reproductions, boldly colored sidebars, and attractive design combine to invite readers to browse this lovely book."
    cleaned, author, conf = guess_title_author(title, snippet)
    
    assert cleaned == "Writing with Pictures: How to Write and Illustrate Children's"
    assert author == "Julie Cummins"
    assert conf == 0.75

def test_guess_title_author_sweet_tooth():
    title = "Sweet Tooth: Palatini, Margie, Davis, Jack E.: 9780689851599 ..."
    snippet = "by Barry Moser (Illustrator) or something"
    cleaned, author, conf = guess_title_author(title, snippet)
    
    assert cleaned == "Sweet Tooth: Palatini, Margie, Davis, Jack E.: 9780689851599"
    assert author == "Margie Palatini"
    assert conf == 0.75

def test_guess_title_author_junk_author():
    title = "Brave Every Day: Ludwig, Trudy, Barton, Patrice: 9780593306376 ..."
    snippet = "USA Today and Scholastic Instructor. Her books and presentations help empower chi"
    cleaned, author, conf = guess_title_author(title, snippet)
    
    assert cleaned == "Brave Every Day: Ludwig, Trudy, Barton, Patrice: 9780593306376"
    assert author == "Trudy Ludwig"
    assert conf == 0.75
