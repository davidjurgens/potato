"""Decide whether a config is safe to put on the public internet, and say why.

Two jobs, kept separate on purpose:

``run_preflight`` **reports**. It runs the config validator, resolves every
referenced path, and checks the settings that decide what a stranger who finds
the URL can do. It changes nothing.

``harden_config`` **changes** only what is unambiguously a deployment concern:
debug off, sessions persistent, paths relative, one worker. It deliberately does
not touch ``user_config``, ``authentication``, ``login`` or ``require_password``.
Silently locking down a task the researcher wrote as open — or opening one they
wrote as closed — would make the deployed task differ from the config in the
repo, and the difference would be invisible.

So access control is reported, never rewritten. The exposure summary exists to
make an open task a decision rather than an accident.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import yaml

from potato.deploy.paths import collect_config_paths

logger = logging.getLogger(__name__)

Severity = str  # "error" | "warning" | "info"


@dataclass
class Finding:
    code: str
    severity: Severity
    message: str
    remedy: str = ""
    key: Optional[str] = None

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


@dataclass
class GeneratedSecrets:
    """Secrets minted for this deployment. Injected as env vars, never bundled."""

    secret_key: str
    admin_api_key: str


@dataclass
class PreflightReport:
    config_file: str
    provider: str
    public: bool
    findings: List[Finding] = field(default_factory=list)
    hardened_config: Dict[str, Any] = field(default_factory=dict)
    generated: Optional[GeneratedSecrets] = None
    exposure: List[str] = field(default_factory=list)

    @property
    def errors(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if f.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {
            "config_file": self.config_file,
            "provider": self.provider,
            "public": self.public,
            "ok": self.ok,
            "findings": [
                {"code": f.code, "severity": f.severity, "message": f.message,
                 "remedy": f.remedy, "key": f.key}
                for f in self.findings
            ],
            "exposure": self.exposure,
        }


# --------------------------------------------------------------------------
# Check registry
# --------------------------------------------------------------------------

_CHECKS: List[Callable] = []


def check(func: Callable) -> Callable:
    """Register a check so the set is inspectable and testable as data."""
    _CHECKS.append(func)
    return func


@dataclass
class CheckContext:
    config: Dict[str, Any]
    config_path: str
    provider: str
    public: bool
    ephemeral_fs: bool = False


# Values that look like a credential someone pasted into a config.
_SECRET_KEY_NAMES = ("api_key", "secret_key", "client_secret", "password",
                     "token", "access_token", "auth_token")
_SECRET_VALUE_SHAPES = (
    re.compile(r"^sk-[A-Za-z0-9_\-]{16,}$"),        # OpenAI-style
    re.compile(r"^hf_[A-Za-z0-9]{16,}$"),           # HuggingFace
    re.compile(r"^dop_v1_[a-f0-9]{32,}$"),          # DigitalOcean
    re.compile(r"^ghp_[A-Za-z0-9]{20,}$"),          # GitHub
    re.compile(r"^xox[baprs]-[A-Za-z0-9\-]{10,}$"), # Slack
)


def _walk(node: Any, path: str = ""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, f"{path}[{index}]")
    else:
        yield path, node


@check
def _check_debug_mode(ctx: CheckContext) -> List[Finding]:
    if not ctx.config.get("debug"):
        return []
    return [Finding(
        "D002", "error",
        "debug is true, which disables admin authentication entirely: "
        "validate_admin_api_key returns True unconditionally in debug mode, so "
        "anyone reaching /admin has full control.",
        "Remove `debug: true` from the config before deploying.",
        key="debug",
    )]


@check
def _check_mcp_surface(ctx: CheckContext) -> List[Finding]:
    """The MCP control surface is remote control, so deploying it needs care."""
    mcp_config = ctx.config.get("mcp") or {}
    if not mcp_config.get("enabled"):
        return []

    findings = []

    if ctx.config.get("debug"):
        findings.append(Finding(
            "D017", "error",
            "mcp.enabled is set on a server running in debug mode. Debug "
            "disables admin authentication server-wide, so an MCP control "
            "surface there is remote control with no lock on it.",
            "Remove `debug: true` before deploying.",
            key="mcp.enabled",
        ))

    from potato.server_utils.agent_tokens import list_tokens

    active = [t for t in list_tokens(ctx.config) if not t.get("revoked")]
    if not active:
        findings.append(Finding(
            "D018", "error",
            "mcp.enabled is set but no agent tokens have been issued, so every "
            "call will be refused. The surface is inert rather than open, but "
            "it is not doing what the config says it does.",
            "Issue one: potato mcp issue-token --config config.yaml "
            "--name <agent> --role <role>",
            key="mcp.enabled",
        ))

    destructive = mcp_config.get("destructive") or []
    if destructive:
        findings.append(Finding(
            "D019", "warning",
            f"mcp.destructive grants {', '.join(destructive)} to agents. These "
            f"tools discard annotation work and cannot be undone.",
            "Confirm this is intended, and keep mcp.audit_log on so the calls "
            "are recorded.",
            key="mcp.destructive",
        ))

    admin_tokens = [t for t in active if t.get("role") == "admin"]
    if admin_tokens and (mcp_config.get("scope") or {}).get("users") is None:
        findings.append(Finding(
            "D020", "warning",
            f"{len(admin_tokens)} admin-role agent token(s) are active with no "
            f"mcp.scope.users restriction, so they may act on any annotator.",
            "Narrow with mcp.scope.users, or issue a lower role.",
            key="mcp.scope",
        ))

    return findings


@check
def _check_inline_secrets(ctx: CheckContext) -> List[Finding]:
    findings = []
    for key_path, value in _walk(ctx.config):
        if not isinstance(value, str) or not value:
            continue
        if value.startswith("${"):  # env reference, resolved at load
            continue
        leaf = key_path.split(".")[-1].split("[")[0]
        looks_secret_by_name = leaf in _SECRET_KEY_NAMES and len(value) >= 12
        looks_secret_by_shape = any(p.match(value) for p in _SECRET_VALUE_SHAPES)
        if looks_secret_by_name or looks_secret_by_shape:
            findings.append(Finding(
                "D006", "error",
                f"{key_path} looks like a literal credential; deploying would "
                "upload it to the host and, for repo-backed providers, publish it.",
                f"Replace it with ${{ENV_VAR}} and pass --secret {leaf.upper()}=<value>.",
                key=key_path,
            ))
    return findings


@check
def _check_referenced_paths(ctx: CheckContext) -> List[Finding]:
    paths = collect_config_paths(ctx.config, ctx.config_path)
    findings = []
    for missing in paths.missing_required:
        findings.append(Finding(
            "D004", "error",
            f"{missing.config_key} references a path that does not exist: {missing.raw}",
            "Fix the path, or remove the entry.",
            key=missing.config_key,
        ))
    for missing in paths.missing:
        if missing.required:
            continue
        findings.append(Finding(
            "D004b", "warning",
            f"{missing.config_key} references a missing path: {missing.raw}",
            "The deploy will proceed; the feature using it will not work.",
            key=missing.config_key,
        ))
    for outside in paths.outside_task_dir:
        findings.append(Finding(
            "D005", "info",
            f"{outside.config_key} points outside the task directory ({outside.raw}); "
            "it will be copied into _bundled/ and the config rewritten.",
            "",
            key=outside.config_key,
        ))
    return findings


@check
def _check_authentication_key_typo(ctx: CheckContext) -> List[Finding]:
    auth = ctx.config.get("authentication")
    if isinstance(auth, dict) and "type" in auth and "method" not in auth:
        return [Finding(
            "D010", "error",
            "authentication.type is not a recognized key — the setting is "
            "authentication.method. As written, authentication silently falls "
            "back to in_memory.",
            "Rename `type:` to `method:`.",
            key="authentication.type",
        )]
    return []


@check
def _check_open_registration(ctx: CheckContext) -> List[Finding]:
    """Report open enrolment. Never change it — that is the researcher's call."""
    if not ctx.public:
        return []
    user_config = ctx.config.get("user_config") or {}
    allow_all = user_config.get("allow_all_users", True)
    auth = ctx.config.get("authentication") or {}
    method = auth.get("method", auth.get("type", "in_memory"))

    if method == "oauth":
        return []
    if not allow_all:
        return []

    passwordless = (
        ctx.config.get("require_no_password") is True
        or ctx.config.get("require_password") is False
        or (ctx.config.get("login") or {}).get("type") in ("url_direct", "prolific")
    )
    detail = (" No password is required, so a username is the only thing "
              "standing between a passer-by and your data."
              if passwordless else "")
    return [Finding(
        "D003", "warning",
        "Anyone who finds the URL can register and annotate." + detail,
        "Set user_config.allow_all_users: false and list your annotators under "
        "user_config.users, or use authentication.method: oauth.",
        key="user_config.allow_all_users",
    )]


