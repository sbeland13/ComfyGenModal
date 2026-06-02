"""CLI entry point for comfy-gen."""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error

from comfy_gen import output


def _app_name(args: argparse.Namespace) -> str | None:
    return getattr(args, "app_name", None)


def cmd_config(args: argparse.Namespace) -> None:
    from comfy_gen import config

    if args.set:
        key, _, value = args.set.partition("=")
        if not value:
            output.error("Invalid format. Use: --set key=value")
        result = config.set_value(key.strip(), value.strip())
        output.success(result)
    elif args.get:
        value = config.get(args.get)
        if value is None:
            output.error(f"Unknown config key: {args.get}")
        output.success({args.get: value})
    else:
        output.success(config.load())


def cmd_submit(args: argparse.Namespace) -> None:
    from comfy_gen import config, serverless

    cfg = config.load()
    timeout = args.timeout or cfg.get("timeout_seconds", 1200)

    overrides: dict[str, dict] = {}
    if args.override:
        for ov in args.override:
            key, _, value = ov.partition("=")
            if not value:
                output.error(f"Invalid override format: {ov}. Use: node_id.param=value")
            node_id, _, param = key.partition(".")
            if not param:
                output.error(f"Invalid override key: {key}. Use: node_id.param=value")
            try:
                coerced: object = int(value)
            except ValueError:
                try:
                    coerced = float(value)
                except ValueError:
                    coerced = value
            overrides.setdefault(node_id, {})[param] = coerced

    file_inputs: dict[str, str] = {}
    if args.input:
        for inp in args.input:
            node_id, _, path = inp.partition("=")
            if not path:
                output.error(f"Invalid input format: {inp}. Use: node_id=/path/to/file")
            if not os.path.isfile(path):
                output.error(f"Input file not found: {path}")
            file_inputs[node_id] = path

    result = serverless.submit(
        workflow_path=args.workflow,
        file_inputs=file_inputs or None,
        overrides=overrides or None,
        timeout=timeout,
        app_name=_app_name(args),
    )
    print(json.dumps(result))
    sys.exit(1 if not result.get("ok", True) else 0)


def _resolve_install_tokens(args: argparse.Namespace) -> tuple[str | None, str | None]:
    """Env-first, argv-fallback token resolution for install-preset/install-call.

    BlockFlow now passes tokens via COMFY_GEN_CIVITAI_TOKEN / COMFY_GEN_HF_TOKEN
    so they don't show up in `ps` output. The --civitai-token / --hf-token
    flags stay for one release as a fallback, with a stderr deprecation warning.
    """
    env_civitai = os.environ.get("COMFY_GEN_CIVITAI_TOKEN")
    env_hf = os.environ.get("COMFY_GEN_HF_TOKEN")
    if args.civitai_token or args.hf_token:
        print(
            "warning: --civitai-token/--hf-token on argv is deprecated; "
            "use COMFY_GEN_CIVITAI_TOKEN / COMFY_GEN_HF_TOKEN env vars instead",
            file=sys.stderr,
        )
    return env_civitai or args.civitai_token, env_hf or args.hf_token


def cmd_install_preset(args: argparse.Namespace) -> None:
    from comfy_gen import install_preset

    civitai_token, hf_token = _resolve_install_tokens(args)
    rc = install_preset.run(
        preset_id=args.preset_id,
        volume_id=args.volume_id,
        pod_id=None,
        token=None,
        image=args.image,
        port=args.port,
        health_timeout_sec=args.health_timeout_sec,
        keep_alive=args.keep_alive,
        civitai_token=civitai_token,
        hf_token=hf_token,
        runtime_repo_ref=args.runtime_repo_ref,
    )
    sys.exit(rc)


def cmd_install_call(args: argparse.Namespace) -> None:
    from comfy_gen import install_preset

    civitai_token, hf_token = _resolve_install_tokens(args)
    rc = install_preset.run(
        preset_id=args.preset_id,
        volume_id=None,
        pod_id=args.pod_id,
        token=args.token,
        port=args.port,
        keep_alive=args.keep_alive,
        civitai_token=civitai_token,
        hf_token=hf_token,
    )
    sys.exit(rc)


def cmd_status(args: argparse.Namespace) -> None:
    from comfy_gen import serverless

    result = serverless.status(args.job_id, app_name=_app_name(args))
    print(json.dumps(result))
    sys.exit(0 if result.get("status") not in ("failed", "error", "expired") else 1)


