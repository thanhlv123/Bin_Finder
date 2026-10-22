"""Deterministic production scene planning. No Qt, network, LLM or third-party dependency.

raw script -> segmentation -> stable scene IDs -> duration estimate -> conservative
context enrichment. Every structured context value is copied from the script text
(never invented); when nothing structured can be found, ``keywords`` still carries
normalized words from the text so search and heuristic verification stay usable.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from bin_finder.models import SceneContext, SceneRecord


class ScenePlanningError(ValueError):
    """Invalid or oversized script; ``code`` is a short stable identifier."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ScenePlanningPolicy:
    # Bounds mirror session persistence (script_text <= 50000 chars, <= 1000 scenes).
    max_input_chars: int = 50_000
    max_scenes: int = 1000  # session snapshots accept at most 1000 scenes
    # Sentences shorter than min_scene_words are grouped with neighbours (same paragraph)
    # while the group stays within max_scene_words; longer sentences are split.
    min_scene_words: int = 8
    max_scene_words: int = 17
    # Duration estimate: words / words_per_second, clamped, rounded to 0.1 s.
    words_per_second: float = 2.5
    min_duration: float = 3.5
    max_duration: float = 7.0  # F006 ClipPolicy.max_duration: one scene -> one final clip

    def validate(self) -> None:
        if self.max_input_chars < 1 or self.max_scenes < 1:
            raise ValueError("input and scene limits must be positive")
        if not 1 <= self.min_scene_words <= self.max_scene_words:
            raise ValueError("min_scene_words must be within 1..max_scene_words")
        if self.words_per_second <= 0:
            raise ValueError("words_per_second must be positive")
        if not 0 < self.min_duration <= self.max_duration:
            raise ValueError("duration bounds must satisfy 0 < min <= max")
        if self.max_scene_words / self.words_per_second > self.max_duration:
            raise ValueError("max_scene_words would exceed max_duration at words_per_second")


@dataclass(frozen=True)
class ScenePlanningResult:
    scenes: tuple[SceneRecord, ...]


