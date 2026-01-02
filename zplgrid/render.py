from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .exceptions import TemplateRenderError


@dataclass(frozen=True)
class RenderOptions:
    missing_variables: str = 'error'


class _StrictDict(dict):
    def __missing__(self, key: str):
        raise KeyError(key)


class _EmptyMissingDict(dict):
    def __missing__(self, key: str):
        return ''


def render_text(template: str, variables: Mapping[str, Any], *, options: RenderOptions) -> str:
    mapping: dict[str, Any]
    if options.missing_variables == 'empty':
        mapping = _EmptyMissingDict(variables)
    else:
        mapping = _StrictDict(variables)

    try:
        return template.format_map(mapping)
    except KeyError as e:
        raise TemplateRenderError(f'missing template variable: {e.args[0]!r}') from e
    except Exception as e:
        raise TemplateRenderError(f'failed to render text: {e}') from e
