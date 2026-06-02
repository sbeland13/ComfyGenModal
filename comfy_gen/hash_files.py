"""Hash files already on the Modal Volume via a serverless job.

Lets a caller ask "what's the sha256 of these files you already have?" so they
can decide whether to skip a download. Returns per-path sha256 + bytes (with
per-path errors for missing/inaccessible files).
"""

from typing import Any

from comfy_gen import output


def submit_hash(
    paths: list[str],
    timeout: int = 300,
    poll_interval: int = 3,
    app_name: str | None = None,
    endpoint_id: str | None = None,
) -> dict[str, Any]:
    """Submit a hash job to the Modal app.

    Args:
        paths: Absolute paths on /runpod-volume to hash.
        timeout: Max seconds to wait for completion.
        poll_interval: Seconds between status checks.
        app_name: Override Modal app name from config.
        endpoint_id: Deprecated alias for app_name.

    Returns:
        Result dict: {"ok": bool, "files": [{"path", "sha256", "bytes"} | {"path", "sha256": null, "error"}]}.
    """
    from comfy_gen import modal_client

    selected_app = app_name or endpoint_id
    job_input = {"command": "hash", "paths": paths}

    output.log(f"Hashing {len(paths)} file(s) on Modal Volume...")
    job_id = modal_client.submit_job(job_input, app_name=selected_app)

    output.log(f"Job submitted: {job_id}")

    result = modal_client.poll_job(
        job_id=job_id,
        timeout=timeout,
        poll_interval=poll_interval,
    )

    files = result.get("files", [])
    ok_count = sum(1 for f in files if f.get("sha256"))
    output.log(f"Hashed: {ok_count}/{len(files)} ({len(files) - ok_count} errors)")
    return result
