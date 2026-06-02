"""Query ComfyUI's /object_info via the worker's object_info command.

Lets callers introspect what node classes are installed and their accepted
INPUT_TYPES — useful for pre-validating workflows before submission and for
ad-hoc debugging of 'Value not in list' or 'Required input is missing'
errors.
"""

from typing import Any

from comfy_gen import output


def submit_object_info(
    class_types: list[str] | None = None,
    timeout: int = 120,
    poll_interval: int = 3,
    app_name: str | None = None,
    endpoint_id: str | None = None,
) -> dict[str, Any]:
    """Submit an object_info job to the Modal app.

    Args:
        class_types: Optional list of class names to filter the response.
            Omit (or pass None) to get every installed class.
        timeout: Max seconds to wait for completion.
        poll_interval: Seconds between status checks.
        app_name: Override Modal app name from config.
        endpoint_id: Deprecated alias for app_name.

    Returns:
        Result dict: {"ok": bool, "classes": {"<ClassName>": {input, output, ...}}}.
    """
    from comfy_gen import modal_client

    selected_app = app_name or endpoint_id

    job_input: dict[str, Any] = {"command": "object_info"}
    if class_types:
        job_input["class_types"] = list(class_types)

    n = "all" if not class_types else f"{len(class_types)}"
    output.log(f"Fetching object_info for {n} class(es)...")
    job_id = modal_client.submit_job(job_input, app_name=selected_app)

    output.log(f"Job submitted: {job_id}")

    result = modal_client.poll_job(
        job_id=job_id,
        timeout=timeout,
        poll_interval=poll_interval,
    )

    classes = result.get("classes", {})
    output.log(f"Got info for {len(classes)} class(es)")
    return result
