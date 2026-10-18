"""Qwen jobs on the same durable GPU queue as H3. No inference during preparation."""

import copy
import hashlib
import json
import secrets

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from frutinovelas.models import Asset, ComfyConnection, GenerationJob
from frutinovelas.schemas import SceneUpdate
from frutinovelas.services import qwen21_workflow, scenes
from frutinovelas.services.comfy import ComfyClient, ComfyError, identity_key
from frutinovelas.services.generation import connection_token
from frutinovelas.services.reference_prep import cast_contract, reference_preparation

EDIT_WORKFLOW = "QWEN_EDIT_2511.api.json"
T2I_WORKFLOW = "QWEN_2512_T2I.api.json"


def ancestors(graph, node_id):
    found = set()

    def visit(id):
        if id in found or id not in graph:
            return
        found.add(id)
        for value in graph[id].get("inputs", {}).values():
            if (
                isinstance(value, list)
                and len(value) == 2
                and isinstance(value[0], str)
                and isinstance(value[1], int)
            ):
                visit(value[0])

    visit(node_id)
    return found


def graph_contract(graph, edit):
    if (
        not isinstance(graph, dict)
        or not graph
        or not all(isinstance(n, dict) and isinstance(n.get("inputs"), dict) for n in graph.values())
    ):
        raise ComfyError("El flujo Qwen no es un grafo API compatible.")
    outputs = [id for id, node in graph.items() if node.get("class_type") == "SaveImage"]
    if len(outputs) != 1:
        raise ComfyError("Se requiere un único SaveImage en el flujo Qwen.")
    active = ancestors(graph, outputs[0])
    samplers = [id for id in active if graph[id].get("class_type") == "KSampler"]
    if len(samplers) != 1:
        raise ComfyError("El flujo Qwen debe tener un único KSampler conectado a SaveImage.")
    sampler = samplers[0]
    positive = graph[sampler]["inputs"].get("positive")
    if not isinstance(positive, list) or len(positive) != 2:
        raise ComfyError("No se reconoce el condicionamiento positivo Qwen.")
    modern = any(graph[id].get("class_type") == "TextEncodeQwenImage21" for id in active)
    kind = (
        "TextEncodeQwenImage21" if modern else ("TextEncodeQwenImageEditPlus" if edit else "CLIPTextEncode")
    )
    encoders = [id for id in ancestors(graph, positive[0]) if graph[id].get("class_type") == kind]
    if len(encoders) != 1:
        raise ComfyError("No se reconoce el codificador de texto del flujo Qwen publicado.")
    return outputs[0], sampler, encoders[0]


