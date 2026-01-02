from __future__ import annotations

from typing import Any, Mapping, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .exceptions import CompilationError, LayoutError, TemplateRenderError, TemplateValidationError
from .model import DataMatrixElement, LabelTarget, LeafNode, QrElement, SplitNode, Template, TextElement
from .parser import load_template
from .render import RenderOptions, render_text


class RenderTarget(BaseModel):
    width_mm: float = Field(..., gt=0)
    height_mm: float = Field(..., gt=0)
    dpi: int = Field(203, gt=0)
    origin_x_mm: float = Field(0.0, ge=0)
    origin_y_mm: float = Field(0.0, ge=0)


class RenderRequest(BaseModel):
    template: dict[str, Any]
    target: RenderTarget
    variables: dict[str, Any] = Field(default_factory=dict)
    debug: bool = False


class RenderResponse(BaseModel):
    zpl: str


app = FastAPI(title="zplgrid API", version="1.0")


def _assert_variables_present(template: Template, variables: Mapping[str, Any]) -> None:
    options = RenderOptions(missing_variables="error")

    def check_node(node) -> None:
        if isinstance(node, LeafNode):
            element = node.elements[0]
            if isinstance(element, TextElement):
                render_text(element.text, variables, options=options)
            elif isinstance(element, QrElement):
                render_text(element.data, variables, options=options)
            elif isinstance(element, DataMatrixElement):
                render_text(element.data, variables, options=options)
            return
        if isinstance(node, SplitNode):
            for child in node.children:
                check_node(child)

    check_node(template.layout)


@app.post("/v1/render/zpl", response_model=RenderResponse)
def render_zpl(payload: RenderRequest) -> RenderResponse:
    try:
        template = load_template(payload.template)
        _assert_variables_present(template, payload.variables)
        target = LabelTarget(
            width_mm=payload.target.width_mm,
            height_mm=payload.target.height_mm,
            dpi=payload.target.dpi,
            origin_x_mm=payload.target.origin_x_mm,
            origin_y_mm=payload.target.origin_y_mm,
        )
        zpl = template.compile(target=target, variables=payload.variables, debug=payload.debug)
        return RenderResponse(zpl=zpl)
    except TemplateValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TemplateRenderError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except (CompilationError, LayoutError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
