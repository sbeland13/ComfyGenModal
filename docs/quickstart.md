# Quick Start Guide

This stack runs ComfyUI workflows on Modal H100 GPU workers and stores ComfyUI models/custom nodes on a Modal Volume.

Recommended setup order:

```text
ComfyGen CLI
        |
Modal app on H100
        |
Modal Volume for ComfyUI models and custom nodes
        |
BlockFlow (optional visual UI)
```

## Prerequisites

- Modal account and local Modal authentication: run `modal setup`, or set `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`.
- S3-compatible storage for file transfer:
  - AWS S3
  - Cloudflare R2
  - Backblaze B2
  - MinIO or any S3-compatible service
- Python 3.11+
- Git
- Optional CivitAI API token from [civitai.com/user/account](https://civitai.com/user/account)

## 1. Install ComfyGen

```bash
git clone https://github.com/Hearmeman24/ComfyGen.git
cd ComfyGen
pip install -e .
modal setup
```

For pipx:

```bash
pipx install --editable .
pipx inject comfy-gen modal boto3
modal setup
```

Verify:

```bash
comfy-gen --help
```

## 2. Run the Setup Wizard

```bash
comfy-gen init
```

The wizard:

- creates or hydrates the Modal Volume
- creates or hydrates the Modal Dict used for job progress
- stores storage credentials in a Modal Secret
- deploys the Modal app on `H100!`
- verifies S3-compatible storage

## 3. Download Models

You can download models directly to the Modal Volume:

```bash
comfy-gen download civitai 456789 --dest loras
```

or:

```bash
comfy-gen download url https://huggingface.co/.../model.safetensors --dest checkpoints
```

Files are stored under `/runpod-volume/ComfyUI/models/<dest>/` inside the Modal worker. The mount path is kept for compatibility with the existing ComfyUI handler; the backing storage is a Modal Volume.

## 4. Run Your First Workflow

```bash
comfy-gen submit workflow.json
```

If the workflow references missing custom nodes, the worker tries to resolve and install them through ComfyUI-Manager. If the workflow references Manager-known missing models, the worker downloads them to the Modal Volume before queueing the prompt.

Example output:

```json
{
  "ok": true,
  "output": {
    "url": "https://bucket.s3.region.amazonaws.com/output.png"
  },
  "job_id": "fc-..."
}
```

## 5. Optional BlockFlow

BlockFlow is a visual pipeline editor for generation pipelines.

```bash
git clone https://github.com/Hearmeman24/BlockFlow
cd BlockFlow
cp .env.example .env
uv run app.py
```

The app starts at:

```text
Frontend: http://localhost:3000
Backend:  http://localhost:8000
```

## Full Documentation

Read the main README for configuration keys, storage providers, workflow format, output format, model downloads, and error handling:

https://github.com/Hearmeman24/ComfyGen#readme
