"""List model files on the Modal Volume via a serverless job."""

from __future__ import annotations

from typing import Any

from comfy_gen import output


def submit_list(
    model_type: str = "loras",
    timeout: int = 60,
    poll_interval: int = 3,
    app_name: str | None = None,
) -> dict[str, Any]:
    """Submit a list_models job to the Modal app."""
    from comfy_gen import modal_client

    job_input = {
        "command": "list_models",
        "model_type": model_type,
    }

    output.log(f"Listing {model_type} on Modal Volume...")
    job_id = modal_client.submit_job(job_input, app_name=app_name)
    output.log(f"Job submitted: {job_id}")

    result = modal_client.poll_job(
        job_id=job_id,
        timeout=timeout,
        poll_interval=poll_interval,
    )

    files = result.get("files", [])
    output.log(f"Found {len(files)} {model_type} file(s)")
    for f in files:
        output.log(f"  {f.get('filename', '?')} ({f.get('size_mb', '?')} MB)")
    return result
