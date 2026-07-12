from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

import requests


@dataclass(frozen=True)
class ZebraTamerJob:
    job_id: str
    state: str
    bytes_sent: int


def _base_url(connection: Mapping[str, Any]) -> str:
    value = str(connection.get("base_url") or "").strip().rstrip("/")
    if not value:
        raise ValueError("ZebraTamer connection.base_url is required")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("ZebraTamer connection.base_url must be an HTTP(S) URL")
    return value


def _agent_printer_id(connection: Mapping[str, Any]) -> str:
    value = str(connection.get("printer_id") or "").strip()
    if not value:
        raise ValueError("ZebraTamer connection.printer_id is required")
    return value


def _timeout(connection: Mapping[str, Any]) -> float:
    return max(0.1, int(connection.get("timeout_ms", 10_000)) / 1000.0)


def _unwrap(response: requests.Response) -> Any:
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"ZebraTamer request failed: {exc}") from exc
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("ZebraTamer returned an invalid response")
    error = payload.get("error")
    if error:
        message = error.get("message") if isinstance(error, dict) else str(error)
        raise RuntimeError(message or "ZebraTamer request failed")
    return payload.get("data")


def submit_zpl(
    connection: Mapping[str, Any],
    zpl: str,
    *,
    origin: str = "printhub",
    description: str | None = None,
    label_count: int | None = None,
) -> ZebraTamerJob:
    payload = zpl.encode("utf-8")
    headers = {
        "Content-Type": "application/zpl",
        "X-ZPL-Origin": origin,
    }
    if description:
        headers["X-ZPL-Description"] = description
    if label_count is not None:
        headers["X-ZPL-Label-Count"] = str(label_count)
    url = f"{_base_url(connection)}/v1/printers/{_agent_printer_id(connection)}/jobs"
    try:
        response = requests.post(url, data=payload, headers=headers, timeout=_timeout(connection))
    except requests.RequestException as exc:
        raise RuntimeError(f"ZebraTamer is unavailable: {exc}") from exc
    data = _unwrap(response)
    if not isinstance(data, dict) or not data.get("id"):
        raise RuntimeError("ZebraTamer did not return a job id")
    return ZebraTamerJob(
        job_id=str(data["id"]),
        state=str(data.get("state") or "queued"),
        bytes_sent=int(data.get("bytes") or len(payload)),
    )


def get_snapshot(connection: Mapping[str, Any]) -> dict[str, Any]:
    url = f"{_base_url(connection)}/v1/printers/{_agent_printer_id(connection)}/snapshot"
    try:
        response = requests.get(url, timeout=_timeout(connection))
    except requests.RequestException as exc:
        raise RuntimeError(f"ZebraTamer is unavailable: {exc}") from exc
    data = _unwrap(response)
    if not isinstance(data, dict):
        raise RuntimeError("ZebraTamer returned an invalid printer snapshot")
    return data


def list_agent_printers(base_url: str, timeout_s: float = 2.0) -> list[dict[str, Any]]:
    normalized = _base_url({"base_url": base_url})
    try:
        response = requests.get(f"{normalized}/v1/printers", timeout=timeout_s)
    except requests.RequestException as exc:
        raise RuntimeError(f"ZebraTamer is unavailable: {exc}") from exc
    data = _unwrap(response)
    if not isinstance(data, list):
        raise RuntimeError("ZebraTamer returned an invalid printer list")
    return [entry for entry in data if isinstance(entry, dict)]


def configured_agent_urls(extra: Iterable[str] = ()) -> list[str]:
    env_urls = os.getenv("ZPLGRID_ZEBRA_TAMER_AGENTS", "").split(",")
    values = [*extra, *env_urls]
    result: list[str] = []
    for value in values:
        normalized = str(value).strip().rstrip("/")
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def discover_agent_urls(timeout_s: float = 0.8) -> list[str]:
    """Discover ZebraTamer agents via their `_zpl-agent._tcp.local.` announcement.

    Discovery is best-effort. Explicit URLs from `ZPLGRID_ZEBRA_TAMER_AGENTS`
    always remain available when multicast DNS is blocked by the host network.
    """

    found = configured_agent_urls()
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    except ImportError:
        return found

    class Listener(ServiceListener):
        def add_service(self, zeroconf: Any, service_type: str, name: str) -> None:
            info = zeroconf.get_service_info(service_type, name, timeout=int(timeout_s * 1000))
            if info is None:
                return
            addresses = info.parsed_scoped_addresses()
            if not addresses:
                return
            url = f"http://{addresses[0]}:{info.port}"
            if url not in found:
                found.append(url)

        def update_service(self, zeroconf: Any, service_type: str, name: str) -> None:
            self.add_service(zeroconf, service_type, name)

        def remove_service(self, zeroconf: Any, service_type: str, name: str) -> None:
            return

    zeroconf = Zeroconf()
    try:
        ServiceBrowser(zeroconf, "_zpl-agent._tcp.local.", Listener())
        import time

        time.sleep(timeout_s)
    finally:
        zeroconf.close()
    return found
