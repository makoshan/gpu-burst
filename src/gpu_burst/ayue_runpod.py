from __future__ import annotations

import json
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PACKAGE_ID = "ayue-720p-19-jobpack"
EXPECTED_DELIVERABLE_IDS = frozenset(
    {
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
    }
)
EXPECTED_EXECUTIONS = 29
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE = re.compile(r"^[^\s@]+@sha256:[0-9a-f]{64}$")


class AyuePlanError(ValueError):
    """The requested Ayue plan is unsafe or does not match the approved scope."""


@dataclass(frozen=True)
class AyueRunPodPlan:
    package_id: str
    jobpack: Path
    image_ref: str
    deliverable_count: int
    execution_count: int
    approval_status: str
    package_fingerprint: str | None
    launch_contract_sha256: str
    max_hourly_cost_usd: float
    blockers: tuple[str, ...]
    sky_yaml: str
    bootstrap_yaml: str

    @property
    def paid_launch_allowed(self) -> bool:
        return not self.blockers

    def as_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "jobpack": str(self.jobpack),
            "image_ref": self.image_ref,
            "deliverable_count": self.deliverable_count,
            "execution_count": self.execution_count,
            "approval_status": self.approval_status,
            "package_fingerprint": self.package_fingerprint,
            "launch_contract_sha256": self.launch_contract_sha256,
            "max_hourly_cost_usd": self.max_hourly_cost_usd,
            "blockers": list(self.blockers),
            "paid_launch_allowed": self.paid_launch_allowed,
        }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AyuePlanError(f"missing jobpack file: {path.name}") from exc
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AyuePlanError(f"invalid jobpack file: {path.name}") from exc
    if not isinstance(payload, dict):
        raise AyuePlanError(f"invalid jobpack file: {path.name}")
    return payload


def _normalized_image_ref(image_ref: str) -> str:
    normalized = image_ref.removeprefix("docker:").strip()
    if not _IMAGE.fullmatch(normalized):
        raise AyuePlanError("container image must be immutable: repository@sha256:<64 lowercase hex>")
    return normalized


