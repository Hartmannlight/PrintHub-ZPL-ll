"""Discovery observes inventory; registration is a separate explicit operation."""
from __future__ import annotations

from typing import Any
from concurrent.futures import ThreadPoolExecutor
import threading

from .printer_registry import PrinterRegistry, RegistryConflict, normalize_agent_url
from .zebra_tamer import configured_agent_urls, discover_agent_urls, get_agent_info, list_agent_printers

_scan_lock = threading.Lock()


def inspect_agent(base_url: str) -> dict[str, Any]:
    base_url = normalize_agent_url(base_url)
    info = get_agent_info(base_url)
    printers = list_agent_printers(base_url)
    ids = [p.get('id') for p in printers]
    if any(not isinstance(value, str) or not value for value in ids) or len(set(ids)) != len(ids):
        raise ValueError('Agent returned missing or duplicate printer IDs')
    return {'base_url': base_url, 'agent_id': info.get('agent_id'), 'available': True,
            'identity_quality': 'stable' if info.get('agent_id') else 'endpoint', 'printers': printers}


def discover_printers(registry: PrinterRegistry, extra: list[str] | None = None) -> dict[str, Any]:
    with _scan_lock:
        return _discover_printers(registry, extra)


def _discover_printers(registry: PrinterRegistry, extra: list[str] | None) -> dict[str, Any]:
    known = registry.list()
    known_urls = [p['connection']['base_url'] for p in known if p['connection']['protocol'] == 'zebra_tamer']
    warning = None
    try:
        discovered = discover_agent_urls()
    except Exception as exc:
        discovered = configured_agent_urls()
        warning = f'mDNS unavailable; using configured addresses: {exc}'
    urls: list[str] = []
    for value in [*known_urls, *(extra or []), *discovered]:
        normalized = normalize_agent_url(value)
        if normalized not in urls:
            urls.append(normalized)
    agents: list[dict[str, Any]] = []
    by_identity: dict[str, dict[str, Any]] = {}
    def inspect(url: str) -> dict[str, Any]:
        try:
            return inspect_agent(url)
        except Exception as exc:
            return {'base_url': url, 'available': False, 'printers': [], 'error': str(exc)}
    with ThreadPoolExecutor(max_workers=4) as pool:
        observations = list(pool.map(inspect, urls))
    for agent in observations:
        url = agent['base_url']
        if not agent['available']:
            agents.append(agent)
            continue
        identity = agent['agent_id'] or url
        if identity in by_identity:
            by_identity[identity].setdefault('aliases', []).append(url)
            continue
        by_identity[identity] = agent
        agents.append(agent)

    # Only the observed inventory determines availability. A missing agent never deletes a printer.
    for printer in known:
        if printer['connection']['protocol'] == 'zebra_tamer':
            registry.unavailable(printer['id'], 'Agent or printer not reachable in the latest discovery')
    for agent in agents:
        if not agent['available']:
            continue
        for printer in agent['printers']:
            try:
                matches = [registry.match(url, printer['id'], agent.get('agent_id'))
                           for url in [agent['base_url'], *agent.get('aliases', [])]]
                if len({p['id'] for p in matches if p}) > 1:
                    raise RegistryConflict('Multiple saved printers resolve to this device; no identities were merged')
                existing = registry.observe(agent['base_url'], printer['id'], agent.get('agent_id'))
                printer['registered_id'] = existing['id'] if existing else None
                printer['registration_conflict'] = None
            except RegistryConflict as exc:
                printer['registered_id'] = None
                printer['registration_conflict'] = str(exc)
    return {'agents': agents, 'warning': warning}
