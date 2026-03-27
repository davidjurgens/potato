"""
Aider Chat History Converter

Converts Aider's markdown chat history format to Potato's canonical format.
Aider uses a distinctive edit block format with `<<<< ORIGINAL` / `>>>> UPDATED`
markers for file edits.

Supported input:
- Aider chat history files (markdown with edit blocks)
- JSON-wrapped chat history (from aider --dump-chat)
"""

import re
from typing import Any, Dict, List, Optional

from ..base import BaseTraceConverter, CanonicalTrace

# Aider edit block patterns
ORIGINAL_MARKER = re.compile(r'^<<<+\s*ORIGINAL\s*$', re.MULTILINE)
DIVIDER_MARKER = re.compile(r'^===+\s*$', re.MULTILINE)
UPDATED_MARKER = re.compile(r'^>>>+\s*UPDATED\s*$', re.MULTILINE)
FILE_HEADER = re.compile(r'^```\S*\s*\n(.+?)$', re.MULTILINE)
EDIT_BLOCK = re.compile(
    r'```\S*\s*\n(.+?)\n'
    r'<<<+\s*ORIGINAL\s*\n(.*?)\n'
    r'===+\s*\n(.*?)\n'
    r'>>>+\s*UPDATED\s*\n```',
    re.DOTALL
)


class AiderConverter(BaseTraceConverter):
    """Converter for Aider chat history format."""

    format_name = "aider"
    description = "Aider AI pair programming chat history (markdown with edit blocks)"
    file_extensions = [".md", ".json", ".jsonl"]

    def convert(self, data: Any, options: Optional[Dict] = None) -> List[CanonicalTrace]:
        options = options or {}
        items = data if isinstance(data, list) else [data]
        results = []

        for item in items:
            if isinstance(item, str):
                # Raw markdown content
                results.append(self._convert_markdown(item, len(results)))
            elif isinstance(item, dict):
                results.append(self._convert_dict(item, len(results)))

        return results

    def _convert_dict(self, item: dict, index: int) -> CanonicalTrace:
        """Convert a dict-wrapped Aider session."""
        trace_id = item.get("id", f"aider_{index}")
        chat_text = item.get("chat_history", item.get("content", item.get("text", "")))
        task = item.get("task_description", item.get("task", item.get("prompt", "")))
        model = item.get("model", "")

        if isinstance(chat_text, str):
            turns, files_edited = self._parse_chat(chat_text)
        else:
            turns = []
            files_edited = set()

        if not task and turns:
            # Use first user message as task
            for t in turns:
                if t.get("role") == "user":
                    task = t.get("content", "")
                    break

        conversation = self._flatten_conversation(turns)
        metadata = []
        if model:
            metadata.append({"Property": "Model", "Value": model})
        if files_edited:
            metadata.append({"Property": "Files edited", "Value": str(len(files_edited))})

        return CanonicalTrace(
            id=str(trace_id),
            task_description=task,
            conversation=conversation,
            agent_name=model,
            metadata_table=metadata,
            extra_fields={"structured_turns": turns},
        )

    def _convert_markdown(self, text: str, index: int) -> CanonicalTrace:
        """Convert raw markdown chat history."""
        turns, files_edited = self._parse_chat(text)
        task = ""
        for t in turns:
            if t.get("role") == "user":
                task = t.get("content", "")
                break

        conversation = self._flatten_conversation(turns)
        return CanonicalTrace(
            id=f"aider_{index}",
            task_description=task,
            conversation=conversation,
            extra_fields={"structured_turns": turns},
        )

    def _parse_chat(self, text: str):
        """Parse Aider chat markdown into structured turns."""
        turns = []
        files_edited = set()

        # Split by user/assistant markers
        # Aider format: lines starting with ">" are user, rest is assistant
        lines = text.split("\n")
        current_role = "assistant"
        current_content = []
        current_tool_calls = []

        for line in lines:
            if line.startswith("> "):
                # User message
                if current_content or current_tool_calls:
                    turns.append({
                        "role": current_role,
                        "content": "\n".join(current_content).strip(),
                        "tool_calls": current_tool_calls,
                    })
                    current_content = []
                    current_tool_calls = []
                current_role = "user"
                current_content.append(line[2:])
            else:
                if current_role == "user" and line.strip():
                    # Switch to assistant
                    if current_content:
                        turns.append({
                            "role": "user",
                            "content": "\n".join(current_content).strip(),
                            "tool_calls": [],
                        })
                        current_content = []
                        current_tool_calls = []
                    current_role = "assistant"
                current_content.append(line)

        # Flush remaining
        if current_content:
            turns.append({
                "role": current_role,
                "content": "\n".join(current_content).strip(),
                "tool_calls": current_tool_calls,
            })

        # Extract edit blocks from assistant turns
        for turn in turns:
            if turn["role"] != "assistant":
                continue
            content = turn["content"]
            for match in EDIT_BLOCK.finditer(content):
                file_path = match.group(1).strip()
                old_string = match.group(2)
                new_string = match.group(3)
                files_edited.add(file_path)
                turn["tool_calls"].append({
                    "tool": "Edit",
                    "input": {
                        "file_path": file_path,
                        "old_string": old_string,
                        "new_string": new_string,
                    },
                    "output": "Edit applied",
                    "output_type": "diff",
                })

        return turns, files_edited

    def _flatten_conversation(self, turns: list) -> List[Dict[str, str]]:
        """Flatten to speaker/text format."""
        conv = []
        for turn in turns:
            role = turn.get("role", "assistant")
            content = turn.get("content", "")
            if content:
                speaker = "User" if role == "user" else "Agent"
                conv.append({"speaker": speaker, "text": content})
            for tc in turn.get("tool_calls", []):
                conv.append({
                    "speaker": f"Agent ({tc.get('tool', 'Edit')})",
                    "text": f"{tc['tool']}({tc.get('input', {}).get('file_path', '')})",
                })
        return conv

    def detect(self, data: Any) -> bool:
        items = data if isinstance(data, list) else [data]
        if not items:
            return False
        first = items[0]

        if isinstance(first, str):
            return bool(ORIGINAL_MARKER.search(first) and UPDATED_MARKER.search(first))

        if isinstance(first, dict):
            chat = first.get("chat_history", first.get("content", ""))
            if isinstance(chat, str):
                return bool(ORIGINAL_MARKER.search(chat) and UPDATED_MARKER.search(chat))

        return False