@check
def _check_session_persistence(ctx: CheckContext) -> List[Finding]:
    if ctx.config.get("secret_key") or os.environ.get("POTATO_SECRET_KEY"):
        return []
    return [Finding(
        "D012", "info",
        "No secret_key is set, so one will be generated and injected as "
        "POTATO_SECRET_KEY. Sessions survive restarts only because of it.",
        "",
    )]


@check
def _check_ephemeral_filesystem(ctx: CheckContext) -> List[Finding]:
    if not ctx.ephemeral_fs:
        return []
    backup = ctx.config.get("huggingface_backup") or {}
    if backup.get("enabled"):
        return []
    return [Finding(
        "D011", "warning",
        f"The {ctx.provider} filesystem is ephemeral: annotations are lost when "
        "the host restarts or redeploys.",
        "Provide an HF token so a backup dataset can be configured, or pass "
        "--demo to accept throwaway data.",
    )]


@check
def _check_multiworker(ctx: CheckContext) -> List[Finding]:
    workers = (ctx.config.get("server") or {}).get("workers")
    if workers in (None, 1):
        return []
    return [Finding(
        "D013", "error",
        f"server.workers is {workers}. Potato keeps its item pool and user state "
        "in memory per process, so a second worker hands out duplicate "
        "assignments and silently overwrites annotations.",
        "Set workers to 1 and raise threads instead.",
        key="server.workers",
    )]


