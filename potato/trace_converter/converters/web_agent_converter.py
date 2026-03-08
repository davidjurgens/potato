"""
Web Agent Converter

Converts various web agent trace formats to Potato's canonical format
with rich step-level data suitable for the web_agent_trace display type.

Supported input formats:
- WebArena/VisualWebArena (action_type + element_id in steps)
- Mind2Web (operation + target_html in steps)
- Anthropic Computer Use (type: "computer_20241022" tool blocks)
- Raw recording format (mouse_path + viewport in steps)

The output includes extra_fields with a "steps" array containing
screenshot URLs, action types, element bounding boxes, mouse paths,
and viewport dimensions.
"""

import base64
import json
import os
from typing import Any, Dict, List, Optional

from ..base import BaseTraceConverter, CanonicalTrace


class WebAgentConverter(BaseTraceConverter):
    """Converter for web agent browsing trace formats."""

    format_name = "web_agent"
    description = "Web agent browsing traces (WebArena, Mind2Web, Anthropic Computer Use, raw recordings)"
    file_extensions = [".json", ".jsonl"]

    def convert(self, data: Any, options: Optional[Dict] = None) -> List[CanonicalTrace]:
        options = options or {}
        traces = data if isinstance(data, list) else [data]
        results = []

        for idx, item in enumerate(traces):
            if not isinstance(item, dict):
                continue

            # Detect sub-format and convert
            if self._is_anthropic_computer_use(item):
                trace = self._convert_anthropic_cu(item, idx, options)
            elif self._is_mind2web(item):
                trace = self._convert_mind2web(item, idx, options)
            elif self._is_raw_recording(item):
                trace = self._convert_raw_recording(item, idx, options)
            elif self._is_webarena_style(item):
                trace = self._convert_webarena(item, idx, options)
            else:
                # Generic fallback - try to extract what we can
                trace = self._convert_generic(item, idx, options)

            if trace:
                results.append(trace)

        return results

    def detect(self, data: Any) -> bool:
        items = data if isinstance(data, list) else [data]
        if not items:
            return False
        first = items[0]
        if not isinstance(first, dict):
            return False

        # Check for web_agent-SPECIFIC format markers that won't appear in
        # plain webarena traces. We only claim data that has:
        # - Anthropic Computer Use tool blocks
        # - Mind2Web format (operation/target_html)
        # - Raw recordings with mouse_path + viewport in steps
        # - "site" top-level key combined with "screenshot_url" in steps
        #   (web_agent recorder output format)
        if (self._is_anthropic_computer_use(first)
                or self._is_mind2web(first)
                or self._is_raw_recording(first)):
            return True

        # Check for web_agent recorder output: "site" at top level
        # combined with steps that have "screenshot_url"
        if "site" in first:
            steps = first.get("steps", [])
            if isinstance(steps, list) and steps:
                first_step = steps[0]
                if isinstance(first_step, dict) and "screenshot_url" in first_step:
                    # Also require mouse_path or viewport in steps to
                    # distinguish from plain webarena
                    if "mouse_path" in first_step or "viewport" in first_step:
                        return True

        return False

    # --- Format detection ---

    def _is_anthropic_computer_use(self, item: Dict) -> bool:
        """Detect Anthropic Computer Use format (tool_use blocks with computer_20241022)."""
        messages = item.get("messages", item.get("content", []))
        if not isinstance(messages, list):
            return False
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        tool_type = block.get("type", "")
                        if "computer" in tool_type:
                            return True
                        # Also check tool_use with computer tool
                        if block.get("type") == "tool_use":
                            name = block.get("name", "")
                            if "computer" in name:
                                return True
        return False

    def _is_mind2web(self, item: Dict) -> bool:
        """Detect Mind2Web format (operation + target_html or pos_candidates)."""
        actions = item.get("actions", item.get("action_reprs", []))
        if not isinstance(actions, list) or not actions:
            return False
        first_action = actions[0]
        if not isinstance(first_action, dict):
            return False
        return (
            "operation" in first_action
            or "target_html" in first_action
            or "pos_candidates" in first_action
        )

    def _is_raw_recording(self, item: Dict) -> bool:
        """Detect raw recording format (steps with mouse_path + viewport)."""
        steps = item.get("steps", [])
        if not isinstance(steps, list) or not steps:
            return False
        first_step = steps[0]
        if not isinstance(first_step, dict):
            return False
        return "mouse_path" in first_step and "viewport" in first_step

    def _is_webarena_style(self, item: Dict) -> bool:
        """Detect WebArena-style format with coordinate data."""
        has_task = "intent" in item or "task" in item or "task_description" in item
        has_actions = "actions" in item or "action_history" in item or "steps" in item
        return has_task and has_actions

    def _is_webarena_with_coords(self, item: Dict) -> bool:
        """Detect WebArena format that includes coordinate/bbox data (distinct from plain webarena)."""
        steps = item.get("steps", item.get("actions", item.get("action_history", [])))
        if not isinstance(steps, list) or not steps:
            return False
        first = steps[0]
        if not isinstance(first, dict):
            return False
        # Must have coordinate-level data to distinguish from plain webarena converter
        has_coords = "coordinates" in first or "mouse_path" in first
        has_element_bbox = (
            isinstance(first.get("element"), dict)
            and "bbox" in first.get("element", {})
        )
        return has_coords or has_element_bbox or "viewport" in first

    # --- Converters ---

    def _convert_webarena(self, item: Dict, idx: int, options: Dict) -> CanonicalTrace:
        """Convert WebArena/VisualWebArena format with rich step data."""
        trace_id = str(item.get("task_id", item.get("id", f"web_agent_{idx}")))
        task_desc = item.get("intent", item.get("task", item.get("task_description", "")))
        site = item.get("url", item.get("start_url", item.get("site", "")))
        raw_actions = item.get("actions", item.get("action_history", item.get("steps", [])))
        evaluation = item.get("evaluation", {})

        steps = []
        conversation = []
        screenshots = []

        for i, action in enumerate(raw_actions):
            if not isinstance(action, dict):
                continue
            step = self._normalize_step(action, i)
            steps.append(step)

            # Build conversation entries
            thought = action.get("thought", action.get("reasoning", ""))
            if thought:
                conversation.append({"speaker": "Agent (Thought)", "text": thought})

            action_text = self._format_action_text(action)
            conversation.append({"speaker": "Agent (Action)", "text": action_text})

            obs = action.get("observation", action.get("page_state", ""))
            if obs:
                conversation.append({"speaker": "Environment", "text": str(obs)})

            screenshot = action.get("screenshot_url", action.get("screenshot", ""))
            if screenshot:
                screenshots.append(screenshot)

        metadata_table = [{"Property": "Steps", "Value": str(len(steps))}]
        if site:
            metadata_table.append({"Property": "Site", "Value": site})
        if evaluation:
            if "success" in evaluation:
                metadata_table.append({"Property": "Success", "Value": str(evaluation["success"])})
            if "reward" in evaluation:
                metadata_table.append({"Property": "Reward", "Value": str(evaluation["reward"])})

        return CanonicalTrace(
            id=trace_id,
            task_description=task_desc,
            conversation=conversation,
            agent_name=item.get("agent", item.get("model", "")),
            metadata_table=metadata_table,
            screenshots=screenshots,
            extra_fields={
                "steps": steps,
                "site": site,
            },
        )

    def _convert_mind2web(self, item: Dict, idx: int, options: Dict) -> CanonicalTrace:
        """Convert Mind2Web format."""
        trace_id = str(item.get("annotation_id", item.get("id", f"web_agent_{idx}")))
        task_desc = item.get("confirmed_task", item.get("task", ""))
        site = item.get("website", item.get("domain", ""))
        raw_actions = item.get("actions", item.get("action_reprs", []))

        steps = []
        conversation = []
        screenshots = []

        for i, action in enumerate(raw_actions):
            if not isinstance(action, dict):
                continue

            # Mind2Web action format
            operation = action.get("operation", {})
            if isinstance(operation, str):
                action_type = operation
                value = ""
            elif isinstance(operation, dict):
                action_type = operation.get("op", operation.get("original_op", "click"))
                value = operation.get("value", "")
            else:
                action_type = "click"
                value = ""

            # Extract element info from target_html or pos_candidates
            element = {}
            target_html = action.get("target_html", "")
            if target_html:
                element["text"] = self._extract_text_from_html(target_html)
                element["tag"] = self._extract_tag_from_html(target_html)

            # Extract bbox from pos_candidates if available
            pos = action.get("pos_candidates", [])
            if pos and isinstance(pos, list) and isinstance(pos[0], dict):
                bbox_data = pos[0].get("bbox", pos[0].get("position", None))
                if bbox_data and isinstance(bbox_data, list) and len(bbox_data) >= 4:
                    element["bbox"] = bbox_data[:4]

            screenshot = action.get("screenshot", action.get("screenshot_url", ""))

            step = {
                "step_index": i,
                "screenshot_url": screenshot,
                "action_type": action_type.lower(),
                "element": element,
                "coordinates": {},
                "mouse_path": [],
                "thought": action.get("thought", ""),
                "observation": action.get("observation", ""),
                "timestamp": "",
                "viewport": action.get("viewport", {"width": 1280, "height": 720}),
                "typed_text": value,
            }
            steps.append(step)

            # Conversation
            conversation.append({
                "speaker": "Agent (Action)",
                "text": f"{action_type}(element='{element.get('text', '')}')"
                        + (f", value='{value}'" if value else ""),
            })

            if screenshot:
                screenshots.append(screenshot)

        metadata_table = [
            {"Property": "Steps", "Value": str(len(steps))},
            {"Property": "Source", "Value": "Mind2Web"},
        ]
        if site:
            metadata_table.append({"Property": "Site", "Value": site})

        return CanonicalTrace(
            id=trace_id,
            task_description=task_desc,
            conversation=conversation,
            metadata_table=metadata_table,
            screenshots=screenshots,
            extra_fields={"steps": steps, "site": site},
        )

    def _convert_anthropic_cu(self, item: Dict, idx: int, options: Dict) -> CanonicalTrace:
        """Convert Anthropic Computer Use format."""
        trace_id = str(item.get("id", f"web_agent_{idx}"))
        task_desc = ""
        messages = item.get("messages", [])
        conversation = []
        steps = []
        screenshots = []
        screenshot_dir = options.get("screenshot_dir", "screenshots")

        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role", "")
            content = msg.get("content", "")

            if isinstance(content, str):
                if role == "user" and not task_desc:
                    task_desc = content
                conversation.append({
                    "speaker": "User" if role == "user" else "Agent",
                    "text": content,
                })
                continue

            if not isinstance(content, list):
                continue

            for block in content:
                if not isinstance(block, dict):
                    continue

                block_type = block.get("type", "")

                if block_type == "text":
                    text = block.get("text", "")
                    if role == "user" and not task_desc:
                        task_desc = text
                    conversation.append({
                        "speaker": "User" if role == "user" else "Agent (Thought)",
                        "text": text,
                    })

                elif block_type == "tool_use":
                    name = block.get("name", "")
                    inp = block.get("input", {})
                    if "computer" in name:
                        action_type = inp.get("action", "click")
                        coords = {}
                        if "coordinate" in inp:
                            coord = inp["coordinate"]
                            if isinstance(coord, list) and len(coord) >= 2:
                                coords = {"x": coord[0], "y": coord[1]}
                        step = {
                            "step_index": len(steps),
                            "screenshot_url": "",
                            "action_type": action_type,
                            "element": {},
                            "coordinates": coords,
                            "mouse_path": [],
                            "thought": "",
                            "observation": "",
                            "timestamp": "",
                            "viewport": {"width": inp.get("width", 1280),
                                         "height": inp.get("height", 720)},
                            "typed_text": inp.get("text", ""),
                        }
                        steps.append(step)
                        conversation.append({
                            "speaker": "Agent (Action)",
                            "text": f"{action_type}({json.dumps(inp)})",
                        })

                elif block_type == "tool_result":
                    result_content = block.get("content", [])
                    if isinstance(result_content, list):
                        for rc in result_content:
                            if isinstance(rc, dict) and rc.get("type") == "image":
                                # Base64 screenshot
                                b64_data = rc.get("source", {}).get("data", "")
                                if b64_data and steps:
                                    # Save screenshot
                                    step_idx = len(screenshots)
                                    screenshot_path = f"{screenshot_dir}/step_{step_idx:03d}.png"
                                    screenshots.append(screenshot_path)
                                    steps[-1]["screenshot_url"] = screenshot_path
                    elif isinstance(result_content, str):
                        conversation.append({
                            "speaker": "Environment",
                            "text": result_content,
                        })

        metadata_table = [
            {"Property": "Steps", "Value": str(len(steps))},
            {"Property": "Source", "Value": "Anthropic Computer Use"},
        ]
        if item.get("model"):
            metadata_table.append({"Property": "Model", "Value": item["model"]})

        return CanonicalTrace(
            id=trace_id,
            task_description=task_desc,
            conversation=conversation,
            agent_name=item.get("model", ""),
            metadata_table=metadata_table,
            screenshots=screenshots,
            extra_fields={"steps": steps},
        )

    def _convert_raw_recording(self, item: Dict, idx: int, options: Dict) -> CanonicalTrace:
        """Convert raw recording format (direct step data with mouse paths)."""
        trace_id = str(item.get("id", f"web_agent_{idx}"))
        task_desc = item.get("task_description", item.get("task", ""))
        site = item.get("site", item.get("url", ""))
        raw_steps = item.get("steps", [])

        steps = []
        conversation = []
        screenshots = []

        for i, raw_step in enumerate(raw_steps):
            if not isinstance(raw_step, dict):
                continue
            step = self._normalize_step(raw_step, i)
            steps.append(step)

            thought = raw_step.get("thought", "")
            if thought:
                conversation.append({"speaker": "Agent (Thought)", "text": thought})

            action_text = self._format_action_text(raw_step)
            conversation.append({"speaker": "Agent (Action)", "text": action_text})

            obs = raw_step.get("observation", "")
            if obs:
                conversation.append({"speaker": "Environment", "text": obs})

            screenshot = step.get("screenshot_url", "")
            if screenshot:
                screenshots.append(screenshot)

        metadata_table = [{"Property": "Steps", "Value": str(len(steps))}]
        if site:
            metadata_table.append({"Property": "Site", "Value": site})

        return CanonicalTrace(
            id=trace_id,
            task_description=task_desc,
            conversation=conversation,
            metadata_table=metadata_table,
            screenshots=screenshots,
            extra_fields={"steps": steps, "site": site},
        )

    def _convert_generic(self, item: Dict, idx: int, options: Dict) -> CanonicalTrace:
        """Generic fallback for unrecognized but plausible web agent data."""
        trace_id = str(item.get("id", f"web_agent_{idx}"))
        task_desc = item.get("task_description", item.get("task", item.get("intent", "")))
        raw_steps = item.get("steps", item.get("actions", item.get("action_history", [])))

        steps = []
        conversation = []
        screenshots = []

        if isinstance(raw_steps, list):
            for i, raw_step in enumerate(raw_steps):
                if not isinstance(raw_step, dict):
                    continue
                step = self._normalize_step(raw_step, i)
                steps.append(step)

                action_text = self._format_action_text(raw_step)
                conversation.append({"speaker": "Agent (Action)", "text": action_text})

                screenshot = step.get("screenshot_url", "")
                if screenshot:
                    screenshots.append(screenshot)

        return CanonicalTrace(
            id=trace_id,
            task_description=task_desc,
            conversation=conversation,
            metadata_table=[{"Property": "Steps", "Value": str(len(steps))}],
            screenshots=screenshots,
            extra_fields={"steps": steps},
        )

    # --- Helpers ---

    def _normalize_step(self, raw: Dict, index: int) -> Dict[str, Any]:
        """Normalize a raw step dict to the standard step format."""
        element = raw.get("element", {})
        if not isinstance(element, dict):
            element = {"text": str(element)} if element else {}

        coords = raw.get("coordinates", {})
        if not isinstance(coords, dict):
            coords = {}

        viewport = raw.get("viewport", {"width": 1280, "height": 720})
        if not isinstance(viewport, dict):
            viewport = {"width": 1280, "height": 720}

        mouse_path = raw.get("mouse_path", [])
        if not isinstance(mouse_path, list):
            mouse_path = []

        return {
            "step_index": raw.get("step_index", index),
            "screenshot_url": raw.get("screenshot_url", raw.get("screenshot", "")),
            "action_type": raw.get("action_type", raw.get("type", "unknown")),
            "element": element,
            "coordinates": coords,
            "mouse_path": mouse_path,
            "thought": raw.get("thought", raw.get("reasoning", "")),
            "observation": raw.get("observation", raw.get("page_state", "")),
            "timestamp": raw.get("timestamp", ""),
            "viewport": viewport,
            "typed_text": raw.get("typed_text", raw.get("value", "")),
            "scroll_direction": raw.get("scroll_direction", raw.get("direction", "")),
        }

    def _format_action_text(self, action: Dict) -> str:
        """Format action as readable text."""
        action_type = action.get("action_type", action.get("type", "unknown"))
        element = action.get("element", {})
        value = action.get("typed_text", action.get("value", ""))
        coords = action.get("coordinates", {})

        if isinstance(element, dict):
            elem_desc = element.get("text", element.get("id", element.get("tag", "")))
        else:
            elem_desc = str(element) if element else ""

        parts = [action_type]
        if elem_desc:
            parts.append(f"element='{elem_desc}'")
        if coords and isinstance(coords, dict) and "x" in coords:
            parts.append(f"at=({coords['x']},{coords['y']})")
        if value:
            parts.append(f"text='{value}'")

        return f"{parts[0]}({', '.join(parts[1:])})" if len(parts) > 1 else f"{parts[0]}()"

    def _extract_text_from_html(self, html_str: str) -> str:
        """Extract visible text from an HTML string (simple regex-free)."""
        import re
        clean = re.sub(r'<[^>]+>', '', str(html_str))
        clean = clean.strip()
        return clean[:100] if clean else ""

    def _extract_tag_from_html(self, html_str: str) -> str:
        """Extract the tag name from an HTML string."""
        import re
        match = re.match(r'<(\w+)', str(html_str))
        return match.group(1) if match else ""
