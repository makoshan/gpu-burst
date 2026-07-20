"""Minimal read/destroy client for the Vast.ai HTTP API.

Used for post-teardown destroy verification and billing reconciliation.
Stdlib-only on purpose: this must work even when SkyPilot is broken.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

API_HOST = "https://console.vast.ai"
API_BASE = f"{API_HOST}/api/v0"  # users/current still lives here
API_BASE_V1 = f"{API_HOST}/api/v1"  # instances moved here (v0 returns 410 Gone)
DEFAULT_KEY_PATH = Path.home() / ".config" / "vastai" / "vast_api_key"


class VastApiError(RuntimeError):
    """Sanitized Vast API failure (no key material in the message)."""


@dataclass(frozen=True)
class VastInstance:
    instance_id: int
    gpu_name: str | None
    dph_total: float | None
    geolocation: str | None
    actual_status: str | None
    label: str | None = None

    @classmethod
    def from_payload(cls, row: dict[str, Any]) -> "VastInstance":
        return cls(
            instance_id=int(row["id"]),
            gpu_name=row.get("gpu_name"),
            dph_total=row.get("dph_total"),
            geolocation=row.get("geolocation"),
            actual_status=row.get("actual_status"),
            label=row.get("label"),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "gpu_name": self.gpu_name,
            "dph_total": self.dph_total,
            "geolocation": self.geolocation,
            "actual_status": self.actual_status,
            "label": self.label,
        }


class VastClient:
    def __init__(self, api_key: str | None = None, *, key_path: Path = DEFAULT_KEY_PATH,
                 opener: Callable[..., Any] | None = None):
        if api_key is None:
            try:
                api_key = key_path.read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise VastApiError("vast api key file is not readable") from exc
        if not api_key:
            raise VastApiError("vast api key is empty")
        self._api_key = api_key
        self._opener = opener or urllib.request.urlopen

    def _request(self, method: str, path: str, *, base: str = API_BASE,
                 network_retries: int = 3) -> dict[str, Any]:
        last_network_error: Exception | None = None
        for attempt in range(network_retries):
            request = urllib.request.Request(
                f"{base}{path}",
                method=method,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Accept": "application/json",
                },
            )
            try:
                with self._opener(request, timeout=30) as response:
                    body = response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                raise VastApiError(f"vast api {method} {path} failed with HTTP {exc.code}") from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_network_error = exc
                if attempt < network_retries - 1:
                    time.sleep(2.0 * (attempt + 1))
                continue
            try:
                return json.loads(body) if body else {}
            except json.JSONDecodeError as exc:
                raise VastApiError(f"vast api {method} {path} returned malformed JSON") from exc
        raise VastApiError(
            f"vast api {method} {path} failed: network error after {network_retries} attempts"
        ) from last_network_error

    def list_instances(self) -> list[VastInstance]:
        payload = self._request("GET", "/instances/", base=API_BASE_V1)
        rows = payload.get("instances", payload if isinstance(payload, list) else [])
        return [VastInstance.from_payload(row) for row in rows]

    def destroy_instance(self, instance_id: int) -> None:
        try:
            self._request("DELETE", f"/instances/{instance_id}/", base=API_BASE_V1)
        except VastApiError as exc:
            message = str(exc)
            if "404" in message:
                return  # already gone — destruction is the desired end state
            if "410" not in message:
                raise
            try:
                self._request("DELETE", f"/instances/{instance_id}/")
            except VastApiError as fallback_exc:
                if "404" in str(fallback_exc):
                    return
                raise

    def current_balance(self) -> float | None:
        payload = self._request("GET", "/users/current/")
        credit = payload.get("credit")
        return float(credit) if credit is not None else None


@dataclass(frozen=True)
class DestroyVerification:
    verified: bool
    escalated: bool
    leaked_ids: tuple[int, ...]
    checks: int


def verify_destroyed(
    client: VastClient,
    instance_ids: set[int],
    *,
    attempts: int = 8,
    delay_seconds: float = 10.0,
    escalate: bool = True,
    sleeper: Callable[[float], None] = time.sleep,
) -> DestroyVerification:
    """Poll until none of `instance_ids` remain; optionally force-destroy leftovers.

    Returns verified=True only when a final poll observes zero remaining ids.
    """
    if not instance_ids:
        return DestroyVerification(verified=True, escalated=False, leaked_ids=(), checks=0)

    escalated = False
    remaining: set[int] = set(instance_ids)
    checks = 0
    for attempt in range(attempts):
        remaining = {i.instance_id for i in client.list_instances()} & set(instance_ids)
        checks += 1
        if not remaining:
            return DestroyVerification(verified=True, escalated=escalated, leaked_ids=(), checks=checks)
        if escalate and attempt >= max(1, attempts // 2) and not escalated:
            for instance_id in sorted(remaining):
                try:
                    client.destroy_instance(instance_id)
                except VastApiError:
                    pass
            escalated = True
        if attempt < attempts - 1:
            sleeper(delay_seconds)
    return DestroyVerification(verified=False, escalated=escalated,
                               leaked_ids=tuple(sorted(remaining)), checks=checks)
