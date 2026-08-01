"""Minimal RunPod REST client used for leak detection and forced cleanup."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from gpu_burst.config import runpod_config_file


API_HOST = "https://rest.runpod.io/v1"


class RunPodApiError(RuntimeError):
    """Sanitized RunPod API failure with no response body or key material."""


@dataclass(frozen=True)
class RunPodPod:
    pod_id: str
    name: str = ""
    desired_status: str = ""
    gpu_name: str | None = None
    cost_per_hour: float | None = None
    image: str | None = None

    @classmethod
    def from_payload(cls, row: dict[str, Any]) -> "RunPodPod":
        gpu = row.get("gpu") if isinstance(row.get("gpu"), dict) else {}
        rate = row.get("adjustedCostPerHr", row.get("costPerHr"))
        try:
            parsed_rate = float(rate) if rate is not None else None
        except (TypeError, ValueError):
            parsed_rate = None
        return cls(
            pod_id=str(row.get("id", "")),
            name=str(row.get("name", "")),
            desired_status=str(row.get("desiredStatus", "")),
            gpu_name=str(gpu.get("displayName")) if gpu.get("displayName") is not None else None,
            cost_per_hour=parsed_rate,
            image=(
                str(row.get("imageName", row.get("image")))
                if row.get("imageName", row.get("image")) is not None
                else None
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "pod_id": self.pod_id,
            "name": self.name,
            "desired_status": self.desired_status,
            "gpu_name": self.gpu_name,
            "cost_per_hour": self.cost_per_hour,
            "image": self.image,
        }


@dataclass(frozen=True)
class TerminationVerification:
    verified: bool
    escalated: bool
    leaked_ids: tuple[str, ...]
    checks: int


def _key_from_toml(path: Path) -> str:
    import tomllib

    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle).get("default", {}).get("api_key", "")
    except (OSError, tomllib.TOMLDecodeError, TypeError) as exc:
        raise RunPodApiError("runpod credential file is unreadable") from exc
    key = str(value).strip()
    if not key:
        raise RunPodApiError("runpod api key is empty")
    return key


class RunPodClient:
    def __init__(
        self,
        *,
        api_key: str | None = None,
        config_path: Path | None = None,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        key = (api_key or os.environ.get("RUNPOD_API_KEY") or "").strip()
        self._api_key = key or _key_from_toml(config_path or runpod_config_file())
        self._opener = opener

    def _request(self, method: str, path: str, *, allow_404: bool = False) -> Any:
        request = urllib.request.Request(
            f"{API_HOST}{path}",
            method=method,
            headers={"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"},
        )
        try:
            with self._opener(request, timeout=15) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            if allow_404 and exc.code == 404:
                return None
            raise RunPodApiError(f"runpod api {method} {path} failed with HTTP {exc.code}") from exc
        except (OSError, urllib.error.URLError) as exc:
            raise RunPodApiError(f"runpod api {method} {path} failed: network error") from exc
        if not body:
            return None
        try:
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RunPodApiError(f"runpod api {method} {path} returned malformed JSON") from exc

    def list_pods(self) -> list[RunPodPod]:
        payload = self._request("GET", "/pods")
        rows = payload.get("pods", []) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            raise RunPodApiError("runpod api GET /pods returned malformed JSON")
        return [RunPodPod.from_payload(row) for row in rows if isinstance(row, dict) and row.get("id")]

    def terminate_pod(self, pod_id: str) -> None:
        self._request("DELETE", f"/pods/{pod_id}", allow_404=True)


def verify_terminated(
    client: RunPodClient,
    pod_ids: set[str],
    *,
    attempts: int = 6,
    interval_seconds: float = 2,
    sleeper: Callable[[float], None] = time.sleep,
) -> TerminationVerification:
    if not pod_ids:
        return TerminationVerification(True, False, (), 0)
    escalated = False
    for check in range(1, attempts + 1):
        live = {pod.pod_id for pod in client.list_pods()} & pod_ids
        if not live:
            return TerminationVerification(True, escalated, (), check)
        if not escalated and check >= max(1, attempts // 2):
            escalated = True
            for pod_id in sorted(live):
                try:
                    client.terminate_pod(pod_id)
                except RunPodApiError:
                    pass
        if check < attempts:
            sleeper(interval_seconds)
    leaked = tuple(sorted({pod.pod_id for pod in client.list_pods()} & pod_ids))
    return TerminationVerification(not leaked, escalated, leaked, attempts)
