import pytest
from pydantic import ValidationError

from gpu_burst.manifests import TaskSpec, item_key, validate_for_run


def valid_task_dict() -> dict:
    return {
        "schema_version": 1,
        "workload": "song-cards",
        "profile": "fast",
        "runtime": {
            "workload_repo": "makoshan/comfy-batch",
            "workload_commit": "61db1c4840e739516647fce867e44a4ef563baff",
            "image_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "workflow_digest": "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            "model_manifest_digest": "sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
        },
        "resources": {
            "gpu": "RTX4090",
            "gpu_count": 1,
            "min_gpu_memory_gb": 24,
            "min_system_memory_gb": 32,
            "disk_gb": 80,
            "datacenter_only": True,
            "max_hourly_cost_usd": 0.80,
        },
        "budget": {
            "max_total_usd": 3.00,
            "max_wall_seconds": 1800,
        },
        "items": [
            {
                "item_id": "song-card-0001",
                "prompt": "A flat screen-print illustration on a simple blue background.",
                "seed": 42,
                "required": True,
                "output_key": "items/song-card-0001.png",
            }
        ],
    }


def test_task_spec_accepts_valid_song_cards_task() -> None:
    task = TaskSpec.model_validate(valid_task_dict())

    assert task.workload == "song-cards"
    assert task.items[0].item_id == "song-card-0001"


def test_task_spec_rejects_missing_required_item() -> None:
    raw = valid_task_dict()
    raw["items"][0]["required"] = False

    with pytest.raises(ValidationError, match="at least one required item"):
        TaskSpec.model_validate(raw)


def test_task_spec_rejects_path_traversal_output_key() -> None:
    raw = valid_task_dict()
    raw["items"][0]["output_key"] = "../items/song-card-0001.png"

    with pytest.raises(ValidationError, match="unsafe path"):
        TaskSpec.model_validate(raw)


def test_task_spec_rejects_non_fast_profile_for_run() -> None:
    raw = valid_task_dict()
    raw["profile"] = "quality"
    task = TaskSpec.model_validate(raw)

    with pytest.raises(ValueError, match="only the fast profile"):
        validate_for_run(task, dry_run=True)


def test_validate_for_run_rejects_example_digest_for_paid_run() -> None:
    raw = valid_task_dict()
    raw["runtime"]["image_digest"] = "sha256:example-image-digest"
    task = TaskSpec.model_validate(raw)

    validate_for_run(task, dry_run=True)
    with pytest.raises(ValueError, match="placeholder runtime digest"):
        validate_for_run(task, dry_run=False)


def test_item_key_is_stable_and_sensitive_to_prompt_changes() -> None:
    task = TaskSpec.model_validate(valid_task_dict())
    first = item_key(task, task.items[0])
    second = item_key(task, task.items[0])

    changed = valid_task_dict()
    changed["items"][0]["prompt"] = "A different prompt."
    changed_task = TaskSpec.model_validate(changed)

    assert first == second
    assert first.startswith("sha256:")
    assert first != item_key(changed_task, changed_task.items[0])

