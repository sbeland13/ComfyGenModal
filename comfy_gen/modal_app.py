"""Modal deployment for the ComfyGen ComfyUI runner."""

from __future__ import annotations

import importlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path
from typing import Any

import modal


APP_NAME = os.environ.get("COMFY_GEN_MODAL_APP_NAME", "comfy-gen")
VOLUME_NAME = os.environ.get("COMFY_GEN_MODAL_VOLUME_NAME", "comfy-gen-comfyui")
SECRET_NAME = os.environ.get("COMFY_GEN_MODAL_SECRET_NAME", "comfy-gen-storage")
JOBS_NAME = os.environ.get("COMFY_GEN_MODAL_JOBS_NAME", "comfy-gen-jobs")
GPU_TYPE = os.environ.get("COMFY_GEN_MODAL_GPU", "H100!")
SINGLE_USE_CONTAINERS = os.environ.get("COMFY_GEN_MODAL_SINGLE_USE_CONTAINERS", "true").lower() not in ("0", "false", "no")
MAX_CONTAINERS = int(os.environ.get("COMFY_GEN_MODAL_MAX_CONTAINERS", "3"))
DOWNLOAD_TIMEOUT = int(os.environ.get("COMFY_GEN_DOWNLOAD_TIMEOUT", "1800"))

BASE_IMAGE = os.environ.get("COMFY_GEN_BASE_IMAGE", "hearmeman/comfyui-serverless:v17")
HANDLER_REPO = os.environ.get(
    "COMFY_GEN_HANDLER_REPO",
    "https://github.com/Hearmeman24/remote-comfy-gen-handler.git",
)
HANDLER_REF = os.environ.get("COMFY_GEN_HANDLER_REF", "main")

COMFYUI_DIR = Path(os.environ.get("COMFYUI_DIR", "/ComfyUI"))
VOLUME_MOUNT = Path("/runpod-volume")
VOLUME_COMFYUI = VOLUME_MOUNT / "ComfyUI"
VOLUME_MODELS = VOLUME_COMFYUI / "models"
VOLUME_CUSTOM_NODES = VOLUME_COMFYUI / "custom_nodes"
HANDLER_DIR = Path("/opt/remote-comfy-gen-handler")
COMFY_LOG = Path("/tmp/comfyui_startup.log")
COMFYUI_PORT = int(os.environ.get("COMFYUI_PORT", "8188"))
COMFY_HOST = f"127.0.0.1:{COMFYUI_PORT}"


app = modal.App(APP_NAME)
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
job_state = modal.Dict.from_name(JOBS_NAME, create_if_missing=True)

image = (
    modal.Image.from_registry(BASE_IMAGE)
    .entrypoint([])
    .run_commands(
        f"rm -rf {HANDLER_DIR}",
        f"git clone --depth 1 --branch {HANDLER_REF} {HANDLER_REPO} {HANDLER_DIR}",
        f"python3 -m pip install -r {HANDLER_DIR}/requirements.txt",
        "python3 -m pip install 'modal>=1.2.6'",
    )
    .env(
        {
            "COMFY_HOST": COMFY_HOST,
            "COMFYUI_DIR": str(COMFYUI_DIR),
            "COMFYUI_PORT": str(COMFYUI_PORT),
            "PIP_CACHE_DIR": str(VOLUME_MOUNT / ".pip-cache"),
        }
    )
)

_COMFY_STARTED = False
_COMFY_PROC: subprocess.Popen | None = None


def _now() -> float:
    return round(time.time(), 3)


def _put_state(job_id: str, **updates: Any) -> None:
    state: dict[str, Any] = {"job_id": job_id, "updated_at": _now()}
    try:
        existing = job_state.get(job_id)
        if isinstance(existing, dict):
            state.update(existing)
    except Exception:
        pass
    state.update(updates)
    state["job_id"] = job_id
    state["updated_at"] = _now()
    job_state.put(job_id, state)


def _patch_legacy_handler_module() -> None:
    """Replace legacy handler progress hooks with Modal Dict updates."""

    class _Serverless:
        @staticmethod
        def progress_update(job: dict, data: dict) -> None:
            job_id = job.get("id", "unknown")
            _put_state(job_id, status="in_progress", **data)

        @staticmethod
        def start(_config: dict) -> None:
            return None

    fake = types.ModuleType("runpod")
    fake.serverless = _Serverless()
    sys.modules["runpod"] = fake