def cmd_cancel(args: argparse.Namespace) -> None:
    from comfy_gen import serverless

    result = serverless.cancel(args.job_id, app_name=_app_name(args))
    output.success(result)


def cmd_download(args: argparse.Namespace) -> None:
    from comfy_gen import download

    downloads: list[dict] = []
    if args.batch:
        with open(args.batch) as f:
            downloads = json.load(f)
        if not isinstance(downloads, list):
            output.error("Batch file must contain a JSON array of download specs")
    else:
        if not args.source or not args.target:
            output.error("Usage: comfy-gen download <civitai|url> <version_id|url> [--dest ...]\n  Or:  comfy-gen download --batch <file.json>")
        dl: dict = {"source": args.source, "dest": args.dest}
        if args.source == "civitai":
            dl["version_id"] = args.target
        elif args.source == "url":
            dl["url"] = args.target
            if args.filename:
                dl["filename"] = args.filename
        downloads.append(dl)

    result = download.submit_download(
        downloads=downloads,
        timeout=args.timeout or 1200,
        app_name=_app_name(args),
    )
    print(json.dumps(result))
    sys.exit(0 if result.get("ok", True) else 1)


def cmd_delete(args: argparse.Namespace) -> None:
    from comfy_gen import delete_files

    paths: list[str] = []
    if args.batch:
        with open(args.batch) as f:
            paths = json.load(f)
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            output.error("Batch file must contain a JSON array of path strings")
    else:
        paths = list(args.paths or [])
        if not paths:
            output.error("Usage: comfy-gen delete <path>...\n  Or:  comfy-gen delete --batch <file.json>")

    result = delete_files.submit_delete(
        paths=paths,
        timeout=args.timeout or 300,
        app_name=_app_name(args),
    )
    print(json.dumps(result))
    sys.exit(0 if result.get("ok", True) else 1)


def cmd_object_info(args: argparse.Namespace) -> None:
    from comfy_gen import object_info

    class_types: list[str] = list(args.classes or [])
    result = object_info.submit_object_info(
        class_types=class_types or None,
        timeout=args.timeout or 120,
        app_name=_app_name(args),
    )
    print(json.dumps(result))
    sys.exit(0 if result.get("ok", True) else 1)


def cmd_hash(args: argparse.Namespace) -> None:
    from comfy_gen import hash_files

    paths: list[str] = []
    if args.batch:
        with open(args.batch) as f:
            paths = json.load(f)
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            output.error("Batch file must contain a JSON array of path strings")
    else:
        paths = list(args.paths or [])
        if not paths:
            output.error("Usage: comfy-gen hash <path>...\n  Or:  comfy-gen hash --batch <file.json>")

    result = hash_files.submit_hash(
        paths=paths,
        timeout=args.timeout or 300,
        app_name=_app_name(args),
    )
    print(json.dumps(result))
    sys.exit(0 if result.get("ok", True) else 1)


def cmd_list(args: argparse.Namespace) -> None:
    from comfy_gen import list_models

    result = list_models.submit_list(
        model_type=args.model_type,
        timeout=args.timeout or 60,
        app_name=_app_name(args),
    )
    print(json.dumps(result))
    sys.exit(0 if result.get("ok", True) else 1)


def cmd_info(args: argparse.Namespace) -> None:
    from comfy_gen import query_info

    result = query_info.submit_query(
        timeout=args.timeout or 60,
        app_name=_app_name(args),
    )
    print(json.dumps(result))
    sys.exit(0 if result.get("ok", True) else 1)


def cmd_version(args: argparse.Namespace) -> None:
    from comfy_gen import version_check

    result = version_check.submit_version(
        timeout=args.timeout or 60,
        app_name=_app_name(args),
    )
    print(json.dumps(result))
    sys.exit(0 if result.get("ok") else 1)


def cmd_init(args: argparse.Namespace) -> None:
    from comfy_gen import init

    init.run(args)


