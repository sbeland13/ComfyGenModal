"""Serverless workflow execution via Modal + S3."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from comfy_gen import output


def _upload_input(local_path: str, cfg: dict | None = None) -> str:
    """Upload a local file and return a URL the worker can download from."""
    from comfy_gen import storage

    return storage.upload_input(local_path, config=cfg)


def _detect_file_inputs(workflow: dict) -> dict[str, dict]:
    """Find LoadImage nodes in a workflow that reference local files."""
    file_inputs = {}
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type", "")
        if class_type != "LoadImage":
            continue
        image_val = node.get("inputs", {}).get("image", "")
        if isinstance(image_val, str) and image_val and os.path.isfile(image_val):
            file_inputs[node_id] = {
                "field": "image",
                "local_path": image_val,
                "filename": Path(image_val).name,
            }
    return file_inputs


def _format_comfy_errors(comfy_err: dict) -> str:
    """Format a parsed ComfyUI error JSON into a readable message."""
    err_type = comfy_err.get("error", {}).get("type", "")
    err_msg = comfy_err.get("error", {}).get("message", "")
    extra = comfy_err.get("error", {}).get("extra_info", {})
    node_errors = comfy_err.get("node_errors", {})

    if err_type == "missing_node_type":
        node_title = extra.get("node_title", "")
        class_type = extra.get("class_type", "")
        return f"Missing custom node: {node_title or class_type}"

    if node_errors:
        lines = ["Workflow validation failed:"]
        for node_id, info in node_errors.items():
            class_type = info.get("class_type", node_id)
            for e in info.get("errors", []):
                details = e.get("details", e.get("message", "unknown error"))
                input_name = e.get("extra_info", {}).get("input_name", "")
                received = e.get("extra_info", {}).get("received_value", "")
                if input_name and received:
                    lines.append(f"  Node {node_id} ({class_type}): '{received}' not found for input '{input_name}'")
                else:
                    if len(details) > 200:
                        details = details[:200] + "..."
                    lines.append(f"  Node {node_id} ({class_type}): {details}")
        return "\n".join(lines)

    if err_msg:
        return f"ComfyUI error: {err_msg}"
    return str(comfy_err)


def _format_job_error(raw_error: Any) -> str:
    """Extract a human-readable error from the worker's raw error payload."""
    if not raw_error:
        return "Unknown error"

    try:
        err = json.loads(raw_error) if isinstance(raw_error, str) else raw_error
    except (json.JSONDecodeError, ValueError):
        err = None

    if isinstance(err, dict) and "error_message" in err:
        msg = err["error_message"]
    elif isinstance(err, dict):
        if "error" in err and "node_errors" in err:
            return _format_comfy_errors(err)
        msg = str(raw_error)
    else:
        msg = str(raw_error)

    json_start = msg.find('{"error"')
    if json_start != -1:
        try:
            comfy_err = json.loads(msg[json_start:])
            return _format_comfy_errors(comfy_err)
        except (json.JSONDecodeError, ValueError):
            pass

    if "Job failed after" in msg:
        idx = msg.find(": ")
        if idx != -1:
            msg = msg[idx + 2 :]

    if "ComfyUI /prompt returned" in msg:
        idx = msg.find(": ")
        if idx != -1:
            remainder = msg[idx + 2 :]
            if not remainder.startswith("{"):
                msg = remainder

    return msg.split("\n")[0] if "\n" in msg else msg


def _progress(elapsed: int, status: str, prog: dict[str, Any]) -> None:
    msg = prog.get("message", "")
    pct = prog.get("percent")
    stage = prog.get("stage", status)
    completed = prog.get("completed_nodes")
    total = prog.get("total_nodes")
    node_prefix = f"({completed}/{total}) " if completed and total else ""

    if msg and pct is not None:
        output.log(f"[{elapsed}s] {stage}: {node_prefix}{msg} ({pct:.0f}%)")
    elif msg:
        output.log(f"[{elapsed}s] {stage}: {node_prefix}{msg}")
    else:
        output.log(f"[{elapsed}s] {status}")


def submit(
    workflow_path: str,
    file_inputs: dict[str, str] | None = None,
    overrides: dict[str, dict] | None = None,
    timeout: int = 1200,
    poll_interval: int = 3,
    app_name: str | None = None,
) -> dict[str, Any]:
    """Submit a workflow to the deployed Modal app."""
    from comfy_gen import modal_client

    with open(workflow_path) as f:
        workflow = json.load(f)

    has_class_type = any(isinstance(v, dict) and "class_type" in v for v in workflow.values())
    if not has_class_type:
        raise ValueError("Workflow is not in ComfyUI API format (no class_type found). Export via 'Save (API Format)'.")

    payload_file_inputs = {}
    auto_detected = _detect_file_inputs(workflow)
    for node_id, info in auto_detected.items():
        output.log(f"Uploading input file: {info['local_path']}")
        url = _upload_input(info["local_path"])
        payload_file_inputs[node_id] = {
            "field": info["field"],
            "url": url,
            "filename": info["filename"],
        }

    if file_inputs:
        for node_id, local_path in file_inputs.items():
            output.log(f"Uploading input file for node {node_id}: {local_path}")
            url = _upload_input(local_path)
            node = workflow.get(node_id, {})
            class_type = node.get("class_type", "") if isinstance(node, dict) else ""
            field = "video" if class_type in ("VHS_LoadVideo", "LoadVideo") else "image"
            payload_file_inputs[node_id] = {
                "field": field,
                "url": url,
                "filename": Path(local_path).name,
            }

    job_input: dict[str, Any] = {
        "workflow": workflow,
        "timeout": timeout,
    }
    if payload_file_inputs:
        job_input["file_inputs"] = payload_file_inputs
    if overrides:
        job_input["overrides"] = overrides

    log_path = Path.home() / ".comfy-gen" / "logs.txt"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as logf:
        logf.write(f"\n{'=' * 80}\n")
        logf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] MODAL run_job\n")
        logf.write(json.dumps(job_input, indent=2))
        logf.write("\n")
    output.log(f"Full request logged to {log_path.resolve()}")

    output.log("Submitting to Modal H100 worker...")
    job_id = modal_client.submit_job(job_input, app_name=app_name)
    output.log(f"Job submitted: {job_id}")

    result = modal_client.poll_job(
        job_id=job_id,
        timeout=timeout,
        poll_interval=poll_interval,
        progress_fn=_progress,
    )

    if result.get("error_message") or result.get("error"):
        result["error_message"] = _format_job_error(result.get("error_message") or result.get("error"))

    url = result.get("output", {}).get("url", "")
    ext = url.rsplit(".", 1)[-1].lower() if url else ""
    media_type = "video" if ext in ("mp4", "webm", "avi", "mov", "mkv", "gif") else "image"
    elapsed = result.get("elapsed_seconds", 0)
    if result.get("ok", True):
        output.log(f"Completed in {elapsed}s. 1 {media_type}")
    return result


def status(job_id: str, app_name: str | None = None) -> dict[str, Any]:
    """Check the status of a Modal job."""
    from comfy_gen import modal_client

    result = modal_client.status(job_id)
    if result.get("error"):
        result["error"] = _format_job_error(result["error"])
    return result


def cancel(job_id: str, app_name: str | None = None) -> dict[str, Any]:
    """Cancel a Modal job."""
    from comfy_gen import modal_client

    return modal_client.cancel(job_id)
