"""Chromium executor route: Studio claim/events/results and the bot's decision logic.

No browser, Flow account or credits are used: the Flow page is a fake and the Studio
API is the real FastAPI app through TestClient.
"""
import json
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from scripts import flow_browser_bot as bot
from sqlalchemy import select

from conftest import png_bytes
from frutinovelas.db import session_factory
from frutinovelas.models import Asset, FlowJob, NarratedVideo
from frutinovelas.services.flow_transport import local_secret


def narrated(client, *, mode="static", aspect="9:16", references=None, title="Historia"):
    project = client.post("/api/v1/projects", json={"name": title}).json()
    with session_factory()() as session:
        audio = Asset(kind="narration", rel_path=f"assets/{uuid4().hex}.wav", sha256=uuid4().hex * 2,
                      mime="audio/wav", duration_seconds=8, size_bytes=10, original_name="voz.wav")
        session.add(audio)
        session.commit()
        audio_id = audio.id
    response = client.post(f"/api/v1/projects/{project['id']}/narrated-videos", json={
        "title": title, "audio_asset_id": audio_id, "transcript": "Texto.", "aspect_ratio": aspect,
        "shots": [{"start_seconds": 0, "end_seconds": 8, "image_prompt": " Fruta «ñ» bajo el sol.\r\n",
                   "animation_prompt": " Mira arriba.\n", "motion": "still", "media_mode": mode,
                   "references": references or []}],
    })
    assert response.status_code == 201, response.text
    return response.json()


def connect_browser(client):
    assert client.post("/api/v1/flow/connect", json={"mode": "browser", "authorized": True}).status_code == 200


def dispatch(client, video, **extra):
    body = {"expected_revision": video["revision"], "request_id": str(uuid4()), **extra}
    response = client.post(f"/api/v1/narrated-videos/{video['id']}/flow", json=body)
    assert response.status_code == 202, response.text
    return response.json()


class ClientAPI:
    """bot.StudioAPI over TestClient."""

    def __init__(self, client, key=None):
        self.client = client
        self.headers = {"X-Fruti-Flow-Bot": key or local_secret("browser")}
        self.events = []

    def _check(self, response):
        if response.status_code >= 400:
            raise RuntimeError(f"Studio rechazó la operación ({response.status_code}): {response.text}")
        return response.json()

    def claim(self):
        return self._check(self.client.post("/api/v1/flow/browser/claim", headers=self.headers))

    def event(self, job_id, event, error="", project_url=None):
        self.events.append(event)
        body = {"event": event, "error": error[:1000], "project_url": project_url}
        return self._check(self.client.post(f"/api/v1/flow/browser/jobs/{job_id}/event", json=body, headers=self.headers))

    def upload(self, job_id, path):
        with open(path, "rb") as stream:
            return self._check(self.client.post(f"/api/v1/flow/browser/jobs/{job_id}/result", headers=self.headers,
                                                files={"file": (Path(path).name, stream, "application/octet-stream")}))


class FakePage:
    created = 0

    def __init__(self, result=None, fail_at=None, known=("old",)):
        self.calls, self.result, self.fail_at, self.known = [], result, fail_at, set(known)
        self.prompt = None
        self.url = None

    def _step(self, name):
        self.calls.append(name)
        if self.fail_at == name:
            raise RuntimeError("control ausente")

    def open_project(self, url):
        self._step("open")
        if not url:
            FakePage.created += 1
            url = f"https://flow.google.com/project/p{FakePage.created}"
            self.calls.append("new_project")
        self.url = url
        return url

    def attach(self, refs):
        self._step("attach")
        self.attached = [Path(r).read_bytes() for r in refs]

    def configure(self, job):
        self._step("configure")
        self.job = job

    def results(self, kind):
        return set(self.known)

    def write_prompt(self, prompt):
        self._step("prompt")
        self.prompt = prompt

    def start_generation(self, **_):
        self._step("start")

    def wait_new_result(self, kind, known, timeout=None, **_):
        self.calls.append(("wait", tuple(sorted(known))))
        return None if self.result is None else "new"

    def download(self, handle, output):
        self.calls.append("download")
        Path(output).write_bytes(self.result)


def factory(page):
    @contextmanager
    def make():
        yield page
    return make


def run(client, tmp_path, page):
    journal = bot.Journal(tmp_path / "journal")
    return bot.run_once(ClientAPI(client), journal, factory(page), tmp_path / "files"), journal


