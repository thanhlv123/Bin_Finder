"""License metadata for discovery, independent of acquisition authorization."""
from dataclasses import dataclass
import re


@dataclass(frozen=True)
class LicenseInfo:
    provider: str
    source_id: str
    title: str
    creator: str
    creator_url: str
    source_url: str
    license_name: str
    license_url: str
    attribution_required: bool
    usable_in_video: bool
    notes: str = ""


def license_for(candidate):
    metadata = candidate.source_metadata
    provider = candidate.provider
    licenses = {
        "pexels": ("Pexels License", "https://www.pexels.com/license/"),
        "pixabay": ("Pixabay Content License", "https://pixabay.com/service/license-summary/"),
        "coverr": ("Coverr License", "https://coverr.co/license"),
        "storyblocks": ("Storyblocks License", "https://www.storyblocks.com/license"),
    }
    name, link = licenses.get(provider, (str(metadata.get("license") or candidate.rights_status),
                                           str(metadata.get("license_url") or "")))
    usable = provider in licenses
    required = False
    notes = "Discovery metadata; acquisition authorization remains separate."
    if provider == "commons":
        tokens = [str(metadata.get("license") or ""), candidate.rights_status]
        normalized = [re.sub(r"[ _]+", "-", token.lower()).strip() for token in tokens]
        # Reject restrictive or ambiguous multi-license metadata, even if another token is permissive.
        restricted = any(re.search(r"(^|-)n[cd](-|$)", token) for token in normalized)
        allowed = any(re.fullmatch(r"(?:cc0(?:-1\.0)?|public-domain|pd(?:-old(?:-auto)?)?|cc-by(?:-sa)?(?:-[1-4]\.0)?)", token)
                      for token in normalized)
        usable = allowed and not restricted and not metadata.get("restrictions")
        required = bool(metadata.get("attribution_required", True))
        notes = str(metadata.get("credit") or "")
    elif provider == "youtube":
        usable = False
        notes = "Reference metadata only. License hints do not grant permission; no YouTube download."
    return LicenseInfo(provider, candidate.source_id, candidate.title, candidate.creator,
                       str(metadata.get("creator_url") or ""), candidate.source_url, name, link,
                       required, usable, notes)


def credit_line(info):
    creator = info.creator or "Unknown creator"
    display_name = {"pexels": "Pexels", "pixabay": "Pixabay", "commons": "Wikimedia Commons",
                    "coverr": "Coverr", "youtube": "YouTube", "storyblocks": "Storyblocks"}.get(info.provider, info.provider)
    line = f"Video by {creator} on {display_name} ({info.source_url}) \u2014 {info.license_name}"
    if info.provider == "commons":
        line += f"; title: {info.title}"
    if info.creator_url:
        line += f"; creator: {info.creator_url}"
    if info.license_url:
        line += f" ({info.license_url})"
    if info.notes and (info.provider == "commons" or not info.usable_in_video):
        line += f"; {info.notes}"
    if not info.usable_in_video:
        line += "; REFERENCE / NOT CLEARED FOR VIDEO"
    return line.replace("\r", " ").replace("\n", " ")


def render_credits(infos):
    unique = {info.source_id: info for info in infos}
    lines = [f"Footage credits \u2014 {len(unique)} unique sources"]
    for provider in sorted({info.provider for info in unique.values()}):
        lines.extend(["", provider])
        lines.extend(credit_line(info) for info in unique.values() if info.provider == provider)
    return "\n".join(lines) + "\n"