def prepare_image_graph(graph, prompt, cast, seed, names, job_id):
    edit = bool(cast)
    output, sampler, encoder = graph_contract(graph, edit)
    if len(cast) != len(names) or len(cast) > 2:
        raise ComfyError("No coinciden los personajes con las referencias subidas.")
    g = copy.deepcopy(graph)
    modern = g[encoder]["class_type"] == "TextEncodeQwenImage21"
    # The editor's literal prompt is preserved. Add deterministic, enforceable-looking
    # cast constraints only to the effective graph submitted to Qwen.
    positive = prompt + cast_contract(cast)
    if edit:
        # Bind actual image tensors to both encoders; never leave template sample images attached.
        for i, name in enumerate(names, 1):
            id = f"fruti_reference_{i}"
            if id in g:
                raise ComfyError("El flujo utiliza un ID reservado para referencias.")
            g[id] = {"class_type": "LoadImage", "inputs": {"image": name}}
        for node in g.values():
            if node.get("class_type") == "TextEncodeQwenImage21":
                for key in list(node["inputs"]):
                    if key == "images" or key.startswith("images."):
                        node["inputs"].pop(key)
                for i, _name in enumerate(names, 1):
                    node["inputs"][f"images.image_{i}"] = [f"fruti_reference_{i}", 0]
            elif node.get("class_type") == "TextEncodeQwenImageEditPlus":
                for i in range(1, 4):
                    node["inputs"].pop(f"image{i}", None)
                    if i <= len(names):
                        node["inputs"][f"image{i}"] = [f"fruti_reference_{i}", 0]
    if modern:
        # Explicit model-native reference indices; keep the saved prompt literal.
        positive += "".join(
            f" <image{i}> is the identity reference for {c.get('name', 'character')} in the new scene."
            for i, c in enumerate(cast, 1)
        )
        if not edit:
            for key in list(g[encoder]["inputs"]):
                if key == "images" or key.startswith("images."):
                    g[encoder]["inputs"].pop(key)
    g[encoder]["inputs"]["prompt" if edit or modern else "text"] = positive
    # Compose a new scene in the video canvas; reference images are identity conditioning.
    if "fruti_canvas" in g:
        raise ComfyError("El flujo utiliza un ID reservado para el canvas.")
    g["fruti_canvas"] = {
        "class_type": "EmptyLatentImage" if modern else "EmptySD3LatentImage",
        "inputs": {
            "width": qwen21_workflow.WIDTH if modern else 576,
            "height": qwen21_workflow.HEIGHT if modern else 1024,
            "batch_size": 1,
        },
    }
    g[sampler]["inputs"]["latent_image"] = ["fruti_canvas", 0]
    g[sampler]["inputs"]["seed"] = seed
    g[output]["inputs"]["filename_prefix"] = "FRUTINOVELAS/IMAGE-" + job_id
    active = ancestors(g, output)
    result = {id: node for id, node in g.items() if id in active}
    if any(
        n.get("class_type") == "LoadImage"
        and id not in {f"fruti_reference_{i}" for i in range(1, len(names) + 1)}
        for id, n in result.items()
    ):
        raise ComfyError("El flujo conserva una imagen de plantilla sin asignar; no se enviará.")
    return result


def public_image_job(job):
    return _image_summary(
        id=job.id,
        scene_id=job.scene_id,
        state=job.state,
        error=job.error,
        revision_number=job.snapshot["revision_number"],
        seed=job.snapshot["seed"],
        references=job.snapshot.get("cast", []),
        result_asset_id=job.result_asset_id,
        created_at=job.created_at,
        auto_finish_done=job.snapshot.get("auto_finish_done", True),
        approval_mode=job.snapshot.get("approval_mode", "manual"),
    )


def _image_summary(
    *,
    id,
    scene_id,
    state,
    error,
    revision_number,
    seed,
    references,
    result_asset_id,
    created_at,
    auto_finish_done=True,
    approval_mode="manual",
):
    return dict(
        id=id,
        scene_id=scene_id,
        kind="image",
        state=state,
        error=error,
        revision_number=revision_number,
        seed=seed,
        references=references or [],
        auto_finish_done=auto_finish_done,
        approval_mode=approval_mode or "manual",
        result_asset_id=result_asset_id,
        created_at=created_at,
        result_url=f"/api/v1/assets/{result_asset_id}/content" if result_asset_id else None,
    )


def list_image_jobs(session, scene_id):
    rows = session.execute(
        select(
            GenerationJob.id,
            GenerationJob.scene_id,
            GenerationJob.state,
            GenerationJob.error,
            GenerationJob.result_asset_id,
            GenerationJob.created_at,
            GenerationJob.snapshot["revision_number"].as_integer().label("revision_number"),
            GenerationJob.snapshot["seed"].as_integer().label("seed"),
            GenerationJob.snapshot["cast"].label("references"),
            GenerationJob.snapshot["auto_finish_done"].as_boolean().label("auto_finish_done"),
            GenerationJob.snapshot["approval_mode"].as_string().label("approval_mode"),
        )
        .where(GenerationJob.scene_id == scene_id, GenerationJob.kind == "image")
        .order_by(GenerationJob.created_at.desc())
    )
    return [_image_summary(**row) for row in rows.mappings()]


