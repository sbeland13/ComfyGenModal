from __future__ import annotations

from comfy_gen import workflow_format


OBJECT_INFO = {
    "CheckpointLoaderSimple": {
        "input": {
            "required": {
                "ckpt_name": [["model.safetensors"], {}],
            }
        }
    },
    "KSampler": {
        "input": {
            "required": {
                "model": ["MODEL"],
                "seed": ["INT", {}],
                "steps": ["INT", {}],
                "cfg": ["FLOAT", {}],
                "sampler_name": [["euler"], {}],
                "scheduler": [["normal"], {}],
                "positive": ["CONDITIONING"],
                "negative": ["CONDITIONING"],
                "latent_image": ["LATENT"],
                "denoise": ["FLOAT", {}],
            }
        }
    },
    "LoadImage": {
        "input": {
            "required": {
                "image": ["STRING", {}],
            },
            "optional": {
                "upload": ["STRING", {}],
            },
        }
    },
}


def test_detects_api_and_ui_workflows():
    assert workflow_format.workflow_format({"1": {"class_type": "KSampler", "inputs": {}}}) == "api"
    assert workflow_format.workflow_format({"nodes": []}) == "ui"
    assert workflow_format.workflow_format({"hello": "world"}) == "unknown"


def test_ui_to_api_maps_links_and_ksampler_widget_values():
    ui = {
        "nodes": [
            {
                "id": 4,
                "type": "CheckpointLoaderSimple",
                "widgets_values": ["model.safetensors"],
            },
            {
                "id": 3,
                "type": "KSampler",
                "title": "Sampler",
                "inputs": [
                    {"name": "model", "link": 10},
                    {"name": "positive", "link": 11},
                    {"name": "negative", "link": 12},
                    {"name": "latent_image", "link": 13},
                ],
                "widgets_values": [123, "randomize", 20, 7.5, "euler", "normal", 0.8],
            },
        ],
        "links": [
            [10, 4, 0, 3, 0, "MODEL"],
            [11, 6, 0, 3, 1, "CONDITIONING"],
            [12, 7, 0, 3, 2, "CONDITIONING"],
            [13, 5, 0, 3, 3, "LATENT"],
        ],
    }

    api = workflow_format.ui_to_api_workflow(ui, OBJECT_INFO)

    assert api["4"]["inputs"]["ckpt_name"] == "model.safetensors"
    assert api["3"]["class_type"] == "KSampler"
    assert api["3"]["_meta"] == {"title": "Sampler"}
    assert api["3"]["inputs"] == {
        "model": ["4", 0],
        "positive": ["6", 0],
        "negative": ["7", 0],
        "latent_image": ["5", 0],
        "seed": 123,
        "steps": 20,
        "cfg": 7.5,
        "sampler_name": "euler",
        "scheduler": "normal",
        "denoise": 0.8,
    }


def test_ui_file_input_detection_uses_load_image_widget_path(tmp_path):
    image = tmp_path / "input.png"
    image.write_bytes(b"png")
    ui = {
        "nodes": [
            {
                "id": 9,
                "type": "LoadImage",
                "widgets_values": [str(image), "image"],
            }
        ]
    }

    assert workflow_format.detect_file_inputs(ui) == {
        "9": {
            "field": "image",
            "local_path": str(image),
            "filename": "input.png",
        }
    }
