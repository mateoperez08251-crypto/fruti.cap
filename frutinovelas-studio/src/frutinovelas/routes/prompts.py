"""Herramientas de preparación: sin escrituras, red externa ni trabajos GPU."""

from fastapi import APIRouter

from frutinovelas.prompts import (
    H3Draft,
    ImageDraft,
    Issue,
    LintRequest,
    PromptResult,
    compile_h3,
    compile_image,
    lint_h3,
)

router = APIRouter(prefix="/prompts", tags=["prompts"])


@router.post("/h3", response_model=PromptResult)
def build_h3(data: H3Draft):
    return compile_h3(data)


@router.post("/image", response_model=PromptResult)
def build_image(data: ImageDraft):
    return compile_image(data)


@router.post("/lint", response_model=list[Issue])
def check_prompt(data: LintRequest):
    return lint_h3(data)
