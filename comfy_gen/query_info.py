"""Query ComfyUI options via the Modal app."""

from __future__ import annotations

from typing import Any

from comfy_gen import output


def submit_query(
    timeout: int = 60,
    poll_interval: int = 3,
    app_name: str | None = None,
) -> dict[str, Any]:
    """Submit a query_info job to the Modal app."""
    from comfy_gen import modal_client

    job_input = {"command": "query_info"}

    output.log("Querying Modal ComfyUI worker for available options...")
    job_id = modal_client.submit_job(job_input, app_name=app_name)
    output.log(f"Job submitted: {job_id}")

    result = modal_client.poll_job(
        job_id=job_id,
        timeout=timeout,
        poll_interval=poll_interval,
    )

    samplers = result.get("samplers", [])
    schedulers = result.get("schedulers", [])
    loras = result.get("loras", [])
    output.log(f"Found {len(samplers)} samplers, {len(schedulers)} schedulers, {len(loras)} loras")
    return result
