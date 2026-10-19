"""Preparación determinista de prompts; no invoca un LLM ni consume GPU.

La dirección creativa se escribe en inglés; los diálogos se conservan literalmente.
Las comprobaciones de texto no certifican identidad, física ni calidad audiovisual.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

H3Profile = Literal["h3_balanced_default", "h3_quality_bf16_optional"]
ImageProfile = Literal["qwen21_bf16", "qwen2512_t2i", "qwen_edit2511_fp8mixed", "qwen_edit2511_bf16"]
Text = Annotated[str, Field(min_length=1, max_length=6000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Character(StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    description: str = Field(min_length=1, max_length=700)
    # None means this character never speaks in this clip.
    voice: str | None = Field(default=None, min_length=1, max_length=400)


class Beat(StrictModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    action: Text
    sound: str = Field(default="", max_length=1000)
    speaker: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{0,31}$")
    dialogue: str | None = Field(default=None, min_length=1, max_length=3000)
    language: str = Field(default="Spanish", pattern=r"^[A-Za-z -]{2,40}$")
    delivery: str = Field(default="at a natural conversational pace", max_length=500)
    voiceover: bool = False

    @model_validator(mode="after")
    def valid_beat(self):
        if self.end <= self.start:
            raise ValueError("Cada acción necesita end > start.")
        if (self.speaker is None) != (self.dialogue is None):
            raise ValueError("speaker y dialogue deben aparecer juntos.")
        if self.dialogue is not None and not self.dialogue.strip():
            raise ValueError("El diálogo no puede estar vacío.")
        if self.voiceover and not self.dialogue:
            raise ValueError("voiceover requiere un diálogo.")
        return self


class Shot(StrictModel):
    start: float = Field(default=0, ge=0)
    composition: Text
    camera: Text = "The camera holds a static shot."
    beats: list[Beat] = Field(min_length=1, max_length=20)


class H3Draft(StrictModel):
    profile: H3Profile = "h3_balanced_default"
    mode: Literal["I2VA", "FL2VA"] = "I2VA"
    duration_seconds: float = Field(default=5, ge=4, le=15)
    has_start_image: bool = True
    has_end_image: bool = False
    visual_style: Text = "Cinematic 3D CG animation, vertical 9:16."
    characters: list[Character] = Field(default_factory=list, max_length=12)
    lighting: Text
    background: Text
    continuity: list[Text] = Field(default_factory=list, max_length=20)
    shots: list[Shot] = Field(min_length=1, max_length=8)
    end_state: Text
    overall_soundscape: Text
    non_diegetic_music: Text = "N/A"

    @model_validator(mode="after")
    def valid_timeline(self):
        if sum(len(s.beats) for s in self.shots) > 24 or sum(map(len, _strings(self.model_dump()))) > 24000:
            raise ValueError("El plan supera 24 acciones o 24000 caracteres. Divide la escena.")
        if not self.has_start_image:
            raise ValueError("El flujo del repositorio necesita una imagen inicial.")
        if self.has_end_image != (self.mode == "FL2VA"):
            raise ValueError("FL2VA requiere imagen final; I2VA usa solo la inicial.")
        keys = [c.key for c in self.characters]
        if len(set(keys)) != len(keys):
            raise ValueError("Las claves de personajes deben ser únicas.")
        chars = {c.key: c for c in self.characters}
        starts = [s.start for s in self.shots]
        if starts[0] != 0 or any(a >= b for a, b in zip(starts, starts[1:], strict=False)):
            raise ValueError("El primer plano empieza en 0 y los cortes deben aumentar.")
        speech = []
        for i, shot in enumerate(self.shots):
            limit = starts[i + 1] if i + 1 < len(starts) else self.duration_seconds
            if shot.start >= limit:
                raise ValueError("Un corte está fuera de la duración solicitada.")
            if any(a.start > b.start for a, b in zip(shot.beats, shot.beats[1:], strict=False)):
                raise ValueError("Ordena las acciones por su inicio.")
            for beat in shot.beats:
                if beat.start < shot.start or beat.end > limit:
                    raise ValueError("Una acción cruza un corte o excede la duración solicitada.")
                if beat.speaker:
                    char = chars.get(beat.speaker)
                    if not char or char.voice is None:
                        raise ValueError(
                            "El hablante debe existir y tener una voz; un personaje silencioso no habla."
                        )
                    speech.append(beat)
        speech.sort(key=lambda b: b.start)
        if any(a.end > b.start for a, b in zip(speech, speech[1:], strict=False)):
            raise ValueError("Los diálogos se solapan: separa los turnos de voz.")
        # Free-text fields may not inject a second structural section or a dialogue tag.
        for value in _strings(self.model_dump()):
            if re.search(
                r"</?d>|<Picture\s+\d+>|\[Shot\s+\d+\]|(?:integrated_multimodal_description|overall_soundscape|non_diegetic_music):",
                value,
                re.I,
            ):
                raise ValueError("Escribe contenido sin etiquetas H3; el compilador añade su estructura.")
        return self


class ImageDraft(StrictModel):
    profile: ImageProfile = "qwen21_bf16"
    mode: Literal["T2I", "EDIT"] = "T2I"
    has_reference_image: bool = False
    subject: Text
    composition: Text
    environment: Text
    lighting: Text
    materials: Text
    expression: Text
    starting_pose: Text
    preserve: list[Text] = Field(default_factory=list, max_length=20)
    changes: list[Text] = Field(default_factory=list, max_length=20)
    visible_text: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def valid_mode(self):
        editing = self.mode == "EDIT" if self.profile == "qwen21_bf16" else self.profile != "qwen2512_t2i"
        if editing != (self.mode == "EDIT"):
            raise ValueError("Qwen-Image-2512 usa T2I; Qwen-Image-Edit-2511 usa EDIT.")
        if editing and (not self.has_reference_image or not self.changes or not self.preserve):
            raise ValueError("EDIT requiere referencia, cambios concretos y atributos que conservar.")
        if not editing and (self.has_reference_image or self.changes or self.preserve):
            raise ValueError("Para editar o preservar una referencia, selecciona el modo EDIT de Qwen 2.1 o Qwen-Image-Edit-2511.")
        return self


class Issue(StrictModel):
    severity: Literal["error", "warning", "info"]
    code: str
    message: str


class PromptResult(StrictModel):
    prompt: str
    profile: str
    issues: list[Issue] = Field(default_factory=list)
    frames: int | None = None
    effective_seconds: float | None = None


class LintRequest(StrictModel):
    prompt: str = Field(max_length=60000)
    duration_seconds: float = Field(ge=0.5, le=60)
    has_start_image: bool
    has_end_image: bool = False


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)


def h3_frames(seconds: float) -> int:
    frames = max(5, round(seconds * 24))
    return frames + (5 - frames % 17) % 17


def _cut_time(seconds: float) -> str:
    millis = round(seconds * 1000)
    return f"{millis // 60000:02d}:{millis // 1000 % 60:02d}.{millis % 1000:03d}"


def compile_h3(draft: H3Draft) -> PromptResult:
    frames = h3_frames(draft.duration_seconds)
    effective = frames / 24
    if draft.mode == "I2VA":
        anchor = "For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced."
    else:
        anchor = (
            "How the reference pictures align with the target video — Picture 1 (from Shot 1) "
            "aligns with the 0.00-second mark of the target video; "
            f"Picture 2 (from Shot {len(draft.shots)}) aligns with the {effective:.2f}-second mark of the target video."
        )
    voices = {}
    chars = {c.key: c for c in draft.characters}
    paragraphs = []
    issues = []
    for i, shot in enumerate(draft.shots, 1):
        intro = f"[Shot {i}] "
        if i == 1:
            intro += draft.visual_style + " "
        else:
            intro += f"At {_cut_time(shot.start)}, the camera cuts to "
        parts = [intro + shot.composition, shot.camera]
        if i == 1:
            parts += [draft.lighting, draft.background, *draft.continuity]
            parts += [
                f"{c.description} remains silent, with lips resting closed between facial reactions."
                for c in draft.characters
                if c.voice is None
            ]
        for beat in shot.beats:
            parts.append(f"From {beat.start:.2f} to {beat.end:.2f} seconds, {beat.action}")
            if beat.sound:
                parts.append("Synchronized physical sound: " + beat.sound)
            if beat.speaker:
                char = chars[beat.speaker]
                voices.setdefault(beat.speaker, f"S{len(voices) + 1}")
                verb = "says in an off-screen voiceover" if beat.voiceover else "says"
                parts.append(
                    f"{char.description}, with {char.voice} ({voices[beat.speaker]}), {beat.delivery}, "
                    f"{verb}: <d>[{beat.language}] {beat.dialogue}</d>"
                    + (
                        " The corresponding on-screen character's lips remain completely closed."
                        if beat.voiceover
                        else ""
                    )
                )
                words = len(re.findall(r"\b\w+\b", beat.dialogue or ""))
                rate = words / (beat.end - beat.start)
                if rate > 3:
                    issues.append(
                        Issue(
                            severity="warning",
                            code="speech_pace",
                            message=f"{char.key}: {rate:.1f} palabras/s; amplía el turno o divide el plano. Es una estimación editorial.",
                        )
                    )
        if i == len(draft.shots):
            parts.append(draft.end_state)
            if draft.mode == "FL2VA":
                parts.append(
                    "Settle into the pose, object placement and composition of Picture 2 at the end."
                )
            parts.append(f"Let the final reaction settle naturally through {effective:.2f} seconds.")
        paragraphs.append(" ".join(parts))
    prompt = anchor + "\n\nintegrated_multimodal_description: " + "\n\n".join(paragraphs)
    prompt += f"\n\noverall_soundscape: {draft.overall_soundscape}\n\nnon_diegetic_music: {draft.non_diegetic_music}"
    issues += lint_h3(
        LintRequest(
            prompt=prompt,
            duration_seconds=draft.duration_seconds,
            has_start_image=True,
            has_end_image=draft.has_end_image,
        )
    )
    return PromptResult(
        prompt=prompt, profile=draft.profile, frames=frames, effective_seconds=effective, issues=issues
    )


def compile_image(draft: ImageDraft) -> PromptResult:
    parts = ["Create one vertical cinematic frame, ready for animation."]
    if draft.mode == "EDIT":
        parts = [
            "Edit the supplied reference image.",
            "Keep unchanged: " + "; ".join(draft.preserve) + ".",
            "Change only: " + "; ".join(draft.changes) + ".",
        ]
    parts += [
        draft.subject,
        draft.composition,
        draft.environment,
        draft.lighting,
        draft.materials,
        draft.expression,
        "Initial pose before the main action: " + draft.starting_pose,
    ]
    parts.append(
        "Visible lettering: " + "; ".join(json.dumps(t, ensure_ascii=False) for t in draft.visible_text)
        if draft.visible_text
        else (
            "Preserve existing lettering unless a requested change explicitly alters it."
            if draft.mode == "EDIT"
            else "Keep sign surfaces blank and the frame visually clean."
        )
    )
    return PromptResult(
        prompt="\n\n".join(parts),
        profile=draft.profile,
        issues=[
            Issue(
                severity="info",
                code="image_workflow",
                message="Prompt preparado para el perfil declarado. La app aún no ejecuta Qwen: usa su flujo ComfyUI, comprueba el resultado y prepara la referencia a 576×1024 antes de H3.",
            )
        ],
    )


def lint_h3(data: LintRequest) -> list[Issue]:
    issues = []

    def add(severity, code, message):
        issues.append(Issue(severity=severity, code=code, message=message))

    p = data.prompt
    if not p.strip():
        add("error", "empty_prompt", "Escribe el prompt antes de generar.")
    if not 4 <= data.duration_seconds <= 15:
        add(
            "error",
            "duration",
            "El perfil H3 admite 4–15 s; para un montaje de 3 s genera al menos 4 s y recorta después.",
        )
    if not data.has_start_image:
        add("error", "start_image", "Falta la imagen inicial requerida por el flujo.")
    refs = {int(n) for n in re.findall(r"\bPicture\s+(\d+)\b", p, re.I)}
    if any(n > (2 if data.has_end_image else 1) for n in refs):
        add("error", "reference", "El prompt menciona una imagen que no está adjunta a esta escena.")
    fields = ["integrated_multimodal_description:", "overall_soundscape:", "non_diegetic_music:"]
    positions = [p.find(f) for f in fields]
    if (
        any(pos < 0 for pos in positions)
        or positions != sorted(positions)
        or any(p.count(f) != 1 for f in fields)
    ):
        add(
            "warning",
            "structure",
            "Usa una sola vez los tres campos H3, en orden: descripción, ambiente y música.",
        )
    depth = 0
    broken_tags = False
    for tag in re.findall(r"</?d>", p):
        depth += -1 if tag == "</d>" else 1
        if depth not in (0, 1):
            broken_tags = True
    if depth != 0 or broken_tags:
        add("error", "dialogue_tags", "Hay etiquetas <d> sin pareja o anidadas.")
    lines = re.findall(r"<d>(.*?)</d>", p, re.S)
    if any(not re.match(r"\[[A-Za-z -]+\]\s*\S", line) for line in lines):
        add(
            "warning",
            "dialogue_language",
            "Cada diálogo necesita idioma y palabras dentro de <d>, por ejemplo [Spanish].",
        )
    if lines and not re.search(r"\(S\d+(?:,S\d+)*\)", p):
        add("warning", "speakers", "Asigna un ID de voz estable (S1), (S2) a quien habla.")
    effective = h3_frames(data.duration_seconds) / 24
    first = p.split("\n", 1)[0]
    if data.has_end_image:
        expected = f"{effective:.2f}-second mark"
        if (
            "How the reference pictures align" not in first
            or "Picture 2" not in first
            or expected not in first
        ):
            add(
                "warning",
                "end_alignment",
                f"FL2VA debe alinear la imagen final a {effective:.2f} s efectivos en la primera línea.",
            )
    elif not first.startswith("For the target video, at 0.00 seconds"):
        add("warning", "start_alignment", "Añade la instrucción inicial I2VA antes de los tres campos.")
    if re.search(r"negative_prompt\s*:|\bno subtitles\b|\bno on-screen text\b", p, re.I):
        add(
            "warning",
            "negative_branch",
            "H3 usa BasicGuider sin rama negativa: describe el resultado deseado en positivo.",
        )
    if re.search(r"<Audio\s+\d+>|<Video\s+\d+>|subject_definitions:", p, re.I):
        add("error", "unsupported_reference", "Este flujo no tiene entradas Ref2VA de audio o video.")
    if re.search(
        r"static shot|locked camera|camera (?:remains|stays|is) (?:fixed|locked)", p, re.I
    ) and re.search(r"camera (?:pushes|pans|trucks|zooms|orbits|tracks)", p, re.I):
        add(
            "warning",
            "camera_review",
            "Aparecen cámara fija y móvil: comprueba si pertenecen a planos distintos.",
        )
    add(
        "info",
        "effective_duration",
        f"{h3_frames(data.duration_seconds)} fotogramas a 24 fps: {effective:.2f} s efectivos.",
    )
    add(
        "info",
        "review_limits",
        "Revisión textual orientativa: verifica también imágenes, gestos, voces, sombras y sincronía del resultado.",
    )
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compilar o revisar prompts sin llamar a modelos.")
    parser.add_argument("command", choices=["h3", "image", "lint", "schema"])
    parser.add_argument("input", nargs="?", help="JSON de entrada; '-' lee stdin")
    parser.add_argument("--output", type=Path, help="Guardar resultado JSON en este archivo")
    args = parser.parse_args(argv)
    try:
        if args.command == "schema":
            result = {
                "h3": H3Draft.model_json_schema(),
                "image": ImageDraft.model_json_schema(),
                "lint": LintRequest.model_json_schema(),
            }
        else:
            if not args.input:
                parser.error("Indica un archivo JSON o '-'.")
            raw = sys.stdin.read() if args.input == "-" else Path(args.input).read_text(encoding="utf-8-sig")
            if args.command == "h3":
                result = compile_h3(H3Draft.model_validate_json(raw)).model_dump()
            elif args.command == "image":
                result = compile_image(ImageDraft.model_validate_json(raw)).model_dump()
            else:
                result = {"issues": [i.model_dump() for i in lint_h3(LintRequest.model_validate_json(raw))]}
        text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return int(any(i["severity"] == "error" for i in result.get("issues", [])))
    except (ValidationError, OSError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