_TOKEN = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+(?:['’-][^\W\d_]+)*")
_TERMINATORS = ".!?…。！？"
_FULLWIDTH = "。！？"
_CLOSERS = "\"'”’)]»"
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "inc", "ltd", "co",
    "mt", "gen", "col", "capt", "sgt", "lt", "e.g", "i.e", "u.s", "u.k", "a.m", "p.m",
    "ông", "bà", "tp", "ts", "gs", "ths", "pgs",
}
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_STOP = frozenset("""
a an the and or but nor of to in on at by for from with without into onto over under about as
is are was were be been being am do does did has have had having will would can could should may
might must shall it its this that these those there here he she they them his her their him we
us our you your i me my not no so than then too very just also still even only own same such
while when where which who whom whose what how why if because until before after again once
và của là một những các có được trong cho với này đó khi để từ tại ở thì mà cũng đã sẽ đang
rất như nhưng hoặc nếu vì bởi theo về lên xuống ra vào
""".split())

_PEOPLE = frozenset("""
people person man men woman women child children kid kids boy girl boys girls worker workers
employee employees staff student students teacher teachers doctor doctors nurse nurses farmer
farmers driver drivers soldier soldiers police officer officers family families crowd customer
customers tourist tourists mechanic mechanics engineer engineers vendor vendors passenger
passengers couple parents mother father grandfather grandmother granddaughter grandson friends
residents citizens pedestrians commuters artist artists chef cook fisherman fishermen
protesters players athletes musicians
""".split())
_MODIFIERS = frozenset("""
young old elderly little small tired busy local homeless poor rich retired middle-aged
""".split())
_OBJECTS = frozenset("""
office offices desk desks building buildings tower towers skyscraper skyscrapers car cars truck
bus train bicycle bike boat ship plane airplane airport ticket tickets suitcase luggage bag
laptop computer screen phone window windows door table chair lights light lamp lamps street
road bridge market shop store factory farm field kitchen restaurant hospital school classroom
house home room harbor port river sea beach mountain forest tools machine machines camera book
books flag sign food
""".split())
_VERB_BASES = (
    "work walk repair sit stand hold run drive talk read write cook eat play wait watch carry "
    "build cross gather paint clean climb dance sing smile laugh cry wash load unload pack open "
    "close push pull ride sail fish plant harvest study teach serve sell buy shop wave point "
    "type sleep burn shine fly land board hug shake wear"
).split()
_IRREGULAR = {"sit": ("sat",), "stand": ("stood",), "hold": ("held",), "run": ("ran",),
              "drive": ("drove", "driven"), "write": ("wrote", "written"), "eat": ("ate",),
              "wear": ("wore",), "fly": ("flew",), "sing": ("sang",), "sleep": ("slept",),
              "build": ("built",), "sell": ("sold",), "buy": ("bought",), "shake": ("shook",),
              "ride": ("rode",), "teach": ("taught",)}
_ADVERBS = frozenset("late hard slowly quickly together alone silently carefully".split())
_NOT_ACTIONS = frozenset("""
morning evening building buildings ceiling nothing something anything everything king thing
things spring string wedding during ring bring evening opening beginning meeting clothing
""".split())
_LOCATION_PREPS = frozenset("""
in at near across over inside outside through around along ở tại trong ngoài đến gần quanh
""".split())
_NOT_PLACES = frozenset("""
monday tuesday wednesday thursday friday saturday sunday january february march april may june
july august september october november december i
""".split())


def _verb_forms() -> frozenset[str]:
    forms = set()
    for base in _VERB_BASES:
        forms.update((base, base + "s", base + "es", base + "ed", base + "ing"))
        if base.endswith("e"):
            forms.update((base + "d", base[:-1] + "ing"))
        if base.endswith("y"):
            forms.update((base[:-1] + "ies", base[:-1] + "ied"))
        if len(base) == 3 and base[1] in "aeiou" and base[2] not in "aeiouwy":
            forms.update((base + base[2] + "ed", base + base[2] + "ing"))
        forms.update(_IRREGULAR.get(base, ()))
    return frozenset(forms)


_VERB_FORMS = _verb_forms()
_MAX_ITEMS = 6
_MAX_ITEM_CHARS = 80


def _words(text: str) -> list[str]:
    return _TOKEN.findall(text)


def content_words(text: str, limit: int = 10) -> list[str]:
    """Distinct non-stopword tokens in order of appearance, original casing preserved."""
    result, seen = [], set()
    for token in _words(text):
        key = token.casefold()
        if (len(key) < 2 and not key.isdigit()) or key in _STOP or key in seen:
            continue
        seen.add(key)
        result.append(token)
        if len(result) >= limit:
            break
    return result


def _is_abbreviation(line: str, index: int) -> bool:
    start = index
    while start > 0 and (line[start - 1].isalnum() or line[start - 1] == "."):
        start -= 1
    word = line[start:index].casefold()
    if word in _ABBREVIATIONS:
        return True
    if len(word) == 1 and word.isalpha() and line[start].isupper():
        return True  # initial such as "J. Smith"
    if word == "no":
        rest = line[index + 1:].lstrip()
        return bool(rest) and rest[0].isdigit()
    return False


def _split_sentences(line: str) -> list[str]:
    sentences, start, i, n = [], 0, 0, len(line)
    while i < n:
        char = line[i]
        if char not in _TERMINATORS:
            i += 1
            continue
        j = i
        while j + 1 < n and line[j + 1] in _TERMINATORS:
            j += 1
        k = j
        while k + 1 < n and line[k + 1] in _CLOSERS:
            k += 1
        boundary = char in _FULLWIDTH or k + 1 >= n or line[k + 1].isspace()
        if boundary and not (char == "." and j == i and _is_abbreviation(line, i)):
            sentences.append(line[start:k + 1])
            start = k + 1
        i = k + 1
    if line[start:].strip():
        sentences.append(line[start:])
    return sentences


def _split_long(sentence: str, limit: int) -> list[str]:
    """Split an over-long sentence at clause marks, then at word boundaries."""
    if len(_words(sentence)) <= limit:
        return [sentence]
    clauses = [c for c in re.split(r"(?<=[,;:—–])\s+", sentence) if c.strip()]
    pieces, current = [], ""
    for clause in clauses:
        for part in _chunk_words(clause, limit):
            joined = f"{current} {part}".strip()
            if current and len(_words(joined)) > limit:
                pieces.append(current)
                current = part
            else:
                current = joined
    if current:
        pieces.append(current)
    return pieces


def _chunk_words(text: str, limit: int) -> list[str]:
    tokens = text.split()
    chunks = [" ".join(tokens[i:i + limit]) for i in range(0, len(tokens), limit)]
    return [c for c in chunks if len(_words(c)) > 0] or [text]


def _count(text: str) -> int:
    return len(_words(text))


def _group(sentences: list[str], policy: ScenePlanningPolicy) -> list[str]:
    groups: list[list[str]] = []
    current: list[str] = []
    current_words = 0
    for sentence in sentences:
        words = _count(sentence)
        if current and current_words < policy.min_scene_words \
                and current_words + words <= policy.max_scene_words:
            current.append(sentence)
            current_words += words
        else:
            if current:
                groups.append(current)
            current, current_words = [sentence], words
    if current:
        groups.append(current)
    texts = [" ".join(g) for g in groups]
    if (len(texts) > 1 and _count(texts[-1]) < policy.min_scene_words
            and _count(texts[-2]) + _count(texts[-1]) <= policy.max_scene_words):
        texts[-2:] = [f"{texts[-2]} {texts[-1]}"]
    return texts


def _normalize(script: str) -> str:
    text = unicodedata.normalize("NFC", script).replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROL.sub("", text.replace("\t", " ").replace(" ", " "))


def segment(script: str, policy: ScenePlanningPolicy | None = None) -> list[str]:
    """Return scene texts for ``script`` (no IDs, durations or context)."""
    policy = policy or ScenePlanningPolicy()
    policy.validate()
    if not isinstance(script, str):
        raise ScenePlanningError("script-not-text")
    if len(script) > policy.max_input_chars:
        raise ScenePlanningError("script-too-long")
    texts: list[str] = []
    for paragraph in re.split(r"\n\s*\n", _normalize(script)):
        sentences = []
        for line in paragraph.split("\n"):
            for sentence in _split_sentences(line):
                sentence = " ".join(sentence.split())
                if _count(sentence):
                    sentences.extend(_split_long(sentence, policy.max_scene_words))
        if sentences:
            texts.extend(_group(sentences, policy))
    # A one-word remnant is never a scene of its own; fold it into a neighbour.
    merged: list[str] = []
    for text in texts:
        if merged and _count(text) < 2 and _count(merged[-1]) + _count(text) <= policy.max_scene_words:
            merged[-1] = f"{merged[-1]} {text}"
        else:
            merged.append(text)
    if (len(merged) > 1 and _count(merged[0]) < 2
            and _count(merged[0]) + _count(merged[1]) <= policy.max_scene_words):
        merged[1:2] = [f"{merged[0]} {merged[1]}"]
        del merged[0]
    if len(merged) > policy.max_scenes:
        raise ScenePlanningError("too-many-scenes")
    return merged


def estimate_duration(text: str, policy: ScenePlanningPolicy | None = None) -> float:
    """Narration estimate: words / words_per_second clamped to [min, max], 0.1 s steps."""
    policy = policy or ScenePlanningPolicy()
    seconds = _count(text) / policy.words_per_second
    return round(min(policy.max_duration, max(policy.min_duration, seconds)), 1)


def _unique(items, limit=_MAX_ITEMS) -> tuple[str, ...]:
    result, seen = [], set()
    for item in items:
        item = " ".join(item.split())[:_MAX_ITEM_CHARS].strip()
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            result.append(item)
        if len(result) >= limit:
            break
    return tuple(result)


def _spans(text: str):
    return [(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(text)]


def _sentence_initial(text: str, start: int) -> bool:
    before = text[:start].rstrip()
    return not before or before[-1] in _TERMINATORS + "\n"


def enrich_context(text: str) -> SceneContext:
    """Conservative text-derived context. Mood, avoid and suggested sources stay empty."""
    spans = _spans(text)
    subjects, actions, locations = [], [], []
    for index, (token, start, _end) in enumerate(spans):
        key = token.casefold()
        if key in _PEOPLE:
            first = index
            for _ in range(2):
                if first == 0:
                    break
                prev, prev_start, prev_end = spans[first - 1]
                if text[prev_end:spans[first][1]].strip():
                    break
                if prev.casefold() in _MODIFIERS or (
                        prev[0].isupper() and prev.casefold() not in _STOP
                        and not _sentence_initial(text, prev_start)):
                    first -= 1
                else:
                    break
            subjects.append(text[spans[first][1]:spans[index][2]])
        if key in _VERB_FORMS or (key.endswith("ing") and len(key) >= 6
                                  and key not in _NOT_ACTIONS and key not in _STOP):
            phrase = token
            nxt = spans[index + 1] if index + 1 < len(spans) else None
            if nxt and nxt[0].casefold() in _ADVERBS and not text[_end:nxt[1]].strip():
                phrase = f"{token} {nxt[0]}"
            actions.append(phrase.lower())
        if key in _LOCATION_PREPS and index + 1 < len(spans):
            parts = []
            cursor = _end
            for word, w_start, w_end in spans[index + 1:index + 4]:
                if text[cursor:w_start].strip() or not word[0].isupper() \
                        or word.casefold() in _STOP or word.casefold() in _NOT_PLACES:
                    break
                parts.append(word)
                cursor = w_end
            if parts:
                locations.append(" ".join(parts))
    # Contiguous object nouns form one phrase ("office lights"); isolated ones stay single.
    phrases, run = [], []
    for token, start, end in spans:
        if token.casefold() in _OBJECTS and (not run or not text[run[-1][2]:start].strip()):
            run.append((token.casefold(), start, end))
            continue
        if run:
            phrases.append(" ".join(r[0] for r in run[:3]))
        run = [(token.casefold(), start, end)] if token.casefold() in _OBJECTS else []
    if run:
        phrases.append(" ".join(r[0] for r in run[:3]))
    subject, action = _unique(subjects, 4), _unique(actions, 4)
    location, objs = _unique(locations, 3), _unique(phrases)
    keywords: list[str] = []
    anchor = subject[0] if subject else (objs[0] if objs else "")
    for place in location[:2]:
        if anchor:
            keywords.append(f"{place} {anchor}")
    if subject and action:
        keywords.append(f"{subject[0]} {action[0]}")
    if objs and location:
        keywords.append(f"{location[0]} {objs[0]}")
    fallback = " ".join(content_words(text, 8)) or " ".join(text.split())[:100]
    keywords.append(fallback)
    return SceneContext(subject=subject, action=action, location=location, objects=objs,
                        keywords=_unique(keywords, 5))


class ScenePlanner:
    def __init__(self, policy: ScenePlanningPolicy | None = None):
        self.policy = policy or ScenePlanningPolicy()
        self.policy.validate()

    def plan(self, script: str) -> ScenePlanningResult:
        texts = segment(script, self.policy)
        return ScenePlanningResult(tuple(
            SceneRecord(scene_id=f"scene_{i:03d}", order=i, english_text=text,
                        target_duration=estimate_duration(text, self.policy),
                        context=enrich_context(text))
            for i, text in enumerate(texts, 1)))
