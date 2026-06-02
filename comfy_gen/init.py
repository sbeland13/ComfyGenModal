"""Interactive setup wizard for ComfyGen on Modal."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
import time
from typing import Any

from comfy_gen import config, modal_client, output

BANNER = r"""
   ______                 __       ______
  / ____/___  ____ ___  / __/_  _/ ____/__  ____
 / /   / __ \/ __ `__ \/ /_/ / / / / __/ _ \/ __ \
/ /___/ /_/ / / / / / / __/ /_/ / /_/ /  __/ / / /
\____/\____/_/ /_/ /_/_/  \__, /\____/\___/_/ /_/
                         /____/
                              by HearmemanAI
"""

DEFAULT_APP_NAME = "comfy-gen"
DEFAULT_VOLUME_NAME = "comfy-gen-comfyui"
DEFAULT_SECRET_NAME = "comfy-gen-storage"
DEFAULT_JOBS_NAME = "comfy-gen-jobs"
DEFAULT_GPU = "H100!"

EXAMPLE_MODEL_URL = (
    "https://huggingface.co/Nextcloud-AI/sdxl-turbo/resolve/main/"
    "sd_xl_turbo_1.0_fp16.safetensors"
)
EXAMPLE_WORKFLOW = "examples/sdxl_turbo_portrait.json"


def _log(msg: str = "") -> None:
    print(msg, file=sys.stderr)


def _prompt(label: str, default: str = "", hidden: bool = False) -> str:
    if hidden and default:
        prompt_text = f"  {label} [configured]: "
    elif default:
        prompt_text = f"  {label} [{default}]: "
    else:
        prompt_text = f"  {label}: "
    print(prompt_text, end="", file=sys.stderr, flush=True)
    if hidden:
        value = getpass.getpass(prompt="")
    else:
        value = input()
    return value.strip() or default


def _test_storage(s3_config: dict[str, str]) -> None:
    """Upload a test file to S3, download it back, and verify contents match."""
    import tempfile
    import urllib.request

    try:
        import boto3
        from botocore.config import Config
    except ImportError as e:
        raise RuntimeError("boto3 is required for S3 storage. Install via: pip install boto3") from e

    client_kwargs: dict[str, Any] = {
        "region_name": s3_config.get("s3_region", "eu-west-2"),
        "aws_access_key_id": s3_config["aws_access_key_id"],
        "aws_secret_access_key": s3_config["aws_secret_access_key"],
        "config": Config(signature_version="s3v4"),
    }
    endpoint_url = s3_config.get("s3_endpoint_url", "")
    if endpoint_url:
        client_kwargs["endpoint_url"] = endpoint_url

    client = boto3.client("s3", **client_kwargs)
    bucket = s3_config["s3_bucket"]
    test_key = "comfy-gen/.storage-test"
    test_data = b"comfy-gen storage test"

    client.put_object(Bucket=bucket, Key=test_key, Body=test_data)
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": test_key},
        ExpiresIn=60,
    )
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    try:
        urllib.request.urlretrieve(url, tmp.name)
        downloaded = open(tmp.name, "rb").read()
    finally:
        os.unlink(tmp.name)

    if downloaded != test_data:
        raise RuntimeError("Downloaded content does not match uploaded content")

    client.delete_object(Bucket=bucket, Key=test_key)


def _collect_storage_config(args: argparse.Namespace, non_interactive: bool) -> dict[str, str]:
    s3_config: dict[str, str] = {}
    has_s3_args = getattr(args, "s3_access_key", None) and getattr(args, "s3_secret_key", None)

    if non_interactive and not has_s3_args:
        output.error("S3 storage is required. Provide --s3-access-key, --s3-secret-key, and --s3-bucket.")
    if non_interactive and has_s3_args:
        s3_config = {
            "aws_access_key_id": args.s3_access_key,
            "aws_secret_access_key": args.s3_secret_key,
            "s3_bucket": getattr(args, "s3_bucket", "") or "",
            "s3_region": getattr(args, "s3_region", "eu-west-2") or "eu-west-2",
            "s3_endpoint_url": getattr(args, "s3_endpoint_url", "") or "",
        }
        if not s3_config["s3_bucket"]:
            output.error("--s3-bucket is required when configuring S3 storage.")
        return s3_config

    while True:
        _log()
        _log("  You'll need an API token from your storage provider.")
        _log("  For Cloudflare R2: Dashboard -> R2 -> Manage R2 API Tokens\n")
        s3_config["aws_access_key_id"] = _prompt("Access Key ID")
        s3_config["aws_secret_access_key"] = _prompt("Secret Access Key", hidden=True)
        s3_config["s3_bucket"] = _prompt("Bucket name")
        _log()
        _log("  For AWS S3, the region is e.g. 'us-east-1' or 'eu-west-2'.")
        _log("  For Cloudflare R2, enter 'auto'.\n")
        s3_config["s3_region"] = _prompt("Region", default="auto")
        _log()
        _log("  Endpoint URL is required for non-AWS providers:")
        _log("    Cloudflare R2:  https://<account-id>.r2.cloudflarestorage.com")
        _log("    Backblaze B2:   https://s3.<region>.backblazeb2.com")
        _log("    MinIO:          http://your-minio:9000")
        _log("    AWS S3:         leave empty\n")
        s3_config["s3_endpoint_url"] = _prompt("Endpoint URL (empty for AWS S3)", default="")

        if not s3_config["aws_access_key_id"] or not s3_config["aws_secret_access_key"]:
            _log("  Access key and secret key are required. Try again.\n")
            continue
        if not s3_config["s3_bucket"]:
            _log("  Bucket name is required. Try again.\n")
            continue
        return s3_config


def _secret_env(s3_config: dict[str, str], civitai_token: str = "") -> dict[str, str]:
    env = {
        "AWS_ACCESS_KEY_ID": s3_config["aws_access_key_id"],
        "AWS_SECRET_ACCESS_KEY": s3_config["aws_secret_access_key"],
        "S3_BUCKET": s3_config["s3_bucket"],
        "S3_REGION": s3_config.get("s3_region", "eu-west-2"),
    }
    if s3_config.get("s3_endpoint_url"):
        env["S3_ENDPOINT_URL"] = s3_config["s3_endpoint_url"]
    if civitai_token:
        env["CIVITAI_TOKEN"] = civitai_token
    return env


def _run_example(app_name: str) -> None:
    from comfy_gen import download, serverless

    _log("\n  Downloading SDXL Turbo model (~3.5GB)...")
    _log(f"  comfy-gen download url {EXAMPLE_MODEL_URL} --dest checkpoints\n")
    try:
        dl_result = download.submit_download(
            downloads=[{"source": "url", "url": EXAMPLE_MODEL_URL, "dest": "checkpoints"}],
            timeout=900,
            app_name=app_name,
        )
        if not dl_result.get("ok"):
            _log(f"  Download failed: {dl_result.get('error', 'Unknown error')}")
            return
    except Exception as e:
        _log(f"  Download failed: {e}")
        return

    import pathlib

    pkg_root = pathlib.Path(__file__).resolve().parent.parent
    workflow_path = pkg_root / EXAMPLE_WORKFLOW
    if not workflow_path.exists():
        _log(f"  Example workflow not found at {workflow_path}")
        return

    _log("  Generating a portrait with SDXL Turbo...")
    _log(f"  comfy-gen submit {EXAMPLE_WORKFLOW}\n")
    try:
        result = serverless.submit(
            workflow_path=str(workflow_path),
            timeout=300,
            app_name=app_name,
        )
        url = result.get("output", {}).get("url", "")
        elapsed = result.get("elapsed_seconds", 0)
        if url:
            _log(f"  Image generated in {elapsed}s!")
            _log(f"  View your image: {url}\n")
        else:
            _log(f"  Generation complete in {elapsed}s (no URL in output)\n")
    except Exception as e:
        _log(f"  Generation failed: {e}")


def run(args: argparse.Namespace) -> None:
    """Run the init wizard."""
    non_interactive = getattr(args, "non_interactive", False)

    if config.is_initialized() and not getattr(args, "force", False):
        if non_interactive:
            output.error("Already initialized. Use --force to re-initialize.")
        _log("\n  ComfyGen is already initialized.")
        _log("  Run with --force to re-initialize.\n")
        output.success(config.load_init())

    if not non_interactive:
        _log(BANNER)
        _log("  Welcome to ComfyGen setup. This will deploy a Modal H100 worker")
        _log("  and create a Modal Volume for ComfyUI models and custom nodes.\n")

    cfg = config.load()
    app_name = getattr(args, "app_name", None) or cfg.get("modal_app_name", DEFAULT_APP_NAME)
    volume_name = getattr(args, "volume_name", None) or cfg.get("modal_volume_name", DEFAULT_VOLUME_NAME)
    secret_name = getattr(args, "secret_name", None) or cfg.get("modal_secret_name", DEFAULT_SECRET_NAME)
    jobs_name = getattr(args, "jobs_name", None) or cfg.get("modal_jobs_name", DEFAULT_JOBS_NAME)

    if not non_interactive:
        _log("─── Step 1: Modal Resources ──────────────────────────────────\n")
        _log("  Modal authentication must already be configured.")
        _log("  If needed, run: modal setup\n")
        app_name = _prompt("Modal app name", default=app_name)
        volume_name = _prompt("Modal Volume name", default=volume_name)
        secret_name = _prompt("Modal Secret name", default=secret_name)
        jobs_name = _prompt("Modal job state Dict name", default=jobs_name)

    if not non_interactive:
        _log("\n─── Step 2: Storage ──────────────────────────────────────────\n")
        _log("  ComfyGen needs S3-compatible storage for inputs and outputs.\n")

    s3_config = _collect_storage_config(args, non_interactive)

    _log("  Testing storage connection...")
    try:
        _test_storage(s3_config)
        _log("  Storage test passed\n")
    except Exception as e:
        output.error(f"Storage test failed: {e}")

    civitai_token = getattr(args, "civitai_token", None) or cfg.get("civitai_token", "")
    if not non_interactive:
        _log("─── Step 3: CivitAI Token (optional) ─────────────────────────\n")
        _log("  A CivitAI API token lets workers download models from CivitAI.")
        _log("  Get your token at: https://civitai.com/user/account\n")
        if civitai_token:
            _log("  Existing token configured. Press Enter to keep it.\n")
        civitai_token = _prompt("CivitAI API token", default=civitai_token, hidden=True)

    if not non_interactive:
        _log("─── Step 4: Deploy Modal App ─────────────────────────────────\n")
    _log(f"  Creating/hydrating Modal Volume: {volume_name}")
    _log(f"  Creating/hydrating Modal job state Dict: {jobs_name}")
    try:
        modal_client.ensure_modal_objects(volume_name, jobs_name)
    except Exception as e:
        output.error(
            "Modal authentication failed. Run 'modal setup' or configure "
            f"MODAL_TOKEN_ID/MODAL_TOKEN_SECRET, then retry. Details: {e}"
        )

    _log(f"  Creating/updating Modal Secret: {secret_name}")
    try:
        modal_client.create_or_update_secret(secret_name, _secret_env(s3_config, civitai_token))
    except Exception as e:
        output.error(f"Failed to create/update Modal Secret: {e}")

    _log(f"  Deploying Modal app '{app_name}' on {DEFAULT_GPU}...")
    try:
        modal_client.deploy_app(app_name, volume_name, secret_name, jobs_name)
    except Exception as e:
        output.error(f"Failed to deploy Modal app: {e}")

    cfg["modal_app_name"] = app_name
    cfg["modal_volume_name"] = volume_name
    cfg["modal_secret_name"] = secret_name
    cfg["modal_jobs_name"] = jobs_name
    cfg["modal_function_name"] = "run_job"
    cfg["civitai_token"] = civitai_token
    cfg.update(s3_config)
    config.save(cfg)

    init_data = {
        "initialized_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provider": "modal",
        "app_name": app_name,
        "function_name": "run_job",
        "volume_name": volume_name,
        "secret_name": secret_name,
        "jobs_name": jobs_name,
        "gpu_type": DEFAULT_GPU,
    }
    config.save_init(init_data)

    if not non_interactive:
        _log("\n  Config saved to ~/.comfy-gen/config.json\n")
        _log("─── Step 5: Try It Out ───────────────────────────────────────\n")
        _log("  Want to test your setup with a quick image generation?")
        _log("  This will download a small model (~3.5GB) and generate a portrait.\n")
        try_example = _prompt("Run example? [Y/n]", default="Y")
        if try_example.lower() not in ("n", "no"):
            _run_example(app_name)

        _log("─── Setup Complete ───────────────────────────────────────────\n")
        _log("  Next steps:")
        _log("    1. Download models to your Modal Volume:")
        _log("       comfy-gen download url <huggingface-url> --dest checkpoints")
        _log("    2. Run a workflow:")
        _log("       comfy-gen submit workflow.json\n")

    output.success(init_data)