def _add_app_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--app-name", metavar="NAME", help="Modal app name (overrides config)")
    parser.add_argument("--endpoint-id", dest="app_name", help=argparse.SUPPRESS)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="comfy-gen",
        description=(
            "Agent-first CLI for executing ComfyUI workflows on Modal H100 workers.\n"
            "All commands output structured JSON to stdout. Human-readable logs go to stderr.\n"
            "\n"
            "Quick start:\n"
            "  comfy-gen init\n"
            "  comfy-gen submit workflow.json\n"
            "\n"
            "Manual config:\n"
            "  comfy-gen config --set modal_app_name=comfy-gen\n"
            "  comfy-gen config --set aws_access_key_id=AKIA...\n"
            "  comfy-gen config --set aws_secret_access_key=...\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_init = subparsers.add_parser(
        "init",
        help="Deploy Modal app, create Modal Volume, and configure storage",
        description=(
            "Deploys the ComfyGen Modal app on H100 GPU hardware, creates a Modal\n"
            "Volume for ComfyUI models/custom nodes, creates a Modal Secret for\n"
            "storage credentials, and verifies S3-compatible input/output storage.\n"
            "\n"
            "Modal authentication must already be configured. Run 'modal setup' or\n"
            "set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET before this command.\n"
            "\n"
            "Non-interactive example:\n"
            "  comfy-gen init --non-interactive --app-name comfy-gen \\\n"
            "    --s3-access-key AKIA... --s3-secret-key ... --s3-bucket my-bucket\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_init.add_argument("--force", action="store_true", help="Re-initialize even if already set up")
    p_init.add_argument("--non-interactive", action="store_true", help="Skip interactive prompts")
    p_init.add_argument("--app-name", default=None, help="Modal app name (default: comfy-gen)")
    p_init.add_argument("--volume-name", default=None, help="Modal Volume name (default: comfy-gen-comfyui)")
    p_init.add_argument("--secret-name", default=None, help="Modal Secret name (default: comfy-gen-storage)")
    p_init.add_argument("--jobs-name", default=None, help="Modal Dict name for job progress (default: comfy-gen-jobs)")
    p_init.add_argument("--s3-access-key", metavar="KEY", help="S3 access key ID")
    p_init.add_argument("--s3-secret-key", metavar="KEY", help="S3 secret access key")
    p_init.add_argument("--s3-bucket", metavar="NAME", help="S3 bucket name")
    p_init.add_argument("--s3-region", metavar="REGION", default="eu-west-2", help="S3 region (default: eu-west-2)")
    p_init.add_argument("--s3-endpoint-url", metavar="URL", help="Custom S3 endpoint for R2/B2/MinIO")
    p_init.add_argument("--civitai-token", metavar="TOKEN", help="CivitAI API token for model downloads")
    p_init.add_argument("--api-key", help=argparse.SUPPRESS)
    p_init.add_argument("--tier", help=argparse.SUPPRESS)
    p_init.add_argument("--volume-size", help=argparse.SUPPRESS)

    p_config = subparsers.add_parser(
        "config",
        help="Manage persistent configuration",
        description=(
            "Read and write persistent configuration stored at ~/.comfy-gen/config.json.\n"
            "\n"
            "Common config keys:\n"
            "  modal_app_name        Modal app name\n"
            "  modal_volume_name     Modal Volume for models/custom nodes\n"
            "  modal_secret_name     Modal Secret with S3 credentials\n"
            "  modal_jobs_name       Modal Dict for job progress\n"
            "  aws_access_key_id     Access key (S3/R2/B2/etc.)\n"
            "  aws_secret_access_key Secret key (S3/R2/B2/etc.)\n"
            "  s3_region             S3 region (default: eu-west-2)\n"
            "  s3_bucket             Bucket name\n"
            "  s3_endpoint_url       Custom endpoint for R2/B2/MinIO/etc.\n"
            "  civitai_token         CivitAI API token for model downloads\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_config.add_argument("--set", metavar="KEY=VALUE", help="Set a config value")
    p_config.add_argument("--get", metavar="KEY", help="Get a single config value by key name")
    p_config.add_argument("--list", action="store_true", help="List all config values")

    p_submit = subparsers.add_parser(
        "submit",
        help="Submit a ComfyUI workflow for execution on Modal",
        description=(
            "Submit a ComfyUI API-format workflow to the deployed Modal app.\n"
            "Local LoadImage file paths are uploaded to S3 automatically. Missing\n"
            "custom nodes are resolved through ComfyUI-Manager and installed onto\n"
            "the Modal Volume. Manager-known missing models are downloaded to the\n"
            "Modal Volume before the workflow is queued.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_submit.add_argument("workflow", help="Path to ComfyUI workflow JSON file (API format)")
    p_submit.add_argument("--input", action="append", metavar="NODE_ID=FILE_PATH", help="Upload a local file for a specific node")
    p_submit.add_argument("--override", action="append", metavar="NODE_ID.PARAM=VALUE", help="Override a workflow parameter")
    p_submit.add_argument("--timeout", type=int, help="Max seconds to wait for completion")
    _add_app_args(p_submit)

    p_status = subparsers.add_parser("status", help="Check the status of a submitted Modal job")
    p_status.add_argument("job_id", help="Modal FunctionCall ID returned by submit/download/list/info")
    _add_app_args(p_status)

    p_cancel = subparsers.add_parser("cancel", help="Cancel a running or queued Modal job")
    p_cancel.add_argument("job_id", help="Modal FunctionCall ID to cancel")
    _add_app_args(p_cancel)

    p_download = subparsers.add_parser(
        "download",
        help="Download models to the Modal Volume",
        description=(
            "Download model files to /runpod-volume/ComfyUI/models/<dest>/ on the\n"
            "Modal Volume. Supports CivitAI model version IDs and direct URLs.\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_download.add_argument(
        "source", nargs="?", choices=["civitai", "url"],
        help="Download source: 'civitai' (model version ID) or 'url' (direct URL)",
    )
    p_download.add_argument(
        "target", nargs="?",
        help="CivitAI model version ID or direct download URL",
    )
    p_download.add_argument(
        "--dest", default="checkpoints",
        help="Model subfolder under /runpod-volume/ComfyUI/models/ (default: checkpoints)",
    )
    p_download.add_argument(
        "--filename", help="Output filename (URL mode only; derived from URL if omitted)",
    )
    p_download.add_argument(
        "--timeout", type=int,
        help=(
            "Max seconds to wait for completion (default: 1200). Plumbed to both "
            "the orchestrator polling loop AND the worker's per-subprocess "
            "(aria2c, civitai-downloader) timeouts. BlockFlow computes this from "
            "the preset's disk_size_estimate_gb as 300 + size_gb * 60."
        ),
    )
    p_download.add_argument(
        "--batch", metavar="FILE",
        help="Path to JSON file with array of download specs (overrides positional args)",
    )
    _add_app_args(p_download)

    # delete
    p_delete = subparsers.add_parser(
        "delete",
        help="Delete files on the Modal Volume by path",
        description=(
            "Delete one or more files on the Modal Volume. The worker\n"
            "validates every path with realpath (symlinks + `..` followed) and\n"
            "rejects anything that doesn't land strictly under /runpod-volume,\n"
            "so /etc/passwd and friends are safe. Missing files are idempotent\n"
            "- they return an error entry rather than failing the batch.\n"
            "\n"
            "DESTRUCTIVE: this permanently removes files from the network\n"
            "volume. There is no trash/undo. Pair with `comfy-gen hash` and\n"
            "`comfy-gen list` if you want to verify what you're about to remove.\n"
            "\n"
            "Output JSON fields:\n"
            "  ok                 true if the batch ran (per-path errors are\n"
            "                     non-fatal and surface in results[].error)\n"
            "  results            Array of:\n"
            "                       {path, deleted: true}                 on success\n"
            "                       {path, deleted: false, error: ...}    on failure\n"
            "                       per-path errors: 'not found',\n"
            "                       'path outside /runpod-volume', or an OSError msg\n"
            "\n"
            "Examples:\n"
            "  comfy-gen delete /runpod-volume/ComfyUI/models/loras/old.safetensors\n"
            "  comfy-gen delete /rv/.../a.safetensors /rv/.../b.safetensors\n"
            "  comfy-gen delete --batch paths.json   # paths.json: [\"/path/a\", ...]\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_delete.add_argument("paths", nargs="*", help="Absolute path(s) under /runpod-volume to delete")
    p_delete.add_argument(
        "--batch", metavar="FILE",
        help="Path to JSON file with array of path strings (overrides positional args)",
    )
    p_delete.add_argument(
        "--timeout", type=int, help="Max seconds to wait for completion (default: 300)",
    )
    _add_app_args(p_delete)

    # object-info
    p_object_info = subparsers.add_parser(
        "object-info",
        help="Introspect ComfyUI node classes (INPUT_TYPES, output spec)",
        description=(
            "Query the remote ComfyUI's /object_info for one or more node\n"
            "classes — returns each class's accepted required/optional inputs\n"
            "(including dropdown enums) and output spec.\n"
            "\n"
            "Useful for diagnosing 'Value not in list' or 'Required input is\n"
            "missing' errors: hit the live endpoint to see exactly what the\n"
            "currently-deployed node version accepts. Pair with the smoke\n"
            "gate's pre-flight validator (automation/validate_workflow.py)\n"
            "for batch workflow validation.\n"
            "\n"
            "Pass class names as positional args; omit to get every installed\n"
            "class (large payload; ComfyUI usually registers 200+).\n"
            "\n"
            "Output JSON fields:\n"
            "  ok                 true if the call succeeded\n"
            "  classes            Object keyed by class_type; each value is the\n"
            "                     raw ComfyUI INPUT_TYPES shape:\n"
            "                       {input: {required, optional}, output, output_name, ...}\n"
            "  job_id             Modal FunctionCall ID\n"
            "\n"
            "Examples:\n"
            "  comfy-gen object-info KSampler\n"
            "  comfy-gen object-info OnnxDetectionModelLoader OpenRouterNode\n"
            "  comfy-gen object-info               # returns ALL ~200+ classes\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_object_info.add_argument(
        "classes", nargs="*",
        help="Node class names to fetch (omit for all installed classes)",
    )
    p_object_info.add_argument(
        "--timeout", type=int, help="Max seconds to wait for completion (default: 120)",
    )
    _add_app_args(p_object_info)

    # hash
    p_hash = subparsers.add_parser(
        "hash",
        help="SHA256 + size for files already on the network volume",
        description=(
            "Compute sha256 + size for one or more files already on the Modal\n"
            "network volume. Submit paths and the worker streams the hash of\n"
            "each file (in 64 KiB chunks) and returns per-path results.\n"
            "\n"
            "Use this to decide whether to skip a download — pair the result\n"
            "with `comfy-gen download`'s sha256-based dedup so a file that\n"
            "already matches the expected hash is not re-fetched.\n"
            "\n"
            "Security: paths are resolved via realpath on the worker; any\n"
            "path that doesn't resolve under /runpod-volume is rejected per-\n"
            "path (the batch still completes with an error entry).\n"
            "\n"
            "Output JSON fields:\n"
            "  ok                 true if the batch ran (per-file errors are\n"
            "                     non-fatal and surface in files[].error)\n"
            "  files              Array of:\n"
            "                       {path, sha256, bytes}            on success\n"
            "                       {path, sha256: null, error: ...} on failure\n"
            "                       per-path errors: 'not found',\n"
            "                       'not a file', 'path outside /runpod-volume'\n"
            "\n"
            "Examples:\n"
            "  comfy-gen hash /runpod-volume/ComfyUI/models/loras/my.safetensors\n"
            "  comfy-gen hash /rv/.../a.safetensors /rv/.../b.safetensors\n"
            "  comfy-gen hash --batch paths.json   # paths.json: [\"/path/a\", ...]\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_hash.add_argument("paths", nargs="*", help="Absolute path(s) under /runpod-volume to hash")
    p_hash.add_argument(
        "--batch", metavar="FILE",
        help="Path to JSON file with array of path strings (overrides positional args)",
    )
    p_hash.add_argument(
        "--timeout", type=int, help="Max seconds to wait for completion (default: 300)",
    )
    _add_app_args(p_hash)

    # list
    p_list = subparsers.add_parser(
        "list",
        help="List model files on the Modal Volume",
        description=(
            "List model files installed on the Modal Volume by submitting\n"
            "a lightweight job to the Modal app. Scans both the baked-in\n"
            "ComfyUI models directory and the network volume, plus any paths from\n"
            "extra_model_paths.yaml.\n"
            "\n"
            "Supported model types (subfolder under models/):\n"
            "  loras              LoRA models (default)\n"
            "  checkpoints        SD, SDXL, Flux, Wan, etc.\n"
            "  vae                VAE models\n"
            "  clip               CLIP models\n"
            "  diffusion_models   Diffusion model weights\n"
            "  text_encoders      Text encoder weights\n"
            "  controlnet         ControlNet models\n"
            "  upscale_models     Upscaler models\n"
            "  embeddings         Text embeddings\n"
            "\n"
            "Output JSON fields:\n"
            "  ok                 true on success\n"
            "  model_type         The model type queried\n"
            "  files              Array of {filename, path, size_mb}\n"
            "  search_paths       Directories that were scanned\n"
            "  job_id             Modal FunctionCall ID\n"
            "\n"
            "Examples:\n"
            "  comfy-gen list loras\n"
            "  comfy-gen list checkpoints\n"
            "  comfy-gen list diffusion_models --app-name comfy-gen\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_list.add_argument(
        "model_type", nargs="?", default="loras",
        help="Model type to list (default: loras)",
    )
    p_list.add_argument(
        "--timeout", type=int, help="Max seconds to wait for completion (default: 60)",
    )
    _add_app_args(p_list)

    # info
    p_info = subparsers.add_parser(
        "info",
        help="Query available samplers, schedulers, and LoRAs from the endpoint",
        description=(
            "Query the remote ComfyUI instance for all dynamic configuration values.\n"
            "Returns available samplers, schedulers, and installed LoRA models in a\n"
            "single response. These are consolidated because they are dynamic options\n"
            "that the BlockFlow UI needs to populate dropdowns and selectors.\n"
            "\n"
            "Output JSON fields:\n"
            "  ok                 true on success\n"
            "  volume_root        Absolute path the worker mounts as the network\n"
            "                     volume root (e.g. /runpod-volume). Callers cache\n"
            "                     this and build model paths from it instead of\n"
            "                     hardcoding the mount point.\n"
            "  samplers           Array of available sampler names\n"
            "  schedulers         Array of available scheduler names\n"
            "  loras              Array of {filename, path, size_mb}\n"
            "  job_id             Modal FunctionCall ID\n"
            "\n"
            "Examples:\n"
            "  comfy-gen info\n"
            "  comfy-gen info --app-name comfy-gen\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_info.add_argument(
        "--timeout", type=int, help="Max seconds to wait for completion (default: 60)",
    )
    _add_app_args(p_info)

    # version (bead bmq.2 / A.7.6) - BlockFlow semver gate against preset's comfygen_min_version
    p_version = subparsers.add_parser(
        "version",
        help="Query the worker version reported by the Modal app",
        description=(
            "Submit a `health` job to the Modal app and report the worker's version. Used\n"
            "by BlockFlow to gate preset installs against a preset-declared\n"
            "`comfygen_min_version`. Cheap call - no GPU/model work.\n"
            "\n"
            "Output JSON fields:\n"
            "  ok                 true on success\n"
            "  worker_version     Semver string reported by the worker (e.g. \"0.2.0\")\n"
            "\n"
            "Exit codes:\n"
            "  0 — ok=true\n"
            "  1 — ok=false or unreachable endpoint\n"
            "\n"
            "Examples:\n"
            "  comfy-gen version\n"
            "  comfy-gen version --app-name comfy-gen\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_version.add_argument("--timeout", type=int, help="Max seconds to wait for completion (default: 60)")
    _add_app_args(p_version)

    # install-preset (bead 5f2)
    p_install = subparsers.add_parser(
        "install-preset",
        help="Spawn a CPU installer pod and stream a BlockFlow preset install over SSE",
        description=(
            "Spawn a CPU installer pod, wait for /health, POST /install/<preset_id>, and\n"
            "stream the server-sent-events response as line-delimited JSON to stdout. The\n"
            "pod self-terminates on /shutdown unless --keep-alive is set.\n"
            "\n"
            "Each stdout line is one event:\n"
            "  {\"type\": \"pod_spawned\", \"pod_id\", \"token\"}\n"
            "  {\"type\": \"preflight_start\"}\n"
            "  {\"type\": \"preflight_ok\", \"models_count\", \"total_bytes\", \"volume_free_bytes\"}\n"
            "  {\"type\": \"preflight_fail\", \"reason\"}\n"
            "  {\"type\": \"download_start\", \"file_index\", \"file\"}\n"
            "  {\"type\": \"download_done\",  \"file_index\", \"file\", \"cached\", \"bytes\", \"sha256\"}\n"
            "  {\"type\": \"install_done\",   \"ok\", \"files\", \"elapsed_sec\"}\n"
            "  {\"type\": \"install_error\",  \"stage\", \"reason\"}\n"
            "\n"
            "Exit codes:\n"
            "  0 — install_done.ok == true\n"
            "  1 — install_error, preflight_fail, health timeout, or stream error\n"
            "\n"
            "Token env vars (preferred over --civitai-token / --hf-token):\n"
            "  COMFY_GEN_CIVITAI_TOKEN  CivitAI API token forwarded to the worker\n"
            "  COMFY_GEN_HF_TOKEN       HuggingFace token forwarded to the worker\n"
            "Argv flags still work for one release as a fallback; using them emits\n"
            "a stderr deprecation warning. Env vars keep tokens out of `ps` output.\n"
            "\n"
            "Examples:\n"
            "  comfy-gen install-preset --preset-id qwen-image-lighting --volume-id 7etzak7vfp\n"
            "  comfy-gen install-preset --preset-id wan-video --volume-id <vid> --keep-alive\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_install.add_argument("--preset-id", required=True, help="Preset id from the BlockFlow preset registry manifest")
    p_install.add_argument("--volume-id", help="RunPod network volume id to attach (required for spawn)")
    p_install.add_argument("--image", default="hearmeman/comfyui-serverless:installer-v6", help="Installer image (default: hearmeman/comfyui-serverless:installer-v6)")
    p_install.add_argument("--port", type=int, default=3000, help="Pod port (default: 3000)")
    p_install.add_argument("--keep-alive", action="store_true", help="Skip the /shutdown call so the pod stays available for follow-up installs")
    p_install.add_argument("--health-timeout-sec", type=int, default=180, help="Max seconds to wait for the pod's /health to come up (default: 180)")
    p_install.add_argument("--civitai-token", help="DEPRECATED — pass via COMFY_GEN_CIVITAI_TOKEN env var instead. Argv exposes the token to `ps`/process listings; the env var path keeps it out. Flag kept for one release for back-compat; emits a stderr warning when used.")
    p_install.add_argument("--hf-token", help="DEPRECATED — pass via COMFY_GEN_HF_TOKEN env var instead. Same rationale as --civitai-token.")
    p_install.add_argument("--runtime-repo-ref", metavar="REF", help="Override RUNTIME_REPO_REF (git ref the pod clones at boot)")

    # install-call (bead 5f2) — drive an existing pod without spawning
    p_install_call = subparsers.add_parser(
        "install-call",
        help="Drive an existing installer pod's /install endpoint (no spawn)",
        description=(
            "Stream an install against a pod that's already running. Use this for\n"
            "multi-op flows (install preset A, then B on the same pod) so you don't\n"
            "pay another cold start.\n"
            "\n"
            "Same stdout shape and exit codes as `install-preset`.\n"
            "\n"
            "Examples:\n"
            "  comfy-gen install-call --pod-id abc123 --token <t> --preset-id wan-video\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_install_call.add_argument("--pod-id", required=True, help="Running installer pod id")
    p_install_call.add_argument("--token", required=True, help="INSTALLER_TOKEN the pod was spawned with")
    p_install_call.add_argument("--preset-id", required=True, help="Preset id from the manifest")
    p_install_call.add_argument("--port", type=int, default=3000)
    p_install_call.add_argument("--keep-alive", action="store_true")
    p_install_call.add_argument("--civitai-token", help="DEPRECATED — pass via COMFY_GEN_CIVITAI_TOKEN env var instead.")
    p_install_call.add_argument("--hf-token", help="DEPRECATED — pass via COMFY_GEN_HF_TOKEN env var instead.")

    args = parser.parse_args()

    try:
        {
            "init": cmd_init,
            "config": cmd_config,
            "submit": cmd_submit,
            "download": cmd_download,
            "delete": cmd_delete,
            "hash": cmd_hash,
            "object-info": cmd_object_info,
            "status": cmd_status,
            "cancel": cmd_cancel,
            "list": cmd_list,
            "info": cmd_info,
            "version": cmd_version,
            "install-preset": cmd_install_preset,
            "install-call": cmd_install_call,
        }[args.command](args)
    except ValueError as e:
        output.error(str(e))
    except FileNotFoundError as e:
        output.error(str(e))
    except RuntimeError as e:
        output.error(str(e))
    except ConnectionError as e:
        output.error(f"Connection failed: {e}")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            output.error("HTTP 401 Unauthorized. Check your storage or Modal credentials.")
        elif e.code == 404:
            output.error("HTTP 404 Not Found. Check the configured resource name.")
        else:
            output.error(f"HTTP {e.code} at {e.url}: {e.reason}")
    except urllib.error.URLError as e:
        output.error(f"Network error: {e.reason}. Check your internet connection.")
    except json.JSONDecodeError as e:
        output.error(f"Invalid JSON file: {e}")
    except KeyboardInterrupt:
        output.error("Interrupted")
    except Exception as e:
        output.error(f"Unexpected error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