def test_end_to_end_submit_download_assign_with_literal_prompt(client, tmp_path):
    reference_bytes = png_bytes()
    reference = client.post("/api/v1/assets", files={"file": ("ref.png", reference_bytes, "image/png")}).json()
    video = narrated(client, references=[{"asset_id": reference["id"], "role": "identity"}])
    connect_browser(client)
    jobs = dispatch(client, video)["jobs"]
    page = FakePage(result=png_bytes(size=(90, 160)))
    (result, job_id), _ = run(client, tmp_path, page)
    assert (result, job_id) == ("completed", jobs[0]["id"])
    assert page.prompt == " Fruta «ñ» bajo el sol.\r\n"
    assert page.job["aspect_ratio"] == "9:16" and page.job["outputs"] == 1 and page.job["model"] == "Nano Banana 2.1"
    assert page.attached == [reference_bytes]
    # References are attached before configuring; the new tile excludes earlier tiles.
    assert page.calls.index("attach") < page.calls.index("configure") < page.calls.index("prompt") < page.calls.index("start")
    assert ("wait", ("old",)) in page.calls
    synced = client.post(f"/api/v1/narrated-videos/{video['id']}/sync",
                         json={"expected_revision": video["revision"] + 1}).json()["video"]
    with session_factory()() as session:
        job = session.get(FlowJob, job_id)
        assert job.state == "completed"
        assert synced["shots"][0]["image_asset_id"] == job.result_asset_id
        assert hashlib_of(session, job.result_asset_id) == job.result_sha256


def hashlib_of(session, asset_id):
    return session.get(Asset, asset_id).sha256


def test_same_story_reuses_project_and_new_story_creates_another(client, tmp_path):
    FakePage.created = 0
    first = narrated(client, title="Uno")
    second = narrated(client, title="Dos")
    connect_browser(client)
    dispatch(client, first)
    page = FakePage(result=png_bytes(size=(90, 160)))
    assert run(client, tmp_path, page)[0][0] == "completed"
    url = page.url
    # Retry within the same story: same Flow project, no "New project".
    with session_factory()() as session:
        job = session.scalars(select(FlowJob)).one()
        job_id = job.id
    with session_factory()() as session:
        job = session.get(FlowJob, job_id)
        job.state, job.remote_stopped, job.active_key = "failed", True, None
        session.commit()
    retried = client.post(f"/api/v1/flow/jobs/{job_id}/retry", json={"request_id": str(uuid4())})
    assert retried.status_code == 202, retried.text
    again = FakePage(result=png_bytes(color=(1, 2, 3), size=(90, 160)))
    assert run(client, tmp_path, again)[0][0] == "completed"
    assert again.url == url and "new_project" not in again.calls
    dispatch(client, second)
    other = FakePage(result=png_bytes(color=(9, 9, 9), size=(90, 160)))
    assert run(client, tmp_path, other)[0][0] == "completed"
    assert "new_project" in other.calls and other.url != url
    projects = client.get("/api/v1/flow/browser/projects").json()
    assert projects == {first["id"]: url, second["id"]: other.url}


def test_stop_before_click_releases_job_and_click_error_stays_uncertain(client, tmp_path):
    video = narrated(client)
    connect_browser(client)
    dispatch(client, video)
    (result, job_id), _ = run(client, tmp_path, FakePage(fail_at="configure"))
    assert result == "not_submitted"
    with session_factory()() as session:
        job = session.get(FlowJob, job_id)
        assert job.state == "failed" and job.remote_stopped and "control ausente" in job.error
    other = narrated(client, title="Otra")
    dispatch(client, other)
    (result, second_id), journal = run(client, tmp_path, FakePage(fail_at="start"))
    assert result == "uncertain"
    with session_factory()() as session:
        assert session.get(FlowJob, second_id).state == "unknown"
    # The next claim reconciles and never presses Start generation again.
    page = FakePage(result=png_bytes(size=(90, 160)))
    (result, same), _ = bot.run_once(ClientAPI(client), journal, factory(page), tmp_path / "files"), None
    assert result == "uncertain" and same == second_id and "start" not in page.calls
    assert client.post(f"/api/v1/flow/jobs/{second_id}/retry", json={"request_id": str(uuid4())}).status_code == 409


def test_double_claim_never_returns_a_second_submission(client):
    video = narrated(client)
    connect_browser(client)
    dispatch(client, video)
    api = ClientAPI(client)
    first = api.claim()
    second = api.claim()
    assert first["action"] == "submit" and second["action"] == "reconcile"
    assert second["request_id"] == first["request_id"] and second["references"] == []


