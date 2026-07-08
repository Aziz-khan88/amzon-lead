from leadfinder.services.ai.classify_video import choose_video_status, classify_video


def test_animated_trailer_status():
    vc = classify_video({"title": "Bella and the Brave Little Cloud Animated Book Trailer"})
    status, confidence, _ = choose_video_status([vc])
    assert status == "found_animated_video"
    assert confidence >= 0.75


def test_book_trailer_status():
    vc = classify_video({"title": "Bella and the Brave Little Cloud Book Trailer"})
    status, _, _ = choose_video_status([vc])
    assert status == "found_trailer"


def test_read_aloud_only_status():
    vc = classify_video({"title": "Bella and the Brave Little Cloud Read Aloud"})
    status, _, _ = choose_video_status([vc])
    assert status == "found_read_aloud_only"


def test_unrelated_result_no_public_video_or_unclear():
    vc = classify_video({"title": "Unrelated channel update"})
    status, _, _ = choose_video_status([vc])
    assert status in {"no_public_video_found", "unclear"}
