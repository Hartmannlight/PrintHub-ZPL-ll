from __future__ import annotations

import json
import os
import string
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping


_COUNTERS_PATH = Path(os.getenv('ZPLGRID_COUNTERS_PATH', 'counters.json'))


@dataclass(frozen=True)
class MacroContext:
    template_name: str | None
    printer_id: str | None
    draft_id: str | None
    now: datetime
    increment_counters: bool


def collect_template_placeholders(template) -> set[str]:
    formatter = string.Formatter()
    used: set[str] = set()

    def add_from_text(text: str) -> None:
        for _, field_name, _, _ in formatter.parse(text):
            if not field_name:
                continue
            base = field_name.split('.', 1)[0].split('[', 1)[0]
            if base:
                used.add(base)

    def check_node(node) -> None:
        from .model import DataMatrixElement, LeafNode, QrElement, SplitNode, TextElement

        if isinstance(node, LeafNode):
            element = node.elements[0]
            if isinstance(element, TextElement):
                add_from_text(element.text)
            elif isinstance(element, QrElement):
                add_from_text(element.data)
            elif isinstance(element, DataMatrixElement):
                add_from_text(element.data)
            return
        if isinstance(node, SplitNode):
            for child in node.children:
                check_node(child)

    check_node(template.layout)
    return used


def build_macro_variables(
    used_names: Iterable[str],
    *,
    existing_variables: Mapping[str, Any],
    context: MacroContext,
) -> dict[str, Any]:
    available = {name for name in used_names if name not in existing_variables}
    if not available:
        return {}

    macros: dict[str, Any] = {}
    now = context.now
    today = now.strftime('%Y-%m-%d')

    def add_if(name: str, value: Any) -> None:
        if name in available:
            macros[name] = value

    add_if('_now_iso', now.isoformat())
    add_if('_date_yyyy_mm_dd', now.strftime('%Y-%m-%d'))
    add_if('_date_dd_mm_yyyy', now.strftime('%d.%m.%Y'))
    add_if('_time_hh_mm', now.strftime('%H:%M'))
    add_if('_time_hh_mm_ss', now.strftime('%H:%M:%S'))
    add_if('_timestamp_ms', int(now.timestamp() * 1000))
    add_if('_uuid', str(uuid.uuid4()))
    add_if('_short_id', uuid.uuid4().hex[:8])

    if context.draft_id:
        add_if('_draft_id', context.draft_id)
    if context.printer_id:
        add_if('_printer_id', context.printer_id)
    if context.template_name:
        add_if('_template_name', context.template_name)

    counter_map = {
        '_counter_global': ('global', False),
        '_counter_daily': ('global', True),
    }
    if context.printer_id:
        counter_map['_counter_printer'] = (f'printer:{context.printer_id}', False)
        counter_map['_counter_printer_daily'] = (f'printer:{context.printer_id}', True)
    if context.template_name:
        counter_map['_counter_template'] = (f'template:{context.template_name}', False)
        counter_map['_counter_template_daily'] = (f'template:{context.template_name}', True)

    if any(name in available for name in counter_map):
        store = _load_counters()
        for macro_name, (key, daily) in counter_map.items():
            if macro_name not in available:
                continue
            value = _next_counter(
                store,
                key=key,
                daily=daily,
                today=today,
                increment=context.increment_counters,
            )
            macros[macro_name] = value
        if context.increment_counters and store.get('_dirty'):
            store.pop('_dirty', None)
            _save_counters(store)

    return macros


def _load_counters() -> dict[str, Any]:
    if not _COUNTERS_PATH.exists():
        return {}
    try:
        raw = json.loads(_COUNTERS_PATH.read_text(encoding='utf-8'))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def now_for_macros() -> datetime:
    tz_name = os.getenv('ZPLGRID_TIMEZONE')
    if tz_name:
        try:
            from zoneinfo import ZoneInfo

            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            return datetime.now().astimezone()
    return datetime.now().astimezone()


def _save_counters(payload: Mapping[str, Any]) -> None:
    _COUNTERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = _COUNTERS_PATH.with_suffix('.tmp')
    text = json.dumps(payload, indent=2, ensure_ascii=True)
    temp_path.write_text(text, encoding='utf-8')
    temp_path.replace(_COUNTERS_PATH)


def _next_counter(
    store: dict[str, Any],
    *,
    key: str,
    daily: bool,
    today: str,
    increment: bool,
) -> int:
    entry = store.get(key)
    if not isinstance(entry, dict):
        entry = {}

    if daily:
        if entry.get('date') != today:
            entry = {'value': 0, 'date': today}
    else:
        entry.setdefault('value', 0)

    value = int(entry.get('value', 0))
    if increment:
        value += 1
        entry['value'] = value
        store[key] = entry
        store['_dirty'] = True
    return value
