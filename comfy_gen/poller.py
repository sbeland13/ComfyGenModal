"""Shared polling logic for Modal serverless jobs."""

from __future__ import annotations

from typing import Any


def poll_job(
    job_id: str,
    timeout: int = 600,
    poll_interval: int = 5,
    progress_fn=None,
    **_legacy_kwargs: Any,
) -> dict[str, Any]:
    """Poll a Modal FunctionCall until completion.

    Extra keyword arguments are accepted for compatibility with old call sites.
    """
    from comfy_gen import modal_client

    return modal_client.poll_job(
        job_id=job_id,
        timeout=timeout,
        poll_interval=poll_interval,
        progress_fn=progress_fn,
    )
