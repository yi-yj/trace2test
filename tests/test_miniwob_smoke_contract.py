from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_required_local_configuration_is_ignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert "artifacts/" in gitignore
    assert ".benchmarks/" in gitignore


def test_smoke_runner_records_required_artifacts() -> None:
    source = (ROOT / "scripts/run_miniwob_smoke.py").read_text(encoding="utf-8")
    for required_name in (
        "observation.json",
        "action.json",
        "result.json",
        "screenshot-before.png",
        "screenshot-after.png",
        "manifest.json",
    ):
        assert required_name in source
