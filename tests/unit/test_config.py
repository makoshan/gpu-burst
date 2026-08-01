from gpu_burst.config import Settings, load_settings


def test_load_settings_uses_defaults_when_config_missing(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GPU_BURST_CONFIG", str(tmp_path / "missing.toml"))

    settings = load_settings()

    assert settings.provider.vast.datacenter_only is True
    assert settings.provider.vast.max_hourly_cost_usd == 0.80
    assert settings.safety.autodown_idle_minutes == 10


def test_load_settings_can_select_runpod_without_changing_vast_defaults(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("GPU_BURST_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.setenv("GPU_BURST_PROVIDER", "runpod")

    settings = load_settings()

    assert settings.provider.active == "runpod"
    assert settings.provider.runpod.cloud_type == "COMMUNITY"
    assert settings.provider.runpod.default_gpu == "RTX4090"
    assert settings.provider.runpod.max_hourly_cost_usd == 0.75
    assert settings.provider.vast.default_gpu == "RTX4090"


def test_runpod_config_file_supports_override(tmp_path, monkeypatch) -> None:
    from gpu_burst.config import runpod_config_file

    path = tmp_path / "runpod.toml"
    monkeypatch.setenv("GPU_BURST_RUNPOD_CONFIG_FILE", str(path))

    assert runpod_config_file() == path


def test_invalid_provider_environment_override_is_rejected(tmp_path, monkeypatch) -> None:
    import pytest
    from pydantic import ValidationError

    monkeypatch.setenv("GPU_BURST_CONFIG", str(tmp_path / "missing.toml"))
    monkeypatch.setenv("GPU_BURST_PROVIDER", "not-a-provider")

    with pytest.raises(ValidationError):
        load_settings()


def test_load_settings_reads_toml_override(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[provider.vast]
datacenter_only = false
max_hourly_cost_usd = 0.55
default_gpu = "RTX4090"

[provider.runpod]
cloud_type = "SECURE"
max_hourly_cost_usd = 0.90
default_gpu = "NVIDIA GeForce RTX 4090"
allowed_cuda_versions = ["13.0"]

[storage]
cache_bucket = "gpu-burst-cache-dev"
jobs_bucket = "gpu-burst-jobs-dev"
endpoint = "https://example.r2.cloudflarestorage.com"
aws_profile = "gpu-burst-r2-dev"

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
    assert settings.provider.runpod.cloud_type == "SECURE"
    assert settings.provider.runpod.allowed_cuda_versions == ["13.0"]
    assert settings.storage.cache_bucket == "gpu-burst-cache-dev"
    assert settings.storage.jobs_bucket == "gpu-burst-jobs-dev"
    assert settings.storage.endpoint == "https://example.r2.cloudflarestorage.com"
    assert settings.storage.aws_profile == "gpu-burst-r2-dev"
    assert settings.safety.autodown_idle_minutes == 7
