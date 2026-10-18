"""Isolate one approved identity from multipose character-sheet references.

A single reference sheet can depict the SAME character many times from different
angles. Sending the whole collage to Qwen Edit leads it to copy extra bodies.
The original asset remains untouched; this preparation only affects the temporary
image uploaded for a new Qwen image job.
"""
from __future__ import annotations

import re
from typing import Any

from PIL import Image

ISOLATION_VERSION = 1

# Curated from the original character sheets (SHA-256, not mutable names).
# Rectangles are left, top, right, bottom as fractions of the original image.
# They isolate the first complete frontal pose, not the expressions or turnarounds.
CHARACTER_SHEET_RECIPES: dict[str, tuple[tuple[float, float, float, float], str]] = {
    "ccf51d133d2a5aa9c786cc6f2d8ca535bf1933d2ec24b8524ffef1d7e73700ff":
        ((0.025, 0.064, 0.315, 0.613),
         "A yellow-green PEAR with short wavy dark hair, a light cream shirt, dark trousers and brown shoes."),
    "b015af3705b5bd45ddad5e97c1586a4d5a6be1050bf853305dbc238c79847988":
        ((0.010, 0.124, 0.145, 0.552),
         "A broad-shouldered dark green AVOCADO with short dark hair, a charcoal shirt, dark belt and olive cargo trousers."),
    "26a7d4163f8999f3c5c3a7805b6321007b96903010c7106d76ae20f61a46f10a":
        ((0.010, 0.135, 0.145, 0.555),
         "A bright orange TANGERINE with neat dark hair, light blue shirt, ID lanyard and dark trousers."),
}

# Conventional multiview sheets in the same project layout: front figure
# occupies the first upper-left column. Unknown layouts should be reviewed.
SHEET_FILENAME = re.compile(
    r"character[\s_-]*(?:design[\s_-]*)?sheet|"
    r"ficha[\s_-]*(?:visual[\s_-]*(?:de[\s_-]*)?)?personaje|"
    r"ficha[\s_-]*visual|"
    r"model[\s_-]*sheet|turnaround",
    re.IGNORECASE,
)


def reference_preparation(sha256: str, filename: str, width: int, height: int) -> dict[str, Any]:
    """Freeze a deterministic single-body crop for image generation snapshots."""
    if sha256 in CHARACTER_SHEET_RECIPES:
        rect, identity = CHARACTER_SHEET_RECIPES[sha256]
        return {"version": ISOLATION_VERSION, "mode": "front_pose_crop",
                "normalized_box": list(rect), "identity": identity, "source": "verified_sheet"}
    if width >= 700 and height >= 700 and SHEET_FILENAME.search(filename or ""):
        ratio = width / height
        if ratio < 0.92:
            # Portrait turnarounds with a larger first full-body image.
            rect = [0.025, 0.065, 0.32, 0.62]
        else:
            # Landscape sheets with a row of many views over expression panels.
            rect = [0.012, 0.125, 0.148, 0.555]
        return {"version": ISOLATION_VERSION, "mode": "front_pose_crop",
                "normalized_box": rect, "identity": "",
                "source": "layout_heuristic_review_recommended"}
    return {"version": ISOLATION_VERSION, "mode": "original_single_reference",
            "identity": "", "source": "original"}


def isolated_reference(image: Image.Image, preparation: dict[str, Any] | None) -> Image.Image:
    """Return RGB temporary conditioning image, never alter the source asset."""
    rgb = image.convert("RGB")
    if preparation and preparation.get("mode") == "front_pose_crop":
        box = preparation.get("normalized_box")
        if not isinstance(box, list) or len(box) != 4 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) for v in box
        ):
            raise ValueError("La referencia recortada carece de límites válidos.")
        left, top, right, bottom = box
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise ValueError("Los límites de recorte del personaje son inválidos.")
        w, h = rgb.size
        coordinates = (round(left * w), round(top * h), round(right * w), round(bottom * h))
        if coordinates[2] - coordinates[0] < 64 or coordinates[3] - coordinates[1] < 64:
            raise ValueError("La ficha del personaje es demasiado pequeña para aislar su figura.")
        rgb = rgb.crop(coordinates)
    rgb.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
    # Preserve aspect ratio and avoid feeding extremely tiny cropped figures.
    if max(rgb.size) < 768:
        factor = 768 / max(rgb.size)
        rgb = rgb.resize((round(rgb.width * factor), round(rgb.height * factor)),
                         Image.Resampling.LANCZOS)
    return rgb


def cast_contract(cast: list[dict[str, Any]]) -> str:
    """Explicit, per-image identity binding and exact count, without changing saved prompts."""
    count = len(cast)
    if not count:
        return ""
    names = [str(c.get("name") or f"Character {i}") for i, c in enumerate(cast, 1)]
    binding = []
    for index, character in enumerate(cast, 1):
        identity = str((character.get("reference_preparation") or {}).get("identity") or "").strip()
        description = str(character.get("description") or "").strip()
        facts = " ".join(item for item in (identity, description) if item)
        binding.append(
            f"SUBJECT {index} — {names[index-1]}: exactly ONE on-screen instance. "
            f"Reference image {index} represents this character ONLY. "
            f"{facts} Use this subject's own fruit shape, face, silhouette, hair and clothes."
        )
    return (
        f"\n\nSTRICT SINGLE-INSTANCE CAST COMPOSITION — EXACTLY {count} DISTINCT VISIBLE "
        f"CHARACTER{'S' if count != 1 else ''} IN THE ENTIRE OUTPUT FRAME:\n"
        + "\n".join(binding)
        + "\nThis is ONE narrative moment, NOT a character sheet, contact sheet, lineup, collage, "
          "before-and-after image, or multiple alternate poses. "
          "Each subject occupies ONE coherent full body or permitted crop in the final scene. "
          "Any differing views in the SOURCE images represent the same individual, not other actors. "
          "Render the selected cast exactly once per identity; preserve their separate silhouettes, "
          "relative positions and scene-specific actions. No duplicated body or face, no reflected or "
          "mirrored duplicate, no background bystanders or extra officers, and no new anthropomorphic "
          "figures. Keep background vehicles empty unless a scene explicitly asks otherwise. "
          "Do not turn an unattended vehicle or a shape in the backdrop into another character. "
          "The scene description determines positioning; these constraints preserve its intended cast."
    )