def test_crash_after_click_recovers_download_without_resubmitting(client, tmp_path):
    video = narrated(client)
    connect_browser(client)
    dispatch(client, video)
    journal = bot.Journal(tmp_path / "journal")
    waiting = FakePage(result=None)
    result, job_id = bot.run_once(ClientAPI(client), journal, factory(waiting), tmp_path / "files")
    assert result == "waiting" and "start" in waiting.calls
    later = FakePage(result=png_bytes(size=(90, 160)))
    result, same = bot.run_once(ClientAPI(client), journal, factory(later), tmp_path / "files")
    assert (result, same) == ("completed", job_id)
    assert "start" not in later.calls and "attach" not in later.calls


def test_invalid_download_is_rejected_and_previous_result_is_kept(client, tmp_path):
    video = narrated(client)
    connect_browser(client)
    dispatch(client, video)
    (result, job_id), _ = run(client, tmp_path, FakePage(result=png_bytes(size=(160, 90))))  # 16:9 for a 9:16 shot
    assert result == "rejected"
    with session_factory()() as session:
        job = session.get(FlowJob, job_id)
        assert job.state == "unknown" and job.result_asset_id is None


def test_bot_routes_require_bot_credential(client):
    connect_browser(client)
    assert client.post("/api/v1/flow/browser/claim").status_code == 401
    assert client.post("/api/v1/flow/browser/claim", headers={"X-Fruti-Flow-Bot": "x"}).status_code == 401
    assert client.post("/api/v1/flow/browser/claim", headers={"X-Fruti-Flow-Key": local_secret("mcp"),
                                                              "X-Fruti-Flow-Bot": local_secret("browser")}).status_code == 401
    assert ClientAPI(client).claim()["action"] == "idle"


def test_browser_mode_rejects_durations_flow_does_not_offer(client):
    video = narrated(client, mode="animated")
    connect_browser(client)
    response = client.post(f"/api/v1/narrated-videos/{video['id']}/flow", json={
        "expected_revision": 1, "request_id": str(uuid4()), "clip_seconds": 5})
    assert response.status_code == 409 and "No se redondea" in response.json()["detail"]
    with session_factory()() as session:
        assert not list(session.scalars(select(FlowJob)))
    ok = client.post(f"/api/v1/narrated-videos/{video['id']}/flow", json={
        "expected_revision": 1, "request_id": str(uuid4()), "clip_seconds": 8})
    assert ok.status_code == 202, ok.text


def test_pinned_version_survives_sync_and_retry(client, tmp_path):
    video = narrated(client)
    connect_browser(client)
    dispatch(client, video)
    assert run(client, tmp_path, FakePage(result=png_bytes(size=(90, 160))))[0][0] == "completed"
    row = client.post(f"/api/v1/narrated-videos/{video['id']}/sync", json={"expected_revision": 2}).json()["video"]
    first_job = row["shots"][0]["flow_image_job_id"]
    first_asset = row["shots"][0]["image_asset_id"]
    pinned = client.post(f"/api/v1/narrated-videos/{video['id']}/select-version", json={
        "expected_revision": row["revision"], "shot_index": 0, "job_id": first_job})
    assert pinned.status_code == 200, pinned.text
    retry = client.post(f"/api/v1/flow/jobs/{first_job}/retry", json={"request_id": str(uuid4())})
    assert retry.status_code == 409  # Completed jobs are not resubmitted.
    with session_factory()() as session:
        job = session.get(FlowJob, first_job)
        job.state, job.remote_stopped = "failed", True
        session.commit()
    new_id = client.post(f"/api/v1/flow/jobs/{first_job}/retry", json={"request_id": str(uuid4())}).json()["id"]
    with session_factory()() as session:
        job = session.get(FlowJob, first_job)
        job.state = "completed"
        session.commit()
    assert run(client, tmp_path, FakePage(result=png_bytes(color=(5, 5, 5), size=(90, 160))))[0][0] == "completed"
    current = pinned.json()["video"]
    synced = client.post(f"/api/v1/narrated-videos/{video['id']}/sync",
                         json={"expected_revision": current["revision"]}).json()["video"]
    assert synced["shots"][0]["flow_image_job_id"] == new_id
    assert synced["shots"][0]["image_asset_id"] == first_asset  # Pin wins; both results kept.
    versions = client.get(f"/api/v1/narrated-videos/{video['id']}/shots/0/versions").json()
    assert {v["id"] for v in versions} == {first_job, new_id}
    assert all(v["state"] == "completed" for v in versions)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg no instalado")
