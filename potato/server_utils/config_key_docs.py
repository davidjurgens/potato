"""
Human- and machine-readable documentation for Potato's config keys.

`KNOWN_CONFIG_KEYS` in `config_module.py` is the authoritative list of key
*names* -- it is what `validate_unknown_keys()` checks typos against -- but it
carries no other information. Its values are `None`, a `set` of sub-key names,
or a nested `dict`, and that shape is load-bearing for the recursive walk, so
there is nowhere in it to put a type, a default, or a sentence of prose.

This module supplies that missing half as a parallel table keyed by **dotted
path**, which is what lets nested keys be documented at all: `_object_schema()`
in `config_schema.py` emitted a bare `{}` for every sub-key, so
`attention_checks.failure_handling` had no type and no description anywhere in
the published JSON Schema.

Consumers:

    config_schema.build_config_schema()      -> description / type / default / examples
    scripts/generate_config_reference.py     -> the Description and Default columns
    potato/mcp_server/                       -> the describe_config_key tool

Coverage is a ratchet rather than a requirement: `tests/unit/test_config_key_docs.py`
tolerates the keys that were already undocumented when this table was introduced
but fails on any *new* key that arrives without an entry, so the gap can only
shrink.

Usage:
    from potato.server_utils.config_key_docs import get_key_doc, iter_key_docs
    doc = get_key_doc("attention_checks.frequency")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, Optional, Tuple


class _Unset:
    """Sentinel distinguishing 'no default' from a default of None/False/0."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<unset>"

    def __bool__(self) -> bool:
        return False


UNSET = _Unset()


@dataclass(frozen=True)
class ConfigKeyDoc:
    """What a config key is for, and what shape it takes.

    Attributes:
        summary: One line, no trailing period needed. Written for someone --
            or something -- deciding whether this is the key they want.
        type: JSON Schema type name, or several joined by "|" for the keys that
            genuinely accept more than one shape -- `num_annotators_per_item` is
            an integer or a per-category mapping, and `phases` is a list or an
            ordered mapping. Must not contradict `_OPTIONAL_INT_FIELDS` or
            `_OPTIONAL_BOOL_FIELDS` in config_module, which remain the authority
            for the keys they cover. Use "any" when nothing useful can be said.
        default: The value the server behaves as if it saw. `UNSET` when the key
            has no meaningful default or the default is computed.
        required: True only for keys `validate_yaml_structure()` insists on.
        category: Grouping for the generated reference. Owning it here keeps
            a new key from silently landing in the "Other" bucket.
        example: A short illustrative value.
        see_also: Related dotted paths.
    """

    summary: str
    type: str = "any"
    default: Any = UNSET
    required: bool = False
    category: str = "Other"
    example: Any = None
    see_also: Tuple[str, ...] = field(default_factory=tuple)


_D = ConfigKeyDoc

# Category labels. `scripts/generate_config_reference.py` decides the order they
# are printed in; membership is decided here, next to each key.
CORE = "Core / Required"
DATA = "Data Sources"
ANNOT = "Annotation"
AUTH = "Authentication / Login"
SERVER = "Server"
QC = "Quality Control"
AI = "AI Support"
UI = "UI & Layout"
ASSIGN = "Assignment & Sessions"
FEATURES = "Advanced Features"
CONTENT = "Content"
DEBUG = "Debug / Logging"
INTEG = "External Integrations"
# Labels that already existed as sections in the generated reference (they were
# spelled out in CATEGORY_ORDER in scripts/generate_config_reference.py before
# this table reached their keys). Mirrored here so a documented key keeps the
# section it has always printed in rather than migrating on the first edit.
QDA = "Qualitative Coding (QDA)"
ANNOT_FEAT = "Annotation Features"
MEDIA = "Media"
PUBLISHING = "Publishing & Export"
AGENT = "Agent"
AGENT_EVAL = "Agent Evaluation Suite"
WORKFLOW = "Workflow & Phases"


