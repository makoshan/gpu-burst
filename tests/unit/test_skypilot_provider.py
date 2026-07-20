from pathlib import Path
from subprocess import CompletedProcess

import pytest

from gpu_burst.providers import skypilot
from gpu_burst.providers.skypilot import SkyLaunchPlan


def test_sky_launch_plan_uses_argument_array_and_remote_autodown() -> None:
    plan = SkyLaunchPlan(
        cluster_name="gb-hello-world-a1b2c3",
        task_file=Path("sky/hello-world.yaml"),
        autodown_idle_minutes=10,
    )

    args = plan.launch_args()

    assert args == [
        "sky",
        "launch",
        "-c",
        "gb-hello-world-a1b2c3",
        "sky/hello-world.yaml",
        "--idle-minutes-to-autostop",
        "10",
        "--down",
        "-y",
    ]
    assert isinstance(args, list)


def test_execute_sky_launch_always_tears_down_after_success() -> None:
    plan = SkyLaunchPlan("gb-test", Path("sky/hello-world.yaml"), 10)
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(args)
        return CompletedProcess(args, 0, stdout="ok", stderr="")

    skypilot.execute_sky_launch(plan, runner=runner)

    assert calls == [plan.launch_args(), plan.down_args()]


def test_execute_sky_launch_notifies_before_teardown() -> None:
    plan = SkyLaunchPlan("gb-test", Path("sky/hello-world.yaml"), 10)
    order: list[str] = []

    def runner(args, **kwargs):
        order.append(args[1])
        return CompletedProcess(args, 0, stdout="", stderr="")

    skypilot.execute_sky_launch(plan, runner=runner, on_teardown=lambda: order.append("callback"))

    assert order == ["launch", "callback", "down"]


def test_execute_sky_launch_attempts_teardown_when_launch_fails() -> None:
    plan = SkyLaunchPlan("gb-test", Path("sky/hello-world.yaml"), 10)
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(args)
        return CompletedProcess(args, 1 if args[1] == "launch" else 0, stdout="", stderr="secret remote detail")

    with pytest.raises(skypilot.SkyExecutionError, match="sky launch failed") as exc_info:
        skypilot.execute_sky_launch(plan, runner=runner)

    assert "secret remote detail" not in str(exc_info.value)
    assert calls == [plan.launch_args(), plan.down_args()]


def test_execute_sky_launch_reports_teardown_failure() -> None:
    plan = SkyLaunchPlan("gb-test", Path("sky/hello-world.yaml"), 10)

    def runner(args, **kwargs):
        return CompletedProcess(args, 0 if args[1] == "launch" else 1, stdout="", stderr="provider detail")

    with pytest.raises(skypilot.SkyExecutionError, match="sky down failed") as exc_info:
        skypilot.execute_sky_launch(plan, runner=runner)

    assert "provider detail" not in str(exc_info.value)


def test_execute_sky_launch_sanitizes_runner_exception_and_still_tears_down() -> None:
    plan = SkyLaunchPlan("gb-test", Path("sky/hello-world.yaml"), 10)
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(args)
        if args[1] == "launch":
            raise OSError("secret executable detail")
        return CompletedProcess(args, 0, stdout="", stderr="")

    with pytest.raises(skypilot.SkyExecutionError, match="sky launch could not start") as exc_info:
        skypilot.execute_sky_launch(plan, runner=runner)

    assert "secret executable detail" not in str(exc_info.value)
    assert calls == [plan.launch_args(), plan.down_args()]


def test_execute_sky_launch_calls_on_launched_between_launch_and_teardown() -> None:
    plan = SkyLaunchPlan("gb-test", Path("sky/hello-world.yaml"), 10)
    order: list[str] = []

    def runner(args, **kwargs):
        order.append(args[1])
        return CompletedProcess(args, 0, stdout="", stderr="")

    skypilot.execute_sky_launch(
        plan,
        runner=runner,
        on_launched=lambda: order.append("observe"),
        on_teardown=lambda: order.append("teardown"),
    )

    assert order == ["launch", "observe", "teardown", "down"]


def test_execute_sky_launch_calls_on_launched_even_when_launch_fails() -> None:
    plan = SkyLaunchPlan("gb-test", Path("sky/hello-world.yaml"), 10)
    observed: list[str] = []

    def runner(args, **kwargs):
        return CompletedProcess(args, 1 if args[1] == "launch" else 0, stdout="", stderr="")

    with pytest.raises(skypilot.SkyExecutionError, match="sky launch failed"):
        skypilot.execute_sky_launch(plan, runner=runner, on_launched=lambda: observed.append("observe"))

    assert observed == ["observe"]


def test_execute_sky_launch_sanitizes_on_launched_failure_and_still_tears_down() -> None:
    plan = SkyLaunchPlan("gb-test", Path("sky/hello-world.yaml"), 10)
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(args)
        return CompletedProcess(args, 0, stdout="", stderr="")

    def fail_observation():
        raise OSError("secret api detail")

    with pytest.raises(skypilot.SkyExecutionError, match="post-launch observation failed") as exc_info:
        skypilot.execute_sky_launch(plan, runner=runner, on_launched=fail_observation)

    assert "secret api detail" not in str(exc_info.value)
    assert calls == [plan.launch_args(), plan.down_args()]


def test_execute_sky_launch_still_tears_down_when_callback_fails() -> None:
    plan = SkyLaunchPlan("gb-test", Path("sky/hello-world.yaml"), 10)
    calls: list[list[str]] = []

    def runner(args, **kwargs):
        calls.append(args)
        return CompletedProcess(args, 0, stdout="", stderr="")

    def fail_callback():
        raise OSError("secret ledger detail")

    with pytest.raises(skypilot.SkyExecutionError, match="teardown state update failed") as exc_info:
        skypilot.execute_sky_launch(plan, runner=runner, on_teardown=fail_callback)

    assert "secret ledger detail" not in str(exc_info.value)
    assert calls == [plan.launch_args(), plan.down_args()]
