from pathlib import Path


REPO = Path(__file__).resolve().parents[2]


def test_legacy_vast_launcher_and_30_job_yaml_are_disabled() -> None:
    launcher = (REPO / "sky" / "launch-ayue-720p.sh").read_text(encoding="utf-8")
    legacy_yaml = (REPO / "sky" / "ayue-video-720p.yaml").read_text(encoding="utf-8")

    assert "exit 64" in launcher
    assert "sky launch" not in launcher
    assert "cloud: vast" not in legacy_yaml
    assert "tasks/ayue-720p-jobpack" not in legacy_yaml
    assert not (REPO / "sky" / "ayue-video-720p-runpod.yaml").exists()


def test_runpod_launcher_defaults_to_free_plan_and_delegates_paid_lifecycle_to_cli() -> None:
    launcher = (REPO / "sky" / "launch-ayue-720p-runpod.sh").read_text(encoding="utf-8")

    assert "ayue-720p-plan" in launcher
    assert "--allow-pending" in launcher
    assert "ayue-720p-launch" in launcher
    assert "--confirm-paid" in launcher
    assert "sky launch" not in launcher
