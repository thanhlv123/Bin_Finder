from bin_finder.retrieval.lexical import BM25Ranker, exact_phrase_scores, tokenize


def test_tokenize_handles_vietnamese_and_casefold():
    tokens = tokenize("Thợ sửa xe ở Hà Nội, CLASSIC car")
    assert "thợ" in tokens
    assert "hà" in tokens
    assert "classic" in tokens


def test_bm25_ranks_relevant_transcript_first():
    documents = [
        "family says goodbye at Havana airport",
        "mechanic repairing classic Chevrolet on Cuba street",
        "office workers entering Shanghai metro",
    ]
    scores = BM25Ranker(documents).normalized_scores(
        "Cuba mechanic repairing classic Chevrolet"
    )
    assert scores[1] == 1.0
    assert scores[1] > scores[0]
    assert scores[1] > scores[2]


def test_exact_phrase_scores_count_context_phrases():
    scores = exact_phrase_scores(
        ("classic Chevrolet", "Havana mechanic"),
        [
            "Havana mechanic works on a classic Chevrolet",
            "Cuba street",
        ],
    )
    assert scores == [1.0, 0.0]
