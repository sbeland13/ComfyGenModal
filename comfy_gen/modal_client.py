"""Modal client helpers for submitting and tracking ComfyGen jobs."""

from __future__ import annotations

import importlib
import os
import sys
import time
from typing import Any, Callable

from comfy_gen import output


def _modal():
    from comfy_gen import config

    config.load()
    try:
        import modal
    except ImportError as e:
        raise RuntimeError(
            "The Modal SDK is required in the Python environment running comfy-gen. "
            f"Install it with: {sys.executable} -m pip install modal"
        ) from e
    return modal


def get_names(app_name: str | None = None) -> dict[str, str]:
    """Return Modal object names from config/env/defaults."""
    from comfy_gen import config

    cfg = config.load()
    return {
        "app_name": app_name or cfg.get("modal_app_name", "comfy-gen"),
        "volume_name": cfg.get("modal_volume_name", "comfy-gen-comfyui"),
        "secret_name": cfg.get("modal_secret_name", "comfy-gen-storage"),
        "jobs_name": cfg.get("modal_jobs_name", "comfy-gen-jobs"),
        "function_name": cfg.get("modal_function_name", "run_job"),
    }


def get_function(app_name: str | None = None):
    """Look up the deployed Modal function."""
    modal = _modal()
    names = get_names(app_name)
    try:
        return modal.Function.from_name(names["app_name"], names["function_name"])
    except Exception as e:
        raise RuntimeError(
            f"Could not find Modal app '{names['app_name']}' function "
            f"'{names['function_name']}'. Run: comfy-gen init"
        ) from e


def get_job_store():
    """Look up the Modal Dict used for progress state."""
    modal = _modal()
    names = get_names()
    return modal.Dict.from_name(names["jobs_name"], create_if_missing=True)


def submit_job(job_input: dict[str, Any], app_name: str | None = None) -> str:
    """Spawn a Modal job and return its FunctionCall ID."""
    fn = get_function(app_name)
    names = get_names(app_name)
    try:
        call = fn.spawn(job_input)
    except Exception as e:
        raise RuntimeError(
            f"Could not submit to Modal app '{names['app_name']}'. "
            "Run 'comfy-gen init' to deploy it."
        ) from e
    return call.object_id


def _get_call_result(job_id: str, timeout: float = 0) -> dict[str, Any] | None:
    modal = _modal()
    call = modal.FunctionCall.from_id(job_id)
    try:
        result = call.get(timeout=timeout)
    except modal.exception.TimeoutError:
        return None
    if not isinstance(result, dict):
        return {"ok": True, "result": result}
    result.setdefault("job_id", job_id)
    return result


def status(job_id: str) -> dict[str, Any]:
    """Return current or completed status for a Modal job."""
    modal = _modal()
    state: dict[str, Any] | None = None
    try:
        maybe_state = get_job_store().get(job_id)
        if isinstance(maybe_state, dict):
            state = maybe_state
    except Exception:
        state = None

    try:
        result = _get_call_result(job_id, timeout=0)
    except modal.exception.OutputExpiredError as e:
        return {"job_id": job_id, "status": "expired", "error": str(e)}
    except Exception as e:
        failed = {"job_id": job_id, "status": "failed", "error": str(e)}
        if state:
            failed.update({k: v for k, v in state.items() if k not in failed})
            failed["status"] = "failed"
            failed["ok"] = False
            failed["error"] = str(e)
        return failed

    if result is not None:
        result.setdefault("status", "completed" if result.get("ok", True) else "failed")
        return result

    if state:
        state.setdefault("job_id", job_id)
        state.setdefault("status", "in_progress")
        return state
    return {"job_id": job_id, "status": "in_progress"}


def cancel(job_id: str) -> dict[str, Any]:
    """Cancel a running Modal FunctionCall."""
    modal = _modal()
    call = modal.FunctionCall.from_id(job_id)
    call.cancel(terminate_containers=True)
    try:
        get_job_store().put(job_id, {"job_id": job_id, "status": "cancelled"})
    except Exception:
        pass
    return {"job_id": job_id, "status": "cancelled"}


def poll_job(
    job_id: str,
    timeout: int = 600,
    poll_interval: int = 5,
    progress_fn: Callable[[int, str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Poll a Modal job until it returns a result."""
    started = time.time()
    last_signature: tuple[Any, ...] | None = None

    while True:
        elapsed = int(time.time() - started)
        if elapsed >= timeout:
            raise TimeoutError(f"Job did not complete within {timeout}s")

        state = status(job_id)
        current_status = state.get("status", "in_progress")

        if current_status in ("completed", "failed"):
            if current_status == "failed":
                state.setdefault("ok", False)
                return state
            return state
        if current_status in ("cancelled", "expired"):
            raise RuntimeError(state.get("error", f"Job {current_status}"))

        signature = (
            current_status,
            state.get("stage"),
            state.get("message"),
            state.get("percent"),
            state.get("completed_nodes"),
            state.get("total_nodes"),
        )
        if signature != last_signature:
            last_signature = signature
            if progress_fn:
                progress_fn(elapsed, current_status, state)
            else:
                msg = state.get("message", "")
                pct = state.get("percent")
                stage = state.get("stage", current_status)
                if msg and pct is not None:
                    output.log(f"[{elapsed}s] {stage}: {msg} ({pct:.0f}%)")
                elif msg:
                    output.log(f"[{elapsed}s] {stage}: {msg}")
                else:
                    output.log(f"[{elapsed}s] {current_status}")

        time.sleep(poll_interval)


def create_or_update_secret(secret_name: str, env: dict[str, str]) -> None:
    """Create or update the Modal Secret used by the deployed worker."""
    modal = _modal()
    modal.Secret.objects.delete(secret_name, allow_missing=True)
    modal.Secret.objects.create(secret_name, env)


def ensure_modal_objects(
    volume_name: str,
    jobs_name: str,
) -> None:
    """Create/hydrate the Modal Volume and progress Dict."""
    modal = _modal()
    modal.Volume.from_name(volume_name, create_if_missing=True).hydrate()
    modal.Dict.from_name(jobs_name, create_if_missing=True).hydrate()


def deploy_app(
    app_name: str,
    volume_name: str,
    secret_name: str,
    jobs_name: str,
) -> None:
    """Deploy the Modal app with the selected object names."""
    modal = _modal()
    os.environ["COMFY_GEN_MODAL_APP_NAME"] = app_name
    os.environ["COMFY_GEN_MODAL_VOLUME_NAME"] = volume_name
    os.environ["COMFY_GEN_MODAL_SECRET_NAME"] = secret_name
    os.environ["COMFY_GEN_MODAL_JOBS_NAME"] = jobs_name

    module_name = "comfy_gen.modal_app"
    if module_name in sys.modules:
        del sys.modules[module_name]
    modal_app = importlib.import_module(module_name)

    with modal.enable_output():
        modal_app.app.deploy(name=app_name)
