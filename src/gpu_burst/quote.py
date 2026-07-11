from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from gpu_burst.manifests import TaskSpec


class QuoteEstimate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workload: str
    backend: str
    gpu: str
    item_count: int
    estimated_total_usd: float
    budget_usd: float
    estimated_wall_seconds: int
    valid_for_seconds: int
    assumptions: list[str]


def build_quote(task: TaskSpec) -> QuoteEstimate:
    item_seconds = 45
    startup_seconds = 420
    teardown_seconds = 120
    wall_seconds = startup_seconds + teardown_seconds + len(task.items) * item_seconds
    compute = task.resources.max_hourly_cost_usd * (wall_seconds / 3600)
    disk = 0.02 * (task.resources.disk_gb / 80)
    network = 0.03 + len(task.items) * 0.005
    r2 = 0.01
    estimate = round(compute + disk + network + r2, 4)

    return QuoteEstimate(
        workload=task.workload,
        backend="fake-cloud",
        gpu=task.resources.gpu,
        item_count=len(task.items),
        estimated_total_usd=estimate,
        budget_usd=task.budget.max_total_usd,
        estimated_wall_seconds=wall_seconds,
        valid_for_seconds=300,
        assumptions=[
            "Phase 1 estimate only; no Vast offer is reserved.",
            "Uses configured max hourly cost as the compute ceiling.",
            "R2 and network costs are placeholders until live billing exists.",
        ],
    )

