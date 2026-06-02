"""Delete files on the Modal Volume via a serverless job.

Thin shim over the worker's `delete` command. The worker enforces a
realpath-based security check that rejects any path which doesn't resolve
strictly under /runpod-volume; missing files are idempotent.
"""

from typing import Any

from comfy_gen import output


def submit_delete(
    paths: list[str],
    timeout: int = 300,
    poll_interval: int = 3,
    app_name: str | None = None,
    endpoint_id: str | None = None,
) -> dict[str, Any]:
    """Submit a delete job to the Modal app.

    Args:
        paths: Absolute paths under /runpod-volume to remove.
        timeout: Max seconds to wait for completion.
        poll_interval: Seconds between status checks.
        app_name: Override Modal app name from config.
        endpoint_id: Deprecated alias for app_name.

    Returns:
        Result dict: {"ok": bool, "results": [{"path", "deleted", "error?"}]}.
    """
    from comfy_gen import modal_client

    selected_app = app_name or endpoint_id
    job_input = {"command": "delete", "paths": paths}

    output.log(f"Deleting {len(paths)} path(s) on Modal Volume...")
    job_id = modal_client.submit_job(job_input, app_name=selected_app)

    output.log(f"Job submitted: {job_id}")

    result = modal_client.poll_job(
        job_id=job_id,
        timeout=timeout,
        poll_interval=poll_interval,
    )

    results = result.get("results", [])
    deleted = sum(1 for r in results if r.get("deleted"))
    output.log(f"Deleted: {deleted}/{len(results)} ({len(results) - deleted} errors/skipped)")
    return result
