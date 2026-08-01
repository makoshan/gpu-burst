import json
import hashlib
from pathlib import Path

import pytest


DELIVERABLE_IDS = [
    "scene-membership-speaking",
    "scene-membership-listening",
    "scene-membership-feedback",
    "scene-price-speaking",
    "scene-price-listening",
    "scene-price-feedback",
    "scene-terminal-failure-speaking",
    "scene-terminal-failure-listening",
    "scene-terminal-failure-feedback",
    "scene-bag-speaking",
    "scene-bag-listening",
    "scene-bag-feedback",
    "scene-payment-speaking",
    "scene-payment-feedback",
    "teaching-answer-line-02",
    "teaching-answer-line-04",
    "teaching-answer-line-06",
    "teaching-answer-line-07",
    "teaching-answer-line-09",
]


def _write_jobpack(path: Path, *, approved: bool = False, image: str | None = None) -> Path:
    path.mkdir()
    approval_status = "approved" if approved else "pending"
    spec = {
        "id": "ayue-720p-19-jobpack",
        "target": {"width": 720, "height": 1280, "fps": 25},
        "deliverables": [{"id": item} for item in DELIVERABLE_IDS],
        "executions": [{"id": f"exec-{index}"} for index in range(29)],
        "approval": {
            "status": approval_status,
            "launch_allowed": approved,
        },
    }
    weights = {
        "wav2vec": {"repository": "example/wav2vec", "revision": "abc123" if approved else None},
        "weights": [
            {
                "destination": f"models/model-{index}.safetensors",
                "sha256": str(index) * 64 if approved else None,
            }
            for index in range(6)
        ],
    }
    manifest_bound = {"files": [], "external_bindings": [], "launch_command": []}
    package_fingerprint = hashlib.sha256(
        json.dumps(manifest_bound, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    manifest = {
        "package_id": "ayue-720p-19-jobpack",
        **manifest_bound,
        "fingerprint": package_fingerprint,
    }
    approval = {
        "status": approval_status,
        "package_fingerprint": package_fingerprint,
    }
    (path / "package-spec.json").write_text(json.dumps(spec), encoding="utf-8")
    (path / "weights.lock.json").write_text(json.dumps(weights), encoding="utf-8")
    (path / "approval.json").write_text(json.dumps(approval), encoding="utf-8")
    (path / "package-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name in (
        "verify_package.py",
        "fetch_weights.sh",
        "wait_comfy_ready.py",
        "queue_all.py",
        "collect_outputs.py",
    ):
        (path / name).write_text("# test fixture\n", encoding="utf-8")
    return path


def test_pending_19_jobpack_can_render_free_runpod_plan_with_paid_blockers(tmp_path) -> None:
    from gpu_burst.ayue_runpod import build_ayue_runpod_plan

    jobpack = _write_jobpack(tmp_path / "jobpack")
    image = "registry.example/ayue@sha256:" + "a" * 64

    plan = build_ayue_runpod_plan(jobpack, image, allow_pending=True)

    assert plan.deliverable_count == 19
    assert plan.execution_count == 29
    assert plan.paid_launch_allowed is False
    assert any("approval" in blocker for blocker in plan.blockers)
    assert any("SHA-256" in blocker for blocker in plan.blockers)
    assert any("wav2vec" in blocker for blocker in plan.blockers)
    assert "cloud: runpod" in plan.sky_yaml
    assert f"image_id: docker:{image}" in plan.sky_yaml
    assert "accelerators: RTX4090:1" in plan.sky_yaml
    assert f'  /job: "{jobpack.resolve()}"' in plan.sky_yaml
    setup = plan.sky_yaml.split("setup: |", 1)[1].split("run: |", 1)[0]
    assert "pip install" not in setup
    assert "git clone" not in setup
    assert "apt-get" not in setup
    assert "fetch_weights.sh" in setup
    assert "hashlib.file_digest" in setup
    assert "read_bytes" not in setup
    assert "DRIVER-TOO-OLD" in setup
    assert "580" in setup
    assert "cloud: runpod" in plan.bootstrap_yaml
    assert f"image_id: docker:{image}" in plan.bootstrap_yaml
    assert "setup:" not in plan.bootstrap_yaml
    assert "fetch_weights" not in plan.bootstrap_yaml


def test_mutable_container_tag_is_rejected_even_for_free_plan(tmp_path) -> None:
    from gpu_burst.ayue_runpod import AyuePlanError, build_ayue_runpod_plan

    jobpack = _write_jobpack(tmp_path / "jobpack")

    with pytest.raises(AyuePlanError, match="immutable.*sha256"):
        build_ayue_runpod_plan(jobpack, "registry.example/ayue:latest", allow_pending=True)


def test_wrong_or_old_jobpack_scope_is_rejected(tmp_path) -> None:
    from gpu_burst.ayue_runpod import AyuePlanError, build_ayue_runpod_plan

    jobpack = _write_jobpack(tmp_path / "jobpack")
    spec_path = jobpack / "package-spec.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    spec["deliverables"].append({"id": "scene-payment-listening"})
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    with pytest.raises(AyuePlanError, match="exactly 19"):
        build_ayue_runpod_plan(
            jobpack,
            "registry.example/ayue@sha256:" + "b" * 64,
            allow_pending=True,
        )


def test_paid_plan_refuses_pending_approval_and_unlocked_weights(tmp_path) -> None:
    from gpu_burst.ayue_runpod import AyuePlanError, build_ayue_runpod_plan

    jobpack = _write_jobpack(tmp_path / "jobpack")

    with pytest.raises(AyuePlanError, match="paid launch blocked"):
        build_ayue_runpod_plan(
            jobpack,
            "registry.example/ayue@sha256:" + "c" * 64,
            allow_pending=False,
        )


def test_approved_locked_19_jobpack_is_paid_launch_ready(tmp_path) -> None:
    from gpu_burst.ayue_runpod import build_ayue_runpod_plan

    image = "registry.example/ayue@sha256:" + "d" * 64
    jobpack = _write_jobpack(tmp_path / "jobpack", approved=True)
    preview = build_ayue_runpod_plan(jobpack, image, allow_pending=True)
    approval_path = jobpack / "approval.json"
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    approval.update(
        {
            "provider": "runpod",
            "image_ref": image,
            "launch_contract_sha256": preview.launch_contract_sha256,
        }
    )
    approval_path.write_text(json.dumps(approval), encoding="utf-8")

    plan = build_ayue_runpod_plan(
        jobpack,
        image,
        allow_pending=False,
    )

    assert plan.paid_launch_allowed is True
    assert plan.blockers == ()
    assert "python3 /job/verify_package.py /job" in plan.sky_yaml
    assert "queue_all.py --stage sources" in plan.sky_yaml
    assert "queue_all.py --stage finals" in plan.sky_yaml
    assert "collect_outputs.py" in plan.sky_yaml
