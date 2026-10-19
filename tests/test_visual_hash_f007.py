from bin_finder.visual_hash import hamming_similarity


def test_identical_hashes_have_full_similarity():
    assert hamming_similarity("0123456789abcdef", "0123456789abcdef") == 1.0


def test_opposite_hashes_have_zero_similarity():
    assert hamming_similarity("0000000000000000", "ffffffffffffffff") == 0.0


def test_invalid_hashes_are_safe():
    assert hamming_similarity("bad", "also-bad") == 0.0
