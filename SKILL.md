---
name: comfy-gen
description: >
  Execute ComfyUI image/video generation workflows on Modal H100 workers using the comfy-gen CLI.
  Use this skill whenever the user wants to run ComfyUI workflows remotely, submit workflows,
  check generation status, download models, list installed models, query samplers/schedulers,
  or configure the Modal-backed ComfyGen runner.
---

# comfy-gen: Remote ComfyUI Workflow Execution

ComfyGen is an agent-first CLI for running ComfyUI API-format workflows on Modal H100 workers. Commands output JSON to stdout and human-readable logs to stderr.

## Core Commands

| Command | Purpose |
| --- | --- |
| `comfy-gen init` | Deploy the Modal app, create the Modal Volume, create the Modal Secret, and configure storage |
| `comfy-gen submit` | Submit a workflow for execution |
| `comfy-gen download` | Download models to the Modal Volume |
| `comfy-gen status` | Check a Modal FunctionCall status |
| `comfy-gen cancel` | Cancel a running job |
| `comfy-gen list` | List model files on the Modal Volume |
| `comfy-gen info` | Query samplers, schedulers, and LoRA files |
| `comfy-gen config` | Read/write persistent configuration |

## Setup

```bash
modal setup
comfy-gen init
```

`comfy-gen init` configures:

- Modal app: `comfy-gen`
- Modal function: `run_job`
- Modal Volume: `comfy-gen-comfyui`
- Modal Secret: `comfy-gen-storage`
- Modal Dict for job state: `comfy-gen-jobs`
- S3-compatible input/output storage

Non-interactive:

```bash
comfy-gen init --non-interactive --app-name comfy-gen \
  --s3-access-key AKIA... \
  --s3-secret-key ... \
  --s3-bucket my-bucket
```

## Workflow Submission

```bash
comfy-gen submit workflow.json
comfy-gen submit workflow.json --input 193=/path/to/photo.jpg
comfy-gen submit workflow.json --override 7.seed=42
comfy-gen submit workflow.json --timeout 1200
```

Workflow files must be in ComfyUI API format: JSON keyed by node ID with `class_type` and `inputs`.

The worker automatically:

- uploads local `LoadImage` inputs to S3-compatible storage
- resolves and installs missing custom nodes through ComfyUI-Manager
- downloads Manager-known missing models onto the Modal Volume before queueing the workflow
- uploads outputs to S3-compatible storage and returns URLs

## Model Handling

Models live on the Modal Volume under:

```text
/runpod-volume/ComfyUI/models/<model_type>/
```

The path name is retained for compatibility with the ComfyUI handler, but the backing storage is a Modal Volume.

Common model fields:

| Node/Input | Model folder |
| --- | --- |
| `CheckpointLoaderSimple.ckpt_name` | `checkpoints/` |
| `LoraLoader.lora_name` | `loras/` |
| `VAELoader.vae_name` | `vae/` |
| `UNETLoader.unet_name` | `diffusion_models/` |
| `DualCLIPLoader.clip_name` | `clip/` or `text_encoders/` |
| `ControlNetLoader.control_net_name` | `controlnet/` |
| `UpscaleModelLoader.model_name` | `upscale_models/` |

Manual downloads are still useful for private models, CivitAI models, or models not listed by ComfyUI-Manager:

```bash
comfy-gen download civitai 456789 --dest loras
comfy-gen download url https://huggingface.co/org/repo/resolve/main/model.safetensors --dest checkpoints
comfy-gen download --batch /tmp/downloads.json
```

Batch format:

```json
[
  {"source": "civitai", "version_id": "456789", "dest": "loras"},
  {"source": "url", "url": "https://huggingface.co/.../model.safetensors", "dest": "checkpoints"}
]
```

## Listing and Info

```bash
comfy-gen list loras
comfy-gen list checkpoints
comfy-gen info
```

Prefer `comfy-gen info` when a UI needs samplers, schedulers, and LoRA options together.

## Job Tracking

Every job returns a Modal FunctionCall ID in `job_id`.

```bash
comfy-gen status fc-...
comfy-gen cancel fc-...
```

## Configuration

```bash
comfy-gen config
comfy-gen config --set modal_app_name=comfy-gen
comfy-gen config --get modal_volume_name
```

Important keys:

| Key | Env Var | Purpose |
| --- | --- | --- |
| `modal_app_name` | `COMFY_GEN_MODAL_APP_NAME` | Modal app name |
| `modal_volume_name` | `COMFY_GEN_MODAL_VOLUME_NAME` | Modal Volume name |
| `modal_secret_name` | `COMFY_GEN_MODAL_SECRET_NAME` | Modal Secret with storage credentials |
| `modal_jobs_name` | `COMFY_GEN_MODAL_JOBS_NAME` | Modal Dict for progress |
| `aws_access_key_id` | `AWS_ACCESS_KEY_ID` | S3-compatible access key |
| `aws_secret_access_key` | `AWS_SECRET_ACCESS_KEY` | S3-compatible secret key |
| `s3_bucket` | `S3_BUCKET` | Bucket name |
| `s3_region` | `S3_REGION` | Region |
| `s3_endpoint_url` | `S3_ENDPOINT_URL` | Custom endpoint for R2/B2/MinIO |
| `civitai_token` | `CIVITAI_TOKEN` | CivitAI downloads |

Modal auth is configured outside ComfyGen with `modal setup` or `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`.

## Agent Guidance

When the user provides a workflow JSON:

1. Validate that it is ComfyUI API format.
2. Scan for local file paths and use `--input` if the workflow does not already contain direct local paths for auto-detection.
3. Submit with `comfy-gen submit`.
4. If the result reports unresolved missing models, search HuggingFace/CivitAI for exact filenames and download them with `comfy-gen download`.
5. Return the output URL from the JSON result.

Do not guess model URLs. If a model cannot be confidently identified, ask the user for a direct URL or CivitAI model version ID.
