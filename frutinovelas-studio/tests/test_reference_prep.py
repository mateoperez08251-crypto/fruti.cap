"""Single-body Qwen conditioning for saved multiview character sheets."""
from copy import deepcopy

import pytest
from PIL import Image

from frutinovelas.services.reference_prep import (
    CHARACTER_SHEET_RECIPES, cast_contract, isolated_reference, reference_preparation,
)


@pytest.mark.parametrize("sha,fruit", [
    ("ccf51d133d2a5aa9c786cc6f2d8ca535bf1933d2ec24b8524ffef1d7e73700ff", "PEAR"),
    ("b015af3705b5bd45ddad5e97c1586a4d5a6be1050bf853305dbc238c79847988", "AVOCADO"),
    ("26a7d4163f8999f3c5c3a7805b6321007b96903010c7106d76ae20f61a46f10a", "TANGERINE"),
])
def test_curated_character_sheet_isolates_one_pose_and_identity(sha, fruit):
    prep = reference_preparation(sha, "arbitrary.png", 1312, 1199)
    assert prep["mode"] == "front_pose_crop"
    assert prep["source"] == "verified_sheet"
    assert fruit in prep["identity"]
    image = Image.new("RGB", (1312, 1199), "white")
    original = image.copy()
    clipped = isolated_reference(image, prep)
    assert clipped.width < clipped.height
    assert clipped.width <= 1024 and clipped.height <= 1024
    assert clipped.height >= 768
    assert image.size == original.size
    assert len(CHARACTER_SHEET_RECIPES) >= 3


def test_generic_character_design_sheet_is_isolated_but_normal_photos_are_not():
    landscape = reference_preparation("a"*64, "Nuevo Personaje Character Design Sheet.png", 1312, 1199)
    portrait = reference_preparation("b"*64, "Otra Ficha Visual de Personaje.png", 1122, 1402)
    normal = reference_preparation("c"*64, "Fotograma final.png", 1312, 1199)
    assert landscape["mode"] == portrait["mode"] == "front_pose_crop"
    assert landscape["normalized_box"][2] < portrait["normalized_box"][2]
    assert normal["mode"] == "original_single_reference"
    untouched = isolated_reference(Image.new("RGB", (800, 1100)), normal)
    assert untouched.size == (745, 1024)


def test_invalid_crop_fails_closed():
    im = Image.new("RGB", (1312, 1199))
    with pytest.raises(ValueError, match="límites"):
        isolated_reference(im, {"mode": "front_pose_crop", "normalized_box": [-1, 0, 1, 1]})
    with pytest.raises(ValueError, match="demasiado pequeña"):
        isolated_reference(Image.new("RGB", (80, 80)), {
            "mode": "front_pose_crop", "normalized_box": [0, 0, 0.2, 0.2]})


def test_cast_contract_binds_distinct_people_once_and_keeps_saved_prompt_literal():
    from frutinovelas.services.image_generation import prepare_image_graph
    from test_character_images import graph
    cast = [
        {"name": "Dario", "description": "",
         "reference_preparation": reference_preparation(
             "ccf51d133d2a5aa9c786cc6f2d8ca535bf1933d2ec24b8524ffef1d7e73700ff",
             "sheet.png", 1122, 1402)},
        {"name": "Bruno", "description": "",
         "reference_preparation": reference_preparation(
             "b015af3705b5bd45ddad5e97c1586a4d5a6be1050bf853305dbc238c79847988",
             "sheet.png", 1312, 1199)},
    ]
    literal = "Portrait 9:16. Dario at passenger door, Bruno at driver door."
    frozen = deepcopy(literal)
    out = prepare_image_graph(graph(), literal, cast, 89, ["dario.png", "bruno.png"], "img-job")
    effective = out["positive"]["inputs"]["prompt"]
    assert literal == frozen and effective.startswith(literal)
    assert "EXACTLY 2 DISTINCT VISIBLE CHARACTERS" in effective
    assert "SUBJECT 1 — Dario" in effective and "Reference image 1" in effective
    assert "SUBJECT 2 — Bruno" in effective and "Reference image 2" in effective
    assert "PEAR" in effective and "AVOCADO" in effective
    assert "no background bystanders" in effective
    assert cast_contract([]) == ""
