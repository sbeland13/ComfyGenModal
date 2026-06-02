"""Download models to the Modal Volume via serverless jobs."""

from __future__ import annotations

import os
from typing import Any

from comfy_gen import output


def submit_download(
    downloads: list[dict[str, Any]],
    timeout: int = 1200,
    poll_interval: int = 5,
    app_name: str | None = None,
) -> dict[str, Any]:
    """Submit a model download job to the Modal app."""
    from comfy_gen import config, modal_client

    cfg = config.load()

    has_civitai = any(d.get("source") == "civitai" for d in downloads)
    civitai_token = cfg.get("civitai_token", "") or os.environ.get("CIVITAI_TOKEN", "")
    if has_civitai and not civitai_token:
        raise ValueError(
            "CivitAI downloads require an API token. Set via:\n"
            "  comfy-gen config --set civitai_token=<your-token>\n"
            "  or env var CIVITAI_TOKEN\n"
            "Get your token at: https://civitai.com/user/account"
        )

    job_input: dict[str, Any] = {
        "command": "download",
        "downloads": downloads,
    }
    if civitai_token:
        job_input["civitai_token"] = civitai_token

    output.log(f"Submitting Modal download job ({len(downloads)} file(s))...")
    job_id = modal_client.submit_job(job_input, app_name=app_name)
    output.log(f"Job submitted: {job_id}")

    def _progress(elapsed: int, status: str, prog: dict[str, Any]) -> None:
        msg = prog.get("message", "")
        pct = prog.get("percent")
        if msg and pct is not None:
            output.log(f"[{elapsed}s] {msg} ({pct:.0f}%)")
        elif msg:
            output.log(f"[{elapsed}s] {msg}")
        else:
            output.log(f"[{elapsed}s] {status}")

    result = modal_client.poll_job(
        job_id=job_id,
        timeout=timeout,
        poll_interval=poll_interval,
        progress_fn=_progress,
    )

    files = result.get("files", [])
    exec_time = result.get("elapsed_seconds", 0)
    output.log(f"Download complete: {len(files)} file(s) in {exec_time}s")
    for f in files:
        output.log(f"  {f.get('filename', '?')} ({f.get('size_mb', '?')} MB) -> {f.get('dest', '?')}")
    return result
