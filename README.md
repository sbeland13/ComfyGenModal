# comfy-gen

**An agentic CLI for running ComfyUI workflows on Modal H100 workers.** It is designed for AI coding agents and humans: every command emits structured JSON on stdout, progress goes to stderr, and all commands are discoverable with `--help`.

## How It Works

```bash
comfy-gen submit workflow.json
```

1. Detects local `LoadImage` file paths and uploads them to S3-compatible storage.
2. Spawns the deployed Modal `run_job` function on `H100!` GPU hardware.
3. Mounts a Modal Volume at `/runpod-volume` for compatibility with the existing ComfyUI handler.
4. Stores ComfyUI models at `/runpod-volume/ComfyUI/models` and custom nodes at `/runpod-volume/ComfyUI/custom_nodes`.
5. Automatically resolves and installs missing custom nodes through ComfyUI-Manager.
6. Automatically downloads Manager-known missing models to the Modal Volume before queuing the workflow.
7. Polls Modal job state and returns output URLs as JSON.

Outputs still use S3-compatible storage so results can be accessed from your local machine, scripts, and downstream tools.

## Development & Testing

```bash
pip install -e '.[dev]'    # installs pytest + pytest-mock
python3 -m pytest tests/
```

Tests for the serverless worker (`serverless-runtime/`) use the `dispatch_command` fixture in `tests/conftest.py`, which mirrors the worker's command-dispatch path so routing is exercised end-to-end.

## Installation

Requires Python 3.11+ and Modal authentication.

```bash
git clone https://github.com/Hearmeman24/ComfyGen.git
cd ComfyGen
pip install -e .
modal setup
```

For isolated CLI installs:

```bash
pipx install --editable .
pipx inject comfy-gen modal boto3
modal setup
```

## Quick Start

```bash
# 1. Deploy the Modal app, create the Modal Volume, and configure storage
comfy-gen init

# 2. Optionally download known models to the Modal Volume
comfy-gen download civitai 456789 --dest loras
comfy-gen download url https://huggingface.co/org/repo/resolve/main/model.safetensors --dest checkpoints

# 3. Submit a workflow
comfy-gen submit workflow.json

# 4. Submit with an input image for a LoadImage node
comfy-gen submit workflow.json --input 193=/path/to/photo.jpg

# 5. Override workflow parameters
comfy-gen submit workflow.json --override 7.seed=42 --override 7.denoise=0.8

# 6. Check job status / cancel
comfy-gen status <modal-function-call-id>
comfy-gen cancel <modal-function-call-id>
```

## Commands

### `comfy-gen init`

Deploys the Modal app and creates the required Modal resources:

- Modal app: `comfy-gen`
- Modal function: `run_job`
- Modal Volume: `comfy-gen-comfyui`
- Modal Dict for job progress: `comfy-gen-jobs`
- Modal Secret for S3/CivitAI credentials: `comfy-gen-storage`

Non-interactive example:

```bash
comfy-gen init --non-interactive --app-name comfy-gen \
  --s3-access-key AKIA... \
  --s3-secret-key ... \
  --s3-bucket my-bucket \
  --s3-region us-east-1
```

For R2, B2, MinIO, or DigitalOcean Spaces, include `--s3-endpoint-url`.

### `comfy-gen submit <workflow.json>`

Submits a ComfyUI API-format workflow to Modal and waits for completion.

```bash
comfy-gen submit workflow.json
comfy-gen submit workflow.json --input 193=/path/to/ref.jpg
comfy-gen submit workflow.json --override 7.seed=42
comfy-gen submit workflow.json --timeout 1200
```

Result:

```json
{
  "ok": true,
  "output": {
    "url": "https://bucket.s3.region.amazonaws.com/comfy-gen/outputs/abc123.png",
    "seed": 1027836870258818,
    "resolution": {"width": 828, "height": 1248},
    "model_hashes": {
      "model.safetensors": {"sha256": "240761...", "type": "diffusion_models"}
    }
  },
  "job_id": "fc-...",
  "elapsed_seconds": 27
}
```

### `comfy-gen status <job-id>`

Checks a Modal FunctionCall by ID and returns the latest progress or final result.

```bash
comfy-gen status fc-...
```

### `comfy-gen cancel <job-id>`

Cancels a running or queued Modal FunctionCall.

```bash
comfy-gen cancel fc-...
```

### `comfy-gen download <civitai|url> <target>`

Downloads model files directly to the Modal Volume at `/runpod-volume/ComfyUI/models/<dest>/`.

