from pathlib import Path

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
        "--down",
        "10",
        "-y",
    ]
    assert isinstance(args, list)

