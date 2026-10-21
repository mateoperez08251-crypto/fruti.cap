"""Fixed-loopback transport. No desktop URLs, paths or credentials from MCP."""
import secrets
from pathlib import Path

import httpx

from frutinovelas.config import get_settings
from frutinovelas.services.comfy import cipher


class FlowError(ValueError):
    pass


class FlowIntervention(FlowError):
    """A human verification, quota or rejection must pause the desktop lane."""


class FlowRejected(FlowError):
    """An authenticated agent rejected a request before accepting any work."""


def flow_dir() -> Path:
    folder = get_settings().resolved_data_dir / "flow"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def local_secret(name: str) -> str:
    if name not in ("agent", "mcp"):
        raise ValueError("Unknown credential")
    path = flow_dir() / (name + ".credential")
    # Both processes use the existing local encryption key, never a provider password.
    from frutinovelas.worker import WorkerLock
    lock = WorkerLock(flow_dir() / "credentials.lock")
    if not lock.acquire():
        raise FlowError("El agente está preparando sus credenciales. Reintenta la conexión.")
    try:
        crypt = cipher()
        if not path.exists():
            with path.open("xb") as out:
                out.write(crypt.encrypt(secrets.token_urlsafe(48).encode()))
            path.chmod(0o600)
        return crypt.decrypt(path.read_bytes()).decode()
    finally:
        lock.release()


class FlowClient:
    def __init__(self):
        self.client = httpx.Client(
            base_url=f"http://127.0.0.1:{get_settings().flow_agent_port}/",
            headers={"Authorization": "Bearer " + local_secret("agent")},
            timeout=httpx.Timeout(15, connect=2), trust_env=False, follow_redirects=False,
        )

    def request(self, method, path, body=None):
        response = self.client.request(method, path, json=body) if body is not None else self.client.request(method, path)
        if response.status_code == 404:
            return None
        # 409 may describe an existing/uncertain journal entry, so never infer that
        # remote work stopped from a conflict response.
        if method == "POST" and path == "jobs" and response.status_code in (400, 401, 403, 422):
            raise FlowRejected("El agente no aceptó la solicitud. Comprueba formato, duración, referencias y reservas en su diario.")
        if not response.is_success:
            # Never include a provider response, URL or token in logs/errors.
            raise FlowError("El agente rechazó la operación; revisa su estado local.")
        return response.json()

    def download(self, job_id, destination, limit):
        size = 0
        with self.client.stream("GET", f"jobs/{job_id}/content") as response:
            response.raise_for_status()
            with destination.open("wb") as stream:
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > limit:
                        raise FlowError("El resultado supera el límite de almacenamiento.")
                    stream.write(chunk)

    def close(self):
        self.client.close()
