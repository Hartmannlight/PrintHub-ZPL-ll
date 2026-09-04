"""Transactional printer inventory. YAML is a one-time seed, never a write target."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterator, Mapping
from urllib.parse import urlsplit, urlunsplit
import uuid

from .printers_config import _validate_printers_config, load_printers_config


class RegistryConflict(ValueError):
    """A change would replace a device or overwrite a newer configuration."""


def normalize_agent_url(value: str) -> str:
    parsed = urlsplit(value.strip().rstrip('/'))
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname:
        raise ValueError('Agent URL must be an HTTP(S) URL')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Agent URL must not contain credentials, query or fragment')
    host = parsed.hostname.lower()
    host = f'[{host}]' if ':' in host else host
    port = parsed.port
    if port and port != (443 if parsed.scheme == 'https' else 80):
        host += f':{port}'
    return urlunsplit((parsed.scheme, host, parsed.path.rstrip('/'), '', ''))


def _keys(printer: Mapping[str, Any]) -> tuple[str, str | None]:
    connection = printer['connection']
    protocol = connection['protocol']
    if protocol in {'zebra_tamer', 'driver_agent'}:
        endpoint = [protocol, normalize_agent_url(connection['base_url']), connection['printer_id']]
        identity = [connection['agent_id'], connection['printer_id']] if connection.get('agent_id') else None
    elif protocol == 'raw9100':
        endpoint = ['raw9100', connection['host'].strip().lower(), connection['port']]
        identity = None
    else:
        raise ValueError(f'Unsupported printer connection protocol: {protocol}')
    return json.dumps(endpoint), json.dumps(identity) if identity else None


def _validate(printer: Mapping[str, Any]) -> None:
    json.dumps(printer, allow_nan=False)
    _validate_printers_config({'config_version': 1, 'printers': [printer]})
    _keys(printer)


class PrinterRegistry:
    def __init__(self, path: Path | None = None, seed_path: Path | None = None):
        self.path = path or Path(os.getenv('ZPLGRID_PRINTER_REGISTRY_PATH', 'configs/printers.sqlite3'))
        self.seed_path = seed_path or Path(os.getenv('ZPLGRID_PRINTER_SEED_PATH', 'configs/printers.yml'))

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except sqlite3.IntegrityError as exc:
            db.rollback()
            raise RegistryConflict('Printer ID or device is already registered') from exc
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('''CREATE TABLE IF NOT EXISTS printers (
                id TEXT PRIMARY KEY, config TEXT NOT NULL, endpoint TEXT NOT NULL UNIQUE,
                identity TEXT UNIQUE, revision INTEGER NOT NULL DEFAULT 1,
                source TEXT NOT NULL, available INTEGER, last_seen TEXT, error TEXT)''')
            if db.execute("SELECT 1 FROM metadata WHERE key='seed_imported'").fetchone():
                return
            seed = load_printers_config(self.seed_path)
            for printer in seed['printers']:
                self._insert(db, printer, 'yaml-import')
            # Keep an immutable logical backup, including original public IDs/settings.
            db.execute('INSERT INTO metadata VALUES (?, ?)', ('legacy_seed', json.dumps(seed)))
            db.execute('INSERT INTO metadata VALUES (?, ?)', ('seed_imported', datetime.now(timezone.utc).isoformat()))

    @staticmethod
    def _insert(db: sqlite3.Connection, printer: Mapping[str, Any], source: str) -> None:
        _validate(printer)
        endpoint, identity = _keys(printer)
        db.execute('INSERT INTO printers(id, config, endpoint, identity, source) VALUES (?, ?, ?, ?, ?)',
                   (printer['id'], json.dumps(printer), endpoint, identity, source))

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        printer = json.loads(row['config'])
        printer['registry'] = {'revision': row['revision'], 'source': row['source'],
                               'identity_quality': 'stable' if row['identity'] else 'endpoint'}
        printer['discovery'] = {'available': None if row['available'] is None else bool(row['available']),
                                'last_seen': row['last_seen'], 'error': row['error']}
        return printer

    def list(self) -> list[dict[str, Any]]:
        with self._transaction() as db:
            return [self._public(row) for row in db.execute('SELECT * FROM printers ORDER BY rowid')]

    def get(self, printer_id: str) -> dict[str, Any]:
        with self._transaction() as db:
            row = db.execute('SELECT * FROM printers WHERE id=?', (printer_id,)).fetchone()
            if row is None:
                raise KeyError(printer_id)
            return self._public(row)

    def export(self) -> dict[str, Any]:
        with self._transaction() as db:
            return {'config_version': 1, 'printers': [json.loads(row['config']) for row in db.execute('SELECT config FROM printers ORDER BY rowid')]}

    def create(self, printer: Mapping[str, Any], source: str = 'manual') -> dict[str, Any]:
        """Legacy PUT is create-or-identical, never a destructive replacement."""
        _validate(printer)
        with self._transaction() as db:
            row = db.execute('SELECT config FROM printers WHERE id=?', (printer['id'],)).fetchone()
            if row is not None:
                if json.loads(row['config']) != printer:
                    raise RegistryConflict('Printer ID already exists; use revision-checked PATCH to edit settings')
            else:
                self._insert(db, printer, source)
        return self.get(str(printer['id']))

    def import_config(self, config: Mapping[str, Any]) -> None:
        """Additive and all-or-nothing. Existing settings cannot be replaced by YAML."""
        _validate_printers_config(config)
        with self._transaction() as db:
            for printer in config['printers']:
                _validate(printer)
                row = db.execute('SELECT config FROM printers WHERE id=?', (printer['id'],)).fetchone()
                if row:
                    if json.loads(row['config']) != printer:
                        raise RegistryConflict(f"Printer {printer['id']} already exists with different settings")
                else:
                    self._insert(db, printer, 'yaml-import')

    def patch(self, printer_id: str, changes: Mapping[str, Any], revision: int) -> dict[str, Any]:
        allowed = {'name', 'enabled', 'media', 'alignment', 'zpl', 'driver_options', 'defaults', 'model', 'vendor', 'capabilities'}
        if not changes or set(changes) - allowed:
            raise ValueError('Only printer settings may be changed; ID and connection are immutable')
        with self._transaction() as db:
            row = db.execute('SELECT * FROM printers WHERE id=?', (printer_id,)).fetchone()
            if row is None:
                raise KeyError(printer_id)
            if row['revision'] != revision:
                raise RegistryConflict('Printer changed since it was loaded; refresh before saving')
            printer = json.loads(row['config'])
            for key, value in changes.items():
                if printer.get('connection', {}).get('protocol') == 'zebra_tamer' and key in {'media', 'alignment', 'zpl'}:
                    raise ValueError('Media and device settings are managed exclusively in ZebraTamer')
                printer[key] = deepcopy(value)
            _validate(printer)
            db.execute('UPDATE printers SET config=?, revision=revision+1 WHERE id=?', (json.dumps(printer), printer_id))
        return self.get(printer_id)

    def match(self, base_url: str, local_id: str, agent_id: str | None) -> dict[str, Any] | None:
        candidate = {'connection': {'protocol': 'zebra_tamer', 'base_url': base_url, 'printer_id': local_id, 'agent_id': agent_id}}
        endpoint, identity = _keys(candidate)
        with self._transaction() as db:
            rows = db.execute('SELECT * FROM printers WHERE endpoint=? OR identity=?', (endpoint, identity)).fetchall()
            if len(rows) > 1:
                raise RegistryConflict('Agent identity and endpoint refer to different registered printers; resolve the duplicate manually')
            if not rows:
                return None
            row = rows[0]
            if row['identity'] and row['identity'] != identity:
                raise RegistryConflict('A different or unidentified agent is now using this endpoint')
            return self._public(row)

    def observe(self, base_url: str, local_id: str, agent_id: str | None) -> dict[str, Any] | None:
        """Refresh only verified identity/endpoint and observation metadata."""
        with self._transaction() as db:
            connection = {'protocol': 'zebra_tamer', 'base_url': normalize_agent_url(base_url), 'printer_id': local_id}
            if agent_id:
                connection['agent_id'] = agent_id
            endpoint, identity = _keys({'connection': connection})
            rows = db.execute('SELECT * FROM printers WHERE endpoint=? OR identity=?', (endpoint, identity)).fetchall()
            if len(rows) > 1:
                raise RegistryConflict('Ambiguous printer identity; no endpoint was changed')
            if not rows:
                return None
            row = rows[0]
            if row['identity'] and row['identity'] != identity:
                raise RegistryConflict('Agent identity changed; refusing to redirect this printer')
            printer = json.loads(row['config'])
            previous = deepcopy(printer['connection'])
            printer['connection'].update(connection)
            _validate(printer)
            db.execute('''UPDATE printers SET config=?, endpoint=?, identity=?, revision=revision+?,
                          available=1, last_seen=?, error=NULL WHERE id=?''',
                       (json.dumps(printer), endpoint, identity, int(previous != printer['connection']),
                        datetime.now(timezone.utc).isoformat(), row['id']))
            return self._public(db.execute('SELECT * FROM printers WHERE id=?', (row['id'],)).fetchone())

    def unavailable(self, printer_id: str, error: str) -> None:
        with self._transaction() as db:
            db.execute('UPDATE printers SET available=0, error=? WHERE id=?', (error, printer_id))

    def register(self, printer: Mapping[str, Any]) -> dict[str, Any]:
        connection = printer['connection']
        existing = self.observe(connection['base_url'], connection['printer_id'], connection.get('agent_id'))
        if existing:
            return existing
        endpoint, identity = _keys(printer)
        new = deepcopy(dict(printer))
        new['id'] = f'zt-{uuid.uuid5(uuid.NAMESPACE_URL, identity or endpoint)}'
        try:
            self.create(new, 'discovery')
        except RegistryConflict:
            # A simultaneous identical registration is idempotent, not destructive.
            existing = self.observe(connection['base_url'], connection['printer_id'], connection.get('agent_id'))
            if existing is None:
                raise
            return existing
        return self.observe(connection['base_url'], connection['printer_id'], connection.get('agent_id')) or self.get(new['id'])
