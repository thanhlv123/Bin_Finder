from dataclasses import replace
import pytest
from bin_finder.models import CandidateRecord
from bin_finder.footage.credits import license_for, credit_line, render_credits


def candidate(provider="commons", rights="cc-by-sa-4.0"):
    return CandidateRecord("c", "cue", provider, provider + ":1", "Forest", 12, 0,
                           rights_status=rights, creator="Jane Doe", source_url="https://example.org/video")


@pytest.mark.parametrize("rights,usable", [("cc-by-sa-4.0", True), ("cc-by-4.0", True),
    ("CC0", True), ("public-domain", True), ("cc-by-nc-4.0", False),
    ("cc-by-nd-4.0", False), ("unknown", False), ("not-cc-by-4.0", False)])
def test_commons_license(rights, usable):
    assert license_for(candidate(rights=rights)).usable_in_video is usable


@pytest.mark.parametrize("provider,usable", [("pexels", True), ("pixabay", True),
    ("coverr", True), ("storyblocks", True), ("youtube", False), ("unknown", False)])
def test_provider_license(provider, usable):
    assert license_for(candidate(provider)).usable_in_video is usable


def test_credit_and_deduplication():
    info = license_for(candidate())
    line = credit_line(info)
    assert "Jane Doe" in line and "cc-by-sa-4.0" in line and info.source_url in line
    output = render_credits([info, info])
    assert "1 unique sources" in output and output.count("Video by") == 1


def test_restrictive_metadata_wins():
    c = replace(candidate(), source_metadata={"license": "CC BY-NC 4.0"})
    assert not license_for(c).usable_in_video


@pytest.mark.parametrize("provider,display", [("pexels", "Pexels"), ("pixabay", "Pixabay"),
    ("commons", "Wikimedia Commons"), ("coverr", "Coverr"), ("youtube", "YouTube"),
    ("storyblocks", "Storyblocks")])
def test_credit_display_names_and_notes(provider, display):
    info = replace(license_for(candidate(provider)), notes="Original credit or usage note")
    line = credit_line(info)
    assert f" on {display} (" in line
    assert (info.notes in line) is (provider == "commons" or not info.usable_in_video)
    uncleared = replace(info, usable_in_video=False)
    assert info.notes in credit_line(uncleared)


@pytest.mark.parametrize("provider", ["pexels", "pixabay", "coverr", "storyblocks"])
def test_credits_omit_discovery_note(provider):
    assert "Discovery metadata" not in render_credits([license_for(candidate(provider))])
