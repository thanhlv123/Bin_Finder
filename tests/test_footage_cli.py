import json
from bin_finder.footage.__main__ import main
from bin_finder.providers.registry import ProviderRegistry
from test_footage_service import make_plan, FakeProvider


def test_cli_offline(tmp_path, monkeypatch, capsys):
    import bin_finder.footage.__main__ as cli
    providers = [FakeProvider("pexels"), FakeProvider("youtube"), FakeProvider("coverr", fail=True)]
    monkeypatch.setattr(cli, "create_registry", lambda root: ProviderRegistry(providers))
    briefs = tmp_path / "briefs.json"
    briefs.write_text(json.dumps(make_plan().to_dict()))
    output, credits = tmp_path / "footage.json", tmp_path / "credits.txt"
    assert main([str(briefs), "-o", str(output), "--credits", str(credits),
                 "--project-root", str(tmp_path), "--sources", "pexels,coverr", "--limit-cues", "2"]) == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert len(result["cues"]) == 2 and result["candidates_per_source"] == {"pexels": 2}
    assert not providers[1].calls
    text = credits.read_text(encoding="utf-8")
    assert "Pexels License" in text and text.count("Video by") == 1
    stdout = capsys.readouterr().out
    assert "Cues: 2" in stdout and "fake-secret" not in stdout + text + output.read_text()