def _ensure_volume_layout() -> None:
    VOLUME_MODELS.mkdir(parents=True, exist_ok=True)
    VOLUME_CUSTOM_NODES.mkdir(parents=True, exist_ok=True)
    (VOLUME_MOUNT / ".pip-cache").mkdir(parents=True, exist_ok=True)

    baked_custom_nodes = COMFYUI_DIR / "custom_nodes"
    seed_stamp = VOLUME_MOUNT / ".custom-nodes-seeded"
    if baked_custom_nodes.exists() and not baked_custom_nodes.is_symlink() and not seed_stamp.exists():
        shutil.copytree(baked_custom_nodes, VOLUME_CUSTOM_NODES, dirs_exist_ok=True, symlinks=True)
        seed_stamp.write_text("seeded\n")
        volume.commit()

    if baked_custom_nodes.is_symlink():
        return

    backup = COMFYUI_DIR / "custom_nodes.baked"
    if baked_custom_nodes.exists() and not backup.exists():
        baked_custom_nodes.rename(backup)
    elif baked_custom_nodes.exists():
        shutil.rmtree(baked_custom_nodes)
    baked_custom_nodes.symlink_to(VOLUME_CUSTOM_NODES, target_is_directory=True)


def _patch_manager_config() -> None:
    manager_config_dir = COMFYUI_DIR / "user" / "__manager"
    manager_config_dir.mkdir(parents=True, exist_ok=True)
    config_file = manager_config_dir / "config.ini"
    if not config_file.exists() or "network_mode = offline" not in config_file.read_text(errors="ignore"):
        config_file.write_text("[default]\nnetwork_mode = offline\nsecurity_level = normal\n")


def _patch_extra_model_paths() -> None:
    extra_paths = COMFYUI_DIR / "extra_model_paths.yaml"
    if not extra_paths.exists():
        extra_paths.write_text(
            "modal_volume:\n"
            "  base_path: /runpod-volume/ComfyUI\n"
            "  checkpoints: models/checkpoints\n"
            "  loras: models/loras\n"
            "  vae: models/vae\n"
            "  clip: models/clip\n"
            "  clip_vision: models/clip_vision\n"
            "  controlnet: models/controlnet\n"
            "  diffusion_models: models/diffusion_models\n"
            "  text_encoders: models/text_encoders\n"
            "  upscale_models: models/upscale_models\n"
            "  embeddings: models/embeddings\n"
        )
        return

    text = extra_paths.read_text(errors="ignore")
    if "detection:" not in text:
        text = text.replace("    vae:", "    detection: detection\n    vae:")
        extra_paths.write_text(text)


def _comfy_command() -> list[str]:
    cmd = [
        "python3",
        "main.py",
        "--listen",
        "0.0.0.0",
        "--port",
        str(COMFYUI_PORT),
        "--disable-auto-launch",
        "--disable-metadata",
    ]
    extra_paths = COMFYUI_DIR / "extra_model_paths.yaml"
    if extra_paths.exists():
        cmd += ["--extra-model-paths-config", str(extra_paths)]
    if os.environ.get("EXPERIMENTAL") == "true":
        cmd += ["--fast", "cublas_ops", "--use-flash-attention"]
    return cmd


def _wait_for_comfy(max_wait: int = 180) -> None:
    import urllib.request

    deadline = time.time() + max_wait
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://{COMFY_HOST}/system_stats", timeout=3) as r:
                r.read()
            return
        except Exception:
            time.sleep(2)
    raise RuntimeError(f"ComfyUI failed to start within {max_wait}s")


