"""
Interactive chat session driver for the simulator.

When the annotation server's ``instance_display`` includes an
``interactive_chat`` field, the annotator is expected to chat with a live
agent backend before submitting trajectory ratings.
:class:`InteractiveSessionRunner` plays the user side of that chat: it asks
a small "persona" LLM to generate user messages, posts them to the server's
``/agent_chat/send`` route, and finishes with ``/agent_chat/finish`` so the
captured conversation is written into the instance data.

After the runner returns, the regular annotation pipeline (e.g.
:class:`AgentSimulatorStrategy`) picks up the freshly populated
``conversation`` field and produces ratings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import requests

from .config import InteractiveConfig

logger = logging.getLogger(__name__)


@dataclass
class InteractiveSessionResult:
    """Outcome of one interactive_chat run."""

    instance_id: str
    completed: bool
    turns: int
    conversation: List[Dict[str, Any]]
    error: Optional[str] = None


class InteractiveSessionRunner:
    """Drive a multi-turn ``interactive_chat`` against the server.

    The runner is stateless across instances: ``run`` is called once per
    instance and returns the resulting conversation. The persona LLM is
    initialized lazily on first use so importing the module is cheap.
    """

    def __init__(self, config: InteractiveConfig, server_url: str):
        self.config = config
        self.server_url = server_url.rstrip("/")
        self._endpoint = None  # lazy

    # ------------------------------------------------------------------
    # Persona endpoint setup
    # ------------------------------------------------------------------

    def _get_endpoint(self):
        if self._endpoint is not None:
            return self._endpoint
        try:
            from potato.ai.ai_endpoint import AIEndpointFactory

            ai_cfg: Dict[str, Any] = {
                "model": self.config.model,
                "api_key": self.config.api_key,
                "max_tokens": self.config.max_tokens,
                "temperature": self.config.temperature,
            }
            if self.config.base_url:
                ai_cfg["base_url"] = self.config.base_url

            self._endpoint = AIEndpointFactory.create_endpoint({
                "ai_support": {
                    "enabled": True,
                    "endpoint_type": self.config.endpoint_type,
                    "ai_config": ai_cfg,
                }
            })
        except Exception as e:
            logger.warning("InteractiveSessionRunner: persona endpoint init failed: %s", e)
            self._endpoint = None
        return self._endpoint

    # ------------------------------------------------------------------
    # Persona messaging
    # ------------------------------------------------------------------

    def _generate_persona_message(
        self,
        task: str,
        history: List[Dict[str, str]],
    ) -> Optional[str]:
        endpoint = self._get_endpoint()
        if endpoint is None:
            return None

        if not history and self.config.first_message_template:
            return self.config.first_message_template.format(task=task)

        # Build chat history. The persona's "user" role is what we send to
        # the agent, so from the persona LLM's perspective those are
        # *assistant* messages and the agent's replies are *user* prompts.
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": self.config.persona_system_prompt
                + f"\n\nThe task you want completed is:\n{task}"}
        ]
        for msg in history:
            if msg["role"] == "user":  # what the persona previously sent
                messages.append({"role": "assistant", "content": msg["content"]})
            else:  # agent's reply
                messages.append({"role": "user", "content": msg["content"]})

        try:
            if hasattr(endpoint, "chat_query"):
                reply = endpoint.chat_query(messages)
            else:
                # Fall back to flattening into a single prompt
                flat = "\n".join(f'{m["role"]}: {m["content"]}' for m in messages)
                reply = endpoint.query(flat + "\nassistant:", None)
        except Exception as e:
            logger.warning("Persona LLM call failed: %s", e)
            return None

        if isinstance(reply, dict):
            reply = reply.get("response") or reply.get("content") or str(reply)
        text = str(reply or "").strip()
        return text or None

    # ------------------------------------------------------------------
    # Server interaction
    # ------------------------------------------------------------------

    def _send_to_agent(
        self, session: requests.Session, message: str
    ) -> Optional[Dict[str, Any]]:
        try:
            resp = session.post(
                f"{self.server_url}/agent_chat/send",
                json={"message": message},
                timeout=120,
            )
        except requests.exceptions.RequestException as e:
            logger.warning("agent_chat/send request failed: %s", e)
            return None
        if resp.status_code != 200:
            logger.warning(
                "agent_chat/send returned %d: %s", resp.status_code, resp.text[:200]
            )
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def _finish(self, session: requests.Session) -> bool:
        try:
            resp = session.post(
                f"{self.server_url}/agent_chat/finish",
                timeout=60,
            )
        except requests.exceptions.RequestException as e:
            logger.warning("agent_chat/finish request failed: %s", e)
            return False
        if resp.status_code != 200:
            logger.warning(
                "agent_chat/finish returned %d: %s",
                resp.status_code, resp.text[:200],
            )
            return False
        return True

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def run(
        self,
        session: requests.Session,
        instance_id: str,
        task_description: str,
    ) -> InteractiveSessionResult:
        """Drive one chat session end-to-end."""
        history: List[Dict[str, str]] = []
        completed = False
        error: Optional[str] = None

        for turn in range(self.config.max_turns):
            user_msg = self._generate_persona_message(task_description, history)
            if not user_msg:
                error = error or "persona produced no message"
                break

            # Strip the [DONE] marker before sending so the agent doesn't see
            # it; remember that we should finish after this turn.
            should_finish = self.config.done_marker.lower() in user_msg.lower()
            send_msg = user_msg.replace(self.config.done_marker, "").strip() or "Thanks!"

            agent_reply = self._send_to_agent(session, send_msg)
            if agent_reply is None:
                error = error or "agent send failed"
                break
            history.append({"role": "user", "content": send_msg})
            history.append({
                "role": "agent",
                "content": agent_reply.get("content", ""),
            })

            if should_finish:
                completed = True
                break

        ok = self._finish(session)
        if not ok and not error:
            error = "finish failed"
        if ok and not completed:
            # We hit max_turns without an explicit DONE; still consider the
            # session "done" for accounting purposes.
            completed = True

        # Build the conversation array the way the server's finish route does
        conversation = [
            {
                "speaker": "User" if msg["role"] == "user" else "Agent",
                "text": msg["content"],
            }
            for msg in history
        ]

        return InteractiveSessionResult(
            instance_id=instance_id,
            completed=completed,
            turns=len(history) // 2,
            conversation=conversation,
            error=error,
        )
