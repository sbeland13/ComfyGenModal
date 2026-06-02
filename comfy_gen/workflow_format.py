"""Workflow format detection and conversion helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


PRIMITIVE_WIDGET_TYPES = {
    "BOOLEAN",
    "COMBO",
    "FLOAT",
    "INT",
    "STRING",
}

CONTROL_AFTER_GENERATE_VALUES = {
    "fixed",
    "increment",
    "decrement",
    "randomize",
}


def is_api_workflow(workflow: Any) -> bool:
    """Return True for ComfyUI API-format, node-id-keyed workflows."""
    return (
        isinstance(workflow, dict)
        and not isinstance(workflow.get("nodes"), list)
        and any(isinstance(node, dict) and "class_type" in node for node in workflow.values())
    )


def is_ui_workflow(workflow: Any) -> bool:
    """Return True for ComfyUI UI-format workflows."""
    return isinstance(workflow, dict) and isinstance(workflow.get("nodes"), list)


def workflow_format(workflow: Any) -> str:
    if is_api_workflow(workflow):
        return "api"
    if is_ui_workflow(workflow):
        return "ui"
    return "unknown"


def detect_file_inputs(workflow: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Find local file inputs in API or UI workflows.

    Returns a mapping keyed by node id, matching the worker's `file_inputs`
    contract.
    """
    fmt = workflow_format(workflow)
    if fmt == "api":
        return _detect_api_file_inputs(workflow)
    if fmt == "ui":
        return _detect_ui_file_inputs(workflow)
    return {}


def _detect_api_file_inputs(workflow: dict[str, Any]) -> dict[str, dict[str, str]]:
    file_inputs: dict[str, dict[str, str]] = {}
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = node.get("class_type", "")
        field = _file_input_field(class_type)
        if not field:
            continue
        value = node.get("inputs", {}).get(field, "")
        if isinstance(value, str) and value and os.path.isfile(value):
            file_inputs[str(node_id)] = {
                "field": field,
                "local_path": value,
                "filename": Path(value).name,
            }
    return file_inputs


def _detect_ui_file_inputs(workflow: dict[str, Any]) -> dict[str, dict[str, str]]:
    file_inputs: dict[str, dict[str, str]] = {}
    for node in workflow.get("nodes", []):
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("type") or "")
        field = _file_input_field(class_type)
        if not field:
            continue
        values = _widget_values(node)
        value = values.get(field)
        if value is None and isinstance(node.get("widgets_values"), list) and node["widgets_values"]:
            value = node["widgets_values"][0]
        if isinstance(value, str) and value and os.path.isfile(value):
            file_inputs[str(node.get("id"))] = {
                "field": field,
                "local_path": value,
                "filename": Path(value).name,
            }
    return file_inputs


def _file_input_field(class_type: str) -> str | None:
    if class_type == "LoadImage":
        return "image"
    if class_type in ("VHS_LoadVideo", "LoadVideo"):
        return "video"
    return None


def _widget_values(node: dict[str, Any]) -> dict[str, Any]:
    raw = node.get("widgets_values")
    if isinstance(raw, dict):
        return raw
    values: dict[str, Any] = {}
    widgets = node.get("widgets")
    if isinstance(widgets, list) and isinstance(raw, list):
        for widget, value in zip(widgets, raw):
            if isinstance(widget, dict) and isinstance(widget.get("name"), str):
                values[widget["name"]] = value
    return values


def ui_workflow_skeleton(workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return a class_type-only API workflow for custom-node preinstall."""
    api: dict[str, dict[str, Any]] = {}
    for node in workflow.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        class_type = node.get("type")
        if node_id is None or not class_type:
            continue
        api[str(node_id)] = {"class_type": str(class_type), "inputs": {}}
    return api


def ui_to_api_workflow(
    workflow: dict[str, Any],
    object_info: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Convert a ComfyUI UI workflow into API format.

    The conversion uses live ComfyUI `object_info` to map widget values to input
    names, which is why this runs inside the Modal worker after ComfyUI starts.
    """
    if not is_ui_workflow(workflow):
        raise ValueError("Workflow is not ComfyUI UI format")

    link_map = _build_link_map(workflow.get("links", []))
    api: dict[str, dict[str, Any]] = {}

    for node in workflow.get("nodes", []):
        if not isinstance(node, dict):
            continue
        node_id = node.get("id")
        class_type = node.get("type")
        if node_id is None or not class_type:
            continue

        node_id_str = str(node_id)
        class_type_str = str(class_type)
        inputs: dict[str, Any] = {}

        for ui_input in node.get("inputs", []) or []:
            if not isinstance(ui_input, dict):
                continue
            name = ui_input.get("name")
            link_id = ui_input.get("link")
            if not isinstance(name, str) or link_id in (None, -1):
                continue
            source = link_map.get(str(link_id))
            if source:
                inputs[name] = source

        _apply_widget_inputs(inputs, node, object_info.get(class_type_str, {}))

        api_node: dict[str, Any] = {
            "inputs": inputs,
            "class_type": class_type_str,
        }
        title = node.get("title")
        if isinstance(title, str) and title:
            api_node["_meta"] = {"title": title}
        api[node_id_str] = api_node

    if not api:
        raise ValueError("UI workflow did not contain any convertible nodes")
    return api


def _build_link_map(links: Any) -> dict[str, list[Any]]:
    link_map: dict[str, list[Any]] = {}
    if not isinstance(links, list):
        return link_map
    for link in links:
        if isinstance(link, list) and len(link) >= 3:
            link_id, origin_id, origin_slot = link[0], link[1], link[2]
        elif isinstance(link, dict):
            link_id = link.get("id")
            origin_id = link.get("origin_id")
            origin_slot = link.get("origin_slot")
        else:
            continue
        if link_id is None or origin_id is None or origin_slot is None:
            continue
        link_map[str(link_id)] = [str(origin_id), int(origin_slot)]
    return link_map


def _apply_widget_inputs(inputs: dict[str, Any], node: dict[str, Any], class_info: dict[str, Any]) -> None:
    values_by_name = _widget_values(node)
    candidates = _input_candidates(class_info, set(inputs))

    if values_by_name:
        for name, _spec in candidates:
            if name in values_by_name:
                inputs[name] = values_by_name[name]
        return

    raw_values = node.get("widgets_values")
    if not isinstance(raw_values, list):
        return

    values = list(raw_values)
    value_index = 0
    previous_name = ""
    for name, spec in candidates:
        if value_index >= len(values):
            break
        if not _is_widget_input(spec):
            continue

        value = values[value_index]
        if (
            previous_name == "seed"
            and name != "control_after_generate"
            and isinstance(value, str)
            and value in CONTROL_AFTER_GENERATE_VALUES
        ):
            value_index += 1
            if value_index >= len(values):
                break
            value = values[value_index]

        inputs[name] = value
        previous_name = name
        value_index += 1


def _input_candidates(class_info: dict[str, Any], connected_names: set[str]) -> list[tuple[str, Any]]:
    input_info = class_info.get("input", {}) if isinstance(class_info, dict) else {}
    candidates: list[tuple[str, Any]] = []
    for section in ("required", "optional"):
        fields = input_info.get(section, {})
        if not isinstance(fields, dict):
            continue
        for name, spec in fields.items():
            if name not in connected_names:
                candidates.append((name, spec))
    return candidates


def _is_widget_input(spec: Any) -> bool:
    if not isinstance(spec, list) or not spec:
        return False
    input_type = spec[0]
    if isinstance(input_type, list):
        return True
    if not isinstance(input_type, str):
        return False
    return input_type.upper() in PRIMITIVE_WIDGET_TYPES
