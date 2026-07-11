from gpu_burst.config import Settings, load_settings


def test_load_settings_uses_defaults_when_config_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GPU_BURST_CONFIG", str(tmp_path / "missing.toml"))

    settings = load_settings()

    assert settings.provider.vast.datacenter_only is True
    assert settings.provider.vast.max_hourly_cost_usd == 0.80
    assert settings.safety.autodown_idle_minutes == 10


def test_load_settings_reads_toml_override(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[provider.vast]
datacenter_only = false
max_hourly_cost_usd = 0.55
default_gpu = "RTX4090"

[safety]
autodown_idle_minutes = 7
watchdog_interval_minutes = 3
max_unverified_age_minutes = 11
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("GPU_BURST_CONFIG", str(config_path))

    settings = load_settings()

    assert settings.provider.vast.datacenter_only is False
    assert settings.provider.vast.max_hourly_cost_usd == 0.55
    assert settings.safety.autodown_idle_minutes == 7

