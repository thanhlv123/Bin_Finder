import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def test_cli_json_csv(tmp_path):
    fixture = Path(__file__).parent / "fixtures/brief/k1_excerpt.md"
    out, table = tmp_path / "plan.json", tmp_path / "plan.csv"
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    result = subprocess.run([sys.executable, "-m", "bin_finder.brief", str(fixture), "-o", str(out),
        "--csv", str(table), "--provider", "heuristic", "--project-root", str(tmp_path)],
        env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["cues"]) == len(data["briefs"]) > 0
    assert data["provider_used"] == "heuristic" and data["fallback_count"] == 0
    assert data["script_sha256"] == hashlib.sha256(fixture.read_text(encoding="utf-8").encode()).hexdigest()
    with table.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == len(data["cues"])
    assert rows[0]["text"] == data["cues"][0]["text"]
    assert rows[0]["queries_pexels"]
    assert "fallbacks=0" in result.stdout
