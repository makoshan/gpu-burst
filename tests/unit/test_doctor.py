from gpu_burst.doctor import build_report, exit_code


def _check(report, name: str):
    return next(check for check in report.checks if check.name == name)


def test_doctor_marks_invalid_toml_as_invalid(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[provider.vast\n", encoding="utf-8")
    monkeypatch.setenv("GPU_BURST_CONFIG", str(config_path))

    report = build_report()

    assert _check(report, "config.toml").status == "invalid"
    assert report.paid_runtime_ready is False
    assert exit_code(report) == 3


def test_doctor_marks_empty_vast_key_as_invalid(tmp_path, monkeypatch) -> None:
    key_path = tmp_path / "vast_api_key"
    key_path.write_text("  \n", encoding="utf-8")
    monkeypatch.setenv("GPU_BURST_VAST_API_KEY_FILE", str(key_path))

    report = build_report()

    check = _check(report, "vast_api_key")
    assert check.status == "invalid"
    assert "empty" in check.detail
    assert report.paid_runtime_ready is False
    assert exit_code(report) == 3


def test_doctor_rejects_vast_key_readable_by_other_users(tmp_path, monkeypatch) -> None:
    key_path = tmp_path / "vast_api_key"
    key_path.write_text("secret", encoding="utf-8")
    key_path.chmod(0o644)
    monkeypatch.setenv("GPU_BURST_VAST_API_KEY_FILE", str(key_path))

    report = build_report()

    check = _check(report, "vast_api_key")
    assert check.status == "invalid"
    assert "permissions" in check.detail
    assert "secret" not in check.detail


def test_doctor_reports_ready_for_valid_local_prerequisites(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("", encoding="utf-8")
    key_path = tmp_path / "vast_api_key"
    key_path.write_text("secret", encoding="utf-8")
    key_path.chmod(0o600)
    monkeypatch.setenv("GPU_BURST_CONFIG", str(config_path))
    monkeypatch.setenv("GPU_BURST_VAST_API_KEY_FILE", str(key_path))
    monkeypatch.setattr("gpu_burst.doctor.shutil.which", lambda name: f"/tools/{name}")

    report = build_report()

    assert report.paid_runtime_ready is True
    assert exit_code(report) == 0
