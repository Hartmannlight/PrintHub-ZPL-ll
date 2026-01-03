from __future__ import annotations

import json
import os
import shutil
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


_DRAFTS_DIR = Path(os.getenv('ZPLGRID_PRINT_DRAFTS_DIR', 'drafts'))
_DRAFT_FILENAME = 'draft.json'
_DEFAULT_TTL_MINUTES = 30
_DRAFT_ID_RE = re.compile(r'^[0-9a-f]{32}$')


@dataclass(frozen=True)
class PrintDraftEntry:
    draft_id: str
    created_at: datetime
    expires_at: datetime
    template: dict[str, Any]
    variables: dict[str, Any]
    target: dict[str, Any]
    debug: bool
    dir_path: Path

    @property
    def draft_path(self) -> Path:
        return self.dir_path / _DRAFT_FILENAME


def ensure_drafts_dir() -> Path:
    _DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    return _DRAFTS_DIR


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ttl_minutes() -> int:
    raw = os.getenv('ZPLGRID_PRINT_DRAFT_TTL_MINUTES')
    if raw is None:
        return _DEFAULT_TTL_MINUTES
    try:
        ttl = int(raw)
    except ValueError:
        return _DEFAULT_TTL_MINUTES
    return max(0, ttl)


def _serialize_dt(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _delete_dir(path: Path) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def _make_draft_id(root: Path) -> str:
    while True:
        draft_id = uuid.uuid4().hex
        if not (root / draft_id).exists():
            return draft_id


def _is_valid_draft_id(draft_id: str) -> bool:
    return bool(_DRAFT_ID_RE.fullmatch(draft_id))


def _cleanup_expired(root: Path) -> None:
    now = _utc_now()
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        draft_path = entry / _DRAFT_FILENAME
        if not draft_path.exists():
            continue
        try:
            raw = json.loads(draft_path.read_text(encoding='utf-8'))
            expires_at = _parse_dt(str(raw.get('expires_at') or ''))
        except Exception:
            continue
        if now >= expires_at:
            _delete_dir(entry)


def save_print_draft(
    *,
    template: Mapping[str, Any],
    variables: Mapping[str, Any],
    target: Mapping[str, Any],
    debug: bool,
) -> PrintDraftEntry:
    root = ensure_drafts_dir()
    _cleanup_expired(root)
    draft_id = _make_draft_id(root)
    created_at = _utc_now()
    ttl_minutes = _ttl_minutes()
    expires_at = created_at + timedelta(minutes=ttl_minutes)
    dir_path = root / draft_id
    dir_path.mkdir(parents=True, exist_ok=True)

    payload = {
        'draft_id': draft_id,
        'template': dict(template),
        'variables': dict(variables),
        'target': dict(target),
        'debug': bool(debug),
        'created_at': _serialize_dt(created_at),
        'expires_at': _serialize_dt(expires_at),
    }
    (dir_path / _DRAFT_FILENAME).write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding='utf-8')
    return PrintDraftEntry(
        draft_id=draft_id,
        created_at=created_at,
        expires_at=expires_at,
        template=dict(template),
        variables=dict(variables),
        target=dict(target),
        debug=bool(debug),
        dir_path=dir_path,
    )


def load_print_draft(draft_id: str) -> PrintDraftEntry:
    root = ensure_drafts_dir()
    _cleanup_expired(root)
    if not _is_valid_draft_id(draft_id):
        raise FileNotFoundError(draft_id)
    dir_path = root / draft_id
    draft_path = dir_path / _DRAFT_FILENAME
    if not draft_path.exists():
        raise FileNotFoundError(draft_id)
    try:
        raw = json.loads(draft_path.read_text(encoding='utf-8'))
    except Exception as exc:
        raise ValueError(f'Invalid draft payload: {exc}') from exc
    if not isinstance(raw, dict):
        raise ValueError('Invalid draft payload')

    created_at = _parse_dt(str(raw.get('created_at') or ''))
    expires_at = _parse_dt(str(raw.get('expires_at') or ''))
    if _utc_now() >= expires_at:
        _delete_dir(dir_path)
        raise FileNotFoundError(draft_id)

    return PrintDraftEntry(
        draft_id=str(raw.get('draft_id') or draft_id),
        created_at=created_at,
        expires_at=expires_at,
        template=dict(raw.get('template') or {}),
        variables=dict(raw.get('variables') or {}),
        target=dict(raw.get('target') or {}),
        debug=bool(raw.get('debug', False)),
        dir_path=dir_path,
    )
