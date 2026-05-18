"""
Coding-agent proxies — LLM plans + sandboxed code execution.

Two implementations behind a shared base class:

- :class:`SubprocessCodingAgentProxy` (default, ``type: subprocess_coding``)
  runs each Python or shell action in a per-session temp workspace via
  ``subprocess.run`` with a per-step timeout and an output cap. Light
  isolation — suitable for trusted-input research workflows. The
  workspace is sandboxed (separate cwd) but **not** a security boundary;
  malicious code can still touch the host filesystem outside ``cwd``.

- :class:`DockerCodingAgentProxy` (``type: docker_coding``) runs each
  action inside an ephemeral Docker container with ``--network=none``,
  ``--memory``, ``--cpus``, ``--read-only`` and a writable workspace
  bind-mounted at ``/work``. Real isolation — survives untrusted code.
  Requires the ``docker`` Python package and a running Docker daemon.

Both inherit per-step / per-session / rate-limit enforcement from the
existing :mod:`potato.agent_proxy.sandbox` framework via the standard
``send_message`` flow in ``routes.py:agent_chat_send``.

Configuration shape (both proxies):

    agent_proxy:
      type: subprocess_coding | docker_coding
      llm:
        endpoint_type: ollama
        model: llama3.2:3b
        base_url: http://localhost:11434
        temperature: 0.2
        max_tokens: 800
      execution:
        per_step_timeout: 8           # seconds
        max_output_chars: 4000
        starter_files: {}             # {filename: contents} written into workspace
      docker:                          # only for docker_coding
        image: python:3.11-slim
        memory: 512m
        cpus: 1.0
        network: none                 # "none" or "bridge"
      sandbox: { max_steps: 20, ... } # standard agent-proxy sandbox knobs
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .base import AgentMessage, AgentProxyFactory, AgentResponse, BaseAgentProxy

logger = logging.getLogger(__name__)


_PLANNER_SYSTEM_PROMPT = (
    "You are an autonomous coding agent. The user will give you a coding task. "
    "Each turn, decide a SINGLE next action and respond with ONLY a JSON object "
    "of the form: {\"thought\": str, \"action\": {\"type\": str, \"code\": str}}. "
    "The 'type' must be one of:\n"
    "  - \"python\": run the contents of 'code' as a python script in the workspace\n"
    "  - \"shell\": run 'code' as a bash command in the workspace\n"
    "  - \"finish\": stop and return your final answer in 'code' (which is then shown "
    "to the user as your conclusion -- no execution happens)\n"
    "Keep each action small and focused. Use 'finish' as soon as the task is done."
)


@dataclass
class _ExecResult:
    stdout: str
    stderr: str
    exit_code: Optional[int]
    timed_out: bool = False
    error: Optional[str] = None


class CodingAgentProxy(BaseAgentProxy):
    """Shared planner/executor scaffold for coding agents.

    Subclasses implement :meth:`_execute` to run an action in their
    chosen sandbox. Each call to :meth:`send_message`:

      1. Appends the user message to the running history.
      2. Asks an LLM (configurable endpoint) for a JSON ``{thought, action}``.
      3. Hands ``action`` to the subclass for execution.
      4. Returns a single reply combining thought + tool output.
    """

    def _initialize(self):
        llm_cfg = self.config.get("llm") or {}
        self.llm_endpoint_type = llm_cfg.get("endpoint_type", "ollama")
        self.llm_model = llm_cfg.get("model")
        self.llm_base_url = llm_cfg.get("base_url")
        self.llm_temperature = llm_cfg.get("temperature", 0.2)
        self.llm_max_tokens = llm_cfg.get("max_tokens", 800)
        # OpenAI-compatible servers (vLLM etc.) ignore the key but the SDK
        # requires a non-empty string. Ollama needs none. Without forwarding
        # this the planner silently failed with "planner_unavailable".
        self.llm_api_key = llm_cfg.get("api_key")
        # Last endpoint init / call error, surfaced to the user instead of
        # an opaque "planner unavailable" message.
        self._llm_error: Optional[str] = None

        execution_cfg = self.config.get("execution") or {}
        self.per_step_timeout = execution_cfg.get("per_step_timeout", 8)
        self.max_output_chars = execution_cfg.get("max_output_chars", 4000)
        self.starter_files: Dict[str, str] = execution_cfg.get("starter_files", {}) or {}

        self._llm = None  # lazy

    # ------------------------------------------------------------------
    # LLM lazy-init
    # ------------------------------------------------------------------

    def _get_llm(self):
        if self._llm is not None:
            return self._llm
        try:
            from potato.ai.ai_endpoint import AIEndpointFactory

            ai_cfg: Dict[str, Any] = {
                "model": self.llm_model,
                "max_tokens": self.llm_max_tokens,
                "temperature": self.llm_temperature,
            }
            if self.llm_base_url:
                ai_cfg["base_url"] = self.llm_base_url
            # Forward the key for OpenAI-compatible endpoints; vLLM ignores
            # its value but the OpenAI SDK rejects an empty one. Fall back to
            # env then a non-empty placeholder so local servers just work.
            ai_cfg["api_key"] = (
                self.llm_api_key
                or os.environ.get("OPENAI_API_KEY")
                or os.environ.get("ANTHROPIC_API_KEY")
                or "EMPTY"
            )

            self._llm = AIEndpointFactory.create_endpoint({
                "ai_support": {
                    "enabled": True,
                    "endpoint_type": self.llm_endpoint_type,
                    "ai_config": ai_cfg,
                }
            })
            self._llm_error = None
        except Exception as e:
            logger.warning("CodingAgentProxy: planner LLM init failed: %s", e)
            self._llm_error = f"{type(e).__name__}: {e}"
            self._llm = None
        return self._llm

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_session(self, task_description: str) -> dict:
        workspace = tempfile.mkdtemp(prefix="potato_coding_agent_")
        for filename, contents in self.starter_files.items():
            target = os.path.join(workspace, filename)
            os.makedirs(os.path.dirname(target) or workspace, exist_ok=True)
            with open(target, "w") as f:
                f.write(contents)
        history = [
            {"role": "system", "content": _PLANNER_SYSTEM_PROMPT},
            {
                "role": "system",
                "content": f"Workspace: {workspace}\nTask: {task_description}",
            },
        ]
        return {
            "workspace": workspace,
            "history": history,
            "step": 0,
            "finished": False,
        }

    def end_session(self, session_context: dict):
        workspace = session_context.get("workspace") if session_context else None
        if workspace and os.path.isdir(workspace):
            shutil.rmtree(workspace, ignore_errors=True)

    # ------------------------------------------------------------------
    # Per-turn flow
    # ------------------------------------------------------------------

    def send_message(self, message: str, session_context: dict) -> AgentResponse:
        if session_context.get("finished"):
            return AgentResponse(
                message=AgentMessage(role="agent", content="(session already finished)"),
                done=True,
            )

        history: List[Dict[str, str]] = session_context.setdefault("history", [])
        history.append({"role": "user", "content": message})
        session_context["step"] = session_context.get("step", 0) + 1

        plan = self._plan_next_action(history)
        if plan is None:
            detail = self._llm_error or "no response from planner LLM"
            reply = (
                f"Planner LLM unavailable ({self.llm_endpoint_type}): "
                f"{detail}"
            )
            history.append({"role": "assistant", "content": reply})
            session_context["finished"] = True
            return AgentResponse(
                message=AgentMessage(role="error", content=reply), error="planner_unavailable",
            )

        thought = plan.get("thought", "")
        action = plan.get("action") or {}
        atype = (action.get("type") or "").strip().lower()
        code = action.get("code") or ""

        if atype == "finish":
            reply = self._format_finish_reply(thought, code)
            history.append({"role": "assistant", "content": reply})
            session_context["finished"] = True
            return AgentResponse(
                message=AgentMessage(role="agent", content=reply), done=True,
            )

        if atype not in ("python", "shell"):
            reply = (
                f"{thought}\n\n[invalid action type {atype!r}; try 'python', "
                "'shell', or 'finish']"
            )
            history.append({"role": "assistant", "content": reply})
            return AgentResponse(message=AgentMessage(role="agent", content=reply))

        result = self._execute(atype, code, session_context)
        reply = self._format_exec_reply(thought, atype, code, result)
        history.append({"role": "assistant", "content": reply})
        return AgentResponse(message=AgentMessage(role="agent", content=reply))

    # ------------------------------------------------------------------
    # Planning
    # ------------------------------------------------------------------

    def _plan_next_action(self, history: List[Dict[str, str]]) -> Optional[Dict[str, Any]]:
        endpoint = self._get_llm()
        if endpoint is None:
            return None
        try:
            if hasattr(endpoint, "chat_query"):
                raw = endpoint.chat_query(history)
            else:
                flat = "\n".join(f'{m["role"]}: {m["content"]}' for m in history)
                raw = endpoint.query(flat + "\nassistant:", None)
        except Exception as e:
            logger.warning("Planner LLM call failed: %s", e)
            self._llm_error = f"{type(e).__name__}: {e}"
            return None

        if isinstance(raw, dict):
            return raw  # already parsed JSON
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
        # Last-ditch: treat the whole text as a finish reply.
        return {"thought": "", "action": {"type": "finish", "code": text[:500]}}

    # ------------------------------------------------------------------
    # Reply formatting
    # ------------------------------------------------------------------

    def _format_exec_reply(
        self, thought: str, atype: str, code: str, result: _ExecResult
    ) -> str:
        parts: List[str] = []
        if thought:
            parts.append(thought.strip())
        parts.append(f"```{atype}\n{code.strip()}\n```")
        out_block: List[str] = []
        if result.timed_out:
            out_block.append(f"[timeout after {self.per_step_timeout}s]")
        if result.error:
            out_block.append(f"[error: {result.error}]")
        if result.exit_code is not None:
            out_block.append(f"[exit={result.exit_code}]")
        if result.stdout:
            out_block.append("stdout:\n" + self._truncate(result.stdout))
        if result.stderr:
            out_block.append("stderr:\n" + self._truncate(result.stderr))
        if not out_block:
            out_block.append("(no output)")
        parts.append("\n".join(out_block))
        return "\n\n".join(parts)

    def _format_finish_reply(self, thought: str, final_text: str) -> str:
        parts = []
        if thought:
            parts.append(thought.strip())
        if final_text:
            parts.append(final_text.strip())
        if not parts:
            parts.append("(done)")
        return "\n\n".join(parts)

    def _truncate(self, text: str) -> str:
        if len(text) <= self.max_output_chars:
            return text
        cut = self.max_output_chars
        return text[:cut] + f"\n[...truncated {len(text) - cut} chars]"

    # ------------------------------------------------------------------
    # Sandbox-specific execution
    # ------------------------------------------------------------------

    @abstractmethod
    def _execute(
        self, action_type: str, code: str, session_context: dict
    ) -> _ExecResult:
        """Execute ``code`` (one of 'python' / 'shell') in the sandbox."""


class SubprocessCodingAgentProxy(CodingAgentProxy):
    """Local subprocess-based execution.

    NOT a security boundary -- the per-step timeout + tempdir cwd is the
    only protection. Use ``DockerCodingAgentProxy`` for untrusted input.
    """

    proxy_type = "subprocess_coding"

    def _execute(
        self, action_type: str, code: str, session_context: dict
    ) -> _ExecResult:
        workspace = session_context["workspace"]
        env = self._build_env()
        try:
            if action_type == "python":
                script_path = os.path.join(workspace, "_action.py")
                with open(script_path, "w") as f:
                    f.write(code)
                proc = subprocess.run(
                    ["python", script_path],
                    cwd=workspace,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.per_step_timeout,
                )
            else:  # shell
                proc = subprocess.run(
                    ["bash", "-c", code],
                    cwd=workspace,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=self.per_step_timeout,
                )
        except subprocess.TimeoutExpired as e:
            return _ExecResult(
                stdout=(e.stdout or "") if isinstance(e.stdout, str) else "",
                stderr=(e.stderr or "") if isinstance(e.stderr, str) else "",
                exit_code=None,
                timed_out=True,
            )
        except FileNotFoundError as e:
            return _ExecResult(stdout="", stderr="", exit_code=None, error=str(e))
        return _ExecResult(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            exit_code=proc.returncode,
        )

    def _build_env(self) -> Dict[str, str]:
        # Strip env down to a minimal set so subprocess code can't
        # accidentally exfiltrate the host's secrets via env vars.
        keep = {"PATH", "HOME", "LANG", "LC_ALL"}
        return {k: v for k, v in os.environ.items() if k in keep}


class DockerCodingAgentProxy(CodingAgentProxy):
    """Ephemeral-container execution. Real isolation; requires Docker."""

    proxy_type = "docker_coding"

    def _initialize(self):
        super()._initialize()
        docker_cfg = self.config.get("docker") or {}
        self.docker_image = docker_cfg.get("image", "python:3.11-slim")
        self.docker_memory = docker_cfg.get("memory", "512m")
        self.docker_cpus = str(docker_cfg.get("cpus", 1.0))
        self.docker_network = docker_cfg.get("network", "none")
        self._docker = None  # lazy
        # Sanity check: warn if docker CLI isn't on PATH
        if shutil.which("docker") is None:
            logger.warning(
                "DockerCodingAgentProxy: 'docker' CLI not found on PATH. "
                "Container execution will fail at runtime."
            )

    def _execute(
        self, action_type: str, code: str, session_context: dict
    ) -> _ExecResult:
        workspace = session_context["workspace"]
        # Materialise the code as a file in the workspace so the container
        # can run it without inline injection through `-c`.
        if action_type == "python":
            target = os.path.join(workspace, "_action.py")
            with open(target, "w") as f:
                f.write(code)
            container_cmd = ["python", "/work/_action.py"]
        else:  # shell
            target = os.path.join(workspace, "_action.sh")
            with open(target, "w") as f:
                f.write(code)
            os.chmod(target, 0o755)
            container_cmd = ["bash", "/work/_action.sh"]

        cmd = [
            "docker", "run", "--rm",
            f"--network={self.docker_network}",
            f"--memory={self.docker_memory}",
            f"--cpus={self.docker_cpus}",
            "--read-only",
            "--tmpfs", "/tmp:exec,size=64m",
            "-v", f"{workspace}:/work",
            "-w", "/work",
            self.docker_image,
        ] + container_cmd
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.per_step_timeout + 5,  # docker pull/start overhead
            )
        except subprocess.TimeoutExpired as e:
            return _ExecResult(
                stdout=(e.stdout or "") if isinstance(e.stdout, str) else "",
                stderr=(e.stderr or "") if isinstance(e.stderr, str) else "",
                exit_code=None,
                timed_out=True,
            )
        except FileNotFoundError as e:
            return _ExecResult(stdout="", stderr="", exit_code=None, error=str(e))
        return _ExecResult(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            exit_code=proc.returncode,
        )


# Register both with the factory so configs can refer to them by name.
AgentProxyFactory.register("subprocess_coding", SubprocessCodingAgentProxy)
AgentProxyFactory.register("docker_coding", DockerCodingAgentProxy)