def _start_process() -> subprocess.Popen:
    log_file = open(COMFY_LOG, "w")
    return subprocess.Popen(
        _comfy_command(),
        cwd=COMFYUI_DIR,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _broken_nodes_from_log() -> list[str]:
    if not COMFY_LOG.exists():
        return []
    text = COMFY_LOG.read_text(errors="ignore")
    names = set()
    for match in re.finditer(r"IMPORT FAILED.*custom_nodes/([^\"'\s]+)", text):
        names.add(match.group(1).split("/")[0])
    return sorted(names)


def _install_broken_node_deps() -> bool:
    changed = False
    for node_name in _broken_nodes_from_log():
        req_file = VOLUME_CUSTOM_NODES / node_name / "requirements.txt"
        if req_file.exists():
            subprocess.run(
                ["python3", "-m", "pip", "install", "-q", "-r", str(req_file)],
                capture_output=True,
                text=True,
                timeout=300,
            )
            changed = True
    return changed


def _start_comfyui() -> None:
    global _COMFY_PROC, _COMFY_STARTED
    if _COMFY_STARTED:
        return

    volume.reload()
    _ensure_volume_layout()
    _patch_manager_config()
    _patch_extra_model_paths()

    _COMFY_PROC = _start_process()
    _wait_for_comfy()

    if _install_broken_node_deps():
        _COMFY_PROC.terminate()
        try:
            _COMFY_PROC.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _COMFY_PROC.kill()
        _COMFY_PROC = _start_process()
        _wait_for_comfy()

    _COMFY_STARTED = True


TYPE_TO_FOLDER = {
    "checkpoint": "checkpoints",
    "clip": "clip",
    "clip_vision": "clip_vision",
    "controlnet": "controlnet",
    "diffusion_model": "diffusion_models",
    "embeddings": "embeddings",
    "lora": "loras",
    "upscale": "upscale_models",
    "vae": "vae",
    "text_encoder": "text_encoders",
}

FIELD_TO_FOLDER = {
    "ckpt_name": "checkpoints",
    "lora_name": "loras",
    "vae_name": "vae",
    "clip_name": "clip",
    "clip_l_name": "clip",
    "clip_g_name": "clip",
    "unet_name": "diffusion_models",
    "model_name": "checkpoints",
}


def _patch_download_timeouts(download_handler) -> None:
    if getattr(download_handler, "_MODAL_TIMEOUT_PATCHED", False):
        return

    params = inspect.signature(download_handler._download_url).parameters
    if "timeout_sec" in params:
        download_handler._MODAL_TIMEOUT_PATCHED = True
        return

    parse_progress = download_handler._parse_aria2c_progress

    def _send_download_progress(job: dict | None, message: str, percent: float) -> None:
        if not job:
            return
        try:
            sys.modules["runpod"].serverless.progress_update(
                job,
                {"stage": "download", "percent": round(percent, 1), "message": message},
            )
        except Exception:
            pass

    def _download_url(
        url: str,
        dest_dir: str,
        filename: str | None = None,
        job: dict | None = None,
        item_index: int = 0,
        total_items: int = 1,
        **_kwargs,
    ) -> dict:
        os.makedirs(dest_dir, exist_ok=True)
        if not filename:
            filename = url.rstrip("/").rsplit("/", 1)[-1]
            if "?" in filename:
                filename = filename.split("?")[0]

        proc = subprocess.Popen(
            [
                "aria2c",
                "-d",
                dest_dir,
                "-o",
                filename,
                "--allow-overwrite=true",
                "--summary-interval=3",
                "--console-log-level=notice",
                url,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        output_lines = []
        last_progress_time = 0.0
        if proc.stdout:
            for line in proc.stdout:
                output_lines.append(line)
                parsed = parse_progress(line)
                if parsed and job:
                    dl_pct, speed = parsed
                    now = time.time()
                    if now - last_progress_time >= 3:
                        last_progress_time = now
                        base_pct = (item_index / total_items) * 100
                        item_pct = (dl_pct / 100) * (100 / total_items)
                        overall_pct = base_pct + item_pct
                        speed_str = f" ({speed}/s)" if speed else ""
                        _send_download_progress(
                            job,
                            f"Downloading {item_index + 1}/{total_items}: {filename} {dl_pct}%{speed_str}",
                            overall_pct,
                        )

        proc.wait(timeout=DOWNLOAD_TIMEOUT)
        if proc.returncode != 0:
            full_output = "".join(output_lines).strip()
            raise RuntimeError(f"aria2c download failed (exit {proc.returncode}): {full_output}")

        filepath = os.path.join(dest_dir, filename)
        if not os.path.isfile(filepath):
            raise RuntimeError(f"Download completed but file not found: {filepath}")
        size_mb = round(os.path.getsize(filepath) / (1024 * 1024), 1)
        return {"filename": filename, "path": filepath, "size_mb": size_mb}

    def _download_civitai(version_id: str, dest_dir: str, **_kwargs) -> dict:
        os.makedirs(dest_dir, exist_ok=True)
        before = set(os.listdir(dest_dir)) if os.path.isdir(dest_dir) else set()
        result = subprocess.run(
            ["python3", download_handler.CIVITAI_SCRIPT, "-m", str(version_id), "-o", dest_dir],
            capture_output=True,
            text=True,
            timeout=DOWNLOAD_TIMEOUT,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"CivitAI download failed (exit {result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        after = set(os.listdir(dest_dir)) if os.path.isdir(dest_dir) else set()
        new_files = after - before
        if not new_files:
            raise RuntimeError(f"CivitAI download produced no new files. stdout: {result.stdout.strip()}")
        filename = sorted(new_files)[0]
        filepath = os.path.join(dest_dir, filename)
        size_mb = round(os.path.getsize(filepath) / (1024 * 1024), 1)
        return {"filename": filename, "path": filepath, "size_mb": size_mb}

    download_handler._download_url = _download_url
    download_handler._download_civitai = _download_civitai
    download_handler._MODAL_TIMEOUT_PATCHED = True


def _model_dest(missing_model: dict[str, Any]) -> str:
    save_path = str(missing_model.get("save_path") or "").strip().replace("\\", "/")
    model_type = str(missing_model.get("model_type") or "").lower()
    input_field = str(missing_model.get("input_field") or "")

    if not save_path or save_path == "default":
        save_path = TYPE_TO_FOLDER.get(model_type) or FIELD_TO_FOLDER.get(input_field, "checkpoints")
    for prefix in (
        "/runpod-volume/ComfyUI/models/",
        "runpod-volume/ComfyUI/models/",
        "/ComfyUI/models/",
        "ComfyUI/models/",
        "models/",
    ):
        if save_path.startswith(prefix):
            save_path = save_path[len(prefix) :]
    parts = [part for part in save_path.split("/") if part not in ("", ".", "..")]
    return "/".join(parts) or "checkpoints"


def _patch_handler_modules(worker, node_installer, download_handler) -> None:
    if getattr(worker, "_MODAL_PATCHED", False):
        return

    original_check_models = worker._check_models_exist
    original_ensure_nodes = node_installer.ensure_nodes

    def _check_models_exist_and_download(workflow: dict) -> Any:
        job_id = modal.current_function_call_id()
        missing_result = original_check_models(workflow)
        if isinstance(missing_result, tuple):
            missing_models = list(missing_result[0] or [])
        else:
            missing_models = list(missing_result or [])

        downloadable = [m for m in missing_models if m.get("download_url")]
        if not downloadable:
            return missing_result

        total = len(downloadable)
        download_params = inspect.signature(download_handler._download_url).parameters
        for index, model in enumerate(downloadable):
            url = model.get("download_url")
            if isinstance(url, list):
                url = url[0] if url else ""
            if not isinstance(url, str) or not url:
                continue

            filename = model["filename"]
            dest = _model_dest(model)
            dest_dir = str(VOLUME_MODELS / dest)
            _put_state(
                job_id,
                status="in_progress",
                stage="model_download",
                message=f"Downloading missing model {index + 1}/{total}: {filename}",
                percent=12 + (index / max(total, 1)) * 6,
            )
            kwargs: dict[str, Any] = {
                "filename": filename,
                "job": {"id": job_id, "input": {}},
                "item_index": index,
                "total_items": total,
            }
            if "timeout_sec" in download_params:
                kwargs["timeout_sec"] = DOWNLOAD_TIMEOUT
            expected_sha = model.get("sha256") or model.get("hash")
            if expected_sha and "expected_sha" in download_params:
                kwargs["expected_sha"] = expected_sha
            download_handler._download_url(url, dest_dir, **kwargs)

        volume.commit()
        return original_check_models(workflow)

    def _ensure_nodes_and_commit(workflow: dict, *args, **kwargs) -> list[str]:
        installed = original_ensure_nodes(workflow, *args, **kwargs)
        if installed:
            volume.commit()
        return installed

    worker._check_models_exist = _check_models_exist_and_download
    node_installer.ensure_nodes = _ensure_nodes_and_commit
    worker._MODAL_PATCHED = True


def _load_worker_handler():
    if str(HANDLER_DIR) not in sys.path:
        sys.path.insert(0, str(HANDLER_DIR))
    _patch_legacy_handler_module()
    worker = importlib.import_module("worker")
    node_installer = importlib.import_module("node_installer")
    download_handler = importlib.import_module("download_handler")
    _patch_download_timeouts(download_handler)
    _patch_handler_modules(worker, node_installer, download_handler)
    return worker.handler


def _fetch_object_info() -> dict[str, Any]:
    import urllib.request

    with urllib.request.urlopen(f"http://{COMFY_HOST}/object_info", timeout=30) as r:
        data = json.loads(r.read())
    return data if isinstance(data, dict) else {}


def _class_types_from_api_workflow(workflow: dict[str, Any]) -> set[str]:
    return {
        str(node.get("class_type"))
        for node in workflow.values()
        if isinstance(node, dict) and node.get("class_type")
    }


def _convert_ui_workflow_for_handler(
    job_id: str,
    job_input: dict[str, Any],
    node_installer,
) -> dict[str, Any]:
    from comfy_gen import workflow_format

    workflow = job_input.get("workflow")
    if job_input.get("workflow_format") != "ui" and not workflow_format.is_ui_workflow(workflow):
        return job_input
    if not isinstance(workflow, dict):
        raise ValueError("UI workflow payload must be a JSON object")
    if node_installer is None:
        raise RuntimeError("Cannot convert UI workflow because node_installer is not loaded")

    _put_state(
        job_id,
        status="in_progress",
        stage="workflow_convert",
        message="Converting UI workflow to API format",
        percent=4,
    )

    object_info = _fetch_object_info()
    skeleton = workflow_format.ui_workflow_skeleton(workflow)
    missing_types = sorted(_class_types_from_api_workflow(skeleton) - set(object_info.keys()))
    if missing_types:
        _put_state(
            job_id,
            status="in_progress",
            stage="node_check",
            message=f"Installing {len(missing_types)} missing custom node(s) for UI conversion",
            percent=6,
        )

        def _node_progress(msg: str) -> None:
            _put_state(job_id, status="in_progress", stage="node_check", message=msg, percent=7)

        installed = node_installer.ensure_nodes(skeleton, progress_fn=_node_progress)
        if installed:
            volume.commit()
        object_info = _fetch_object_info()

    still_missing = sorted(_class_types_from_api_workflow(skeleton) - set(object_info.keys()))
    if still_missing:
        names = ", ".join(still_missing)
        raise RuntimeError(
            "Cannot convert UI workflow because ComfyUI does not expose "
            f"object_info for: {names}"
        )

    converted = workflow_format.ui_to_api_workflow(workflow, object_info)
    converted_input = dict(job_input)
    converted_input["workflow"] = converted
    converted_input["workflow_format"] = "api"
    converted_input["ui_workflow_converted"] = True
    _put_state(
        job_id,
        status="in_progress",
        stage="workflow_convert",
        message=f"Converted UI workflow ({len(converted)} nodes)",
        percent=8,
    )
    return converted_input


@app.function(
    image=image,
    gpu=GPU_TYPE,
    volumes={str(VOLUME_MOUNT): volume},
    secrets=[modal.Secret.from_name(SECRET_NAME)],
    timeout=3600,
    startup_timeout=900,
    max_containers=MAX_CONTAINERS,
    scaledown_window=60,
    single_use_containers=SINGLE_USE_CONTAINERS,
    name="run_job",
)
def run_job(job_input: dict[str, Any]) -> dict[str, Any]:
    """Run a ComfyGen command or workflow inside Modal."""
    job_id = modal.current_function_call_id()
    started = time.time()
    _put_state(job_id, status="in_progress", stage="init", message="Preparing Modal worker", percent=0)

    try:
        _start_comfyui()
        handler = _load_worker_handler()
        node_installer = sys.modules.get("node_installer")
        job_input = _convert_ui_workflow_for_handler(job_id, job_input, node_installer)
        result = handler({"id": job_id, "input": job_input})
        if not isinstance(result, dict):
            result = {"ok": True, "result": result}
        if isinstance(result.get("error_message"), str):
            result["error_message"] = result["error_message"].replace("network volume", "Modal Volume")
        result.setdefault("job_id", job_id)
        result.setdefault("elapsed_seconds", int(time.time() - started))
        status = "completed" if result.get("ok", True) else "failed"
        _put_state(job_id, status=status, stage=status, message=status, percent=100, result=result)
        volume.commit()
        return result
    except Exception as e:
        error = str(e)
        _put_state(job_id, status="failed", stage="failed", message=error, percent=100, error=error)
        raise


@app.local_entrypoint()
def main() -> None:
    print(json.dumps({"app": APP_NAME, "function": "run_job", "volume": VOLUME_NAME}))
