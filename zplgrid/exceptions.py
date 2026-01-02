from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class TemplateIssue:
    path: str
    message: str

    def __str__(self) -> str:
        return f'{self.path}: {self.message}'


class ZplGridError(Exception):
    pass


class TemplateValidationError(ZplGridError):
    def __init__(self, issues: Iterable[TemplateIssue]):
        self.issues = list(issues)
        super().__init__(self._format())

    def _format(self) -> str:
        if not self.issues:
            return 'Template validation failed'
        lines = ['Template validation failed:']
        lines.extend(f'  - {issue}' for issue in self.issues)
        return '\n'.join(lines)


class TemplateRenderError(ZplGridError):
    pass


class LayoutError(ZplGridError):
    pass


class CompilationError(ZplGridError):
    pass
