"""ASS captions with short groups and current-word highlighting."""
from pathlib import Path


def ass_time(seconds: float) -> str:
    """Format rounded centiseconds without a sixty-second overflow."""
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    return f"{hours}:{minutes:02d}:{remainder // 100:02d}.{remainder % 100:02d}"


def escape_ass(text: str) -> str:
    """Keep narration text from injecting ASS override tags."""
    return text.replace("\\", "＼").replace("{", "(").replace("}", ")").replace("\n", " ").replace("\r", " ")


def write_subtitles(words: list[dict], output: Path, width: int, height: int) -> None:
    """Highlight one word at a time inside compact caption groups."""
    groups = []
    current = []
    for word in words:
        if current and (len(current) >= 7 or len(" ".join(item["word"] for item in [*current, word])) > 40):
            groups.append(current)
            current = []
        current.append(word)
    if current:
        groups.append(current)
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
             "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
             "Style: Default,Segoe UI,60,&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,100,100,65,1",
             "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for group in groups:
        for index, word in enumerate(group):
            end = group[index + 1]["start"] if index + 1 < len(group) else word["end"]
            text = " ".join((r"{\c&H0097DC3D&}" + escape_ass(item["word"]) + r"{\r}")
                            if position == index else escape_ass(item["word"])
                            for position, item in enumerate(group))
            lines.append(f"Dialogue: 0,{ass_time(word['start'])},{ass_time(end)},Default,,0,0,0,,{text}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8-sig")
