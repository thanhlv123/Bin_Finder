"""Public CLI parsing without network or GUI imports."""
import json
import subprocess
import sys
import os
from pathlib import Path
import pytest
from bin_finder.run.cli import main, load_options, parser


@pytest.mark.parametrize("arguments", [[], ["run"], ["run", "s.txt", "-o", "out", "--from-step", "bad"],
                                      ["run", "s.txt", "-o", "out", "--until-step", "bad"]])
def test_invalid_command(arguments):
    environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    result = subprocess.run([sys.executable, "-m", "bin_finder", *arguments], capture_output=True, env=environment)
    assert result.returncode == 2
    assert b"usage:" in result.stdout + result.stderr


def test_config_unknown_and_override(tmp_path):
    config = tmp_path / "run.json"
    config.write_text(json.dumps({"qa": {"unknown": True}}))
    with pytest.raises(SystemExit) as error:
        main(["script.txt", "-o", str(tmp_path / "out"), "--config", str(config)])
    assert error.value.code == 2
    config.write_text(json.dumps({"qa": {"target_lufs": -20}, "allow_suggested": False}))
    options = load_options(parser().parse_args(["script.txt", "-o", "out", "--config", str(config),
                                               "--target-lufs", "-14", "--allow-suggested"]))
    assert options.target_lufs == -14
    assert options.allow_suggested
