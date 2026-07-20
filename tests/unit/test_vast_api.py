from __future__ import annotations

import pytest

from gpu_burst.providers.vast_api import (
    DestroyVerification,
    VastApiError,
    VastClient,
    VastInstance,
    verify_destroyed,
)


class FakeClient:
    """Scripted stand-in for VastClient list/destroy behaviour."""

    def __init__(self, snapshots: list[list[int]]):
        self.snapshots = snapshots
        self.calls = 0
        self.destroyed: list[int] = []

    def list_instances(self) -> list[VastInstance]:
        snapshot = self.snapshots[min(self.calls, len(self.snapshots) - 1)]
        self.calls += 1
        return [
            VastInstance(instance_id=i, gpu_name="RTX 4090", dph_total=0.35,
                         geolocation="US", actual_status="running")
            for i in snapshot
        ]

    def destroy_instance(self, instance_id: int) -> None:
        self.destroyed.append(instance_id)
        self.snapshots.append([i for i in self.snapshots[-1] if i != instance_id])


def no_sleep(_: float) -> None:
    return None


def test_verify_destroyed_empty_set_is_trivially_verified() -> None:
    result = verify_destroyed(FakeClient([[1]]), set(), sleeper=no_sleep)
    assert result == DestroyVerification(verified=True, escalated=False, leaked_ids=(), checks=0)


def test_verify_destroyed_passes_when_instance_gone() -> None:
    client = FakeClient([[7], []])
    result = verify_destroyed(client, {7}, attempts=4, sleeper=no_sleep)
    assert result.verified is True
    assert result.escalated is False
    assert client.destroyed == []


def test_verify_destroyed_escalates_then_verifies() -> None:
    # instance survives every poll until the escalation destroy removes it
    client = FakeClient([[7], [7], [7], [7]])
    result = verify_destroyed(client, {7}, attempts=6, sleeper=no_sleep)
    assert result.escalated is True
    assert client.destroyed == [7]
    assert result.verified is True
    assert result.leaked_ids == ()


def test_verify_destroyed_reports_leak_when_destroy_fails() -> None:
    class StubbornClient(FakeClient):
        def destroy_instance(self, instance_id: int) -> None:
            raise VastApiError("nope")

    client = StubbornClient([[7]])
    result = verify_destroyed(client, {7}, attempts=3, sleeper=no_sleep)
    assert result.verified is False
    assert result.escalated is True
    assert result.leaked_ids == (7,)


def test_verify_destroyed_ignores_unrelated_instances() -> None:
    client = FakeClient([[1, 2], [1]])
    result = verify_destroyed(client, {2}, attempts=3, sleeper=no_sleep)
    assert result.verified is True


def test_client_requires_key(tmp_path) -> None:
    with pytest.raises(VastApiError):
        VastClient(key_path=tmp_path / "missing")


def test_client_parses_instances() -> None:
    def fake_opener(request, timeout):  # noqa: ANN001
        import io

        class Resp(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        assert request.get_header("Authorization") == "Bearer k"
        return Resp(b'{"instances": [{"id": 5, "gpu_name": "RTX 4090", "dph_total": 0.3}]}')

    client = VastClient(api_key="k", opener=fake_opener)
    instances = client.list_instances()
    assert [i.instance_id for i in instances] == [5]
    assert instances[0].dph_total == 0.3