@check
def _check_ai_keys_present(ctx: CheckContext) -> List[Finding]:
    ai = ctx.config.get("ai_support") or {}
    if not ai or not ai.get("enabled", True):
        return []
    env_names = ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                 "GOOGLE_API_KEY")
    if any(os.environ.get(name) for name in env_names):
        return []
    return [Finding(
        "D014", "warning",
        "ai_support is configured but no LLM API key is present in the "
        "environment; AI features will fail on the host.",
        "Pass the key with --secret OPENAI_API_KEY=<value>.",
        key="ai_support",
    )]


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------


def generate_secrets() -> GeneratedSecrets:
    return GeneratedSecrets(
        secret_key=secrets.token_hex(32),
        admin_api_key=secrets.token_urlsafe(32),
    )


def harden_config(config: Dict[str, Any], *, provider: str = "",
                  workers: int = 1) -> Dict[str, Any]:
    """Return a copy with deployment-mechanical settings corrected.

    Access control is untouched by design — see the module docstring.
    """
    import copy
    hardened = copy.deepcopy(config)

    hardened["debug"] = False
    hardened.pop("debug_phase", None)
    hardened["persist_sessions"] = True

    # The bundle is the task directory, so paths must be relative to it.
    hardened["task_dir"] = "."
    output_dir = hardened.get("output_annotation_dir") or "annotation_output/"
    if os.path.isabs(str(output_dir)):
        output_dir = "annotation_output/"
    hardened["output_annotation_dir"] = output_dir

    server = dict(hardened.get("server") or {})
    server["workers"] = workers
    hardened["server"] = server

    return hardened


