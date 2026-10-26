"""BF-S04A offline sample: editor-authored Gaspard Ulliel news shot proposal.

Research fixture ONLY: short French source excerpts supplied by the user.
The shot proposals are an editorial demonstration, NOT an AI-generated plan
and NOT independent fact checking. No providers, downloads, VLM, or GUI.
"""
from __future__ import annotations

import argparse
import json

from bin_finder.models import SceneRecord
from bin_finder.search.visual_search_contract import (
    FORMAT as VISUAL_FORMAT, parse_semantic_search_plan, script_digest,
)
from bin_finder.search.editorial_shot_plan import (
    FORMAT as SHOT_FORMAT, parse_editorial_shot_plan,
)

_SOURCE = (
    "Gaspard Ulliel. L'un des plus beaux visages du cinéma français. "
    "Deux César. Et Marvel qui l'attendait.",
    "Le 18 janvier 2022, en Savoie, il descend une piste bleue. "
    "Une piste facile. Quelques secondes plus tard, il est allongé "
    "dans la neige. Inconscient.",
    "Le lendemain, il meurt. Il avait trente-sept ans. "
    "Et c'est là que tout devient incompréhensible.",
    "Gaspard naît dans une famille où l'on parle tissus, coupes et silhouettes. "
    "Son père dessine des vêtements. Sa mère travaille dans la mode.",
    "Il a six ans quand ça arrive. Un dobermann. Le petit garçon veut "
    "monter dessus, comme sur un cheval. Le chien se retourne… "
    "et lui lacère la joue gauche.",
    "Enfant, il ne rêve pas de cinéma. Il rêve de jazz. "
    "Il apprend le saxophone, pendant deux ans.",
    "Il a onze ans quand une amie de sa mère, qui vient d'ouvrir "
    "une agence d'acteurs, lui pose une question toute simple.",
)

_ROLE = ("establish", "evidence", "conclude", "context", "develop", "bridge", "transition")
_BRIEF = (
    "Show a verifiable archival portrait of Gaspard Ulliel",
    "Establish an alpine ski location and a gentle marked blue piste",
    "On-screen date and age from narration, pending independent fact check",
    "Illustrate a family working with clothing design and fabrics",
    "Show generic Doberman detail, never fake a filmed childhood incident",
    "Illustrate a young person's dream of jazz and saxophone",
    "Visual transition to a young actor's first opportunity",
)
_STOCK_QUERIES = (
    ("Gaspard Ulliel portrait archive", "Gaspard Ulliel Cannes interview",
     "Gaspard Ulliel Cesar ceremony"),
    ("Savoie alpine ski resort", "blue ski piste marker", "gentle slope skier POV"),
    (),
    ("fashion designer drawing hands", "tailor measuring fabric", "sewing studio fabrics"),
    ("Doberman turning head", "dog silhouette closeup", "black dog looking back"),
    ("vintage saxophone close up", "jazz club ambient lights", "music instrument case"),
    (),
)


def source_and_base():
    scenes = tuple(
        SceneRecord(f"scene_{i:03d}", i, excerpt)
        for i, excerpt in enumerate(_SOURCE, 1)
    )
    base = {
        "format": VISUAL_FORMAT,
        "plan_id": "bf_s04a_gaspard_source",
        "source_digest": script_digest(scenes),
        "beats": [],
        "slots": [],
    }
    for i, scene in enumerate(scenes, 1):
        sid = f"scene_{i:03d}"
        name = f"slot{i}"
        search = i not in (3, 7)
        queries = _STOCK_QUERIES[i - 1]
        base["beats"].append({
            "beat_id": f"beat{i}", "scene_ids": [sid],
            "meaning": _BRIEF[i - 1],
            "anchor_text": scene.english_text[:min(65, len(scene.english_text))],
            "section_context": "Biographical documentary research vignette",
            "metaphor_note": "",
        })
        base["slots"].append({
            "slot_id": name, "beat_id": f"beat{i}",
            "scene_ids": [sid], "role": "context" if i == 7 else _ROLE[i - 1],
            "action": "search" if search else "graphic",
            "evidence_type": "direct" if i == 1 else (
                "contextual" if search else "not_applicable"),
            "entity_policy": "strict" if i == 1 else (
                "contextual" if search else "unspecified"),
            "source_text": scene.english_text[:min(220, len(scene.english_text))],
            "visual_brief": _BRIEF[i - 1],
            "must_show": ["visible documentary subject"] if search else [],
            "must_not_show": [
                "fake original accident footage", "unlabeled reenactment"
            ] if search else [],
            "required_entities": ["Gaspard Ulliel"] if i == 1 else [],
            "queries": [
                {"axis": axis, "text": value}
                for axis, value in zip(("subject", "moment", "action"), queries)
            ] if search else [],
            "reuse_from_slot_id": None,
            "uncertainty": "Identity and historical facts require external sources.",
        })
    return scenes, parse_semantic_search_plan(base, scenes)


