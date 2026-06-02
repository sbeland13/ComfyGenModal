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
    p_download.add_argument("source", nargs="?", choices=["civitai", "url"], help="Download source")
    p_download.add_argument("target", nargs="?", help="CivitAI version ID or direct download URL")
    p_download.add_argument("--dest", default="checkpoints", help="Model subfolder under /runpod-volume/ComfyUI/models/")
    p_download.add_argument("--filename", help="Output filename for URL downloads")
    p_download.add_argument("--timeout", type=int, help="Max seconds to wait for completion")
    p_download.add_argument("--batch", metavar="FILE", help="Path to JSON array of download specs")
    _add_app_args(p_download)

    p_list = subparsers.add_parser("list", help="List model files on the Modal Volume")
    p_list.add_argument("model_type", nargs="?", default="loras", help="Model type to list (default: loras)")
    p_list.add_argument("--timeout", type=int, help="Max seconds to wait for completion")
    _add_app_args(p_list)

    p_info = subparsers.add_parser("info", help="Query samplers, schedulers, and LoRAs from Modal ComfyUI")
    p_info.add_argument("--timeout", type=int, help="Max seconds to wait for completion")
    _add_app_args(p_info)

    args = parser.parse_args()

    try:
        {
            "init": cmd_init,
            "config": cmd_config,
            "submit": cmd_submit,
            "download": cmd_download,
            "status": cmd_status,
            "cancel": cmd_cancel,
            "list": cmd_list,
            "info": cmd_info,
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