def run_preflight(config_path: str, *, provider: str = "local",
                  public: bool = True, ephemeral_fs: bool = False,
                  workers: int = 1) -> PreflightReport:
    """Validate and assess a config for deployment. Changes nothing on disk."""
    from potato.validate_cli import validate_config_file

    report = PreflightReport(config_file=config_path, provider=provider, public=public)

    if not os.path.isfile(config_path):
        report.findings.append(Finding(
            "D000", "error", f"Config file not found: {config_path}",
            "Check the path."))
        return report

    validation = validate_config_file(config_path)
    for error in validation.errors:
        report.findings.append(Finding(
            "D001", "error", error, "Fix the config and re-run `potato deploy check`."))
    for unknown in validation.unknown_keys:
        report.findings.append(Finding(
            "D015", "warning", f"Unrecognized config key: {unknown}",
            "Unknown keys are ignored at runtime; check for a typo."))
    for warning in validation.other_warnings:
        report.findings.append(Finding("D016", "warning", warning, ""))

    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle) or {}
    except Exception as exc:
        report.findings.append(Finding(
            "D001", "error", f"Could not parse config: {exc}", ""))
        return report
    if not isinstance(config, dict):
        report.findings.append(Finding(
            "D001", "error", "Config did not parse to a mapping.", ""))
        return report

    ctx = CheckContext(config=config, config_path=config_path, provider=provider,
                       public=public, ephemeral_fs=ephemeral_fs)
    for check_func in _CHECKS:
        try:
            report.findings.extend(check_func(ctx) or [])
        except Exception:
            logger.exception("preflight check %s failed", getattr(check_func, "__name__", "?"))

    report.hardened_config = harden_config(config, provider=provider, workers=workers)
    report.generated = generate_secrets()
    report.exposure = _describe_exposure(config, provider, public, report)
    return report


def _describe_exposure(config: Dict[str, Any], provider: str, public: bool,
                       report: PreflightReport) -> List[str]:
    """Plain statements about what the deployed task exposes."""
    lines = []
    lines.append(f"Reachable from the public internet: {'yes' if public else 'no'}")

    user_config = config.get("user_config") or {}
    auth = config.get("authentication") or {}
    method = auth.get("method", auth.get("type", "in_memory"))
    allow_all = user_config.get("allow_all_users", True)
    roster = user_config.get("users") or []

    if method == "oauth":
        providers = ", ".join((auth.get("providers") or {}).keys()) or "unspecified"
        lines.append(f"Sign-in: OAuth ({providers})")
    elif allow_all:
        lines.append("Sign-in: open — anyone with the URL can create an account")
    else:
        lines.append(f"Sign-in: restricted to {len(roster)} named user(s)")

    passwordless = (config.get("require_no_password") is True
                    or config.get("require_password") is False)
    lines.append(f"Password required: {'no' if passwordless else 'yes'}")
    lines.append("Admin access: via the generated admin API key "
                 "(injected as POTATO_ADMIN_API_KEY, not written into the bundle)")

    if config.get("ai_support"):
        lines.append("AI features enabled: annotator input may be sent to an LLM provider")

    error_count = len(report.errors)
    warning_count = len(report.warnings)
    lines.append(f"Preflight: {error_count} error(s), {warning_count} warning(s)")
    return lines


def render_report(report: PreflightReport) -> str:
    """Human-readable preflight output."""
    out = [f"Preflight for {report.config_file}  (provider: {report.provider})", ""]

    order = {"error": 0, "warning": 1, "info": 2}
    for finding in sorted(report.findings, key=lambda f: order.get(f.severity, 3)):
        label = {"error": "ERROR  ", "warning": "WARNING", "info": "note   "}.get(
            finding.severity, finding.severity)
        out.append(f"{label} [{finding.code}] {finding.message}")
        if finding.remedy:
            out.append(f"        -> {finding.remedy}")

    if not report.findings:
        out.append("No findings.")

    out.append("")
    out.append("Exposure:")
    out.extend(f"  {line}" for line in report.exposure)
    out.append("")
    out.append("PASS — safe to deploy" if report.ok
               else f"BLOCKED — {len(report.errors)} error(s) must be fixed")
    return "\n".join(out)
