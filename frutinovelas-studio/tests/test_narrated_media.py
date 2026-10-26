import array
import hashlib
import io
import json
import math
import shutil
import subprocess
import uuid
import wave

import pytest
from PIL import Image
from scripts.narrated_gateway import AssemblyError, NarrationStore


def test_active_montage_prevents_deleting_its_uploaded_clip(tmp_path):
    import asyncio

    from aiohttp import web

    store = NarrationStore(tmp_path)
    clip_id = "a" * 64
    path = store.assets / (clip_id + ".mp4")
    path.write_bytes(b"retained")
    store.save({"id": str(uuid.uuid4()), "state": "rendering", "manifest": {
        "audio_id": "b" * 64, "shots": [{"clip_id": clip_id}],
    }})
    with pytest.raises(web.HTTPConflict):
        asyncio.run(store.remove_staged_asset(clip_id, "video"))
    assert path.read_bytes() == b"retained"


def test_remote_mixed_images_and_short_clip_preserve_master_audio_duration(tmp_path):
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        pytest.skip("Real FFmpeg and FFprobe are required for the media proof")
    store = NarrationStore(tmp_path / "montage")
    rate, duration = 16000, 2.25
    samples = array.array("h", (int(12000 * math.sin(2 * math.pi * 220 * i / rate)) for i in range(int(rate * duration))))
    audio = io.BytesIO()
    with wave.open(audio, "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(rate)
        stream.writeframes(samples.tobytes())
    audio_id = hashlib.sha256(audio.getvalue()).hexdigest()
    (store.assets / (audio_id + ".wav")).write_bytes(audio.getvalue())
    image = io.BytesIO()
    Image.new("RGB", (160, 90), "blue").save(image, format="PNG")
    image_id = hashlib.sha256(image.getvalue()).hexdigest()
    (store.assets / (image_id + ".png")).write_bytes(image.getvalue())
    original = tmp_path / "short.mp4"
    subprocess.run([ffmpeg, "-y", "-nostdin", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=160x90:r=24",
                    "-f", "lavfi", "-i", "sine=frequency=880:sample_rate=16000", "-t", "0.35",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(original)],
                   check=True, capture_output=True, timeout=30)
    clip_id = hashlib.sha256(original.read_bytes()).hexdigest()
    shutil.copyfile(original, store.assets / (clip_id + ".mp4"))
    job_id = str(uuid.uuid4())
    manifest = {"id": job_id, "audio_id": audio_id, "aspect_ratio": "16:9", "shots": [
        {"start_seconds": 0, "end_seconds": 1.1, "image_id": image_id, "motion": "still"},
        {"start_seconds": 1.1, "end_seconds": duration, "clip_id": clip_id, "motion": "still"},
    ]}
    store.save({"id": job_id, "state": "queued", "manifest": manifest, "progress": 0, "error": ""})
    store.assemble(manifest)
    assert store.read(job_id)["state"] == "completed", store.read(job_id)
    output = store.output / (job_id + ".mp4")
    inspected = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format=duration:stream=codec_type,nb_frames",
                                "-of", "json", str(output)], check=True, capture_output=True, timeout=20)
    info = json.loads(inspected.stdout)
    assert float(info["format"]["duration"]) == pytest.approx(duration, abs=0.06)
    assert len([s for s in info["streams"] if s["codec_type"] == "audio"]) == 1
    decoded = subprocess.run([ffmpeg, "-v", "error", "-i", str(output), "-vn", "-f", "f32le", "-ac", "1", "-ar", str(rate), "-"],
                             check=True, capture_output=True, timeout=20)
    floats = array.array("f")
    floats.frombytes(decoded.stdout)
    def power(frequency):
        sin = sum(value * math.sin(2 * math.pi * frequency * i / rate) for i, value in enumerate(floats))
        cos = sum(value * math.cos(2 * math.pi * frequency * i / rate) for i, value in enumerate(floats))
        return sin * sin + cos * cos
    assert power(220) > 100 * power(880), "The clip soundtrack must not replace the master narration"


def test_uploaded_video_reference_cannot_be_an_arbitrary_path(tmp_path):
    store = NarrationStore(tmp_path)
    with pytest.raises(AssemblyError):
        store.asset("../outside.mp4", "video")
