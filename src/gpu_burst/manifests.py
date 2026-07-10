from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}$")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _is_safe_relative_path(value: str) -> bool:
    if value.startswith("/") or "\x00" in value:
        return False
    path = PurePosixPath(value)
    return all(part not in {"", ".", ".."} for part in path.parts)


class RuntimeSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workload_repo: str
    workload_commit: str
    image_digest: str
    workflow_digest: str
    model_manifest_digest: str

    @field_validator("workload_repo")
    @classmethod
    def validate_repo(cls, value: str) -> str:
        if value != "makoshan/comfy-batch":
            raise ValueError("only makoshan/comfy-batch is supported")
        return value


class ResourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gpu: str
    gpu_count: int = Field(ge=1, le=1)
    min_gpu_memory_gb: int = Field(ge=1)
    min_system_memory_gb: int = Field(ge=1)
    disk_gb: int = Field(ge=20)
    datacenter_only: bool
    max_hourly_cost_usd: float = Field(gt=0)


class BudgetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_total_usd: float = Field(gt=0)
    max_wall_seconds: int = Field(gt=0)


class ItemSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    prompt: str = Field(min_length=1)
    seed: int
    required: bool = True
    output_key: str

    @field_validator("item_id")
    @classmethod
    def validate_item_id(cls, value: str) -> str:
        if not SAFE_ID_RE.match(value):
            raise ValueError("unsafe item_id")
        return value

    @field_validator("output_key")
    @classmethod
    def validate_output_key(cls, value: str) -> str:
        if not _is_safe_relative_path(value):
            raise ValueError("unsafe path")
        return value


class TaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    workload: Literal["song-cards"]
    profile: Literal["fast", "quality", "style"]
    runtime: RuntimeSpec
    resources: ResourceSpec
    budget: BudgetSpec
    items: list[ItemSpec] = Field(min_length=1)

    @field_validator("items")
    @classmethod
    def validate_unique_items(cls, value: list[ItemSpec]) -> list[ItemSpec]:
        item_ids = [item.item_id for item in value]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("duplicate item_id")
        if not any(item.required for item in value):
            raise ValueError("at least one required item is required")
        return value


def item_key(task: TaskSpec, item: ItemSpec) -> str:
    payload = {
        "workload": task.workload,
        "item": item.model_dump(mode="json"),
        "workload_commit": task.runtime.workload_commit,
        "image_digest": task.runtime.image_digest,
        "workflow_digest": task.runtime.workflow_digest,
        "model_manifest_digest": task.runtime.model_manifest_digest,
    }
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def validate_for_run(task: TaskSpec, *, dry_run: bool) -> None:
    if task.profile != "fast":
        raise ValueError("only the fast profile is allowed in Phase 1")
    if not dry_run:
        digests = [
            task.runtime.image_digest,
            task.runtime.workflow_digest,
            task.runtime.model_manifest_digest,
        ]
        if any("example-" in digest for digest in digests):
            raise ValueError("placeholder runtime digest is not allowed for paid run")


def load_task_json(path) -> TaskSpec:
    return TaskSpec.model_validate_json(path.read_text(encoding="utf-8"))

