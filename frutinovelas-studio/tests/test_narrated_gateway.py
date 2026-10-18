"""Remote montage capabilities, auth, resource validation and no arbitrary paths."""
import hashlib
import io
import sys
import uuid
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from comfy_gateway import create_app  # noqa: E402
from narrated_gateway import NarrationStore, AssemblyError  # noqa: E402

TOKEN = "narration-test-token-1234567"
AUTH = {"Authorization": "Bearer " + TOKEN}


@pytest.mark.asyncio
async def test_remote_capabilities_require_auth(tmp_path):
    app = create_app("http://127.0.0.1:1", TOKEN, narration_dir=tmp_path / "narration")
    async with TestClient(TestServer(app)) as client:
        path = "/frutinovelas/narration/capabilities"
        assert (await client.get(path)).status == 401
        response = await client.get(path, headers=AUTH)
        assert response.status == 200
        assert (await response.json())["max_seconds"] == 300
        assert (await client.get("/frutinovelas/narration/jobs/invalid",headers=AUTH)).status == 404


def test_remote_store_rejects_unknown_assets_paths_and_tampered_manifest(tmp_path):
    store = NarrationStore(tmp_path / "narration", tmp_path / "comfy_output")
    with pytest.raises(AssemblyError):
        store.asset("../etc/passwd", "audio")
    with pytest.raises(AssemblyError):
        store.clip("../../outside.mp4", "")
    with pytest.raises(AssemblyError):
        store.validate({"id":str(uuid.uuid4()),"audio_id":"0"*64,"shots":[]})


@pytest.mark.asyncio
async def test_remote_image_upload_checks_content_and_hash(tmp_path):
    app=create_app("http://127.0.0.1:1", TOKEN, narration_dir=tmp_path/"narration")
    data=io.BytesIO()
    Image.new("RGB",(64,112),"red").save(data,"PNG")
    raw=data.getvalue()
    async with TestClient(TestServer(app)) as client:
        form=__import__("aiohttp").FormData()
        form.add_field("kind","image")
        form.add_field("file",raw,filename="shot.png",content_type="image/png")
        response=await client.post("/frutinovelas/narration/assets",data=form,headers=AUTH)
        assert response.status==200,await response.text()
        assert (await response.json())["id"] == hashlib.sha256(raw).hexdigest()
