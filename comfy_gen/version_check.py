"""Query the Modal app for its worker version via the `health` command.

BlockFlow gates preset installs on a semver check between the preset's
`comfygen_min_version` and the live worker's reported version. Pairs with
serverless-runtime/health_handler.py, which returns {ok, version} fast (no
GPU/model work).
"""

from typing import Any

from comfy_gen import output


def submit_version(
    timeout: int = 60,
    poll_interval: int = 3,
    app_name: str | None = None,
    endpoint_id: str | None = None,
) -> dict[str, Any]:
    """Submit a `health` job and return {ok, worker_version}.

    Args:
        timeout: Max seconds to wait for completion.
        poll_interval: Seconds between status checks.
        app_name: Override Modal app name from config.
        endpoint_id: Deprecated alias for app_name.

    Returns:
        {"ok": True, "worker_version": "X.Y.Z"} on success.

    Raises:
        RuntimeError: on unexpected worker response.
    """
    from comfy_gen import modal_client

    selected_app = app_name or endpoint_id
    job_input = {"command": "health"}

    output.log("Querying worker version on Modal app...")
    job_id = modal_client.submit_job(job_input, app_name=selected_app)

    result = modal_client.poll_job(
        job_id=job_id,
        timeout=timeout,
        poll_interval=poll_interval,
    )

    # The worker's health handler returns {"ok": True, "version": "X.Y.Z"}.
    # Re-shape to BlockFlow's contract: {"ok": True, "worker_version": "..."}.
    worker_version = result.get("version")
    if not worker_version:
        raise RuntimeError(f"Worker health response missing version: {result}")

    return {"ok": True, "worker_version": worker_version}
