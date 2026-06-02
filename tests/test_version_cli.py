"""Tests for the `comfy-gen version` CLI verb.

Bead remote_comfy_generator-bmq.2 (A.7.6): dispatches a `health` job to the
Modal app and surfaces the worker's version as {ok, worker_version} for
BlockFlow's semver gate.
"""

from __future__ import annotations

import pytest

from comfy_gen import version_check


@pytest.fixture
def mocked(monkeypatch):
    """Patch the Modal submission + polling boundaries."""
    state: dict = {"sent": [], "health_response": {"version": "0.2.0"}}

    from comfy_gen import modal_client

    def fake_submit_job(job_input, app_name=None):
        state["sent"].append({"job_input": job_input, "app_name": app_name})
        return "job-123"

    monkeypatch.setattr(modal_client, "submit_job", fake_submit_job)
    monkeypatch.setattr(modal_client, "poll_job", lambda **kw: state["health_response"])
    return state


def test_dispatches_health_command_and_reshapes_response(mocked):
    result = version_check.submit_version(app_name="app-1")
    assert result == {"ok": True, "worker_version": "0.2.0"}
    assert mocked["sent"][0] == {"job_input": {"command": "health"}, "app_name": "app-1"}


def test_endpoint_id_is_deprecated_app_name_alias(mocked):
    version_check.submit_version(endpoint_id="legacy-name")
    assert mocked["sent"][0] == {"job_input": {"command": "health"}, "app_name": "legacy-name"}


def test_missing_version_in_response_raises(mocked):
    mocked["health_response"] = {"ok": True}  # no version field
    with pytest.raises(RuntimeError, match="missing version"):
        version_check.submit_version(app_name="app-1")
