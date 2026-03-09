"""
Chat Manager for LLM-based annotator assistance.

Provides a singleton ChatManager that handles multi-turn conversations
between annotators and an LLM, with context about the current annotation task.
"""

import logging
import time
from typing import Any, Dict, List, Optional

from potato.ai.ai_endpoint import AIEndpointFactory, BaseAIEndpoint, AIEndpointConfigError

logger = logging.getLogger(__name__)

# Singleton instance
_chat_manager: Optional["ChatManager"] = None

DEFAULT_SYSTEM_PROMPT = """You are an annotation assistant for the task "{task_name}".

Task description: {task_description}
Available labels: {annotation_labels}

The annotator is currently looking at this text:
---
{instance_text}
---

Help the annotator think through how to annotate this instance. You may:
- Highlight relevant aspects of the text
- Explain what to look for given the task description
- Clarify label definitions if asked

Do NOT tell the annotator which label to choose. Your role is to help them reason through the decision themselves."""


class ChatManager:
    """Manages LLM chat interactions for annotator assistance."""

    def __init__(self, config: Dict[str, Any]):
        chat_config = config.get("chat_support", {})
        self.enabled = chat_config.get("enabled", False)

        # UI settings
        ui_config = chat_config.get("ui", {})
        self.title = ui_config.get("title", "Ask AI")
        self.placeholder = ui_config.get("placeholder", "Ask about this annotation...")
        self.sidebar_width = ui_config.get("sidebar_width", 380)
        self.max_history_per_instance = ui_config.get("max_history_per_instance", 50)

        # System prompt template
        prompt_config = chat_config.get("system_prompt", {})
        self.system_prompt_template = prompt_config.get("template", DEFAULT_SYSTEM_PROMPT)

        # Extract task-level info for system prompt
        self.task_name = config.get("annotation_task_name", "Annotation Task")
        self.task_description = config.get("annotation_task_description", "")

        # Build label summary from annotation schemes
        labels = []
        for scheme in config.get("annotation_schemes", []):
            name = scheme.get("name", "")
            scheme_labels = scheme.get("labels", [])
            if scheme_labels:
                labels.append(f"{name}: {', '.join(str(l) for l in scheme_labels)}")
            elif scheme.get("description"):
                labels.append(f"{name}: {scheme['description']}")
        self.annotation_labels = "; ".join(labels) if labels else "See task description"

        # Create the LLM endpoint
        self.endpoint: Optional[BaseAIEndpoint] = None
        if self.enabled:
            self._init_endpoint(config)

    def _init_endpoint(self, config: Dict[str, Any]):
        """Initialize the LLM endpoint from chat_support config."""
        chat_config = config["chat_support"]

        # Build a config dict that AIEndpointFactory expects
        # (it looks for ai_support.enabled, ai_support.endpoint_type, ai_support.ai_config)
        endpoint_config = {
            "ai_support": {
                "enabled": True,
                "endpoint_type": chat_config.get("endpoint_type"),
                "ai_config": chat_config.get("ai_config", {}),
            }
        }

        try:
            self.endpoint = AIEndpointFactory.create_endpoint(endpoint_config)
            if self.endpoint:
                logger.info(f"Chat endpoint initialized: {chat_config.get('endpoint_type')}")
            else:
                logger.error("Chat endpoint creation returned None")
                self.enabled = False
        except AIEndpointConfigError as e:
            logger.error(f"Failed to initialize chat endpoint: {e}")
            self.enabled = False

    def build_system_prompt(self, instance_text: str, instance_id: str) -> str:
        """Build the system prompt with current instance context."""
        try:
            return self.system_prompt_template.format(
                task_name=self.task_name,
                task_description=self.task_description,
                annotation_labels=self.annotation_labels,
                instance_text=instance_text,
                instance_id=instance_id,
            )
        except KeyError as e:
            logger.warning(f"System prompt template variable not found: {e}, using default")
            return DEFAULT_SYSTEM_PROMPT.format(
                task_name=self.task_name,
                task_description=self.task_description,
                annotation_labels=self.annotation_labels,
                instance_text=instance_text,
                instance_id=instance_id,
            )

    def send_message(
        self,
        user_message: str,
        instance_text: str,
        instance_id: str,
        history: List[Dict[str, str]],
    ) -> Dict[str, Any]:
        """
        Send a user message and get an LLM response.

        Args:
            user_message: The annotator's message
            instance_text: Current instance text for context
            instance_id: Current instance ID
            history: Previous messages as list of {role, content} dicts

        Returns:
            Dict with 'content' (str) and 'response_time_ms' (int)
        """
        if not self.endpoint:
            return {"content": "Chat support is not configured.", "response_time_ms": 0}

        system_prompt = self.build_system_prompt(instance_text, instance_id)

        # Build messages array: system + history + new user message
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        start_time = time.time()
        try:
            response_text = self.endpoint.chat_query(messages)
            elapsed_ms = int((time.time() - start_time) * 1000)
            return {"content": response_text, "response_time_ms": elapsed_ms}
        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Chat query failed: {e}")
            return {
                "content": "Sorry, I encountered an error. Please try again.",
                "response_time_ms": elapsed_ms,
            }

    def get_ui_config(self) -> Dict[str, Any]:
        """Return UI configuration for the frontend."""
        return {
            "enabled": self.enabled,
            "title": self.title,
            "placeholder": self.placeholder,
            "sidebar_width": self.sidebar_width,
            "max_history_per_instance": self.max_history_per_instance,
        }


def init_chat_manager(config: Dict[str, Any]) -> ChatManager:
    """Initialize the global ChatManager singleton."""
    global _chat_manager
    _chat_manager = ChatManager(config)
    return _chat_manager


def get_chat_manager() -> Optional[ChatManager]:
    """Get the ChatManager singleton. Returns None if not initialized."""
    return _chat_manager


def clear_chat_manager():
    """Clear the ChatManager singleton. Used for testing."""
    global _chat_manager
    _chat_manager = None
