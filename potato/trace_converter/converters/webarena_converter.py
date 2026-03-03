"""
WebArena Converter

Converts WebArena/VisualWebArena/Mind2Web format traces to Potato's
canonical format. These formats are common in GUI agent benchmarks.

Expected input format:
{
    "task_id": "123",
    "intent": "Find the cheapest flight...",
    "url": "https://example.com",
    "actions": [
        {
            "action_type": "click",
            "element": {"tag": "button", "text": "Search", "id": "search-btn"},
            "thought": "I need to click the search button",
            "screenshot": "screenshots/step_0.png"
        },
        {
            "action_type": "type",
            "element": {"tag": "input", "id": "search-field"},
            "value": "wireless headphones",
            "thought": "I need to type the search query",
            "screenshot": "screenshots/step_1.png"
        }
    ],
    "evaluation": {"success": true, "reward": 1.0}
}
"""

from typing import Any, Dict, List, Optional

from ..base import BaseTraceConverter, CanonicalTrace


class WebArenaConverter(BaseTraceConverter):
    """Converter for WebArena/GUI benchmark trace formats."""

    format_name = "webarena"
    description = "WebArena/VisualWebArena GUI benchmark format"
    file_extensions = [".json", ".jsonl"]

    def convert(self, data: Any, options: Optional[Dict] = None) -> List[CanonicalTrace]:
        options = options or {}
        traces = data if isinstance(data, list) else [data]
        results = []

        for item in traces:
            trace_id = str(item.get("task_id", item.get("id", f"trace_{len(results)}")))
            intent = item.get("intent", item.get("task", ""))
            actions = item.get("actions") or item.get("action_history") or []
            evaluation = item.get("evaluation") or {}
            start_url = item.get("url", item.get("start_url", ""))

            # Build conversation
            conversation = []
            screenshots = []

            for i, action in enumerate(actions):
                # Thought
                thought = action.get("thought", action.get("reasoning", ""))
                if thought:
                    conversation.append({
                        "speaker": "Agent (Thought)",
                        "text": thought
                    })

                # Action - format based on action_type
                action_text = self._format_action(action)
                conversation.append({
                    "speaker": "Agent (Action)",
                    "text": action_text
                })

                # Observation / page state
                observation = action.get("observation", action.get("page_state", ""))
                if observation:
                    conversation.append({
                        "speaker": "Environment",
                        "text": str(observation)
                    })

                # Screenshot
                screenshot = action.get("screenshot", action.get("screenshot_path", ""))
                if screenshot:
                    screenshots.append(screenshot)

            # Build metadata table
            metadata_table = [
                {"Property": "Steps", "Value": str(len(actions))},
            ]
            if start_url:
                metadata_table.append({"Property": "Start URL", "Value": start_url})
            if evaluation:
                if "success" in evaluation:
                    metadata_table.append({
                        "Property": "Success",
                        "Value": str(evaluation["success"])
                    })
                if "reward" in evaluation:
                    metadata_table.append({
                        "Property": "Reward",
                        "Value": str(evaluation["reward"])
                    })

            # Add first screenshot as screenshot_url for image display
            extra_fields = {}
            if screenshots:
                extra_fields["screenshot_url"] = screenshots[0]

            trace = CanonicalTrace(
                id=trace_id,
                task_description=intent,
                conversation=conversation,
                agent_name=item.get("agent", ""),
                metadata_table=metadata_table,
                screenshots=screenshots,
                extra_fields=extra_fields,
            )
            results.append(trace)

        return results

    def _format_action(self, action: Dict) -> str:
        """Format a WebArena action as a readable string."""
        action_type = action.get("action_type", action.get("type", "unknown"))
        element = action.get("element", {})
        value = action.get("value", "")

        if isinstance(element, dict):
            elem_desc = element.get("text", element.get("id", element.get("tag", "")))
        else:
            elem_desc = str(element) if element else ""

        if action_type == "click":
            return f"click(element='{elem_desc}')"
        elif action_type == "type":
            return f"type_text(element='{elem_desc}', text='{value}')"
        elif action_type == "scroll":
            direction = action.get("direction", "down")
            return f"scroll(direction='{direction}')"
        elif action_type == "navigate":
            url = action.get("url", value)
            return f"navigate_to(url='{url}')"
        elif action_type == "select":
            return f"select_option(element='{elem_desc}', value='{value}')"
        elif action_type == "hover":
            return f"hover(element='{elem_desc}')"
        elif action_type == "stop":
            return f"stop(answer='{value}')"
        else:
            if value:
                return f"{action_type}(element='{elem_desc}', value='{value}')"
            return f"{action_type}(element='{elem_desc}')"

    def detect(self, data: Any) -> bool:
        items = data if isinstance(data, list) else [data]
        if not items:
            return False
        first = items[0]
        if not isinstance(first, dict):
            return False
        # WebArena has "actions" list with action_type and element
        has_intent = "intent" in first or "task" in first
        has_actions = "actions" in first or "action_history" in first
        if not (has_intent and has_actions):
            return False
        actions = first.get("actions", first.get("action_history", []))
        if not isinstance(actions, list) or not actions:
            return False
        action = actions[0]
        return isinstance(action, dict) and (
            "action_type" in action or "element" in action
        )