CONFIG_KEY_DOCS: Dict[str, ConfigKeyDoc] = {
    # ---------------------------------------------------------------- core --
    "annotation_task_name": _D(
        "Display name for the task, shown in the browser title and the header",
        type="string", required=True, category=CORE, example="Sentiment Annotation",
    ),
    "task_dir": _D(
        "Root directory every other relative path in this config resolves "
        "against, and the boundary path validation refuses to escape",
        type="string", required=True, category=CORE, example=".",
        see_also=("output_annotation_dir",),
    ),
    "output_annotation_dir": _D(
        "Directory annotations, user state and exports are written to",
        type="string", required=True, category=CORE, example="annotation_output/",
    ),
    "output_annotation_format": _D(
        "Deprecated, and read as `export_annotation_format` at load time with "
        "a warning (`json` becomes `jsonl`, since no exporter is called "
        "`json`). It will stop being read in a later release, so rename it. "
        "Annotations are stored as "
        "`<output_annotation_dir>/<user>/user_state.json` whatever it says; "
        "this key never changed that",
        type="string", default="", category=CORE, example="jsonl",
        see_also=("export_annotation_format", "output_annotation_dir"),
    ),
    "item_properties": _D(
        "Maps the fields of your data file onto the roles Potato needs: which "
        "field is the identifier and which holds the text to annotate",
        type="object", required=True, category=CORE,
    ),
    "item_properties.id_key": _D(
        "Field holding each item's unique identifier",
        type="string", required=True, category=CORE, example="id",
    ),
    "item_properties.text_key": _D(
        "Field holding the text shown to the annotator",
        type="string", required=True, category=CORE, example="text",
    ),
    "item_properties.category_key": _D(
        "Field holding a category label, used by category-based assignment",
        type="string", category=CORE, see_also=("assignment_strategy",),
    ),
    "item_properties.kwargs": _D(
        "Extra per-item fields to carry through to the display layer",
        type="object", category=CORE,
    ),
    "task_description": _D(
        "Short description of the task, shown to annotators",
        type="string", category=CORE,
    ),
    "annotation_task_description": _D(
        "Longer task description; falls back to task_description when absent",
        type="string", category=CORE,
    ),

    # ---------------------------------------------------------------- data --
    "data_files": _D(
        "Input data files. JSON, JSONL, CSV and TSV are all accepted; JSON may "
        "be either an array of objects or one object per line",
        type="array", category=DATA, example=["data/items.json"],
        see_also=("data_directory", "data_sources"),
    ),
    "data_directory": _D(
        "Load every data file in a directory instead of listing them",
        type="string", category=DATA, see_also=("watch_data_directory",),
    ),
    "data_directory_encoding": _D(
        "Text encoding used to read files under data_directory",
        type="string", default="utf-8", category=DATA,
    ),
    "data_sources": _D(
        "Remote or live inputs (url, s3, huggingface, google_sheets, database, "
        "google_drive, dropbox, file), optionally polled for new rows",
        type="array", category=DATA,
    ),
    "watch_data_directory": _D(
        "Rescan data_directory while the server runs and pick up new files",
        type="boolean", default=False, category=DATA,
        see_also=("watch_poll_interval",),
    ),
    "watch_poll_interval": _D(
        "Seconds between rescans when watch_data_directory is on",
        type="number", default=5.0, category=DATA,
    ),
    "partial_loading": _D(
        "Load items lazily rather than reading every file at startup",
        type="object", category=DATA,
    ),
    "data_cache": _D(
        "Cache for remote data sources",
        type="object", category=DATA,
    ),
    "data_cache.enabled": _D("Turn the remote-source cache on", type="boolean", category=DATA),
    "data_cache.ttl_seconds": _D(
        "How long a cached fetch stays fresh", type="integer", category=DATA,
    ),
    "data_cache.max_size_mb": _D(
        "Cache size ceiling in megabytes", type="integer", category=DATA,
    ),
    "media_directory": _D(
        "Directory served at /media/, so data files can reference local images, "
        "audio and video by relative path instead of an external URL",
        type="string", default="media", category=DATA,
    ),

    # ---------------------------------------------------------- annotation --
    "annotation_schemes": _D(
        "The questions annotators answer. Each entry needs an annotation_type "
        "from the schema registry plus a name and description",
        type="array", category=ANNOT,
    ),
    "phases": _D(
        "Per-phase configuration (consent, instructions, training, annotation, "
        "post-study). Either a list of phase objects or a mapping with an "
        "`order` key. Phase-level annotation_schemes replace the top-level list "
        "rather than adding to it",
        type="array|object", category=ANNOT,
    ),
    "surveyflow": _D(
        "Survey pages shown before and after annotation",
        type="object", category=ANNOT,
    ),
    "training": _D(
        "Qualification phase annotators must pass before real items",
        type="object", category=ANNOT,
    ),
    "pre_annotation": _D(
        "Seed annotations to show as a starting point for each item",
        type="object", category=ANNOT,
    ),

    # ---------------------------------------------------------------- auth --
    "user_config": _D(
        "Who may log in", type="object", category=AUTH,
    ),
    "user_config.allow_all_users": _D(
        "Let anyone register and annotate, rather than only listed users",
        type="boolean", default=True, category=AUTH,
    ),
    "user_config.users": _D(
        "Allowlist of usernames, used when allow_all_users is false",
        type="array", category=AUTH,
    ),
    "authentication": _D(
        "Identity provider settings for SSO and database-backed accounts",
        type="object", category=AUTH,
    ),
    "authentication.method": _D(
        "Which backend holds accounts: in_memory (the default), database, "
        "oauth or clerk",
        type="string", default="in_memory", category=AUTH, example="database",
        see_also=("authentication.user_config_path", "authentication.database_url"),
    ),
    "authentication.user_config_path": _D(
        "JSONL file of registered accounts, one {username, password} object per "
        "line, with the password stored as salt$hash. Under the default "
        "in_memory backend this is the ONLY thing that makes accounts survive a "
        "restart: unset, registrations live in memory and every annotator loses "
        "their login when the server stops, while their annotations remain in "
        "output_annotation_dir. Set it on anything an annotator will come back to",
        type="string", category=AUTH, example="user_config.json",
        see_also=("authentication.method", "user_config.allow_all_users"),
    ),
    "authentication.database_url": _D(
        "SQLAlchemy URL for the database backend; falls back to the "
        "POTATO_DB_CONNECTION environment variable",
        type="string", category=AUTH, example="sqlite:///potato_users.db",
        see_also=("authentication.method",),
    ),
    "authentication.allow_local_login": _D(
        "Keep username/password registration available alongside SSO",
        type="boolean", category=AUTH,
    ),
    "authentication.auto_register": _D(
        "Create an account the first time an SSO identity signs in",
        type="boolean", category=AUTH,
    ),
    "authentication.providers": _D(
        "OAuth provider settings, keyed by provider name",
        type="object", category=AUTH,
    ),
    "authentication.allowed_domains": _D(
        "Email domains permitted to sign in through SSO",
        type="array", category=AUTH, example=["umich.edu"],
    ),
    "authentication.allowed_domain": _D(
        "Single-domain form of allowed_domains",
        type="string", category=AUTH,
        see_also=("authentication.allowed_domains",),
    ),
    "authentication.allowed_org": _D(
        "Organization permitted to sign in through SSO",
        type="string", category=AUTH,
    ),
    "authentication.user_identity_field": _D(
        "Which claim from the identity provider becomes the Potato username",
        type="string", category=AUTH, example="email",
    ),
    "login": _D(
        "Login mode. type: password, url_direct, or none",
        type="object", category=AUTH,
    ),
    "login.type": _D(
        "How annotators identify themselves",
        type="string", category=AUTH, example="password",
    ),
    "login.url_argument": _D(
        "Query parameter carrying the user id under url_direct login",
        type="string", category=AUTH, example="PROLIFIC_PID",
    ),
    "require_password": _D(
        "Require a password at login", type="boolean", category=AUTH,
    ),
    "require_no_password": _D(
        "Accept a username with no password", type="boolean", category=AUTH,
    ),
    "secret_key": _D(
        "Flask session signing key. Set this for any deployment that must keep "
        "sessions valid across restarts",
        type="string", category=AUTH,
    ),
    "admin_api_key": _D(
        "Shared key for the admin API, sent as the X-API-Key header. Generated "
        "and persisted to {task_dir}/admin_api_key.txt when unset",
        type="string", category=AUTH,
    ),
    "rbac": _D(
        "Role assignments and SSO role mapping", type="object", category=AUTH,
    ),
    "user_roles": _D(
        "Per-user quota and role overrides", type="object", category=AUTH,
    ),

    # -------------------------------------------------------------- server --
    "port": _D(
        "Port to listen on. The -p flag overrides this",
        type="integer", default=8000, category=SERVER,
    ),
    "host": _D(
        "Interface to bind. 0.0.0.0 exposes the server beyond localhost",
        type="string", default="localhost", category=SERVER,
    ),
    "server": _D(
        "Nested port/host/debug block, an alternative to the top-level keys",
        type="object", category=SERVER,
    ),
    "site_dir": _D(
        "Directory holding the HTML templates for this task",
        type="string", category=SERVER,
    ),
    "site_file": _D(
        "Specific template file to render the annotation page with",
        type="string", category=SERVER,
    ),
    "base_html_template": _D(
        "Base template every page extends",
        type="string", category=SERVER,
    ),
    "persist_sessions": _D(
        "Keep annotator sessions across a server restart",
        type="boolean", default=False, category=SERVER,
    ),
    "session_lifetime_days": _D(
        "Days before a persisted session expires",
        type="integer", default=2, category=SERVER,
    ),
    "customjs": _D(
        "Enable custom JavaScript injection", type="boolean", category=SERVER,
    ),
    "customjs_hostname": _D(
        "Hostname custom JavaScript is served from", type="string", category=SERVER,
    ),

    # ----------------------------------------------------------- assignment --
    "assignment_strategy": _D(
        "How items are handed out: random, fixed_order, active_learning, "
        "llm_confidence, max_diversity, least_annotated, category_based, "
        "diversity_clustering, batch, priority, or psychometric",
        type="string", default="fixed_order", category=ASSIGN,
    ),
    "automatic_assignment": _D(
        "Assign items to annotators automatically as they arrive",
        type="object", category=ASSIGN,
    ),
    "max_annotations_per_user": _D(
        "Cap on how many dataset items one annotator may receive. Left unset, "
        "the cap is the number of items loaded, so every annotator is offered "
        "the whole corpus; -1 is explicit unlimited, which is what a dynamic "
        "data source needs for items added after boot to be assignable. "
        "Injected attention checks and gold items do not count against it",
        type="integer", default=-1, category=ASSIGN,
    ),
    "max_annotations_per_item": _D(
        "Cap on how many annotators may label one item. -1 means unlimited",
        type="integer", default=-1, category=ASSIGN,
    ),
    "num_annotators_per_item": _D(
        "Target annotators per item. Either a plain count or a mapping carrying "
        "`default` plus overlap-sampling and adaptive-boost rules",
        type="integer|object", default=3, category=ASSIGN,
    ),
    "min_annotators_per_instance": _D(
        "Floor on annotators per item before it counts as done",
        type="integer", category=ASSIGN,
    ),
    "alert_time_each_instance": _D(
        "Seconds an annotator may spend on one item before being warned. The "
        "default is effectively no limit",
        type="integer", default=10000000, category=ASSIGN,
    ),
    "max_session_seconds": _D(
        "Hard limit on one annotation session", type="integer", category=ASSIGN,
    ),
    "batch_assignment": _D(
        "Split items into named groups and assign whole batches",
        type="object", category=ASSIGN,
    ),
    "random_seed": _D(
        "Seed for assignment shuffling, so an ordering can be reproduced",
        type="integer", category=ASSIGN,
    ),

    # ------------------------------------------------------ quality control --
    "attention_checks": _D(
        "Insert items with a known answer to detect inattentive annotators",
        type="object", category=QC,
    ),
    "attention_checks.enabled": _D("Turn attention checks on", type="boolean", category=QC),
    "attention_checks.items_file": _D(
        "File holding the attention-check items", type="string", category=QC,
    ),
    "attention_checks.frequency": _D(
        "Insert a check every N items", type="integer", category=QC,
    ),
    "attention_checks.probability": _D(
        "Chance of inserting a check, as an alternative to frequency",
        type="number", category=QC,
    ),
    "attention_checks.min_response_time": _D(
        "Responses faster than this many seconds count as a failure",
        type="number", category=QC,
    ),
    "attention_checks.failure_handling": _D(
        "What to do when an annotator fails a check. A bare action name, or a "
        "mapping with warn/block thresholds and messages",
        type="string|object", category=QC,
    ),
    "attention_checks.geometry_iou_tolerance": _D(
        "Overlap a drawn answer must reach to count as correct, as a fraction",
        type="number", category=QC,
    ),
    "gold_standards": _D(
        "Items with known labels, used to score annotators",
        type="object", category=QC,
    ),
    "gold_standards.enabled": _D("Turn gold standards on", type="boolean", category=QC),
    "gold_standards.items_file": _D("File holding the gold items", type="string", category=QC),
    "gold_standards.mode": _D("How gold items are surfaced", type="string", category=QC),
    "gold_standards.frequency": _D("Insert a gold item every N items", type="integer", category=QC),
    "gold_standards.accuracy": _D(
        "Accuracy an annotator must hold to keep going. A bare fraction, or a "
        "mapping with `min_threshold` and `evaluation_count`",
        type="number|object", category=QC,
    ),
    "gold_standards.auto_promote": _D(
        "Promote annotators who pass to the full task. A flag, or a mapping with "
        "`min_annotators` and `agreement_threshold`",
        type="boolean|object", category=QC,
    ),
    "gold_standards.feedback": _D(
        "What an annotator is told after a gold item. A mapping with "
        "`show_correct_answer` and `show_explanation`; both off means silent "
        "scoring",
        type="object", category=QC,
    ),
    "gold_standards.geometry_iou_tolerance": _D(
        "Overlap a drawn answer must reach to count as correct, as a fraction",
        type="number", category=QC,
    ),
    "gold_standards_file": _D(
        "Gold items file, the flat alternative to the gold_standards block",
        type="string", category=QC,
    ),
    "quality_control": _D(
        "Aggregate quality thresholds and actions", type="object", category=QC,
    ),
    "agreement_metrics": _D(
        "Which inter-annotator agreement measures the admin pages compute",
        type="object", category=QC,
    ),
    "adjudication": _D(
        "Resolve disagreements through an adjudication queue",
        type="object", category=QC,
    ),
    "require_fully_annotated": _D(
        "Refuse to advance until every scheme on the page has an answer",
        type="boolean", category=QC,
    ),

    # ------------------------------------------------------------------ ai --
    "ai_support": _D(
        "Model-backed label suggestions shown alongside each item",
        type="object", category=AI,
    ),
    "ai_support.enabled": _D(
        "Turn AI assistance on. Without an endpoint that starts, the boot log "
        "says so and no assistant appears",
        type="boolean", default=False, category=AI,
    ),
    "ai_support.endpoint_type": _D(
        "Which backend to talk to: openai, openai_vision, anthropic, "
        "anthropic_vision, gemini, huggingface, ollama, ollama_vision, "
        "openrouter, vllm, yolo, sam, sam3",
        type="string", default="openai", category=AI, example="vllm",
    ),
    "ai_support.ai_config": _D(
        "Everything about the model itself: model, base_url, api_key, "
        "max_tokens, temperature, timeout, include. One level deeper than the "
        "obvious guess — ai_support.model is not read",
        type="object", category=AI,
    ),
    "ai_support.ai_config.model": _D(
        "Model name as the backend spells it",
        type="string", category=AI, example="gpt-4o",
    ),
    "ai_support.ai_config.base_url": _D(
        "An OpenAI-compatible server to use instead of the vendor's: vLLM, "
        "SGLang, LM Studio, llama.cpp, LiteLLM. Setting it also makes api_key "
        "optional, because self-hosted servers do not have one",
        type="string", category=AI, example="http://localhost:8000/v1",
    ),
    "ai_support.ai_config.api_key": _D(
        "Key for a commercial endpoint. Not needed when base_url points at a "
        "self-hosted server; openai and openai_vision also read OPENAI_API_KEY "
        "from the environment",
        type="string", category=AI,
    ),
    "ai_support.ai_config.max_tokens": _D(
        "Cap on the reply. The multi-label formats (a rationale or a keyword "
        "set for every label) need several hundred; below that the reply is "
        "cut off and the assistant renders empty",
        type="integer", default=800, category=AI, example=800,
    ),
    "ai_support.ai_config.temperature": _D(
        "Sampling temperature, 0 to 2", type="number", default=0.1, category=AI,
    ),
    "ai_support.ai_config.timeout": _D(
        "Seconds to wait for the model", type="integer", default=30, category=AI,
    ),
    "ai_support.ai_config.include": _D(
        "Which schemes get assistants. Off by default: without it every "
        "assistant button is absent and the page renders an empty ai-help div",
        type="object", category=AI,
    ),
    "ai_support.ai_config.include.all": _D(
        "Show assistants on every scheme. This is the switch most authors "
        "want, and nothing warns when it is missing",
        type="boolean", default=False, category=AI, example=True,
    ),
    "ai_support.ai_config.include.special_include": _D(
        "Per-page, per-scheme assistant list, keyed page number -> annotation "
        "id -> list of assistant names. Use instead of include.all to show "
        "assistants on some schemes only",
        type="object", category=AI,
    ),
    "ai_support.ai_config_file": _D(
        "Path to a separate YAML file holding the endpoint settings, so keys "
        "stay out of the repo. Its keys are merged FLAT into ai_config, so the "
        "file holds model/base_url/api_key directly — a nested ai_config: "
        "block inside it becomes ai_config.ai_config and is ignored. "
        "endpoint_type is the one key lifted to the ai_support level. A "
        "missing file disables AI support with a warning, which "
        "`validate --strict` treats as an error",
        type="string", category=AI, example="ai-config.yaml",
    ),
    "ai_support.ai_config.api_base": _D(
        "Older spelling of base_url, accepted by the openai_vision endpoint",
        type="string", category=AI, see_also=("ai_support.ai_config.base_url",),
    ),
    "ai_support.ai_config.enabled": _D(
        "Read by the visual endpoints as a per-endpoint off switch, leaving the "
        "rest of ai_support in place",
        type="boolean", default=True, category=AI,
    ),
    "ai_support.ai_config.detail": _D(
        "How much of the image the model is charged for: low, high or auto "
        "(openai_vision)",
        type="string", default="auto", category=AI,
    ),
    "ai_support.ai_config.json_mode": _D(
        "Ask the server to constrain output to JSON. Servers without "
        "constrained decoding reject it; the endpoint notices and retries "
        "without, so this rarely needs setting (openai_vision)",
        type="boolean", default=True, category=AI,
    ),
    "ai_support.ai_config.max_image_size": _D(
        "Longest edge, in pixels, an image is downscaled to before it is sent",
        type="integer", category=AI,
    ),
    "ai_support.ai_config.think": _D(
        "Let a reasoning model emit its thinking block. Off keeps the reply to "
        "the answer (vllm)",
        type="boolean", default=False, category=AI,
    ),
    "ai_support.ai_config.classes": _D(
        "Detection classes to keep, by name. Anything else the detector finds "
        "is dropped (yolo)",
        type="array", category=AI,
    ),
    "ai_support.ai_config.custom_classes": _D(
        "Open-vocabulary class names for a detector that accepts them, instead "
        "of its trained label set",
        type="array", category=AI,
    ),
    "ai_support.ai_config.confidence_threshold": _D(
        "Lowest detection score kept", type="number", category=AI,
    ),
    "ai_support.ai_config.iou_threshold": _D(
        "Overlap above which two detections are treated as the same object",
        type="number", category=AI,
    ),
    "ai_support.ai_config.device": _D(
        "Where a local model runs: cpu, cuda, mps",
        type="string", category=AI,
    ),
    "ai_support.ai_config.max_frames": _D(
        "Most frames sampled from a video for one request",
        type="integer", category=AI,
    ),
    "ai_support.ai_config.default_video_fps": _D(
        "Frame rate assumed when a video does not declare one",
        type="number", category=AI,
    ),
    "ai_support.cache_config": _D(
        "Disk cache and prefetch for model replies, so an annotator does not "
        "wait for a generation the study has already paid for",
        type="object", category=AI,
    ),
    "chat_support": _D(
        "In-task chat with a model", type="object", category=AI,
    ),
    "active_learning": _D(
        "Order items by model uncertainty", type="object", category=AI,
        see_also=("assignment_strategy",),
    ),
    "icl_labeling": _D(
        "In-context-learning labeler that builds few-shot prompts from "
        "high-confidence annotations already collected",
        type="object", category=AI,
    ),
    "llm_labeling": _D("Bulk labeling by a model", type="object", category=AI),

    # ------------------------------------------------------------------ ui --
    "instance_display": _D(
        "How each item is rendered: one entry per field, with a type drawn from "
        "the display registry (text, image, audio, video, ...)",
        type="object", category=UI,
    ),
    "ui": _D("Interface toggles", type="object", category=UI),
    "ui_config": _D("Additional interface settings", type="object", category=UI),
    "ui_language": _D(
        "Interface language code", type="string", default="en", category=UI,
    ),
    # /admin/iaa agreement-drift strings. Every OTHER ui_language.* key
    # predates the coverage ratchet and sits on the legacy exemption list;
    # new ones are documented here so the published JSON Schema, the config
    # reference and describe_config_key all know about them.
    "ui_language.iaa_drift_title": _D(
        "Heading of the agreement-over-time section on /admin/iaa",
        type="string", category=UI,
    ),
    "ui_language.iaa_drift_note": _D(
        "Sentence explaining what a window is and how it is scored",
        type="string", category=UI,
    ),
    "ui_language.iaa_drift_recalibrate": _D(
        "Label on the prompt raised when agreement falls below baseline",
        type="string", category=UI,
    ),
    "ui_language.iaa_drift_below_baseline": _D(
        "Phrase following the percentage in the re-calibration prompt",
        type="string", category=UI,
    ),
    "ui_language.iaa_drift_baseline": _D(
        "Row label for the whole-project agreement figure",
        type="string", category=UI,
    ),
    "ui_language.iaa_drift_th_window": _D(
        "Short column prefix for a window, e.g. the W in W1, W2",
        type="string", category=UI,
    ),
    "ui_language.iaa_drift_sparse": _D(
        "Note on a window holding too few items to judge",
        type="string", category=UI,
    ),
    "ui_language.iaa_drift_codebook_changes": _D(
        "Label preceding the list of codebook revisions on the timeline",
        type="string", category=UI,
    ),
    "ui_language.iaa_drift_approx": _D(
        "Marks a codebook revision whose date was inferred rather than recorded",
        type="string", category=UI,
    ),
    "ui_language.iaa_drift_untimed": _D(
        "Note about items with no timestamp, which cannot be placed on the "
        "timeline",
        type="string", category=UI,
    ),
    "layout": _D(
        "How the annotation questions are arranged on the page: a grid, "
        "collapsible groups, an explicit order, and responsive breakpoints. "
        "Without it every scheme stacks full-width in config order",
        type="object", category=UI,
        see_also=("layout.grid", "layout.groups", "layout.order"),
    ),
    "layout.grid": _D(
        "Grid the question forms are laid out in",
        type="object", category=UI, example={"columns": 2, "gap": "1rem"},
    ),
    "layout.grid.columns": _D(
        "Columns in the form grid, 1 to 6. A scheme spans one unless its own "
        "layout.columns says otherwise",
        type="integer", default=2, category=UI,
    ),
    "layout.grid.gap": _D(
        "CSS gap between forms, as a string", type="string", default="1rem",
        category=UI, example="0.75rem",
    ),
    "layout.grid.row_gap": _D(
        "CSS gap between rows, when it should differ from gap",
        type="string", category=UI, example="0.75rem",
    ),
    "layout.grid.align_items": _D(
        "Vertical alignment within a row: start, center, end or stretch",
        type="string", default="start", category=UI,
    ),
    "layout.groups": _D(
        "Collapsible titled sections, each holding named schemes. The way to "
        "keep a long question list navigable",
        type="array", category=UI,
        see_also=("layout.order",),
    ),
    "layout.groups.id": _D(
        "Identifier for the group, unique within layout.groups. Required",
        type="string", category=UI, required=True,
    ),
    "layout.groups.schemas": _D(
        "Names of the annotation schemes this group holds, in the order they "
        "should appear. Required, non-empty, and every name must be a real "
        "scheme -- an unknown one fails validation",
        type="array", category=UI, required=True,
    ),
    "layout.groups.title": _D(
        "Heading shown on the group", type="string", category=UI,
    ),
    "layout.groups.description": _D(
        "Line of explanation under the group heading",
        type="string", category=UI,
    ),
    "layout.groups.collapsible": _D(
        "Let annotators fold the group away", type="boolean", category=UI,
    ),
    "layout.groups.collapsed_default": _D(
        "Start the group folded. Only sensible for questions most items do "
        "not need, since a folded question is one annotators skip",
        type="boolean", category=UI,
    ),
    "layout.groups.background_color": _D(
        "CSS colour for this group, overriding the alternating default",
        type="string", category=UI, example="#f8f9fc",
    ),
    "layout.order": _D(
        "Scheme names in the order they should appear, overriding config order",
        type="array", category=UI,
    ),
    "layout.breakpoints": _D(
        "Viewport widths, in pixels, where the grid reduces",
        type="object", category=UI, example={"mobile": 480, "tablet": 768},
    ),
    "layout.breakpoints.mobile": _D(
        "Below this width the grid collapses to one column",
        type="integer", default=480, category=UI,
    ),
    "layout.breakpoints.tablet": _D(
        "Below this width column spans are reduced",
        type="integer", default=768, category=UI,
    ),
    "layout.styling": _D(
        "Colours, padding and alignment for groups and forms",
        type="object", category=UI,
        see_also=("layout.grid",),
    ),
    "layout.styling.align_items": _D(
        "Vertical alignment of forms inside a group: start, center, end or "
        "stretch",
        type="string", default="start", category=UI,
    ),
    "layout.styling.content_align": _D(
        "Horizontal alignment of the content inside a form: left, center or "
        "right",
        type="string", default="left", category=UI,
    ),
    "layout.styling.group_background_odd": _D(
        "Background colour for odd-numbered groups",
        type="string", default="#fafafa", category=UI,
    ),
    "layout.styling.group_background_even": _D(
        "Background colour for even-numbered groups",
        type="string", default="#f8f9fc", category=UI,
    ),
    "layout.styling.group_padding": _D(
        "CSS padding inside a group", type="string", default="0.5rem 0.75rem",
        category=UI,
    ),
    "layout.styling.form_padding": _D(
        "CSS padding inside one question form", type="string",
        default="0.375rem 0.5rem", category=UI,
    ),
    "task_layout": _D(
        "Custom HTML for the annotation form area", type="string", category=UI,
    ),
    "base_css": _D("Extra stylesheet to load", type="string", category=UI),
    "hide_navbar": _D("Hide the top navigation bar", type="boolean", category=UI),
    "list_as_text": _D(
        "Render list-valued fields as text rather than as a list",
        type="object", category=UI,
    ),
    "horizontal_key_bindings": _D(
        "Lay keyboard shortcut hints out horizontally", type="boolean", category=UI,
    ),
    "jumping_to_id_disabled": _D(
        "Remove the jump-to-item control", type="boolean", category=UI,
    ),
    "format_handling": _D(
        "How rich text and markup in item fields are rendered",
        type="object", category=UI,
    ),

    # ------------------------------------------------------------- content --
    "annotation_instructions": _D(
        "Instructions shown on every annotation page, as inline text; a filename here renders as that filename", type="string", category=CONTENT,
    ),
    "credentials": _D(
        "How credentials in the config are resolved before use",
        type="object", category=SERVER,
        example={"env_substitution": True, "env_file": ".env"},
    ),
    "credentials.env_substitution": _D(
        "Expand ${VAR} references in config values from the environment",
        type="boolean", default=True, category=SERVER,
    ),
    "credentials.env_file": _D(
        "Path to a .env file loaded before substitution",
        type="string", category=SERVER,
    ),
    "annotation_codebook_url": _D(
        "Link to an external codebook, shown to annotators",
        type="string", category=CONTENT,
    ),
    "custom_footer_html": _D("HTML appended to every page", type="string", category=CONTENT),
    "header_file": _D("HTML file rendered above the item", type="string", category=CONTENT),
    "header_logo": _D("Logo image shown in the header", type="string", category=CONTENT),
    "completion_code": _D(
        "Code shown when an annotator finishes, for crowdsourcing payout",
        type="string", category=CONTENT,
    ),
    "keyword_highlights_file": _D(
        "File of keywords to highlight in item text", type="string", category=CONTENT,
    ),
    "keyword_highlight_settings": _D(
        "Styling for keyword highlights", type="object", category=CONTENT,
    ),
    "highlight_linebreaks": _D(
        "Make line breaks visible in item text", type="boolean", category=CONTENT,
    ),

    # -------------------------------------------------------- integrations --
    "crowdsourcing": _D(
        "Crowd platform integration (Prolific, MTurk and others)",
        type="object", category=INTEG,
    ),
    "mcp": _D(
        "Model Context Protocol control surface, letting an agent query and "
        "control this running task. Off unless every tool is named explicitly",
        type="object", category=INTEG, see_also=("debug",),
    ),
    "mcp.enabled": _D(
        "Register the /api/mcp/* endpoints. Without this they do not exist",
        type="boolean", default=False, category=INTEG,
    ),
    "mcp.tools": _D(
        "Allowlist of tool names an agent may call. Empty grants nothing, and "
        "an unrecognized name fails at startup rather than warning",
        type="array", category=INTEG,
    ),
    "mcp.destructive": _D(
        "Second, separate opt-in for tools that discard work. A destructive "
        "tool must appear here and in mcp.tools, and callers must pass "
        "confirm: true",
        type="array", category=INTEG, see_also=("mcp.tools",),
    ),
    "mcp.scope": _D(
        "Limits on what agents may touch, e.g. `users` to restrict which "
        "annotators they can act on",
        type="object", category=INTEG,
    ),
    "mcp.auth": _D(
        "Where per-agent tokens live. `tokens_file` defaults to "
        "mcp_tokens.json under task_dir",
        type="object", category=INTEG,
    ),
    "mcp.audit_log": _D(
        "File recording every MCP call and refusal, one JSON object per line",
        type="string", default="mcp_audit.jsonl", category=INTEG,
    ),
    "mcp.allow_debug": _D(
        "Permit the MCP surface on a debug server. Off by default: debug "
        "disables admin authentication server-wide, so the two together are a "
        "remote shell",
        type="boolean", default=False, category=INTEG, see_also=("debug",),
    ),
    "trace_ingestion": _D(
        "Accept agent traces posted to /api/traces/*",
        type="object", category=INTEG,
    ),
    "trace_ingestion.enabled": _D(
        "Register the trace webhook endpoints", type="boolean", default=False,
        category=INTEG,
    ),
    "trace_ingestion.api_key": _D(
        "Shared secret for the trace webhooks, accepted as either "
        "Authorization: Bearer or X-API-Key",
        type="string", category=INTEG,
    ),
    "trace_ingestion.allow_unauthenticated": _D(
        "Accept trace posts with no api_key set. Off by default: without it the "
        "webhook endpoints reject every request rather than running open",
        type="boolean", default=False, category=INTEG,
        see_also=("trace_ingestion.api_key",),
    ),
    "trace_ingestion.sources": _D(
        "Upstream trace sources to poll", type="array", category=INTEG,
    ),
    "trace_ingestion.notify_annotators": _D(
        "Push newly ingested traces to connected annotators",
        type="boolean", category=INTEG,
    ),
    "agent_proxy": _D(
        "Run an agent as the subject of annotation", type="object", category=INTEG,
    ),
    "database": _D("Database connection for item or user storage", type="object", category=INTEG),

    # ------------------------------------------------------------- debug ---
    "debug": _D(
        "Run in debug mode. This disables admin authentication and skips login "
        "entirely, so it must never be set on a deployed server",
        type="boolean", default=False, category=DEBUG,
        see_also=("admin_api_key",),
    ),
    "debug_phase": _D(
        "Jump straight to a workflow phase, for UI debugging",
        type="string", category=DEBUG, example="annotation",
    ),
    "ui_debug": _D(
        "Print browser-side debug logging to the console",
        type="boolean", default=False, category=DEBUG,
    ),
    "debug_log": _D(
        "Which halves of the debug logging to turn on: all, ui, server or none. "
        "The --debug-log flag writes this key",
        type="string", category=DEBUG, example="server",
        see_also=("ui_debug", "server_debug"),
    ),
    "server_debug": _D(
        "Backend debug logging. Note that only the phase pages (consent, "
        "instructions, surveys) read this key; the annotation page asks the "
        "logging module, which is driven by debug_log/verbose/debug",
        type="boolean", default=False, category=DEBUG,
        see_also=("debug_log",),
    ),
    "verbose": _D(
        "Raise the log level. --verbose writes this key",
        type="boolean", default=False, category=DEBUG,
    ),
    "very_verbose": _D(
        "Raise the log level further; equivalent to debug for logging purposes, "
        "without debug's effect on authentication. --veryVerbose writes this key",
        type="boolean", default=False, category=DEBUG, see_also=("debug",),
    ),

    # ----------------------------------------------------------------- qda --
    "qda_mode": _D(
        "Qualitative data analysis mode. Turning it on moves the defaults for "
        "memos, the codebook and case grouping together, rather than each "
        "being switched on separately",
        type="object", category=QDA,
        see_also=("codebook", "annotation_ui", "cases"),
    ),
    "qda_mode.enabled": _D(
        "Master switch for QDA mode", type="boolean", default=False, category=QDA,
    ),
    "qda_mode.memos": _D(
        "QDA memo defaults: `enabled` and `show_sidebar_by_default`, both true. "
        "Memo storage itself is universal; this block only sets the QDA defaults",
        type="object", category=QDA, see_also=("annotation_ui.memos",),
    ),
    "qda_mode.codebook": _D(
        "QDA codebook defaults: `enabled` (true) and `mode` (open). Sub-keys of "
        "qda_mode are not recursed into, so an unrecognized block is carried "
        "through for forward compatibility -- and a typo passes silently",
        type="object", category=QDA, see_also=("codebook",),
    ),
    "codebook": _D(
        "The shared label set a scheme opts into with a scheme-level "
        "`codebook: true`, edited from /codebook and stored per project",
        type="object", category=QDA, see_also=("codebook_mode",),
    ),
    "codebook.enabled": _D(
        "Force the codebook on or off. Left unset it turns itself on when a "
        "scheme sets `codebook: true`, or under qda_mode/solo_mode",
        type="boolean", category=QDA,
    ),
    "codebook.mode": _D(
        "Who may change codes: fixed, extensible (annotators may add) or open "
        "(annotators may add and edit)",
        type="string", category=QDA, example="extensible",
        see_also=("codebook_mode",),
    ),
    "codebook.distiller": _D(
        "What the distilled, prompt-facing view of the codebook contains: "
        "include, include_types, include_doc_sections, scope, procedure, max_chars",
        type="object", category=QDA,
    ),
    "codebook_mode": _D(
        "Top-level shorthand for codebook.mode, and the value that wins when "
        "both are set. Unset it resolves to open under qda_mode/solo_mode and "
        "fixed otherwise; a crowdsourcing backend force-locks fixed",
        type="string", category=QDA, example="open",
        see_also=("codebook.mode", "crowdsourcing"),
    ),
    "codebook_invivo_key": _D(
        "Key that opens the in-vivo 'code from selection' composer while text "
        "is selected in a codebook-backed span scheme. Only the first character "
        "is used",
        type="string", default="i", category=QDA, see_also=("codebook",),
    ),
    "annotation_ui": _D(
        "Annotation-surface toggles that are not gated on QDA mode",
        type="object", category=QDA,
    ),
    "annotation_ui.memos": _D(
        "Show the memo sidebar. Unset means off in standard mode and on under "
        "qda_mode/solo_mode; set explicitly it wins either way",
        type="boolean", category=QDA, see_also=("qda_mode.memos",),
    ),
    "annotation_ui.visibility": _D(
        "Visibility a new memo gets: private or shared. Anything else falls "
        "back to private",
        type="string", default="private", category=QDA,
    ),
    "cases": _D(
        "Group instances into units of analysis -- a participant, an interview "
        "-- so codes can be counted per case rather than per item",
        type="object", category=QDA, see_also=("qda_mode", "sessions"),
    ),
    "cases.enabled": _D(
        "Turn case grouping on or off explicitly. Unset, it follows qda_mode",
        type="boolean", category=QDA,
    ),
    "cases.key": _D(
        "Item field to group on. Unset, detection scans participant_id, "
        "respondent_id and case_id",
        type="string", category=QDA, example="participant_id",
    ),
    "cases.auto_detect": _D(
        "Scan loaded items for cases at startup. Set false to assign cases by hand",
        type="boolean", default=True, category=QDA,
    ),
    "cases.attributes": _D(
        "Item fields lifted onto the case so they can be crosstabbed",
        type="array", category=QDA,
    ),
    "search": _D(
        "Full-text search over loaded items, backed by SQLite FTS5. Admin "
        "search is read-only and always available; annotator search-and-claim "
        "is a separate opt-in",
        type="object", category=QDA,
    ),
    "search.enabled": _D(
        "Build the search index at startup", type="boolean", default=True, category=QDA,
    ),
    "search.backend": _D(
        "Index backend. fts5 is the only one built in; any other name disables "
        "search with a warning",
        type="string", default="fts5", category=QDA,
    ),
    "search.max_instances": _D(
        "Ceiling on how many instances are indexed",
        type="integer", default=100000, category=QDA,
    ),
    "search.annotator_claim": _D(
        "Let annotators search the corpus and claim their own next item. "
        "Refused at startup when combined with a sampling-dependent assignment "
        "strategy or an overlap cap, since self-selection breaks both. Allowed "
        "unconditionally under qda_mode/solo_mode",
        type="boolean", default=False, category=QDA,
        see_also=("assignment_strategy", "num_annotators_per_item"),
    ),

    # ---------------------------------------------------- advanced features --
    "psychometrics": _D(
        "Live IRT. Fits item difficulty and annotator ability as labels arrive, "
        "so labels carry error bars and confident items can stop early",
        type="object", category=FEATURES, see_also=("assignment_strategy",),
    ),
    "psychometrics.enabled": _D(
        "Fit the model and serve the dashboard. Adaptive routing additionally "
        "needs assignment_strategy: psychometric",
        type="boolean", default=False, category=FEATURES,
    ),
    "psychometrics.schema": _D(
        "Scheme the model scores. Defaults to the first radio or likert scheme",
        type="string", category=FEATURES,
    ),
    "psychometrics.refit_interval": _D(
        "Refit once this many new labels have arrived since the last fit",
        type="integer", default=5, category=FEATURES,
    ),
    "psychometrics.min_observations": _D(
        "Cold-start gate: routing falls back to random until this many labels "
        "exist, so early assignments build the overlap the model needs",
        type="integer", default=20, category=FEATURES,
    ),
    "psychometrics.min_annotators_per_item": _D(
        "Floor before an item may be stopped early, however confident the posterior",
        type="integer", default=2, category=FEATURES,
    ),
    "psychometrics.confidence_threshold": _D(
        "Posterior probability at which an item counts as resolved. Outside "
        "0.5-1.0 it is ignored and 0.95 used",
        type="number", default=0.95, category=FEATURES,
    ),
    "psychometrics.cost_per_judgment": _D(
        "Cost of one judgment, used to price the saved judgments on the dashboard",
        type="number", category=FEATURES,
    ),
    "psychometrics.discrimination_flag_threshold": _D(
        "Items whose ability-versus-correctness correlation falls below this "
        "are flagged as likely codebook bugs",
        type="number", default=-0.2, category=FEATURES,
    ),
    "mace": _D(
        "MACE competence estimation: infers per-annotator reliability and a "
        "predicted label per item from the disagreement pattern alone",
        type="object", category=FEATURES, see_also=("agreement_metrics",),
    ),
    "mace.enabled": _D("Run MACE", type="boolean", default=False, category=FEATURES),
    "mace.min_annotations_per_item": _D(
        "Items with fewer annotators than this are left out of the fit",
        type="integer", default=3, category=FEATURES,
    ),
    "mace.min_items": _D(
        "Refuse to fit until this many eligible items exist",
        type="integer", default=5, category=FEATURES,
    ),
    "mace.trigger_every_n": _D(
        "Refit after this many new annotations", type="integer", default=10,
        category=FEATURES,
    ),
    "mace.num_restarts": _D(
        "EM restarts; the best-scoring run is kept", type="integer", default=10,
        category=FEATURES,
    ),
    "mace.num_iters": _D(
        "EM iterations per restart", type="integer", default=50, category=FEATURES,
    ),
    "rooms": _D(
        "Multiplayer rooms at /rooms: live norming sessions, adjudication "
        "huddles and shadowing over a shared event log",
        type="object", category=FEATURES,
    ),
    "rooms.enabled": _D(
        "Register the /rooms surface", type="boolean", default=False, category=FEATURES,
    ),
    "rooms.who_can_create": _D(
        "Who may open a room: any member, or admin only",
        type="string", default="any", category=FEATURES,
    ),
    "rooms.persist_votes": _D(
        "Write a room's final vote into each member's own annotations",
        type="boolean", default=True, category=FEATURES,
    ),
    "rooms.poll_interval_ms": _D(
        "How often clients poll for room events. Clamped to 500-30000",
        type="integer", default=1500, category=FEATURES,
    ),
    "rooms.max_members": _D(
        "Members allowed in one room. Clamped to 2-100",
        type="integer", default=12, category=FEATURES,
    ),
    "rooms.schema": _D(
        "Scheme members vote on. Defaults to the first radio or likert scheme; "
        "with neither present, rooms disable themselves",
        type="string", category=FEATURES,
    ),
    "pocket": _D(
        "Pocket Mode: the phone-sized annotation surface at /pocket, served as "
        "a PWA with an offline queue",
        type="object", category=FEATURES,
    ),
    "pocket.enabled": _D(
        "Register the /pocket surface", type="boolean", default=False, category=FEATURES,
    ),
    "pocket.batch_size": _D(
        "Items per batch request, which is also the offline queue depth. "
        "Clamped to 1-200",
        type="integer", default=25, category=FEATURES,
    ),
    "pocket.auto_redirect": _D(
        "Send phones and tablets that open /annotate to /pocket, when every "
        "scheme in the task is touch-capable. `?desktop=1` opts back out",
        type="boolean", default=True, category=FEATURES,
    ),
    "truth_serum": _D(
        "Surprisingly-popular scoring. Each annotator also predicts how many "
        "others will pick the same label, and an answer that beats its own "
        "predicted popularity wins over the majority",
        type="object", category=FEATURES,
    ),
    "truth_serum.enabled": _D(
        "Ask the prediction question", type="boolean", default=False, category=FEATURES,
    ),
    "truth_serum.schema": _D(
        "Scheme whose labels get popularity predictions. Defaults to the first "
        "radio scheme; with none, predictions stay inactive",
        type="string", category=FEATURES,
    ),
    "truth_serum.question": _D(
        "Prompt shown above the prediction slider",
        type="string", category=FEATURES,
        example="What percentage of other annotators will choose the same label as you?",
    ),
    "truth_serum.min_annotators": _D(
        "Predictions needed on an item before a surprisingly-popular verdict is "
        "computed. Values below 2 are raised to 2",
        type="integer", default=3, category=FEATURES,
    ),
    "thinkaloud": _D(
        "Think-aloud mode: local speech-to-text over spoken rationales, plus "
        "rule-based detection of spoken label phrases",
        type="object", category=FEATURES,
    ),
    "thinkaloud.enabled": _D(
        "Record and transcribe rationales", type="boolean", default=False,
        category=FEATURES,
    ),
    "thinkaloud.schema": _D(
        "Scheme whose labels may be committed by voice. Defaults to the first "
        "radio scheme",
        type="string", category=FEATURES,
    ),
    "thinkaloud.stt": _D(
        "Speech-to-text backend: faster_whisper (local), mock (tests), or auto",
        type="string", default="auto", category=FEATURES,
    ),
    "thinkaloud.model": _D(
        "Whisper model size for the faster_whisper backend",
        type="string", default="tiny.en", category=FEATURES,
    ),
    "thinkaloud.chunk_seconds": _D(
        "Recorder restart interval. Each chunk is a complete audio file so it "
        "can be decoded on its own. Clamped to 2-30",
        type="integer", default=6, category=FEATURES,
    ),
    "thinkaloud.stems": _D(
        "Override the accepted label-phrase stem patterns",
        type="array", category=FEATURES,
    ),
    "thinkaloud.fillers": _D(
        "Filler lexicon behind the hesitation signal",
        type="array", category=FEATURES, example=["um", "uh", "hmm"],
    ),
    "thinkaloud.require_spoken_label": _D(
        "Nudge on Next when no label was committed by voice",
        type="boolean", default=True, category=FEATURES,
    ),
    "thinkaloud.language": _D(
        "Language hint passed to Whisper", type="string", default="en", category=FEATURES,
    ),
    "keystroke_logging": _D(
        "Content-blind typing dynamics on free-text fields -- when someone "
        "pauses, revises or pastes, never which keys -- and the "
        "composed/transcribed/pasted detection built on them",
        type="object", category=FEATURES, see_also=("annotation_telemetry",),
    ),
    "keystroke_logging.enabled": _D(
        "Record typing dynamics. Off by default: it records how annotators "
        "produce free text, so it is opt-in rather than something a project "
        "acquires by upgrading Potato",
        type="boolean", default=False, category=FEATURES,
    ),
    "keystroke_logging.fidelity": _D(
        "How much is kept: off, summary (per-response statistics only), or "
        "events (raw streams as well)",
        type="string", default="events", category=FEATURES,
    ),
    "keystroke_logging.include_schemas": _D(
        "Schemes to record. Empty means every free-text field",
        type="array", default=[], category=FEATURES,
    ),
    "keystroke_logging.exclude_schemas": _D(
        "Schemes to leave alone", type="array", default=[], category=FEATURES,
    ),
    "keystroke_logging.store_events": _D(
        "Write raw event streams to the typing store. Does nothing at summary "
        "fidelity, which the loader warns about",
        type="boolean", default=True, category=FEATURES,
    ),
    "keystroke_logging.classify_paste_source": _D(
        "Try to tell a paste from outside the page from one that only moved "
        "text within it",
        type="boolean", default=True, category=FEATURES,
    ),
    "keystroke_logging.idle_session_ms": _D(
        "Gap that ends one typing session and starts the next",
        type="integer", default=30000, category=FEATURES,
    ),
    "keystroke_logging.flush_interval_ms": _D(
        "How often the browser posts its buffered events",
        type="integer", default=5000, category=FEATURES,
    ),
    "keystroke_logging.pause_thresholds_ms": _D(
        "Pause buckets the summary counts against. Must be positive integers",
        type="array", default=[500, 1000, 2000, 5000, 10000], category=FEATURES,
    ),
    "keystroke_logging.disclose_to_annotators": _D(
        "Show the recording notice. Turning it off collects typing dynamics "
        "silently, which your consent documents and ethics approval have to cover",
        type="boolean", default=True, category=FEATURES,
    ),
    "keystroke_logging.disclosure_text": _D(
        "Replace the default notice. Must be non-empty; omit it to keep the default",
        type="string", category=FEATURES,
    ),
    "keystroke_logging.detection": _D(
        "Rule-based flags: `enabled`, `calibrate`, `on_external_insert` "
        "(allow, warn, block or flag) and `thresholds`. Thresholds are scored "
        "server-side and withheld from the browser, which would otherwise tell "
        "an annotator exactly how slowly to paste to stay under the flag",
        type="object", category=FEATURES,
    ),
    "annotation_telemetry": _D(
        "The drawing-process analogue of keystroke_logging: content-blind "
        "telemetry on geometry schemas -- when someone draws, zooms, revises "
        "and accepts AI suggestions, never what or where -- and the "
        "rubber-stamping screening built on it",
        type="object", category=FEATURES, see_also=("keystroke_logging",),
    ),
    "annotation_telemetry.enabled": _D(
        "Record drawing dynamics", type="boolean", default=False, category=FEATURES,
    ),
    "annotation_telemetry.fidelity": _D(
        "How much is kept: off, summary (per-annotation statistics only), or "
        "events (raw streams as well)",
        type="string", default="events", category=FEATURES,
    ),
    "annotation_telemetry.include_schemas": _D(
        "Schemes to record. Empty means every geometry schema",
        type="array", default=[], category=FEATURES,
    ),
    "annotation_telemetry.exclude_schemas": _D(
        "Schemes to leave alone", type="array", default=[], category=FEATURES,
    ),
    "annotation_telemetry.store_events": _D(
        "Write raw event streams. Does nothing at summary fidelity",
        type="boolean", default=True, category=FEATURES,
    ),
    "annotation_telemetry.idle_ms": _D(
        "Gap above which the annotator is charged to idle rather than active "
        "time. Two minutes rather than something tighter, because studying a "
        "hard image is real work that produces no events at all",
        type="integer", default=120000, category=FEATURES,
    ),
    "annotation_telemetry.flush_interval_ms": _D(
        "How often the browser posts its buffered events",
        type="integer", default=10000, category=FEATURES,
    ),
    "annotation_telemetry.disclose_to_annotators": _D(
        "Show the recording notice", type="boolean", default=True, category=FEATURES,
    ),
    "annotation_telemetry.disclosure_text": _D(
        "Replace the default notice", type="string", category=FEATURES,
    ),
    "annotation_telemetry.detection": _D(
        "Rubber-stamping detection: `enabled`, `calibrate` and `thresholds`",
        type="object", category=FEATURES,
    ),
    "annotator_dashboard": _D(
        "Read-only progress page at /progress. Shows project totals and the "
        "requesting annotator's own stats, never another annotator's identity. "
        "A bare `true` is accepted as shorthand for `{enabled: true}`",
        type="boolean|object", default=False, category=FEATURES,
    ),
    "annotator_dashboard.enabled": _D(
        "Serve /progress", type="boolean", default=False, category=FEATURES,
    ),
    "annotator_dashboard.show_project_progress": _D(
        "Show project-wide totals", type="boolean", default=True, category=FEATURES,
    ),
    "annotator_dashboard.show_personal_progress": _D(
        "Show the requesting annotator's own counts",
        type="boolean", default=True, category=FEATURES,
    ),
    "annotator_dashboard.show_active_annotators": _D(
        "Show how many annotators are currently active",
        type="boolean", default=False, category=FEATURES,
    ),
    "category_assignment": _D(
        "Route items to annotators by the item's category, optionally gated on "
        "a qualification the annotator earned in training",
        type="object", category=FEATURES,
        see_also=("item_properties.category_key", "assignment_strategy"),
    ),
    "category_assignment.enabled": _D(
        "Turn category routing on. Also gates the qualification scoring that "
        "runs when someone finishes training",
        type="boolean", default=False, category=FEATURES,
    ),
    "category_assignment.category_key": _D(
        "Item field holding the category. Must be a non-empty string",
        type="string", category=FEATURES, example="topic",
    ),
    "category_assignment.qualification": _D(
        "How training performance becomes a per-category qualification: "
        "`source` (training, prestudy or both), `threshold` (0-1, default 0.7) "
        "and `min_questions` (default 1)",
        type="object", category=FEATURES, see_also=("training",),
    ),
    "category_assignment.fallback": _D(
        "What an annotator with no matching qualification is given",
        type="string", default="uncategorized", category=FEATURES,
    ),
    "category_assignment.dynamic": _D(
        "Probabilistic expertise routing, which learns who is good at what from "
        "agreement instead of a fixed qualification. Carries its own `enabled`",
        type="object", category=FEATURES,
    ),
    "diversity_ordering": _D(
        "Embed and cluster the corpus, then serve items round-robin across "
        "clusters so an annotator sees the range of the data early",
        type="object", category=FEATURES, see_also=("assignment_strategy",),
    ),
    "diversity_ordering.enabled": _D(
        "Turn diversity ordering on. assignment_strategy: diversity_clustering "
        "turns it on regardless",
        type="boolean", default=False, category=FEATURES,
    ),
    "diversity_ordering.model_name": _D(
        "Sentence-transformer model used for the embeddings",
        type="string", default="all-MiniLM-L6-v2", category=FEATURES,
    ),
    "diversity_ordering.num_clusters": _D(
        "Clusters to build, when auto_clusters is off",
        type="integer", default=10, category=FEATURES,
    ),
    "diversity_ordering.items_per_cluster": _D(
        "Target items per cluster used to size an automatic k",
        type="integer", default=20, category=FEATURES,
    ),
    "diversity_ordering.auto_clusters": _D(
        "Pick the cluster count from the corpus size instead of num_clusters",
        type="boolean", default=True, category=FEATURES,
    ),
    "diversity_ordering.prefill_count": _D(
        "How many items are ordered ahead of the annotator",
        type="integer", default=100, category=FEATURES,
    ),
    "diversity_ordering.batch_size": _D(
        "Embedding batch size", type="integer", default=32, category=FEATURES,
    ),
    "diversity_ordering.recluster_threshold": _D(
        "Fractional corpus growth that triggers a recluster",
        type="number", default=1.0, category=FEATURES,
    ),
    "diversity_ordering.preserve_visited": _D(
        "Keep an item in its place in the order once it has been seen",
        type="boolean", default=True, category=FEATURES,
    ),
    "diversity_ordering.trigger_ai_prefetch": _D(
        "Warm AI suggestions for the items about to be served",
        type="boolean", default=True, category=FEATURES, see_also=("ai_support",),
    ),
    "diversity_ordering.cache_dir": _D(
        "Where computed embeddings are cached", type="string", category=FEATURES,
    ),
    "embedding_visualization": _D(
        "2D embedding scatter of the corpus on the admin dashboard, coloured by "
        "label",
        type="object", category=FEATURES, see_also=("embeddings",),
    ),
    "embedding_visualization.enabled": _D(
        "Compute and serve the plot", type="boolean", default=False, category=FEATURES,
    ),
    "embedding_visualization.sample_size": _D(
        "Items sampled into the plot", type="integer", category=FEATURES,
    ),
    "embedding_visualization.include_all_annotated": _D(
        "Always include annotated items, on top of the sample",
        type="boolean", category=FEATURES,
    ),
    "embedding_visualization.embedding_model": _D(
        "Text embedding model", type="string", category=FEATURES,
    ),
    "embedding_visualization.image_embedding_model": _D(
        "Image embedding model, for image tasks", type="string", category=FEATURES,
    ),
    "embedding_visualization.umap": _D(
        "UMAP projection parameters", type="object", category=FEATURES,
    ),
    "embedding_visualization.label_source": _D(
        "Which label colours the points: mace or majority",
        type="string", default="mace", category=FEATURES, see_also=("mace",),
    ),
    "embeddings": _D(
        "The project-wide embedder shared by the corpus map, diversity ordering "
        "and duplicate detection. `backend` (auto by default), plus `model`, "
        "`source_field`, `cache_dir`, `media_root`; anything else is passed "
        "through to the backend. A custom backend needs `entrypoint` "
        "('module.path:callable') or `endpoint` (an HTTP URL)",
        type="object", category=FEATURES,
        see_also=("corpus_map", "diversity_ordering"),
    ),
    "bws_config": _D(
        "Best-worst scaling. Builds the tuples annotators compare and scores the "
        "results into a ranking. Its presence is what enables BWS",
        type="object", category=FEATURES, see_also=("ibws_config",),
    ),
    "bws_config.tuple_size": _D(
        "Items shown per comparison", type="integer", category=FEATURES, example=4,
    ),
    "bws_config.num_tuples": _D(
        "Tuples generated in total, or null to derive the count from "
        "min_item_appearances",
        type="any", category=FEATURES, see_also=("bws_config.min_item_appearances",),
    ),
    "bws_config.min_item_appearances": _D(
        "Times each item must appear across the tuples",
        type="integer", category=FEATURES,
    ),
    "bws_config.seed": _D(
        "Seed for tuple generation, so a design can be reproduced",
        type="integer", category=FEATURES, see_also=("random_seed",),
    ),
    "bws_config.scoring": _D(
        "Scoring block; `method` selects the estimator (counting by default)",
        type="object", category=FEATURES,
    ),
    "ibws_config": _D(
        "Iterative best-worst scaling: re-generates tuples each round, "
        "concentrating comparisons where the ranking is still uncertain",
        type="object", category=FEATURES, see_also=("bws_config",),
    ),
    "ibws_config.tuple_size": _D(
        "Items shown per comparison", type="integer", category=FEATURES,
    ),
    "ibws_config.max_rounds": _D(
        "Rounds before the process stops, or null to run until every bucket is "
        "terminal",
        type="any", category=FEATURES,
    ),
    "ibws_config.tuples_per_item_per_round": _D(
        "How often each item is compared in one round",
        type="integer", category=FEATURES,
    ),
    "ibws_config.scoring_method": _D(
        "Estimator used to turn comparisons into scores",
        type="string", category=FEATURES,
    ),
    "ibws_config.seed": _D(
        "Seed for tuple generation", type="integer", category=FEATURES,
    ),
    "boundary_probing": _D(
        "Boundary Lab. After a label is chosen, shows counterfactual edits of "
        "the item and asks whether they flip it -- which maps the decision "
        "boundary and exports as a contrast set",
        type="object", category=FEATURES,
    ),
    "boundary_probing.enabled": _D(
        "Show probes", type="boolean", default=False, category=FEATURES,
    ),
    "boundary_probing.schema": _D(
        "Scheme whose labels are probed. Defaults to the first radio scheme",
        type="string", category=FEATURES,
    ),
    "boundary_probing.probes_per_item": _D(
        "Probes per (instance, label), counting the invariance probe",
        type="integer", default=3, category=FEATURES,
    ),
    "boundary_probing.include_invariance": _D(
        "Include a meaning-preserving paraphrase probe. A paraphrase that flips "
        "the label is the quality-control signal this exists to catch",
        type="boolean", default=True, category=FEATURES,
    ),
    "boundary_probing.sources": _D(
        "Ordered generation tiers -- precomputed, llm, rules. Earlier tiers win "
        "and later ones fill the remaining slots",
        type="array", default=["precomputed", "llm", "rules"], category=FEATURES,
    ),
    "boundary_probing.precomputed_key": _D(
        "Item field holding precomputed counterfactuals, a list of "
        "`{text, kind: flip|invariance}`",
        type="string", default="counterfactuals", category=FEATURES,
    ),
    "boundary_probing.rationale_on_flip": _D(
        "Ask for a short written reason when the annotator says a probe flips "
        "their label",
        type="boolean", default=True, category=FEATURES,
    ),
    "boundary_probing.debounce_ms": _D(
        "Delay between choosing a label and fetching probes",
        type="integer", default=900, category=FEATURES,
    ),
    "boundary_probing.ai_support": _D(
        "Endpoint override for the llm tier; falls back to the global ai_support "
        "block",
        type="object", category=FEATURES, see_also=("ai_support",),
    ),
    "corpus_map": _D(
        "Multi-document corpus map: embed, cluster, project with UMAP and build "
        "a KNN graph, then give annotators a 2D navigation surface at /corpus. "
        "The heavy compute is lazy and never runs at boot",
        type="object", category=FEATURES, see_also=("embeddings",),
    ),
    "corpus_map.enabled": _D(
        "Register the corpus map", type="boolean", default=False, category=FEATURES,
    ),
    "corpus_map.build_on_start": _D(
        "Build the map as soon as items load, rather than on first request",
        type="boolean", default=True, category=FEATURES,
    ),
    "corpus_map.embedding_model": _D(
        "Model used to embed documents",
        type="string", default="all-MiniLM-L6-v2", category=FEATURES,
    ),
    "corpus_map.clustering": _D(
        "Clustering parameters", type="object", category=FEATURES,
    ),
    "corpus_map.umap": _D("UMAP projection parameters", type="object", category=FEATURES),
    "corpus_map.knn": _D(
        "Neighbour-graph parameters; `k` defaults to 10",
        type="object", category=FEATURES,
    ),
    "corpus_map.cluster_labeling": _D(
        "How clusters get their human-readable names",
        type="object", category=FEATURES,
    ),
    "corpus_map.sample_size": _D(
        "Documents sampled into the map", type="integer", category=FEATURES,
    ),
    "event_template": _D(
        "Cross-document event registry: admin-defined slots that annotators "
        "fill with evidence drawn from many documents",
        type="object", category=FEATURES, see_also=("corpus_map",),
    ),
    "event_template.enabled": _D(
        "Register the event surface", type="boolean", default=False, category=FEATURES,
    ),
    "event_template.name": _D(
        "Name of the template, shown in the UI",
        type="string", default="event_template", category=FEATURES,
    ),
    "event_template.allow_annotator_create": _D(
        "Let annotators create new events, not only fill existing ones",
        type="boolean", default=True, category=FEATURES,
    ),
    "event_template.seed_events": _D(
        "Events to pre-create when the registry is first written. Either the "
        "events themselves or a path to a JSON file of them. Seeding is "
        "id-idempotent, so an existing event is never clobbered",
        type="array|string", category=FEATURES,
    ),
    "event_template.slots": _D(
        "The slots each event carries", type="array", category=FEATURES,
    ),
    "analytics": _D(
        "Cost and latency analytics over ingested traces: optional per-model "
        "pricing, and the thresholds that raise a regression alert",
        type="object", category=FEATURES, see_also=("trace_ingestion",),
    ),
    "analytics.pricing": _D(
        "Per-model token pricing used to turn token counts into money",
        type="object", category=FEATURES,
    ),
    "analytics.thresholds": _D(
        "Fractional increases that trip an alert: cost_per_trace (0.5), "
        "avg_latency_ms (0.3), and error_rate as absolute percentage points (0.05)",
        type="object", category=FEATURES,
    ),

    # ------------------------------------------------- workflow and phases --
    "triage": _D(
        "Rank items by a priority signal so failures, thumbs-down feedback and "
        "low scores get annotated first. Scoring runs as items are added, so it "
        "covers traces ingested at runtime as well as loaded files",
        type="object", category=WORKFLOW, see_also=("assignment_strategy",),
    ),
    "triage.enabled": _D(
        "Score items into a priority", type="boolean", default=False, category=WORKFLOW,
    ),
    "triage.order": _D(
        "Queue direction: desc serves the highest priority first",
        type="string", default="desc", category=WORKFLOW,
    ),
    "triage.default_priority": _D(
        "Priority given to items no rule matched",
        type="number", default=0, category=WORKFLOW,
    ),
    "triage.show_badge": _D(
        "Show the matching rule's badge on the item",
        type="boolean", default=True, category=WORKFLOW,
    ),
    "triage.signal_field": _D(
        "Item field read as a numeric priority when no rule matches",
        type="string", category=WORKFLOW, example="score",
    ),
    "triage.invert_signal": _D(
        "Negate signal_field, for scores where lower is worse",
        type="boolean", default=False, category=WORKFLOW,
    ),
    "triage.rules": _D(
        "Rules of `when` (the shared condition grammar) plus priority and an "
        "optional badge; the highest-priority match wins. Leaving both this and "
        "signal_field unset installs built-in rules for errored agents, "
        "thumbs-down feedback and scores below 0.5",
        type="array", category=WORKFLOW,
    ),
    "review_mode": _D(
        "Hotkey review queue. Once the current item is complete the page moves "
        "on by itself, which turns keyboard-labelled schemes into press-key-"
        "and-advance",
        type="object", category=WORKFLOW,
    ),
    "review_mode.enabled": _D(
        "Turn review mode on", type="boolean", default=False, category=WORKFLOW,
    ),
    "review_mode.auto_advance": _D(
        "Advance without being asked. Set false to keep review mode on but "
        "navigate by hand",
        type="boolean", default=True, category=WORKFLOW,
    ),
    "review_mode.advance_on": _D(
        "What counts as complete: `complete` (every scheme on the page has a "
        "value) or `required` (the required-validated ones do)",
        type="string", default="complete", category=WORKFLOW,
        see_also=("require_fully_annotated",),
    ),
    "review_mode.delay_ms": _D(
        "Pause between completion and advancing",
        type="integer", default=350, category=WORKFLOW,
    ),
    "review_workflow": _D(
        "Reviewer routing and the kanban board at /admin/review. Keeps its own "
        "state per instance (pending, in_review, needs_second, adjudication, "
        "done) alongside the annotations",
        type="object", category=WORKFLOW, see_also=("adjudication",),
    ),
    "review_workflow.enabled": _D(
        "Register the review board", type="boolean", default=False, category=WORKFLOW,
    ),
    "review_workflow.reviewers": _D(
        "Reviewer pool that round-robin rules draw from",
        type="array", category=WORKFLOW,
    ),
    "review_workflow.auto_enroll": _D(
        "Enroll every loaded instance at startup. Set false to enroll by hand",
        type="boolean", default=True, category=WORKFLOW,
    ),
    "review_workflow.routing": _D(
        "First-match rules of `when` (the shared condition grammar) plus "
        "`state`, `priority`, and either `assign_to` or `round_robin`",
        type="array", category=WORKFLOW,
    ),
    "prestudy": _D(
        "Legacy pre-study screening block. The only code that reads it is an "
        "unreferenced method, so it has no effect -- configure the screening "
        "phase through `phases` or `surveyflow` with `type: prestudy`",
        type="object", category=WORKFLOW, see_also=("phases", "surveyflow"),
    ),

    # ---------------------------------------------- assignment and sessions --
    "per_annotator_quota": _D(
        "Per-annotator workload caps: `default`, plus `by_user` and "
        "`by_user_role` overrides. Any other sub-key is rejected at load rather "
        "than ignored",
        type="object", category=ASSIGN,
        see_also=("max_annotations_per_user", "user_roles"),
    ),
    "scheme_sets": _D(
        "Named, reusable lists of annotation schemes. A batch_assignment group "
        "names one in its `schemes` key to give that cohort its own questions",
        type="object", category=ASSIGN,
        see_also=("batch_assignment", "annotation_schemes"),
    ),
    "sessions": _D(
        "Group items into sessions by session_id or thread_id and score the "
        "whole session at /sessions. Schemes opt in with `session_level: true`",
        type="object", category=ASSIGN, see_also=("cases",),
    ),
    "sessions.enabled": _D(
        "Build sessions at startup", type="boolean", default=False, category=ASSIGN,
    ),
    "sessions.key": _D(
        "Item field holding the session id. Unset, detection tries session_id "
        "then thread_id, looking inside `metadata` as well as at the top level",
        type="string", category=ASSIGN, example="thread_id",
    ),
    "sessions.attributes": _D(
        "Item fields lifted onto the session", type="array", category=ASSIGN,
    ),
    "instance_reclaim": _D(
        "Take assignments back from annotators who abandoned them so the items "
        "can go out again. `enabled` (false) and `timeout_hours` (24), plus "
        "optional `stale`, `manual`, `quality_control` and `prolific` sections "
        "each carrying `preserve_completed_annotations`",
        type="object", category=ASSIGN, see_also=("max_session_seconds",),
    ),
    "solo_mode": _D(
        "Single-coder loop. An LLM labels the corpus, you review where it is "
        "least sure, and the prompt is refined from your corrections",
        type="object", category=ASSIGN, see_also=("active_learning", "codebook"),
    ),
    "solo_mode.enabled": _D(
        "Turn solo mode on", type="boolean", default=False, category=ASSIGN,
    ),
    "solo_mode.labeling_models": _D(
        "Endpoints that label the corpus. Each is endpoint_type plus model, and "
        "optionally api_key, base_url, max_tokens, temperature, think, timeout",
        type="array", category=ASSIGN,
    ),
    "solo_mode.revision_models": _D(
        "Endpoints used to revise the prompt. Defaults to labeling_models",
        type="array", category=ASSIGN,
    ),
    "solo_mode.embedding": _D(
        "Embedder for diversity and textbox similarity; `model_name` defaults "
        "to all-MiniLM-L6-v2",
        type="object", category=ASSIGN,
    ),
    "solo_mode.uncertainty": _D(
        "How model uncertainty is estimated: `strategy` "
        "(direct_confidence, direct_uncertainty, token_entropy, "
        "sampling_diversity) and a `sampling_diversity` block",
        type="object", category=ASSIGN,
    ),
    "solo_mode.thresholds": _D(
        "The stopping and agreement thresholds -- including "
        "end_human_annotation_agreement (0.90) and minimum_validation_sample "
        "(50) -- plus the per-scheme-type match tolerances",
        type="object", category=ASSIGN,
    ),
    "solo_mode.instance_selection": _D(
        "Weights that decide what you are shown next: low_confidence_weight "
        "(0.4), diversity_weight (0.3), random_weight (0.2), "
        "disagreement_weight (0.1), and the opt-in edge_case_rule, cartography "
        "and llm_predicted weights",
        type="object", category=ASSIGN,
    ),
    "solo_mode.batches": _D(
        "Batch sizes for LLM labeling: llm_labeling_batch (50) and "
        "max_parallel_labels (200)",
        type="object", category=ASSIGN,
    ),
    "solo_mode.prompt_optimization": _D(
        "Automatic prompt search: enabled (true), find_smallest_model, "
        "target_accuracy (0.85), optimization_interval_seconds, and the "
        "accuracy/length/consistency weights",
        type="object", category=ASSIGN,
    ),
    "solo_mode.edge_case_rules": _D(
        "Rules distilled from your corrections and applied before the model",
        type="object", category=ASSIGN,
    ),
    "solo_mode.labeling_functions": _D(
        "Programmatic labeling functions run alongside the model",
        type="object", category=ASSIGN,
    ),
    "solo_mode.confidence_routing": _D(
        "Where an item goes by confidence band: auto-accept, review, or human",
        type="object", category=ASSIGN,
    ),
    "solo_mode.confusion_analysis": _D(
        "Confusion-pair analysis over model-versus-human disagreements",
        type="object", category=ASSIGN,
    ),
    "solo_mode.state_dir": _D(
        "Where solo-mode state is persisted", type="string", category=ASSIGN,
    ),
    "solo_mode.refinement_loop": _D(
        "The automatic refine-evaluate-keep cycle over the labeling prompt",
        type="object", category=ASSIGN,
    ),
    "solo_mode.refinement_loop.enabled": _D(
        "Run the refinement cycle", type="boolean", category=ASSIGN,
    ),
    "solo_mode.refinement_loop.trigger_interval": _D(
        "New human labels between cycles", type="integer", category=ASSIGN,
    ),
    "solo_mode.refinement_loop.max_cycles": _D(
        "Cycles before the loop stops", type="integer", category=ASSIGN,
    ),
    "solo_mode.refinement_loop.require_approval": _D(
        "Hold a candidate prompt until it is approved, rather than adopting it",
        type="boolean", category=ASSIGN,
        see_also=("solo_mode.refinement_loop.auto_apply_suggestions",),
    ),
    "solo_mode.refinement_loop.auto_apply_suggestions": _D(
        "Adopt a winning candidate prompt without asking",
        type="boolean", category=ASSIGN,
    ),
    "solo_mode.refinement_loop.dry_run": _D(
        "Score candidates but never adopt one", type="boolean", category=ASSIGN,
    ),
    "item_store": _D(
        "Where item payloads live. `backend` is memory (the default) or paged; "
        "paged writes to `path` -- .item_cache.sqlite under the output "
        "directory when unset -- and keeps `cache_size` items resident. An "
        "unknown backend warns and falls back to memory rather than refusing "
        "to start",
        type="object", category=DATA, see_also=("partial_loading",),
    ),
    "item_store.backend": _D(
        "memory or paged", type="string", default="memory", category=DATA,
    ),
    "item_store.path": _D(
        "SQLite file the paged backend uses", type="string", category=DATA,
    ),
    "item_store.cache_size": _D(
        "Items the paged backend keeps in memory", type="integer", category=DATA,
    ),

    # -------------------------------------------------- annotation features --
    "auto_redirect_on_completion": _D(
        "Send annotators to the crowd platform's completion URL when they "
        "finish, instead of leaving them on the done page",
        type="boolean", default=False, category=ANNOT_FEAT,
        see_also=("crowdsourcing", "completion_code"),
    ),
    "auto_redirect_delay": _D(
        "Milliseconds on the completion page before that redirect fires",
        type="integer", default=5000, category=ANNOT_FEAT,
        see_also=("auto_redirect_on_completion",),
    ),
    "allow_phase_back_navigation": _D(
        "Let annotators go back to an earlier workflow phase. Off by default, "
        "so consent and training cannot be revisited and re-answered",
        type="boolean", default=False, category=ANNOT_FEAT,
    ),
    "export_annotation_format": _D(
        "Formats the periodic auto-export writes, as a list (a bare string is "
        "accepted). Empty means no auto-export",
        type="array|string", default=[], category=ANNOT_FEAT,
        see_also=("auto_export_interval", "output_annotation_format"),
    ),
    "auto_export_interval": _D(
        "Seconds between automatic exports",
        type="integer", default=60, category=ANNOT_FEAT,
        see_also=("export_annotation_format",),
    ),
    "export_include_phase_data": _D(
        "Include consent, instruction and survey responses in exports. Off by "
        "default: survey answers are usually where the PII is",
        type="boolean", default=False, category=ANNOT_FEAT,
    ),
    "export_include_annotation_changes": _D(
        "Write annotation_changes.csv, the timestamped record of every answer "
        "revision. Off by default: it is far larger than the annotations and "
        "carries interaction detail not every study wants to distribute",
        type="boolean", default=False, category=ANNOT_FEAT,
    ),

    # --------------------------------------------------------------- media --
    "audio_annotation": _D(
        "Server-side waveform service backing audio_annotation schemes. Only "
        "read when the task actually has one",
        type="object", category=MEDIA,
    ),
    "audio_annotation.waveform_cache_dir": _D(
        "Where precomputed waveforms are cached. Relative paths resolve against "
        "task_dir; unset it is waveform_cache/ there",
        type="string", category=MEDIA,
    ),
    "audio_annotation.waveform_look_ahead": _D(
        "Clips whose waveforms are precomputed ahead of the annotator",
        type="integer", default=5, category=MEDIA,
    ),
    "audio_annotation.waveform_cache_max_size": _D(
        "Waveforms kept in the cache", type="integer", default=100, category=MEDIA,
    ),
    "audio_annotation.client_fallback_max_duration": _D(
        "Seconds of audio the browser may decode itself when the server has no "
        "waveform ready",
        type="integer", default=1800, category=MEDIA,
    ),

    # ---------------------------------------------------------- integration --
    "mturk": _D(
        "Amazon Mechanical Turk. Needs `enabled: true` and `config_file_path` "
        "pointing at the credentials YAML, plus boto3 installed. MTurk closed "
        "to new customers in July 2026 and the loader says so on startup",
        type="object", category=INTEG, see_also=("crowdsourcing", "prolific"),
    ),
    "huggingface_backup": _D(
        "Mirror the annotation directory to a Hugging Face dataset repo on a "
        "schedule. Needs `enabled` and `repo_id`; the token comes from `token` (env "
        "substitution is applied) or HF_TOKEN, and `schedule_minutes` sets the "
        "cadence. A misconfiguration logs an error and lets the server run",
        type="object", category=INTEG, see_also=("output_annotation_dir",),
    ),
    "webhooks": _D(
        "Post task events to external URLs as they happen",
        type="object", category=INTEG,
    ),
    "webhooks.enabled": _D(
        "Dispatch webhooks", type="boolean", default=False, category=INTEG,
    ),
    "webhooks.endpoints": _D(
        "Endpoints to post to, and which events each one wants",
        type="array", category=INTEG,
    ),

    # ------------------------------------------------------------ publishing --
    "publish": _D(
        "Dataset publishing options: `default_target` (archive, huggingface or "
        "zenodo) and an `options` block covering which splits are included, "
        "aggregation, min_annotators, PII scrubbing, media bundling and file "
        "format. Publishing works with none of this set",
        type="object", category=PUBLISHING, see_also=("dataset_metadata",),
    ),
    "dataset_metadata": _D(
        "Descriptive metadata for the generated dataset card and Zenodo "
        "deposit: license, authors, citation, keywords, version, funding, "
        "related_links, tags, task_categories. Title and description fall back "
        "to the task's own name and description",
        type="object", category=PUBLISHING, see_also=("publish",),
    ),

    # ---------------------------------------------------------------- agent --
    "live_agent": _D(
        "Run a live agent inside the annotation page, so annotators judge a "
        "conversation as it happens rather than a recorded trace. Its presence "
        "enables the feature, and an instance_display field of type live_agent "
        "renders it",
        type="object", category=AGENT, see_also=("agent_proxy", "instance_display"),
    ),
    "live_coding_agent": _D(
        "Same idea for a coding agent: runs the agent against a repository and "
        "streams its tool calls into a live_coding_agent display field",
        type="object", category=AGENT, see_also=("live_agent",),
    ),
    "live_coding_agent.backend_type": _D(
        "Which agent backend drives the session: ollama_tool_use, "
        "anthropic_tool_use, openai_tool_use, claude_sdk",
        type="string", default="ollama_tool_use", category=AGENT,
    ),
    "live_coding_agent.ai_config": _D(
        "Model settings passed to the backend (model name, endpoint, API key). "
        "Server-side only: a request cannot override it, because it carries "
        "credentials",
        type="object", category=AGENT,
    ),
    "live_coding_agent.working_dir": _D(
        "Repository the agent works on. Copied per session into a sandbox "
        "workspace rather than used in place, so agent edits never touch it",
        type="string", default=".", category=AGENT,
    ),
    "live_coding_agent.max_turns": _D(
        "Stop the agent loop after this many turns",
        type="integer", default=50, category=AGENT,
    ),
    "live_coding_agent.system_prompt": _D(
        "Extra system prompt prepended to the agent's instructions",
        type="string", default="", category=AGENT,
    ),
    "live_coding_agent.sandbox_mode": _D(
        "Boundary the agent's tool calls run inside: container (Docker or "
        "Podman), bubblewrap (Linux hosts without a container runtime), or "
        "trusted (no isolation, requires "
        "acknowledge_untrusted_code_execution). The former docker, worktree "
        "and direct modes are deprecated aliases; worktree never provided "
        "isolation",
        type="string", default="container", category=AGENT,
        see_also=("live_coding_agent.acknowledge_untrusted_code_execution",),
    ),
    "live_coding_agent.container_cli": _D(
        "Container tool to drive: docker or podman. Rootless Podman needs no "
        "root daemon",
        type="string", default="docker", category=AGENT,
    ),
    "live_coding_agent.container_runtime": _D(
        "Alternative container runtime, passed straight through as --runtime. "
        "Use runsc for gVisor (syscall interception in userspace) or kata for "
        "a hardware VM boundary. Unset uses the daemon default",
        type="string", category=AGENT,
    ),
    "live_coding_agent.sandbox_image": _D(
        "Image the sandbox container runs. Point this at your own image to "
        "give the agent more tooling; pin a digest if you need reproducibility",
        type="string", default="python:3.12-slim", category=AGENT,
    ),
    "live_coding_agent.sandbox_network": _D(
        "Container network mode. Left at none the agent cannot reach the "
        "network, so it cannot exfiltrate what it reads",
        type="string", default="none", category=AGENT,
    ),
    "live_coding_agent.sandbox_user": _D(
        "uid:gid the sandboxed tools run as. Defaults to nobody",
        type="string", default="65534:65534", category=AGENT,
    ),
    "live_coding_agent.sandbox_memory": _D(
        "Memory limit for the sandbox container, in Docker syntax",
        type="string", default="512m", category=AGENT,
    ),
    "live_coding_agent.sandbox_cpus": _D(
        "CPU limit for the sandbox container",
        type="number", default=1, category=AGENT,
    ),
    "live_coding_agent.sandbox_pids_limit": _D(
        "Maximum processes inside the sandbox container, which caps fork bombs",
        type="integer", default=128, category=AGENT,
    ),
    "live_coding_agent.sandbox_root": _D(
        "Directory holding per-session workspace copies. Defaults to a "
        ".potato-sandboxes directory beside working_dir",
        type="string", category=AGENT,
    ),
    "live_coding_agent.acknowledge_untrusted_code_execution": _D(
        "Required alongside sandbox_mode: trusted. Confirms you accept that "
        "annotator-editable tool calls, including arbitrary shell commands, "
        "run directly on this host as the Potato user",
        type="boolean", default=False, category=AGENT,
        see_also=("live_coding_agent.sandbox_mode",),
    ),

    # ----------------------------------------------------- agent evaluation --
    "datasets": _D(
        "Versioned evaluation datasets and experiment runs, served at /datasets",
        type="object", category=AGENT_EVAL,
    ),
    "datasets.enabled": _D(
        "Register the datasets surface", type="boolean", default=False,
        category=AGENT_EVAL,
    ),
    "datasets.storage": _D(
        "Where datasets are stored: file or sqlite. Anything else falls back to file",
        type="string", default="file", category=AGENT_EVAL,
    ),
    "automation": _D(
        "Rules engine over incoming items: filter, sample, then act",
        type="object", category=AGENT_EVAL, see_also=("triage",),
    ),
    "automation.enabled": _D(
        "Run the rules", type="boolean", default=False, category=AGENT_EVAL,
    ),
    "automation.rules": _D(
        "Rules of `when` (the shared condition grammar), an optional sample "
        "rate, and the actions to take on a match",
        type="array", category=AGENT_EVAL,
    ),
    "curation": _D(
        "Semantic curation (the Catalog): an embedding index over items, "
        "similarity search, and saved slices that stay live as data arrives",
        type="object", category=AGENT_EVAL, see_also=("embeddings", "search"),
    ),
    "curation.enabled": _D(
        "Register the catalog", type="boolean", default=False, category=AGENT_EVAL,
    ),
    "curation.model_name": _D(
        "Embedding model", type="string", default="all-MiniLM-L6-v2",
        category=AGENT_EVAL,
    ),
    "curation.embed_on_ingest": _D(
        "Embed each item as it arrives. Off by default because it adds boot "
        "time and memory",
        type="boolean", default=False, category=AGENT_EVAL,
    ),
    "curation.text_key": _D(
        "Item field to embed. Empty means the item's text field",
        type="string", default="", category=AGENT_EVAL,
        see_also=("item_properties.text_key",),
    ),
    "arena": _D(
        "Multi-model arena: send one prompt to several providers and collect "
        "side-by-side preferences",
        type="object", category=AGENT_EVAL,
    ),
    "arena.enabled": _D(
        "Register the arena", type="boolean", default=False, category=AGENT_EVAL,
    ),
    "arena.models": _D(
        "Models to fan out to. Each is endpoint_type plus model, with optional "
        "label, base_url, temperature and ai_config",
        type="array", category=AGENT_EVAL,
    ),
    "ai_budget": _D(
        "Cost estimate and spend cap for AI actions. The complaint about "
        "commercial platforms is not the price but the surprise -- credits "
        "consumed by auto-labelling and discovered at export time",
        type="object", category=AI, see_also=("ai_support",),
    ),
    "ai_budget.cap_usd": _D(
        "Dollar ceiling for this project's AI spend. A run projected to cross "
        "it is refused BEFORE it starts, so it cannot leave a part-labelled "
        "dataset and a bill for it",
        type="number", category=AI, example=25.0,
    ),
    "calibration": _D(
        "Agreement drift tracking and the re-calibration prompt on /admin/iaa. "
        "Agreement is scored per time window so a fall in recent work is "
        "visible, instead of averaging into one whole-project number",
        type="object", category=QC, see_also=("num_annotators_per_item",),
    ),
    "calibration.enabled": _D(
        "Compute the agreement timeline. Costs one extra IAA pass per window, "
        "so it can be turned off on very large projects",
        type="boolean", default=True, category=QC,
    ),
    "calibration.windows": _D(
        "How many time windows the timeline is cut into",
        type="integer", default=6, category=QC,
    ),
    "calibration.window_by": _D(
        "'count' gives every window the same number of items, 'time' the same "
        "duration. Equal-count is the default because a study that ran in "
        "bursts leaves equal-duration windows empty, and an empty window has "
        "no agreement rather than low agreement",
        type="string", default="count", category=QC,
    ),
    "calibration.drop_threshold": _D(
        "Relative fall below the project baseline that raises the "
        "re-calibration prompt, e.g. 0.15 for 15%",
        type="number", default=0.15, category=QC,
    ),
    "judge_alignment": _D(
        "LLM-as-judge alignment: score items with a judge, compare against the "
        "humans, and track the agreement across prompt versions",
        type="object", category=AGENT_EVAL, see_also=("judge_calibration", "ai_support"),
    ),
    "judge_alignment.enabled": _D(
        "Turn the judge on", type="boolean", default=False, category=AGENT_EVAL,
    ),
    "judge_alignment.ai_support": _D(
        "Endpoint the judge uses; falls back to the global ai_support block. "
        "Several evaluators read this same override",
        type="object", category=AGENT_EVAL, see_also=("ai_support",),
    ),
    "judge_alignment.schemas": _D(
        "Per-scheme judge settings, keyed by scheme name. The keys present are "
        "also an allow-list: only radio, select and likert schemes named here "
        "get judged. Omit it to judge every categorical scheme",
        type="object", category=AGENT_EVAL,
    ),
    "judge_alignment.few_shot": _D(
        "Few-shot examples added to the judge prompt",
        type="object", category=AGENT_EVAL,
    ),
    "judge_alignment.inline": _D(
        "Show the judge's prediction beside the item while annotating. "
        "`enabled` turns it on; without `compute_on_demand` it only shows "
        "predictions an admin already ran",
        type="object", category=AGENT_EVAL,
    ),
    "judge_calibration": _D(
        "Judge calibration: auto-label a sample with one or more judges, have "
        "humans re-label the same items blind, and report the agreement and "
        "calibration curve",
        type="object", category=AGENT_EVAL, see_also=("judge_alignment",),
    ),
    "judge_calibration.enabled": _D(
        "Register the calibration surface", type="boolean", default=False,
        category=AGENT_EVAL,
    ),
    "judge_calibration.prompt": _D(
        "Prompt given to the judge", type="string", default="", category=AGENT_EVAL,
    ),
    "judge_calibration.models": _D(
        "Judge models to run and compare", type="array", category=AGENT_EVAL,
    ),
    "judge_calibration.k_samples": _D(
        "Samples per item, used to measure the judge's own consistency",
        type="integer", default=5, category=AGENT_EVAL,
    ),
    "judge_calibration.max_items": _D(
        "Hard cap on items labeled", type="integer", category=AGENT_EVAL,
    ),
    "judge_calibration.fraction": _D(
        "Fraction of the corpus to label, as an alternative to max_items",
        type="number", category=AGENT_EVAL,
    ),
    "judge_calibration.sampling": _D(
        "How the calibration sample is drawn: strategy (random), stratify_by, "
        "sample_size (200), seed (42)",
        type="object", category=AGENT_EVAL,
    ),
    "judge_calibration.human": _D(
        "The human side: num_raters (1) and how gold is formed (`gold`, single "
        "by default)",
        type="object", category=AGENT_EVAL,
    ),
    "judge_calibration.schemas": _D(
        "Schemes to calibrate", type="array", category=AGENT_EVAL,
    ),
    "judge_calibration.calibration": _D(
        "Calibration-curve settings; `n_bins` defaults to 10",
        type="object", category=AGENT_EVAL,
    ),
    "judge_calibration.output": _D(
        "Where the report goes: `dir` (judge_calibration_output) and a `files` "
        "block naming the labels, JSON report and HTML report",
        type="object", category=AGENT_EVAL,
    ),
    "judge_calibration.state_dir": _D(
        "Run state directory. Unset it is .judge_calibration under the output "
        "directory",
        type="string", category=AGENT_EVAL,
    ),
    "cot_segmentation": _D(
        "Split a long chain-of-thought string into labelable steps once, at "
        "load time, so the cot_trace display and the process_reward scheme read "
        "the same cached list",
        type="object", category=AGENT_EVAL,
    ),
    "cot_segmentation.source_key": _D(
        "Item field holding the reasoning string. Required whenever the block "
        "is present",
        type="string", required=False, category=AGENT_EVAL, example="reasoning",
    ),
    "cot_segmentation.target_key": _D(
        "Item field the step list is written to. Point the display's and "
        "scheme's `steps_key` at this",
        type="string", default="cot_steps", category=AGENT_EVAL,
    ),
    "cot_segmentation.strategy": _D(
        "How to split: blank_line, numbered, markers, sentence, llm, or auto. "
        "llm needs an ai_support or judge_alignment endpoint and falls back to "
        "the heuristics if it cannot reach one",
        type="string", default="auto", category=AGENT_EVAL,
        see_also=("ai_support", "judge_alignment"),
    ),
    "cot_segmentation.min_step_chars": _D(
        "Steps shorter than this are merged into the previous one",
        type="integer", category=AGENT_EVAL,
    ),
    "cot_segmentation.max_steps": _D(
        "Hard cap on steps per item, which keeps pathological input from reaching "
        "the UI",
        type="integer", category=AGENT_EVAL,
    ),
    "cot_segmentation.markers": _D(
        "Separator strings for the markers strategy",
        type="array", category=AGENT_EVAL,
    ),
    "cot_segmentation.sentences_per_step": _D(
        "Sentences grouped into one step by the sentence strategy",
        type="integer", category=AGENT_EVAL,
    ),
    "cot_segmentation.llm_max_chars": _D(
        "Characters of reasoning sent to the model under the llm strategy",
        type="integer", category=AGENT_EVAL,
    ),

    # ------------------------------------------------------------- internal --
    "config_file": _D(
        "Path to the config file being run. Written by the loader from the "
        "command line, not something to set yourself; task_dir falls back to "
        "its directory",
        type="string", category=SERVER, see_also=("task_dir",),
    ),
}


def get_key_doc(path: str) -> Optional[ConfigKeyDoc]:
    """Documentation for one dotted config path, or None if undocumented."""
    return CONFIG_KEY_DOCS.get(path)


def iter_key_docs() -> Iterator[Tuple[str, ConfigKeyDoc]]:
    """Every documented path, in sorted order."""
    for path in sorted(CONFIG_KEY_DOCS):
        yield path, CONFIG_KEY_DOCS[path]


def documented_paths() -> set:
    """The set of dotted paths this table covers."""
    return set(CONFIG_KEY_DOCS)


def json_schema_type(doc: ConfigKeyDoc):
    """The `type` value to emit in JSON Schema: a string, a list, or None."""
    if not doc.type or doc.type == "any":
        return None
    parts = [p.strip() for p in doc.type.split("|") if p.strip()]
    if not parts:
        return None
    return parts[0] if len(parts) == 1 else parts


def category_for(path: str, fallback: str = "Other") -> str:
    """Category a key belongs to, for the generated reference."""
    doc = CONFIG_KEY_DOCS.get(path)
    return doc.category if doc else fallback