```bash
comfy-gen download civitai 456789 --dest loras
comfy-gen download url https://huggingface.co/Comfy-Org/flux1-dev/resolve/main/flux1-dev-fp8.safetensors --dest checkpoints
comfy-gen download url https://example.com/model.safetensors --dest diffusion_models --filename my_model.safetensors
comfy-gen download --batch models.json
```

Supported `--dest` values include `checkpoints`, `loras`, `vae`, `clip`, `diffusion_models`, `text_encoders`, `controlnet`, and `upscale_models`.

Batch file format:

```json
[
  {"source": "civitai", "version_id": "456789", "dest": "loras"},
  {"source": "url", "url": "https://huggingface.co/.../model.safetensors", "dest": "checkpoints"}
]
```

### `comfy-gen list [model_type]`

Lists model files on the Modal Volume.

```bash
comfy-gen list loras
comfy-gen list checkpoints
comfy-gen list diffusion_models
```

### `comfy-gen info`

Queries the remote ComfyUI worker for dynamic options such as samplers, schedulers, and installed LoRAs.

```bash
comfy-gen info
```

## Configuration

Config is read from:

**config.json > .env file > environment variables > defaults**

| Key | Description | Env Var | Default |
|-----|-------------|---------|---------|
| `modal_app_name` | Modal app name | `COMFY_GEN_MODAL_APP_NAME` | `comfy-gen` |
| `modal_volume_name` | Modal Volume for models/custom nodes | `COMFY_GEN_MODAL_VOLUME_NAME` | `comfy-gen-comfyui` |
| `modal_secret_name` | Modal Secret for S3/CivitAI credentials | `COMFY_GEN_MODAL_SECRET_NAME` | `comfy-gen-storage` |
| `modal_jobs_name` | Modal Dict for job progress | `COMFY_GEN_MODAL_JOBS_NAME` | `comfy-gen-jobs` |
| `aws_access_key_id` | S3 access key | `AWS_ACCESS_KEY_ID` | - |
| `aws_secret_access_key` | S3 secret key | `AWS_SECRET_ACCESS_KEY` | - |
| `s3_bucket` | S3 bucket name | `S3_BUCKET` | - |
| `s3_region` | S3 region | `S3_REGION` | `eu-west-2` |
| `s3_endpoint_url` | Custom S3 endpoint | `S3_ENDPOINT_URL` | - |
| `civitai_token` | CivitAI API token | `CIVITAI_TOKEN` | - |
| `timeout_seconds` | Max wait for workflow completion | `COMFY_GEN_TIMEOUT` | `1200` |
| `poll_interval_seconds` | Status poll interval | `COMFY_GEN_POLL_INTERVAL` | `3` |

Modal authentication is handled by the Modal SDK via `modal setup` or `MODAL_TOKEN_ID` / `MODAL_TOKEN_SECRET`.

## Storage

ComfyGen requires S3-compatible storage for local input uploads and worker output uploads.

| Service | Config |
|---------|--------|
| AWS S3 | `aws_access_key_id`, `aws_secret_access_key`, `s3_bucket`, `s3_region` |
| Cloudflare R2 | Same as above plus `s3_endpoint_url=https://<account-id>.r2.cloudflarestorage.com`, `s3_region=auto` |
| Backblaze B2 | Same as above plus `s3_endpoint_url=https://s3.<region>.backblazeb2.com` |
| MinIO | Same as above plus `s3_endpoint_url=http://your-minio:9000` |
| DigitalOcean Spaces | Same as above plus `s3_endpoint_url=https://<region>.digitaloceanspaces.com` |

Uploads are content-addressed, so identical input files are not re-uploaded.

## Workflow Format

Workflows must be in ComfyUI API format: node-ID-keyed JSON with `class_type` and `inputs` fields. Export from ComfyUI using Save (API Format), or enable Dev Mode first.

```json
{
  "7": {
    "inputs": {"seed": 42, "steps": 20, "cfg": 7.0, "model": ["10", 0]},
    "class_type": "KSampler"
  },
  "10": {
    "inputs": {"ckpt_name": "model.safetensors"},
    "class_type": "CheckpointLoaderSimple"
  }
}
```

## Output Format

All commands output JSON to stdout. Progress and logs go to stderr.

```bash
comfy-gen submit workflow.json 2>/dev/null | jq -r '.output.url'
```

Success exits with code `0`; errors exit with code `1`.

## Prerequisites

1. A Modal account and local Modal authentication (`modal setup`).
2. S3-compatible storage for input and output transfer.
3. Python 3.11+.
4. Optional: CivitAI API token for CivitAI downloads.

## License

MIT
