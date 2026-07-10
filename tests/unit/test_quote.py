from gpu_burst.manifests import TaskSpec
from gpu_burst.quote import build_quote

from tests.unit.test_manifests import valid_task_dict


def test_quote_stays_within_budget_for_example_task() -> None:
    task = TaskSpec.model_validate(valid_task_dict())

    quote = build_quote(task)

    assert quote.workload == "song-cards"
    assert quote.backend == "fake-cloud"
    assert quote.estimated_total_usd > 0
    assert quote.estimated_total_usd <= task.budget.max_total_usd
    assert quote.valid_for_seconds == 300