def enqueue_image(
    session,
    scene_id,
    expected_revision,
    request_id,
    client_factory=ComfyClient,
    auto_animate=False,
    force_automatic=False,
    runtime_key=None,
    chapter_render_id=None,
):
    scene = scenes.load_scene(session, scene_id)
    existing = session.get(GenerationJob, request_id)
    if existing:
        if (
            existing.scene_id != scene_id
            or existing.kind != "image"
            or existing.snapshot["scene_revision"] != expected_revision
        ):
            raise ComfyError("El ID de petición pertenece a otra operación.")
        return existing
    if scene.revision != expected_revision:
        raise scenes.Conflict(scene.revision)
    rev = scene.current
    parameters = dict(rev.parameters or {}) if rev else {}
    if auto_animate and (not rev or not rev.prompt.strip() or not 4 <= rev.duration_seconds <= 15):
        raise ComfyError(
            "Guarda un prompt H3 y una duración de 4–15 segundos antes de solicitar imagen y video."
        )
    approval_mode = "automatic" if force_automatic else parameters.get("image_approval", "manual")
    if auto_animate and approval_mode != "automatic":
        raise ComfyError("Activa y guarda la aprobación automática antes de solicitar imagen y video.")
    prompt = parameters.get("image_prompt", "")
    if not prompt.strip():
        raise ComfyError("Guarda el prompt de imagen antes de generar con Qwen.")
    cast = copy.deepcopy(parameters.get("cast", []))
    if parameters.get("character_ids", []) != [c["character_id"] for c in cast]:
        raise ComfyError("Vuelve a guardar la selección de personajes antes de generar.")
    # Freeze a single frontal pose per reference image before remote submission.
    # Original library assets and previously generated job snapshots remain unchanged.
    for character in cast:
        asset = session.get(Asset, character["asset_id"])
        if not asset or asset.kind != "image" or asset.sha256 != character.get("sha256"):
            raise ComfyError("La imagen original del personaje cambió o no está disponible.")
        character["reference_preparation"] = reference_preparation(
            asset.sha256, asset.original_name, asset.width, asset.height
        )
    connection = session.get(ComfyConnection, "default")
    if not connection:
        raise ComfyError("Configura la conexión de ComfyUI antes de generar imágenes.")
    url, token, encrypted = connection.url, connection_token(connection), connection.encrypted_token
    saved_identity_key = identity_key(connection.identity)
    snapshot = dict(
        scene_revision=scene.revision,
        revision_number=rev.number,
        prompt=prompt,
        cast=cast,
        seed=parameters.get("seed") if parameters.get("seed_mode") == "fixed" else secrets.randbelow(2**53),
        url=url,
        approval_mode=approval_mode,
        auto_animate=auto_animate,
        chapter_render_id=chapter_render_id,
        auto_finish_done=approval_mode != "automatic",
    )
    if type(snapshot["seed"]) is not int or not 0 <= snapshot["seed"] < 2**53:
        raise ComfyError("La semilla debe ser un entero entre 0 y 9007199254740991.")
    # Release SQLite before remote validation; recheck the revision afterwards.
    session.rollback()
    client = client_factory(url, token)
    try:
        identity = client.get("/frutinovelas/identity")
        if auto_animate and identity_key(identity) != saved_identity_key:
            raise ComfyError(
                "La conexión guardada cambió. Usa Guardar y comprobar antes de generar imagen y video."
            )
        if runtime_key and identity_key(identity) != runtime_key:
            raise ComfyError(
                "Cambió el servidor de este capítulo. El proceso se detiene sin reasignar trabajos."
            )
        modern_filename = qwen21_workflow.EDIT_WORKFLOW if cast else qwen21_workflow.T2I_WORKFLOW
        filename = (
            modern_filename
            if modern_filename in (identity.get("workflows") or {})
            else (EDIT_WORKFLOW if cast else T2I_WORKFLOW)
        )
        expected = (identity.get("workflows") or {}).get(filename)
        if not expected:
            raise ComfyError(f"El servidor no publica {filename}. Activa ese perfil Qwen en RunPod.")
        raw = client.request("GET", "/frutinovelas/workflows/" + filename).content
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ComfyError("No coincide el SHA-256 del flujo Qwen con la identidad del servidor.")
        graph = json.loads(raw)
        graph_contract(graph, bool(cast))
    finally:
        client.close()
    session.expire_all()
    fresh = scenes.load_scene(session, scene_id)
    if fresh.revision != expected_revision:
        raise scenes.Conflict(fresh.revision)
    if session.scalar(select(GenerationJob.id).where(GenerationJob.active_scene_id == scene_id)):
        raise ComfyError("Esta escena tiene una generación en curso. Espera a que termine.")
    snapshot.update(identity=identity, graph=graph)
    job = GenerationJob(
        id=request_id,
        prompt_id=request_id,
        scene_id=scene_id,
        active_scene_id=scene_id,
        kind="image",
        state="queued",
        snapshot=snapshot,
        encrypted_token=encrypted,
    )
    session.add(job)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        existing = session.get(GenerationJob, request_id)
        if (
            existing
            and existing.kind == "image"
            and existing.scene_id == scene_id
            and existing.snapshot["scene_revision"] == expected_revision
        ):
            return existing
        raise ComfyError("Ya hay una generación activa para esta escena.") from exc
    return job


