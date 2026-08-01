from __future__ import annotations

import importlib
import io
import urllib.error


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def runpod_api():
    return importlib.import_module("gpu_burst.providers.runpod_api")


def no_sleep(_: float) -> None:
    return None


def test_client_parses_runpod_pods_and_uses_bearer_auth() -> None:
    module = runpod_api()

    def opener(request, timeout):  # noqa: ANN001
        assert request.full_url == "https://rest.runpod.io/v1/pods"
        assert request.get_header("Authorization") == "Bearer test-key"
        return Response(
            b'[{"id":"pod-1","name":"gb-ayue-head","desiredStatus":"RUNNING",'
            b'"adjustedCostPerHr":0.69,"imageName":"repo/image@sha256:abc",'
            b'"gpu":{"displayName":"NVIDIA GeForce RTX 4090"}}]'
        )

    pods = module.RunPodClient(api_key="test-key", opener=opener).list_pods()

    assert [pod.pod_id for pod in pods] == ["pod-1"]
    assert pods[0].name == "gb-ayue-head"
    assert pods[0].gpu_name == "NVIDIA GeForce RTX 4090"
    assert pods[0].cost_per_hour == 0.69
    assert pods[0].image == "repo/image@sha256:abc"


def test_terminate_pod_treats_404_as_already_gone() -> None:
    module = runpod_api()

    def opener(request, timeout):  # noqa: ANN001
        raise urllib.error.HTTPError(request.full_url, 404, "not found", {}, None)

    module.RunPodClient(api_key="test-key", opener=opener).terminate_pod("pod-gone")


def test_verify_terminated_escalates_delete_then_passes() -> None:
    module = runpod_api()

    class FakeClient:
        def __init__(self):
            self.snapshots = [["pod-1"], ["pod-1"], []]
            self.deleted = []

        def list_pods(self):
            ids = self.snapshots.pop(0) if len(self.snapshots) > 1 else self.snapshots[0]
            return [module.RunPodPod(pod_id=value, name="job", desired_status="RUNNING") for value in ids]

        def terminate_pod(self, pod_id):
            self.deleted.append(pod_id)

    client = FakeClient()
    result = module.verify_terminated(client, {"pod-1"}, attempts=3, sleeper=no_sleep)

    assert result.verified is True
    assert result.escalated is True
    assert result.leaked_ids == ()
    assert client.deleted == ["pod-1"]


def test_api_errors_never_include_key_or_response_body() -> None:
    module = runpod_api()

    def opener(request, timeout):  # noqa: ANN001
        raise urllib.error.HTTPError(
            request.full_url,
            401,
            "unauthorized test-key provider-detail",
            {},
            io.BytesIO(b"test-key provider body"),
        )

    client = module.RunPodClient(api_key="test-key", opener=opener)
    try:
        client.list_pods()
    except module.RunPodApiError as exc:
        assert "test-key" not in str(exc)
        assert "provider-detail" not in str(exc)
        assert "HTTP 401" in str(exc)
    else:
        raise AssertionError("expected RunPodApiError")
