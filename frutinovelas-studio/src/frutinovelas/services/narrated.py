"""Narrated video assembly: subtle FFmpeg motion with the untouched source narration.

Each scene is a photograph with a slowly animated crop; no H3 GPU calls are made.
All media paths are resolved from registered assets, not user supplied paths.
"""
import json
import math
import os
import shutil
import subprocess
import threading
from pathlib import Path

from frutinovelas.config import get_settings
from frutinovelas.db import session_factory
from frutinovelas.models import Asset, NarratedVideo
from frutinovelas.services.assets import asset_path


def _run(args, *, timeout=900):
    proc = subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    if proc.returncode:
        raise ValueError("FFmpeg no pudo procesar los fotogramas o el audio. Revisa los archivos de entrada.")
    return proc


def _motion_filter(motion: str, seconds: float, width: int, height: int) -> str:
    frames = max(1, round(seconds * 24))
    # Begin with a larger padded source to allow controlled motion without black borders.
    zoom = {
        "zoom_in": "1+0.10*on/{frames}",
        "zoom_out": "1.10-0.10*on/{frames}",
        "pan_left": "1.10",
        "pan_right": "1.10",
        "still": "1",
    }[motion].format(frames=frames)
    x = "iw/2-(iw/zoom/2)"
    if motion == "pan_left":
        x = "(iw-iw/zoom)*(1-on/{frames})".format(frames=frames)
    elif motion == "pan_right":
        x = "(iw-iw/zoom)*on/{frames}".format(frames=frames)
    return (f"scale={width*2}:{height*2}:force_original_aspect_ratio=increase,"
            f"crop={width*2}:{height*2},"
            f"zoompan=z='{zoom}':x='{x}':y='ih/2-(ih/zoom/2)':"
            f"d={frames}:s={width}x{height}:fps=24,"
            f"trim=duration={seconds:.5f},setpts=PTS-STARTPTS,format=yuv420p")


def _audio_file(session, row):
    asset = session.get(Asset, row.audio_asset_id)
    if not asset or asset.kind != "narration":
        raise ValueError("El audio de narración ya no está disponible.")
    return asset_path(get_settings(), asset)


def render_video(video_id: str):
    settings = get_settings()
    factory = session_factory()
    tempfiles: list[Path] = []
    with factory() as session:
        video = session.get(NarratedVideo, video_id)
        if not video or video.state != "queued":
            return
        video.state = "rendering"
        video.error = ""
        session.commit()
    try:
        ffmpeg = shutil.which(settings.ffmpeg_path)
        if not ffmpeg:
            raise ValueError("Instala FFmpeg para exportar el video.")
        with factory() as session:
            video = session.get(NarratedVideo, video_id)
            audio = _audio_file(session, video)
            shots = list(video.shots)
            width, height = (576, 1024) if video.aspect_ratio == "9:16" else (1024, 576)
            total = session.get(Asset, video.audio_asset_id).duration_seconds
            clips = []
            for index, shot in enumerate(shots):
                asset = session.get(Asset, shot["image_asset_id"])
                if not asset or asset.kind != "image":
                    raise ValueError(f"Falta la imagen de la toma {index+1}.")
                picture = asset_path(settings, asset)
                seconds = round(shot["end_seconds"]-shot["start_seconds"], 5)
                clip = settings.tmp_dir / f"narrated-{video_id}-{index}.mp4"
                tempfiles.append(clip)
                _run([ffmpeg, "-y", "-nostdin", "-v", "error", "-loop", "1",
                      "-framerate", "24", "-i", str(picture),
                      "-vf", _motion_filter(shot["motion"], seconds, width, height),
                      "-frames:v", str(round(seconds*24)), "-an",
                      "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                      "-pix_fmt", "yuv420p", str(clip)], timeout=180)
                clips.append(clip)
                video.progress = round((index+1)*90/len(shots))
                session.commit()
            concat = settings.tmp_dir / f"narrated-{video_id}-concat.txt"
            tempfiles.append(concat)
            concat.write_text("".join("file '"+str(p).replace("\\","/").replace("'","'\\''")+"'\n" for p in clips), encoding="utf-8")
            output = settings.exports_dir / f"narrated-{video_id}.mp4"
            partial = settings.tmp_dir / f"narrated-{video_id}.partial.mp4"
            tempfiles.append(partial)
            _run([ffmpeg, "-y", "-nostdin", "-v", "error", "-f", "concat", "-safe", "0",
                  "-i", str(concat), "-i", str(audio), "-map", "0:v:0",
                  "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                  "-t", str(total), "-movflags", "+faststart", str(partial)], timeout=300)
            os.replace(partial, output)
            video.result_path = output.relative_to(settings.resolved_data_dir).as_posix()
            video.progress = 100
            video.state = "completed"
            session.commit()
    except Exception as exc:
        with factory() as session:
            row = session.get(NarratedVideo, video_id)
            if row:
                row.state = "failed"
                row.error = str(exc) if isinstance(exc, (ValueError, subprocess.TimeoutExpired)) else "El montaje falló; revisa el registro del programa."
                session.commit()
    finally:
        for path in tempfiles:
            path.unlink(missing_ok=True)


def start_video(video_id: str):
    thread = threading.Thread(target=render_video, args=(video_id,), name="narration-"+video_id[:8], daemon=True)
    thread.start()