def attach_image(session, job_id, expected_revision, role):
    job = session.get(GenerationJob, job_id)
    if not job or job.kind != "image" or job.state != "completed" or not job.result_asset_id:
        raise ComfyError("La imagen aún no está disponible.")
    scene = scenes.load_scene(session, job.scene_id)
    data = {"expected_revision": expected_revision, f"{role}_asset_id": job.result_asset_id}
    scenes.update_scene(session, scene, SceneUpdate(**data))
    job.snapshot = {**job.snapshot, "approved_scene_revision": scene.revision, "approved_role": role}
    session.commit()
    session.expunge_all()
    return scenes.to_out(scenes.load_scene(session, job.scene_id))


def video_request_id(image_job_id):
    from uuid import UUID, uuid5

    return str(uuid5(UUID(image_job_id), "video"))


def finish_automatic_image(factory, job_id):
    """Resume after restart; attachment and its revision marker commit together."""
    from frutinovelas.services.generation import enqueue, transition

    with factory() as session:
        job = session.get(GenerationJob, job_id)
        if not job or job.state != "completed" or job.snapshot.get("auto_finish_done"):
            return
        try:
            if job.snapshot.get("chapter_render_id"):
                from frutinovelas.models import Chapter, ChapterRender

                run = session.get(ChapterRender, job.snapshot["chapter_render_id"])
                chapter = session.get(Chapter, run.chapter_id) if run else None
                if (
                    not run
                    or not run.active_chapter_id
                    or not chapter
                    or chapter.revision != run.snapshot["chapter_revision"]
                ):
                    raise ComfyError(
                        "El capítulo cambió o su proceso se detuvo. Revisa la imagen antes de continuar."
                    )
            if job.snapshot.get("auto_animate") and session.get(GenerationJob, video_request_id(job_id)):
                pass
            else:
                approved_revision = job.snapshot.get("approved_scene_revision")
                if approved_revision is None:
                    approved = attach_image(
                        session,
                        job_id,
                        job.snapshot["scene_revision"],
                        "start",
                    )
                    approved_revision = approved.revision
                if job.snapshot.get("auto_animate"):
                    connection = session.get(ComfyConnection, "default")
                    if (
                        not connection
                        or connection.url != job.snapshot["url"]
                        or identity_key(connection.identity) != identity_key(job.snapshot["identity"])
                    ):
                        raise ComfyError("Cambió la conexión. Compruébala antes de animar.")
                    video = enqueue(session, job.scene_id, approved_revision, video_request_id(job_id))
                    if video.id != video_request_id(job_id):
                        raise ComfyError(
                            "Otra animación ocupa esta escena. Revisa los trabajos antes de continuar."
                        )
        except (scenes.NotFound, scenes.Conflict, scenes.Invalid, ComfyError) as exc:
            session.rollback()
            transition(
                factory,
                job_id,
                "completed",
                "Continuación automática detenida: " + str(exc),
                expected_states=("completed",),
            )
        session.expire_all()
        job = session.get(GenerationJob, job_id)
        job.snapshot = {**job.snapshot, "auto_finish_done": True}
        session.commit()