def _validate_structure(spec: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if spec.get("id") != PACKAGE_ID:
        raise AyuePlanError(f"jobpack id must be {PACKAGE_ID}")
    deliverables = spec.get("deliverables")
    executions = spec.get("executions")
    if not isinstance(deliverables, list) or len(deliverables) != len(EXPECTED_DELIVERABLE_IDS):
        count = len(deliverables) if isinstance(deliverables, list) else "invalid"
        raise AyuePlanError(f"jobpack must contain exactly 19 deliverables; got {count}")
    ids = {item.get("id") for item in deliverables if isinstance(item, dict)}
    if ids != EXPECTED_DELIVERABLE_IDS:
        missing = sorted(EXPECTED_DELIVERABLE_IDS - ids)
        unexpected = sorted(item for item in ids - EXPECTED_DELIVERABLE_IDS if isinstance(item, str))
        raise AyuePlanError(f"19-deliverable scope mismatch; missing={missing} unexpected={unexpected}")
    if not isinstance(executions, list) or len(executions) != EXPECTED_EXECUTIONS:
        count = len(executions) if isinstance(executions, list) else "invalid"
        raise AyuePlanError(f"jobpack must contain exactly 29 executions; got {count}")
    target = spec.get("target")
    if target != {"width": 720, "height": 1280, "fps": 25}:
        raise AyuePlanError("jobpack target must be exactly 720x1280 at 25 fps")
    return deliverables, executions


def _paid_blockers(
    spec: dict[str, Any],
    weights: dict[str, Any],
    approval: dict[str, Any],
    *,
    image_ref: str,
    launch_contract_sha256: str,
    manifest_blockers: tuple[str, ...],
) -> tuple[str, ...]:
    blockers = list(manifest_blockers)
    spec_approval = spec.get("approval") if isinstance(spec.get("approval"), dict) else {}
    approval_status = str(approval.get("status", "missing"))
    if (
        approval_status != "approved"
        or spec_approval.get("status") != "approved"
        or spec_approval.get("launch_allowed") is not True
    ):
        blockers.append("approval is not approved and launch_allowed")
    fingerprint = approval.get("package_fingerprint")
    if not isinstance(fingerprint, str) or not _SHA256.fullmatch(fingerprint):
        blockers.append("approval package fingerprint is not locked to SHA-256")
    if approval.get("provider") != "runpod":
        blockers.append("approval is not bound to provider runpod")
    if approval.get("image_ref") != image_ref:
        blockers.append("approval is not bound to the immutable RunPod image")
    if approval.get("launch_contract_sha256") != launch_contract_sha256:
        blockers.append("approval is not bound to the RunPod launch contract SHA-256")

    items = weights.get("weights")
    if not isinstance(items, list) or not items:
        blockers.append("weights.lock.json has no weights")
    else:
        unlocked = [
            str(item.get("destination", f"item-{index}"))
            for index, item in enumerate(items)
            if not isinstance(item, dict)
            or not isinstance(item.get("sha256"), str)
            or not _SHA256.fullmatch(item["sha256"])
        ]
        if unlocked:
            blockers.append(f"weight SHA-256 values are missing or invalid: {', '.join(unlocked)}")
    wav2vec = weights.get("wav2vec")
    revision = wav2vec.get("revision") if isinstance(wav2vec, dict) else None
    if not isinstance(revision, str) or not revision.strip():
        blockers.append("wav2vec immutable revision is missing")
    return tuple(blockers)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest_status(jobpack: Path, approval: dict[str, Any]) -> tuple[str | None, tuple[str, ...]]:
    manifest_path = jobpack / "package-manifest.json"
    try:
        manifest = _load_json(manifest_path)
    except AyuePlanError as exc:
        return None, (str(exc),)
    bound = {
        "files": manifest.get("files"),
        "external_bindings": manifest.get("external_bindings"),
        "launch_command": manifest.get("launch_command"),
    }
    computed = hashlib.sha256(
        json.dumps(bound, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    blockers: list[str] = []
    declared = manifest.get("fingerprint")
    if declared != computed:
        blockers.append("package manifest fingerprint mismatch")
    if approval.get("package_fingerprint") != computed:
        blockers.append("approval package fingerprint is stale")

    for key, root in (("files", jobpack), ("external_bindings", jobpack.parents[1])):
        items = manifest.get(key)
        if not isinstance(items, list):
            blockers.append(f"package manifest {key} is invalid")
            continue
        root = root.resolve()
        for index, item in enumerate(items):
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                blockers.append(f"package manifest {key}[{index}] is invalid")
                continue
            candidate = (root / item["path"]).resolve()
            if not candidate.is_relative_to(root):
                blockers.append(f"package manifest path escapes root: {item['path']}")
                continue
            expected = item.get("sha256")
            if not candidate.is_file():
                blockers.append(f"package manifest file is missing: {item['path']}")
            elif not isinstance(expected, str) or not _SHA256.fullmatch(expected):
                blockers.append(f"package manifest SHA-256 is invalid: {item['path']}")
            elif _sha256_file(candidate) != expected:
                blockers.append(f"package manifest SHA-256 mismatch: {item['path']}")
    return computed, tuple(blockers)


def _launch_contract_sha256(
    image_ref: str, package_fingerprint: str | None, max_hourly_cost_usd: float
) -> str:
    contract = {
        "provider": "runpod",
        "image_ref": image_ref,
        "gpu": "RTX4090:1",
        "minimum_nvidia_driver_major": 580,
        "disk_size_gb": 80,
        "use_spot": False,
        "maximum_usd_per_hour": max_hourly_cost_usd,
        "package_id": PACKAGE_ID,
        "package_fingerprint": package_fingerprint,
        "deliverables": len(EXPECTED_DELIVERABLE_IDS),
        "executions": EXPECTED_EXECUTIONS,
    }
    return hashlib.sha256(
        json.dumps(contract, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _render_yaml(jobpack: Path, image_ref: str) -> str:
    jobpack_json = json.dumps(str(jobpack), ensure_ascii=False)
    return f"""# Generated by gpu-burst. Do not hand-edit or launch without the paid gates.
resources:
  cloud: runpod
  accelerators: RTX4090:1
  image_id: docker:{image_ref}
  disk_size: 80
  use_spot: false

envs:
  R2_ENDPOINT: https://1df50a43697ddc762baf3b76d1dc9ef1.r2.cloudflarestorage.com
  R2_CACHE: gpu-burst-cache
  R2_JOBS: gpu-burst-jobs

file_mounts:
  /job: {jobpack_json}
  /root/.aws/credentials: ~/.config/gpu-burst/r2-credentials

setup: |
  set -euo pipefail
  DRIVER_MAJOR="$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 | cut -d. -f1)"
  test "$DRIVER_MAJOR" -ge 580 || {{ echo "DRIVER-TOO-OLD: $DRIVER_MAJOR < 580" >&2; exit 47; }}
  test -d /root/ComfyUI
  command -v s5cmd >/dev/null
  command -v ffprobe >/dev/null
  python3 /job/verify_package.py /job
  bash /job/fetch_weights.sh
  python3 -c 'import hashlib,json,pathlib; lock=json.load(open("/job/weights.lock.json")); root=pathlib.Path("/root/ComfyUI/models"); [(lambda p,w: (_ for _ in ()).throw(SystemExit("weight SHA-256 mismatch: "+w["destination"])) if hashlib.file_digest(p.open("rb"),"sha256").hexdigest()!=w["sha256"] else None)(root/w["destination"],w) for w in lock["weights"]]'

run: |
  set -euo pipefail
  mkdir -p /job/results
  cd /root/ComfyUI
  python main.py --listen 127.0.0.1 --port 8188 > /job/results/comfyui.log 2>&1 &
  cp /job/inputs/* /root/ComfyUI/input/
  python3 /job/wait_comfy_ready.py
  python3 /job/queue_all.py --stage sources
  python3 /job/queue_all.py --stage finals
  python3 /job/collect_outputs.py
  s5cmd --endpoint-url "$R2_ENDPOINT" cp '/job/results/*' "s3://$R2_JOBS/ayue-720p-19-$(date +%Y%m%d-%H%M%S)/"
"""


def _render_bootstrap_yaml(image_ref: str) -> str:
    return f"""# Provision only; gpu-burst checks the observed Pod rate before the workload runs.
resources:
  cloud: runpod
  accelerators: RTX4090:1
  image_id: docker:{image_ref}
  disk_size: 80
  use_spot: false

run: |
  set -euo pipefail
  nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
"""


def build_ayue_runpod_plan(
    jobpack: Path,
    image_ref: str,
    *,
    allow_pending: bool = False,
    max_hourly_cost_usd: float = 0.75,
) -> AyueRunPodPlan:
    if max_hourly_cost_usd <= 0:
        raise AyuePlanError("maximum hourly cost must be greater than zero")
    resolved = jobpack.expanduser().resolve()
    if not resolved.is_dir():
        raise AyuePlanError(f"jobpack directory does not exist: {resolved}")
    image = _normalized_image_ref(image_ref)
    spec = _load_json(resolved / "package-spec.json")
    weights = _load_json(resolved / "weights.lock.json")
    approval = _load_json(resolved / "approval.json")
    deliverables, executions = _validate_structure(spec)
    package_fingerprint, manifest_blockers = _manifest_status(resolved, approval)
    launch_contract_sha256 = _launch_contract_sha256(
        image, package_fingerprint, max_hourly_cost_usd
    )
    blockers = _paid_blockers(
        spec,
        weights,
        approval,
        image_ref=image,
        launch_contract_sha256=launch_contract_sha256,
        manifest_blockers=manifest_blockers,
    )
    if blockers and not allow_pending:
        raise AyuePlanError("paid launch blocked: " + "; ".join(blockers))
    return AyueRunPodPlan(
        package_id=PACKAGE_ID,
        jobpack=resolved,
        image_ref=image,
        deliverable_count=len(deliverables),
        execution_count=len(executions),
        approval_status=str(approval.get("status", "missing")),
        package_fingerprint=package_fingerprint,
        launch_contract_sha256=launch_contract_sha256,
        max_hourly_cost_usd=max_hourly_cost_usd,
        blockers=blockers,
        sky_yaml=_render_yaml(resolved, image),
        bootstrap_yaml=_render_bootstrap_yaml(image),
    )