def _shot(shot_id, slot, anchor, brief, kind, duration, tone, terms=(),
          *, queries=(), fallback="no_match", media="video"):
    return {
        "shot_id": shot_id,
        "slot_id": slot.slot_id,
        "beat_id": slot.beat_id,
        "scene_ids": list(slot.scene_ids),
        "source_anchor": anchor,
        "visual_brief": brief,
        "asset_evidence_type": kind,
        "media_type": media,
        "target_duration_seconds": duration,
        "visual_tone": tone,
        "must_show": list(terms),
        "must_not_show": (
            list(slot.must_not_show) if kind != "graphic" else []
        ),
        "search_queries": [
            {"language": language, "text": text}
            for language, text in queries
        ],
        "fallback_policy": fallback,
    }


def proposed_shots(base):
    s = base.slots
    shot_rows = [
        _shot("GASPARD_001", s[0], "Gaspard Ulliel.",
              "Verified photo or footage of the named actor",
              "authentic_person", 2.0, "somber",
              ("Gaspard Ulliel face",),
              queries=(("fr", "Gaspard Ulliel portrait interview archive"),
                       ("en", "Gaspard Ulliel Cannes red carpet portrait"))),
        _shot("GASPARD_002", s[0], "Deux César.",
              "Actual archival Cesar ceremony footage, if licensed and confirmed",
              "authentic_event", 2.0, "neutral", ("César awards ceremony",),
              queries=(("fr", "Gaspard Ulliel cérémonie César archives"),)),
        _shot("GASPARD_003", s[1], "en Savoie",
              "Generic alpine landscape of Savoie, labelled illustrative",
              "location_context", 2.0, "somber", ("snow-covered Alps",),
              queries=(("en", "Savoie ski resort aerial panorama"),
                       ("fr", "station ski Savoie vue aérienne")),
              fallback="contextual_illustration_labeled"),
        _shot("GASPARD_004", s[1], "une piste bleue",
              "Blue beginner ski piste sign on gentle slope, no real crash claim",
              "illustrative_stock", 2.0, "neutral", ("blue piste sign",),
              queries=(("en", "blue ski piste marker gentle slope"),),
              fallback="contextual_illustration_labeled"),
        _shot("GASPARD_005", s[1], "il descend une piste bleue",
              "Skier gliding calmly on a gentle slope; no crash reenactment",
              "illustrative_stock", 3.0, "suspense", ("skier", "gentle slope"),
              queries=(("en", "POV skier on easy groomed piste"),),
              fallback="contextual_illustration_labeled"),
        _shot("GASPARD_006", s[2], "Il avait trente-sept ans.",
              "Minimal black title with age, pending verification",
              "graphic", 2.0, "somber", media="graphic",
              fallback="graphic_with_source"),
        _shot("GASPARD_007", s[3], "Son père dessine des vêtements.",
              "Generic fashion designer hands sketching garments",
              "illustrative_stock", 2.0, "nostalgic",
              ("hand drawing fashion sketch",),
              queries=(("en", "fashion designer pencil sketch hands"),),
              fallback="contextual_illustration_labeled"),
        _shot("GASPARD_008", s[3], "Sa mère travaille dans la mode.",
              "Generic tailor handling folded fabric close up",
              "illustrative_stock", 2.0, "warm", ("fabric", "sewing workshop"),
              queries=(("en", "tailor cutting fabric close up"),),
              fallback="contextual_illustration_labeled"),
        _shot("GASPARD_009", s[4], "Un dobermann.",
              "Generic Doberman close up, explicitly not original event footage",
              "illustrative_stock", 2.0, "suspense", ("Doberman dog",),
              queries=(("en", "Doberman pinscher close up turning head"),),
              fallback="contextual_illustration_labeled"),
        _shot("GASPARD_010", s[4], "Le chien se retourne",
              "Symbolic sudden silhouette cut; no staged attack on child",
              "symbolic", 1.5, "suspense", ("dog silhouette",),
              queries=(("en", "dog silhouette motion close up"),),
              fallback="symbolic_labeled"),
        _shot("GASPARD_011", s[5], "Il rêve de jazz.",
              "Illustrative jazz club instruments and warm stage light",
              "symbolic", 2.5, "nostalgic", ("jazz instruments",),
              queries=(("en", "intimate jazz club stage atmosphere"),),
              fallback="symbolic_labeled"),
        _shot("GASPARD_012", s[5], "Il apprend le saxophone",
              "Hands pressing saxophone keys close up",
              "illustrative_stock", 3.0, "warm", ("saxophone keys", "hands"),
              queries=(("en", "saxophone player hands close up"),),
              fallback="contextual_illustration_labeled"),
        _shot("GASPARD_013", s[6], "Il a onze ans",
              "Simple on-screen age transition; do not invent childhood photo",
              "graphic", 2.0, "neutral", media="graphic",
              fallback="graphic_with_source"),
    ]
    return {
        "format": SHOT_FORMAT,
        "plan_id": "bf_s04a_gaspard_editorial_pilot",
        "base_plan_id": base.plan_id,
        "source_digest": base.source_digest,
        "shots": shot_rows,
    }


