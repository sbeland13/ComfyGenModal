from __future__ import annotations

import os
import types

from comfy_gen.modal_app import _patch_modal_civitai_auth


def _handler(metadata: dict) -> tuple[types.SimpleNamespace, dict]:
    seen: dict = {"metadata": [], "downloads": []}

    def fake_metadata(version_id, token=None):
        seen["metadata"].append({"version_id": version_id, "token": token})
        return metadata

    def fake_download_url(**kwargs):
        seen["downloads"].append(kwargs)
        path = os.path.join(kwargs["dest_dir"], kwargs["filename"])
        os.makedirs(kwargs["dest_dir"], exist_ok=True)
        with open(path, "wb") as f:
            f.write(b"x")
        return {"filename": kwargs["filename"], "path": path, "size_mb": 0.0}

    handler = types.SimpleNamespace(
        _MODAL_CIVITAI_AUTH_PATCHED=False,
        CIVITAI_DOWNLOAD_BASE="https://civitai.com/api/download/models",
        CivitaiMetadataError=RuntimeError,
        _civitai_version_metadata=fake_metadata,
        _find_file_by_sha=lambda *_args, **_kwargs: None,
        _download_url=fake_download_url,
    )
    return handler, seen


def test_modal_civitai_patch_uses_token_query_for_civitai_download(monkeypatch, tmp_path):
    monkeypatch.setenv("CIVITAI_TOKEN", "tok with spaces")
    handler, seen = _handler({
        "filename": "model.safetensors",
        "sha256": "a" * 64,
        "download_url": "https://civitai.com/api/download/models/123?type=Model",
    })

    _patch_modal_civitai_auth(handler)
    handler._download_civitai("123", str(tmp_path))

    assert seen["metadata"] == [{"version_id": "123", "token": "tok with spaces"}]
    call = seen["downloads"][0]
    assert call["url"] == "https://civitai.com/api/download/models/123?type=Model&token=tok+with+spaces"
    assert call["extra_aria_args"] == []


def test_modal_civitai_patch_does_not_add_header_to_signed_storage_url(monkeypatch, tmp_path):
    monkeypatch.setenv("CIVITAI_TOKEN", "secret-token")
    handler, seen = _handler({
        "filename": "model.safetensors",
        "sha256": "b" * 64,
        "download_url": "https://b2.civitai.com/file/x/model.safetensors?Authorization=3_signed",
    })

    _patch_modal_civitai_auth(handler)
    handler._download_civitai("456", str(tmp_path))

    call = seen["downloads"][0]
    assert call["url"] == "https://b2.civitai.com/file/x/model.safetensors?Authorization=3_signed"
    assert call["extra_aria_args"] == []
