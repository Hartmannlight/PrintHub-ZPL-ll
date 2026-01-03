from __future__ import annotations

import socket
from typing import Any, Mapping


def apply_printer_settings(zpl: str, printer: Mapping[str, Any]) -> str:
    settings = _build_print_settings(printer)
    if not settings:
        return zpl

    settings_block = '\n'.join(settings) + '\n'
    if '^XA' in zpl:
        parts = zpl.split('^XA')
        rebuilt = parts[0]
        for part in parts[1:]:
            rebuilt += '^XA' + settings_block + part
        return rebuilt
    return '^XA' + settings_block + zpl + '\n^XZ\n'


def send_raw_zpl(printer: Mapping[str, Any], zpl: str) -> int:
    connection = printer.get('connection') or {}
    protocol = connection.get('protocol')
    if protocol != 'raw9100':
        raise ValueError(f'Unsupported protocol: {protocol}')

    host = str(connection.get('host', '')).strip()
    port = int(connection.get('port', 0))
    timeout_ms = int(connection.get('timeout_ms', 3000))
    if not host:
        raise ValueError('Printer connection.host is required')
    if port <= 0:
        raise ValueError('Printer connection.port must be > 0')

    payload = zpl.encode('utf-8')
    timeout_s = max(0.1, timeout_ms / 1000.0)
    with socket.create_connection((host, port), timeout=timeout_s) as sock:
        sock.settimeout(timeout_s)
        sock.sendall(payload)
    return len(payload)


def query_raw_command(printer: Mapping[str, Any], command: str) -> str:
    connection = printer.get('connection') or {}
    protocol = connection.get('protocol')
    if protocol != 'raw9100':
        raise ValueError(f'Unsupported protocol: {protocol}')

    host = str(connection.get('host', '')).strip()
    port = int(connection.get('port', 0))
    timeout_ms = int(connection.get('timeout_ms', 3000))
    if not host:
        raise ValueError('Printer connection.host is required')
    if port <= 0:
        raise ValueError('Printer connection.port must be > 0')

    payload = (command.strip() + '\n').encode('utf-8')
    timeout_s = max(0.1, timeout_ms / 1000.0)
    chunks: list[bytes] = []
    with socket.create_connection((host, port), timeout=timeout_s) as sock:
        sock.settimeout(timeout_s)
        sock.sendall(payload)
        while True:
            try:
                data = sock.recv(4096)
            except socket.timeout:
                break
            if not data:
                break
            chunks.append(data)
    return b''.join(chunks).decode('utf-8', errors='replace')


def _build_print_settings(printer: Mapping[str, Any]) -> list[str]:
    zpl_cfg = printer.get('zpl') or {}
    defaults = printer.get('defaults') or {}
    settings: list[str] = []

    if 'darkness' in zpl_cfg:
        try:
            darkness = int(zpl_cfg['darkness'])
        except (TypeError, ValueError) as exc:
            raise ValueError('Printer zpl.darkness must be an integer') from exc
        settings.append(f'^MD{darkness}')

    if 'print_speed' in zpl_cfg:
        try:
            speed = int(zpl_cfg['print_speed'])
        except (TypeError, ValueError) as exc:
            raise ValueError('Printer zpl.print_speed must be an integer') from exc
        settings.append(f'^PR{speed}')

    print_mode = zpl_cfg.get('print_mode')
    if print_mode:
        mode_code = _print_mode_code(str(print_mode))
        if mode_code is None:
            raise ValueError(f'Unsupported print_mode: {print_mode}')
        settings.append(f'^MM{mode_code}')

    if 'copies' in defaults:
        try:
            copies = int(defaults['copies'])
        except (TypeError, ValueError) as exc:
            raise ValueError('Printer defaults.copies must be an integer') from exc
        if copies > 0:
            settings.append(f'^PQ{copies}')

    if 'rotation' in defaults:
        try:
            rotation = int(defaults['rotation'])
        except (TypeError, ValueError) as exc:
            raise ValueError('Printer defaults.rotation must be an integer') from exc
        rotation_code = _rotation_code(rotation)
        if rotation_code is None:
            raise ValueError('Printer defaults.rotation must be 0, 90, 180, or 270')
        settings.append(f'^FW{rotation_code}')

    return settings


def _print_mode_code(mode: str) -> str | None:
    normalized = mode.strip().lower()
    mapping = {
        'tear_off': 'T',
        'peel_off': 'P',
        'rewind': 'R',
        'cutter': 'C',
        'delayed_cut': 'D',
        'applicator': 'A',
    }
    return mapping.get(normalized)


def _rotation_code(rotation: int) -> str | None:
    mapping = {0: 'N', 90: 'R', 180: 'I', 270: 'B'}
    return mapping.get(rotation)