def sample():
    scenes, base = source_and_base()
    return scenes, base, parse_editorial_shot_plan(proposed_shots(base), base, scenes)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="BF-S04A offline illustrative shot plan, no LLM/provider calls"
    )
    parser.add_argument("--json", action="store_true",
                        help="Print canonical research JSON proposal")
    args = parser.parse_args(argv)
    _, _, plan = sample()
    if args.json:
        print(json.dumps(plan.to_mapping(), ensure_ascii=False, indent=2))
        return 0
    print("BFS04A_MODE: OFFLINE_EDITOR_AUTHORED_PILOT_NOT_AUTOMATIC_AI")
    print("BFS04A_STATUS:", plan.status)
    print("BFS04A_SHOTS:", len(plan.shots))
    print("BFS04A_UNIQUE_SLOTS:", len(set(x.slot_id for x in plan.shots)))
    print("BFS04A_ARCHIVAL_RESEARCH:", plan.route_counts().get(
        "licensed_archive_human_review", 0))
    print("BFS04A_CONTEXTUAL_STOCK:", plan.route_counts().get(
        "contextual_stock_search", 0))
    print("BFS04A_SYMBOLIC_STOCK:", plan.route_counts().get(
        "symbolic_stock_search", 0))
    print("BFS04A_GRAPHIC:", plan.route_counts().get("graphic_composition", 0))
    print("BFS04A_TOTAL_TARGET_SECONDS:", round(
        sum(x.target_duration_seconds for x in plan.shots), 1))
    print("BFS04A_SOURCE_FACTS_VERIFIED: False")
    print("BFS04A_MEDIA_OR_RIGHTS_APPROVED: False")
    print("BFS04A_PROVIDER_CALLS: 0")
    print("BFS04A_LOCAL_VISION_CALLS: 0")
    print("BFS04A_TIMELINE_CHANGED: False")
    for shot in plan.shots:
        print(
            f"BFS04A_SHOT: {shot.shot_id} slot={shot.slot_id} "
            f"seconds={shot.target_duration_seconds:g} "
            f"kind={shot.asset_evidence_type} route={shot.source_route}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
