import tomllib


def test_write_runpod_config_is_private_and_toml_parseable(tmp_path) -> None:
    from gpu_burst.credentials import write_runpod_config

    path = tmp_path / ".runpod" / "config.toml"
    write_runpod_config("rpa_test_only", path)

    assert path.stat().st_mode & 0o777 == 0o600
    with path.open("rb") as handle:
        assert tomllib.load(handle) == {"default": {"api_key": "rpa_test_only"}}


def test_write_runpod_config_rejects_empty_key(tmp_path) -> None:
    import pytest

    from gpu_burst.credentials import write_runpod_config

    with pytest.raises(ValueError, match="RunPod API key is empty"):
        write_runpod_config("  ", tmp_path / "config.toml")
