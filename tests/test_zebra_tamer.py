from __future__ import annotations

from typing import Any

from zplgrid.printer_io import apply_printer_settings, dispatch_zpl
from zplgrid.zebra_tamer import get_snapshot


class FakeResponse:
    def __init__(self, data: Any, status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        return self._data


def test_dispatches_zpl_to_zebra_tamer(monkeypatch) -> None:
    observed: dict[str, Any] = {}

    def fake_post(url, *, data, headers, timeout):
        observed.update(url=url, data=data, headers=headers, timeout=timeout)
        return FakeResponse(
            {
                "api_version": "v1",
                "data": {"id": "job-42", "state": "queued", "bytes": len(data)},
                "error": None,
            },
            status_code=202,
        )

    monkeypatch.setattr("zplgrid.zebra_tamer.requests.post", fake_post)
    printer = {
        "connection": {
            "protocol": "zebra_tamer",
            "base_url": "http://zpl-agent.local:8080/",
            "printer_id": "schildkrote",
            "timeout_ms": 2500,
        }
    }

    result = dispatch_zpl(printer, "^XA^XZ", description="Test label")

    assert result.job_id == "job-42"
    assert result.job_state == "queued"
    assert observed["url"] == "http://zpl-agent.local:8080/v1/printers/schildkrote/jobs"
    assert observed["headers"]["Content-Type"] == "application/zpl"
    assert observed["headers"]["X-ZPL-Origin"] == "printhub"


def test_reads_zebra_tamer_snapshot(monkeypatch) -> None:
    def fake_get(url, *, timeout):
        assert url.endswith("/v1/printers/schildkrote/snapshot")
        return FakeResponse({"data": {"printer_id": "schildkrote", "status": {"ready": {"value": True}}}})

    monkeypatch.setattr("zplgrid.zebra_tamer.requests.get", fake_get)
    snapshot = get_snapshot(
        {"base_url": "http://zpl-agent.local:8080", "printer_id": "schildkrote"}
    )
    assert snapshot["status"]["ready"]["value"] is True


def test_agent_prints_do_not_override_saved_device_settings():
    printer = {'connection': {'protocol': 'zebra_tamer'}, 'zpl': {'darkness': 10, 'print_speed': 3, 'print_mode': 'tear_off'}, 'defaults': {'copies': 2, 'rotation': 0}}
    generated = '^XA\n^PW400\n^LL200\n^LH0,0\n^FO20,30^FDHello^FS\n^XZ'
    result = apply_printer_settings(generated, printer, generated=True)
    for command in ('^MD', '^PR', '^MM', '^PW', '^LL', '^JUS'):
        assert command not in result
    assert '^PQ2' in result
    assert '^FO20,30^FDHello^FS' in result
    # Explicit caller-supplied raw ZPL is not silently rewritten.
    assert '^PW400' in apply_printer_settings(generated, printer)
    raw_printer = {**printer, 'connection': {'protocol': 'raw9100'}}
    assert '^PR3' in apply_printer_settings(generated, raw_printer)


def test_configuration_read_is_authoritative_and_does_not_send_device_commands(monkeypatch):
    from zplgrid.zebra_tamer import get_configuration
    def fake_get(url, *, timeout):
        assert url.endswith('/v1/printers/p/configuration')
        return FakeResponse({'data': {'media': {'state': None}, 'device': {'observation': None}}})
    monkeypatch.setattr('zplgrid.zebra_tamer.requests.get', fake_get)
    assert get_configuration({'base_url':'http://agent:8080', 'printer_id':'p'})['media']['state'] is None