def test_local_montage_mixes_still_and_flow_clip_with_master_audio_only(client, tmp_path):
    from frutinovelas.config import get_settings
    from frutinovelas.services import narrated as renderer
    settings = get_settings()
    work = tmp_path / "media"
    work.mkdir()
    voice, clip = work / "voz.wav", work / "clip.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=7",
                    str(voice)], check=True)
    # Provider clip with its own audio, 4 s: shorter than its 5 s shot (last frame held).
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=576x1024:rate=24:duration=4",
                    "-f", "lavfi", "-i", "sine=frequency=900:duration=4", "-shortest",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(clip)], check=True)
    narration = client.post("/api/v1/assets/narration", files={"file": ("voz.wav", voice.read_bytes(), "audio/wav")})
    assert narration.status_code == 201, narration.text
    image = client.post("/api/v1/assets", files={"file": ("a.png", png_bytes(size=(90, 160)), "image/png")}).json()
    project = client.post("/api/v1/projects", json={"name": "Montaje"}).json()
    duration = narration.json()["duration_seconds"]
    video = client.post(f"/api/v1/projects/{project['id']}/narrated-videos", json={
        "title": "Mixto", "audio_asset_id": narration.json()["id"], "aspect_ratio": "9:16",
        "shots": [{"start_seconds": 0, "end_seconds": 2, "image_asset_id": image["id"], "motion": "zoom_in",
                   "image_prompt": "a", "animation_prompt": "b", "media_mode": "animated"},
                  {"start_seconds": 2, "end_seconds": duration, "image_asset_id": image["id"], "motion": "still",
                   "image_prompt": "a", "animation_prompt": "Saluda", "media_mode": "animated"}],
    }).json()
    connect_browser(client)
    jobs = dispatch(client, video, clip_seconds=4)["jobs"]
    api = ClientAPI(client)
    # Image results for both shots, then approval releases the clip request.
    for _ in range(2):
        assert bot.run_once(api, bot.Journal(tmp_path / "j"), factory(FakePage(result=png_bytes(size=(90, 160)))),
                            tmp_path / "f")[0] == "completed"
    images = [j for j in jobs if j["kind"] == "image"]
    for job in images:
        review = client.post(f"/api/v1/flow/jobs/{job['id']}/review", json={"expected_revision": 1, "decision": "approved"})
        assert review.status_code == 200, review.text
    page = FakePage(result=clip.read_bytes())
    results = [bot.run_once(api, bot.Journal(tmp_path / "j"), factory(page), tmp_path / "f")[0] for _ in range(2)]
    assert results == ["completed", "completed"]
    row = client.get(f"/api/v1/narrated-videos/{video['id']}").json()
    row = client.post(f"/api/v1/narrated-videos/{video['id']}/sync", json={"expected_revision": row["revision"]}).json()["video"]
    with session_factory()() as session:
        stored = session.get(NarratedVideo, video["id"])
        stored.shots = [{**shot, "media_mode": "static" if i == 0 else "animated"} for i, shot in enumerate(stored.shots)]
        stored.state = "queued"
        session.commit()
    renderer.render_video(video["id"])
    final = client.get(f"/api/v1/narrated-videos/{video['id']}").json()
    assert final["state"] == "completed", final["error"]
    output = settings.exports_dir / f"narrated-{video['id']}.mp4"
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                                       "format=duration:stream=codec_type", "-of", "json", str(output)],
                                      capture_output=True, text=True, check=True).stdout)
    kinds = [s["codec_type"] for s in probe["streams"]]
    assert kinds.count("audio") == 1 and kinds.count("video") == 1
    assert abs(float(probe["format"]["duration"]) - duration) < 0.15


def test_real_page_refuses_unverified_video_before_touching_flow_and_compares_newlines():
    with pytest.raises(bot.ControlsMissing):
        bot.FlowPage(object()).configure({"kind": "video"})
    assert bot.same_text(" Fruta\nsol ", " Fruta\r\nsol\r\n")
    assert bot.same_text("Estilo.\nEscena", "Estilo.\n\nEscena")  # Flow's paragraph blocks.
    assert not bot.same_text("Fruta", "Fruta madura")
    assert not bot.same_text("Canción", "Cancion")


def test_confirmed_browser_submission_cannot_be_released_early(client, tmp_path):
    from datetime import timedelta
    from frutinovelas.models import utcnow
    video = narrated(client)
    connect_browser(client)
    dispatch(client, video)
    (result, job_id), _ = run(client, tmp_path, FakePage(result=None))
    assert result == "waiting"
    body = {"confirmed_no_remote_work": True, "note": "No veo nada en la ventana."}
    early = client.post(f"/api/v1/flow/jobs/{job_id}/resolve", json=body)
    assert early.status_code == 409 and "concilie" in early.json()["detail"]
    with session_factory()() as session:
        job = session.get(FlowJob, job_id)
        assert job.state == "running"
        job.updated_at = utcnow() - timedelta(minutes=21)
        session.commit()
    late = client.post(f"/api/v1/flow/jobs/{job_id}/resolve", json=body)
    assert late.status_code == 200, late.text
