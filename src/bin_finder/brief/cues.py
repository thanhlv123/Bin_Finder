"""Chapter-aware cue splitting, preserving narration order and punctuation."""
import re
from bin_finder.scene_planning import _split_sentences, _split_long, _words, estimate_duration, ScenePlanningPolicy
from .models import Cue


def split_cues(script_text: str, max_words: int = 18) -> list[Cue]:
    if max_words < 3:
        raise ValueError("max_words must be at least 3")
    chapters = []
    chapter, lines = "", []
    for line in script_text.splitlines():
        heading = re.match(r"^\s*#{1,6}\s+(.+?)\s*#*\s*$", line)
        if heading:
            chapters.append((chapter, lines))
            chapter, lines = heading[1].replace("**", ""), []
        elif line.strip():
            lines.append(line.replace("**", "").replace("#", "").strip())
    chapters.append((chapter, lines))
    result = []
    policy = ScenePlanningPolicy(max_scene_words=max_words, max_duration=max(7.0, max_words / 2.5))
    for chapter, lines in chapters:
        pieces = []
        for sentence in _split_sentences(" ".join(lines)):
            # Prefer conjunction boundaries for long sentences; keep conjunctions in narration.
            clauses = (re.split(r"\s+(?=(?:and|but|or|while|because|although)\b)", sentence)
                       if len(_words(sentence)) > max_words else [sentence])
            for clause in clauses:
                pieces.extend(_split_long(" ".join(clause.split()), max_words))
        i = 0
        while i < len(pieces):
            if len(_words(pieces[i])) < 3 and len(pieces) > 1:
                if i:
                    pieces[i-1:i+1] = [pieces[i-1] + " " + pieces[i]]
                    i -= 1
                else:
                    pieces[:2] = [pieces[0] + " " + pieces[1]]
            else:
                i += 1
        # Rebalance merged short fragments at word boundaries when needed.
        balanced = []
        for piece in pieces:
            words = piece.split()
            while len(_words(" ".join(words))) > max_words and len(words) >= 6:
                cut = min(max_words, len(words)-3)
                while cut > 3 and len(_words(" ".join(words[:cut]))) > max_words:
                    cut -= 1
                balanced.append(" ".join(words[:cut]))
                words = words[cut:]
            if words:
                balanced.append(" ".join(words))
        for text in balanced:
            result.append(Cue(f"C{len(result)+1:04d}", chapter, text, len(_words(text)), estimate_duration(text, policy)))
    return result
