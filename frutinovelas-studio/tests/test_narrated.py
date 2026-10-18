"""Narrated mode: audio-length validation, timeline gaps, asset ownership, concurrency."""
import io
import wave
import pytest
from conftest import png_bytes


def wav(seconds=2, rate=8000):
    b = io.BytesIO()
    with wave.open(b, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"\0\0" * (rate * seconds))
    return b.getvalue()


def initial(client, monkeypatch):
    from frutinovelas.routes import narrated
    # Run the actual FFprobe where available; no fake parser in functional tests.
    if not narrated.shutil.which("ffprobe"):
        pytest.skip("FFprobe not installed")
    p = client.post("/api/v1/projects", json={"name": "Narraciones"}).json()
    a = client.post("/api/v1/assets/narration", files={"file": ("voz.wav", wav(), "audio/wav")})
    assert a.status_code == 201, a.text
    created = client.post(f"/api/v1/projects/{p['id']}/narrated-videos", json={
        "title": "Cuento", "audio_asset_id": a.json()["id"], "transcript": "Una vez..."
    })
    assert created.status_code == 201, created.text
    return p, created.json()


def test_create_and_save_timeline(client, monkeypatch):
    p, v = initial(client, monkeypatch)
    assert v["audio_duration"] == pytest.approx(2, abs=.01)
    path = f"/api/v1/narrated-videos/{v['id']}"
    bad = client.patch(path, json={"expected_revision": 1, "shots": [
        {"start_seconds":0,"end_seconds":0.8},
        {"start_seconds":1.0,"end_seconds":2.0}
    ]})
    assert bad.status_code == 422
    saved = client.patch(path, json={"expected_revision": 1, "shots": [
        {"start_seconds": 0, "end_seconds": 1, "image_prompt": "una montaña", "motion": "zoom_in"},
        {"start_seconds": 1, "end_seconds": 2, "image_prompt": "un río", "motion": "pan_right"}
    ]})
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == 2
    assert saved.json()["shots"][1]["image_prompt"] == "un río"
    assert client.patch(path,json={"expected_revision":1,"title":"perdido"}).status_code == 409
    assert len(client.get(f"/api/v1/projects/{p['id']}/narrated-videos").json()) == 1


def test_requires_registered_images(client, monkeypatch):
    _, v = initial(client, monkeypatch)
    path = f"/api/v1/narrated-videos/{v['id']}"
    assert client.post(path+"/render", json={"expected_revision":1}).status_code == 422
    image = client.post("/api/v1/assets",files={"file":("portada.png",png_bytes(),"image/png")})
    assert image.status_code == 201
    updated = client.patch(path,json={"expected_revision":1,"shots":[{
        "start_seconds":0,"end_seconds":2,"image_asset_id":image.json()["id"],"motion":"zoom_in"
    }]})
    assert updated.status_code == 200, updated.text


def test_rejects_oversized_audio(client, monkeypatch):
    from frutinovelas.routes import narrated
    if not narrated.shutil.which("ffprobe"):
        pytest.skip("FFprobe not installed")
    response = client.post("/api/v1/assets/narration",
                           files={"file":("too-long.wav",wav(301),"audio/wav")})
    assert response.status_code == 422
