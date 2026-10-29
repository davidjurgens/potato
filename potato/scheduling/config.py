"""
The ``schedule:`` and ``notifications:`` blocks: validation and the parsed
form the rest of the package reads.

``parse_schedule_config(config, config_dir)`` returns a :class:`ScheduleSpec`
or None when the config has no ``schedule`` block. Every problem raises
``ConfigValidationError`` naming the key, so a bad value stops the server at
boot (and ``potato validate``) rather than surfacing as a reminder that never
goes out.

Credentials are never read from the YAML. A channel names the environment
variable that holds each one (``password_env: POTATO_SMTP_PASSWORD``); writing
``password:`` (or ``token``, ``auth_token``, ``account_sid``, ``username``,
``api_key``) inline is refused.
"""

from __future__ import annotations

import os
import re
import string
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from potato.scheduling import timeutil
from potato.scheduling.questions import load_questions

SCHEDULE_KEYS = {"timezone", "seed", "poll_seconds", "scheduler", "waves",
                 "experience_sampling", "delphi"}
WAVE_KEYS = {"name", "title", "offset", "at", "window", "questions", "questions_file",
             "reminders", "completion_code", "intro"}
ESM_KEYS = {"days", "start_day", "daily_window", "signal", "interval", "expires_after",
            "title", "intro", "questions", "questions_file", "reminders"}
DELPHI_KEYS = {"title", "intro", "items", "items_file", "scale", "comments", "max_rounds",
               "round_length", "gap", "start", "stop", "min_panel", "reminders"}
NOTIFY_KEYS = {"dry_run", "base_url", "channels", "contact", "templates"}
CONTACT_KEYS = {"consent", "delete_after_study"}

CHANNEL_KEYS = {
    "log": {"type"},
    "smtp": {"type", "host", "port", "security", "username_env", "password_env", "from",
             "timeout"},
    "twilio": {"type", "account_sid_env", "auth_token_env", "from_number",
               "messaging_service_sid_env", "timeout"},
    "prolific": {"type", "token_env", "study_id", "timeout"},
}
#: Env-var keys each channel needs (``messaging_service_sid_env`` replaces
#: ``from_number`` on Twilio and is checked separately).
CHANNEL_ENV_DEFAULTS = {
    "smtp": {},
    "twilio": {"account_sid_env": "TWILIO_ACCOUNT_SID", "auth_token_env": "TWILIO_AUTH_TOKEN"},
    "prolific": {"token_env": "PROLIFIC_API_TOKEN"},
}
_INLINE_SECRET = re.compile(r"(password|passwd|secret|token|auth|api_key|apikey|sid|username|user)$",
                            re.IGNORECASE)
#: What a channel delivers to, so the contact page knows what to ask for.
CHANNEL_ADDRESS = {"log": None, "smtp": "email", "twilio": "phone", "prolific": "prolific"}

TEMPLATE_KINDS = ("before_open", "open", "reminder", "prompt", "delphi_round")
TEMPLATE_FIELDS = {"study", "session", "opens", "closes", "time_left", "link", "stop_link"}
DEFAULT_TEMPLATES = {
    "before_open": {
        "subject": "{study}: {session} opens soon",
        "body": "{session} for {study} opens on {opens} and stays open until {closes}.\n\n"
                "Start here when it opens: {link}\n\n"
                "To stop these messages and delete your contact details: {stop_link}",
    },
    "open": {
        "subject": "{study}: {session} is open",
        "body": "{session} for {study} is open until {closes}.\n\nStart here: {link}\n\n"
                "To stop these messages and delete your contact details: {stop_link}",
    },
    "reminder": {
        "subject": "Reminder: {session} closes {closes}",
        "body": "{session} for {study} closes on {closes} ({time_left} left).\n\n"
                "Start here: {link}\n\n"
                "To stop these messages and delete your contact details: {stop_link}",
    },
    "prompt": {
        "subject": "{study}: a short survey is waiting",
        "body": "A short survey for {study} is open for {time_left}: {link}\n\n"
                "Stop messages: {stop_link}",
    },
    "delphi_round": {
        "subject": "{study}: {session} is open",
        "body": "{session} of {study} is open until {closes}. You will see the panel's "
                "ratings from the last round.\n\nStart here: {link}\n\n"
                "To stop these messages and delete your contact details: {stop_link}",
    },
}

DEFAULT_WAVE_REMINDERS = [{"at": "open"}]
DEFAULT_PROMPT_REMINDERS = [{"at": "open"}]
DEFAULT_DELPHI_REMINDERS = [{"at": "open"}]


def _error(message: str):
    from potato.server_utils.config_module import ConfigValidationError
    return ConfigValidationError(message)


# --------------------------------------------------------------------------
# Parsed form
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class ReminderRule:
    """When a message goes out, relative to a session's window."""
    kind: str            # open | before_open | before_close | after_open
    offset: float = 0.0  # seconds

    @property
    def key(self) -> str:
        return self.kind if self.kind == "open" else f"{self.kind}:{int(self.offset)}"

    @property
    def template(self) -> str:
        return {"open": "open", "before_open": "before_open"}.get(self.kind, "reminder")

    def due(self, opens_at: float, closes_at: float) -> float:
        if self.kind == "open":
            return opens_at
        if self.kind == "before_open":
            return opens_at - self.offset
        if self.kind == "after_open":
            return opens_at + self.offset
        return closes_at - self.offset


@dataclass
class WaveSpec:
    name: str
    title: str
    offset: float
    at: Optional[Tuple[int, int]]
    window: float
    questions: List[dict]
    reminders: List[ReminderRule]
    completion_code: str = ""
    intro: str = ""


@dataclass
class EsmSpec:
    days: int
    start_day: int
    window: Tuple[Tuple[int, int], Tuple[int, int]]
    mode: str                          # signal | interval
    per_day: int = 0
    min_gap: float = 0.0
    every: float = 0.0
    times: List[Tuple[int, int]] = field(default_factory=list)
    expires_after: float = 1800.0
    title: str = "Short survey"
    intro: str = ""
    questions: List[dict] = field(default_factory=list)
    reminders: List[ReminderRule] = field(default_factory=list)


@dataclass
class DelphiSpec:
    title: str
    intro: str
    items: List[Dict[str, str]]
    scale_min: int
    scale_max: int
    min_label: str
    max_label: str
    comments: bool
    max_rounds: int
    round_length: float
    gap: float
    start: Optional[float]
    stop: Dict[str, float]
    min_panel: int
    reminders: List[ReminderRule]


@dataclass
class ChannelSpec:
    type: str
    options: Dict[str, Any]

    @property
    def address(self) -> Optional[str]:
        return CHANNEL_ADDRESS[self.type]


@dataclass
class NotifySpec:
    dry_run: bool
    base_url: str
    channels: List[ChannelSpec]
    consent_question: Optional[str]
    consent_value: Any
    delete_after_study: bool
    templates: Dict[str, Dict[str, str]]

    def wants(self, address: str) -> bool:
        return any(c.address == address for c in self.channels)


@dataclass
class ScheduleSpec:
    timezone: str
    seed: str
    poll_seconds: float
    scheduler: bool
    waves: List[WaveSpec]
    esm: Optional[EsmSpec]
    delphi: Optional[DelphiSpec]
    notify: Optional[NotifySpec]
    study: str

    @property
    def session_kinds(self) -> List[str]:
        kinds = []
        if self.waves:
            kinds.append("wave")
        if self.esm:
            kinds.append("prompt")
        if self.delphi:
            kinds.append("round")
        return kinds


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def _dur(value, where):
    try:
        return timeutil.parse_duration(value, where)
    except ValueError as exc:
        raise _error(str(exc))


def _unknown(block: dict, allowed: set, where: str):
    extra = set(block) - allowed
    if extra:
        raise _error(f"{where} has unknown key(s): {', '.join(sorted(map(str, extra)))}. "
                     f"Known keys: {', '.join(sorted(allowed))}")


def _text(block: dict, key: str, where: str, default: str = "") -> str:
    value = block.get(key, default)
    if not isinstance(value, str):
        raise _error(f"{where}.{key} must be text")
    return value


def _reminders(value, where: str, window: Optional[float], default) -> List[ReminderRule]:
    if value is None:
        value = default
    if not isinstance(value, list):
        raise _error(f"{where} must be a list such as [{{at: open}}, {{before_close: 12h}}]")
    rules = []
    for i, entry in enumerate(value):
        at = f"{where}[{i}]"
        if entry == "open" or entry == {"at": "open"}:
            rules.append(ReminderRule("open"))
            continue
        if not isinstance(entry, dict) or len(entry) != 1:
            raise _error(f"{at} must be one of: {{at: open}}, {{before_open: <duration>}}, "
                         "{after_open: <duration>}, {before_close: <duration>}")
        (kind, raw), = entry.items()
        if kind not in ("before_open", "after_open", "before_close"):
            raise _error(f"{at}: unknown reminder {kind!r}; use at, before_open, after_open "
                         "or before_close")
        offset = _dur(raw, f"{at}.{kind}")
        if kind in ("after_open", "before_close") and window is not None and offset >= window:
            raise _error(f"{at}.{kind} ({raw}) must be shorter than the window it sits in")
        rules.append(ReminderRule(kind, offset))
    keys = [r.key for r in rules]
    if len(set(keys)) != len(keys):
        raise _error(f"{where} lists the same reminder twice")
    return rules


def _parse_waves(raw, config_dir) -> List[WaveSpec]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not raw:
        raise _error("schedule.waves must be a non-empty list")
    waves, names = [], set()
    for i, entry in enumerate(raw):
        where = f"schedule.waves[{i}]"
        if not isinstance(entry, dict):
            raise _error(f"{where} must be a mapping")
        _unknown(entry, WAVE_KEYS, where)
        name = entry.get("name")
        if not isinstance(name, str) or not re.match(r"^[A-Za-z0-9_\-]{1,40}$", name):
            raise _error(f"{where}.name must be a short id (letters, digits, _ or -)")
        if name in names:
            raise _error(f"{where}.name {name!r} is used twice")
        names.add(name)
        offset = _dur(entry.get("offset", 0), f"{where}.offset")
        at = None
        if "at" in entry:
            try:
                at = timeutil.parse_clock(entry["at"], f"{where}.at")
            except ValueError as exc:
                raise _error(str(exc))
            if offset % 86400:
                raise _error(f"{where}.at places the wave at a clock time, so {where}.offset "
                             "must be a whole number of days (for example 7d)")
        if "window" not in entry:
            raise _error(f"{where}.window is required: how long the wave stays open (e.g. 48h)")
        window = _dur(entry["window"], f"{where}.window")
        if window < 60:
            raise _error(f"{where}.window must be at least one minute")
        try:
            questions = load_questions(entry, where, config_dir)
        except ValueError as exc:
            raise _error(str(exc))
        waves.append(WaveSpec(
            name=name, title=_text(entry, "title", where, name), offset=offset, at=at,
            window=window, questions=questions,
            reminders=_reminders(entry.get("reminders"), f"{where}.reminders", window,
                                 DEFAULT_WAVE_REMINDERS),
            completion_code=str(_text(entry, "completion_code", where)),
            intro=_text(entry, "intro", where)))
    return waves


def _parse_esm(raw, config_dir) -> Optional[EsmSpec]:
    if raw is None:
        return None
    where = "schedule.experience_sampling"
    if not isinstance(raw, dict):
        raise _error(f"{where} must be a mapping")
    _unknown(raw, ESM_KEYS, where)
    days = raw.get("days")
    if not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 366:
        raise _error(f"{where}.days must be a whole number of days from 1 to 366")
    start_day = raw.get("start_day", 1)
    if not isinstance(start_day, int) or isinstance(start_day, bool) or not 0 <= start_day <= 366:
        raise _error(f"{where}.start_day must be 0 (the enrolment day) or later")
    try:
        window = timeutil.parse_window(raw.get("daily_window", "09:00-21:00"),
                                       f"{where}.daily_window")
    except ValueError as exc:
        raise _error(str(exc))
    win_len = ((window[1][0] * 60 + window[1][1]) - (window[0][0] * 60 + window[0][1])) * 60
    expires = _dur(raw.get("expires_after", "30m"), f"{where}.expires_after")
    if expires < 60:
        raise _error(f"{where}.expires_after must be at least one minute")
    has_signal, has_interval = "signal" in raw, "interval" in raw
    if has_signal == has_interval:
        raise _error(f"{where} needs exactly one of signal (random times) or interval "
                     "(fixed times)")
    spec = EsmSpec(days=days, start_day=start_day, window=window,
                   mode="signal" if has_signal else "interval", expires_after=expires,
                   title=_text(raw, "title", where, "Short survey"),
                   intro=_text(raw, "intro", where))
    if has_signal:
        sig = raw["signal"]
        if not isinstance(sig, dict):
            raise _error(f"{where}.signal must be a mapping with per_day and min_gap")
        _unknown(sig, {"per_day", "min_gap"}, f"{where}.signal")
        per_day = sig.get("per_day")
        if not isinstance(per_day, int) or isinstance(per_day, bool) or not 1 <= per_day <= 48:
            raise _error(f"{where}.signal.per_day must be a whole number from 1 to 48")
        min_gap = _dur(sig.get("min_gap", "60m"), f"{where}.signal.min_gap")
        if min_gap < expires:
            raise _error(f"{where}.signal.min_gap must be at least expires_after, or one "
                         "prompt would still be open when the next arrives")
        # The last prompt still needs its expiry inside the window.
        if (per_day - 1) * min_gap + expires > win_len:
            raise _error(f"{where}: {per_day} prompts {sig.get('min_gap', '60m')} apart do "
                         f"not fit in the daily window {raw.get('daily_window', '09:00-21:00')}")
        spec.per_day, spec.min_gap = per_day, min_gap
    else:
        iv = raw["interval"]
        if not isinstance(iv, dict) or len(iv) != 1 or not ({"every", "times"} & set(iv)):
            raise _error(f"{where}.interval must be {{every: 3h}} or {{times: ['10:00', "
                         "'14:00']}}")
        if "every" in iv:
            every = _dur(iv["every"], f"{where}.interval.every")
            if every < expires:
                raise _error(f"{where}.interval.every must be at least expires_after")
            if every > win_len:
                raise _error(f"{where}.interval.every is longer than the daily window")
            spec.every = every
        else:
            times = iv["times"]
            if not isinstance(times, list) or not times:
                raise _error(f"{where}.interval.times must be a list of clock times")
            try:
                parsed = sorted(timeutil.parse_clock(t, f"{where}.interval.times") for t in times)
            except ValueError as exc:
                raise _error(str(exc))
            mins = [h * 60 + m for h, m in parsed]
            if len(set(mins)) != len(mins):
                raise _error(f"{where}.interval.times repeats a time")
            if any(b - a < expires / 60 for a, b in zip(mins, mins[1:])):
                raise _error(f"{where}.interval.times are closer together than expires_after")
            spec.times = parsed
    try:
        spec.questions = load_questions(raw, where, config_dir)
    except ValueError as exc:
        raise _error(str(exc))
    spec.reminders = _reminders(raw.get("reminders"), f"{where}.reminders", expires,
                                DEFAULT_PROMPT_REMINDERS)
    if any(r.kind == "before_open" for r in spec.reminders):
        raise _error(f"{where}.reminders: before_open would announce a random prompt in "
                     "advance; use at: open and after_open or before_close")
    return spec


def _parse_delphi(raw, config_dir) -> Optional[DelphiSpec]:
    if raw is None:
        return None
    where = "schedule.delphi"
    if not isinstance(raw, dict):
        raise _error(f"{where} must be a mapping")
    _unknown(raw, DELPHI_KEYS, where)
    if ("items" in raw) == ("items_file" in raw):
        raise _error(f"{where} needs exactly one of items or items_file")
    items = raw.get("items")
    if "items_file" in raw:
        from potato.scheduling.questions import resolve_file
        try:
            path = resolve_file(str(raw["items_file"]), config_dir, f"{where}.items_file")
        except ValueError as exc:
            raise _error(str(exc))
        import json
        with open(path, "r", encoding="utf-8") as fh:
            if path.endswith(".jsonl"):
                items = [json.loads(line) for line in fh if line.strip()]
            elif path.endswith((".yaml", ".yml")):
                import yaml
                items = yaml.safe_load(fh)
            else:
                items = json.load(fh)
    if not isinstance(items, list) or not items:
        raise _error(f"{where}.items must be a non-empty list of {{id, text}}")
    parsed, ids = [], set()
    for i, it in enumerate(items):
        if not isinstance(it, dict) or not isinstance(it.get("id"), (str, int)) \
                or not isinstance(it.get("text"), str) or not it["text"].strip():
            raise _error(f"{where}.items[{i}] must have an id and a text")
        iid = str(it["id"])
        if iid in ids:
            raise _error(f"{where}.items[{i}].id {iid!r} is used twice")
        ids.add(iid)
        parsed.append({"id": iid, "text": it["text"]})
    scale = raw.get("scale", {}) or {}
    if not isinstance(scale, dict):
        raise _error(f"{where}.scale must be a mapping with min and max")
    _unknown(scale, {"min", "max", "min_label", "max_label"}, f"{where}.scale")
    lo, hi = scale.get("min", 1), scale.get("max", 9)
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in (lo, hi)) \
            or hi <= lo or hi - lo > 20:
        raise _error(f"{where}.scale needs whole numbers min < max (at most 21 points)")
    max_rounds = raw.get("max_rounds", 3)
    if not isinstance(max_rounds, int) or isinstance(max_rounds, bool) or not 1 <= max_rounds <= 10:
        raise _error(f"{where}.max_rounds must be a whole number from 1 to 10")
    if "round_length" not in raw:
        raise _error(f"{where}.round_length is required: how long each round stays open")
    round_length = _dur(raw["round_length"], f"{where}.round_length")
    if round_length < 60:
        raise _error(f"{where}.round_length must be at least one minute")
    gap = _dur(raw.get("gap", 0), f"{where}.gap")
    start = None
    if raw.get("start") is not None:
        try:
            start = timeutil.parse_instant(raw["start"], f"{where}.start")
        except ValueError as exc:
            raise _error(str(exc))
    stop_raw = raw.get("stop", {}) or {}
    if not isinstance(stop_raw, dict):
        raise _error(f"{where}.stop must be a mapping")
    _unknown(stop_raw, {"iqr_at_most", "median_change_at_most", "changed_share_below"},
             f"{where}.stop")
    stop = {}
    for key, value in stop_raw.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
            raise _error(f"{where}.stop.{key} must be a number of at least 0")
        if key == "changed_share_below" and value > 1:
            raise _error(f"{where}.stop.changed_share_below is a share from 0 to 1")
        stop[key] = float(value)
    min_panel = raw.get("min_panel", 3)
    if not isinstance(min_panel, int) or isinstance(min_panel, bool) or min_panel < 1:
        raise _error(f"{where}.min_panel must be a whole number of at least 1")
    comments = raw.get("comments", True)
    if not isinstance(comments, bool):
        raise _error(f"{where}.comments must be true or false")
    return DelphiSpec(
        title=_text(raw, "title", where, "Delphi round"), intro=_text(raw, "intro", where),
        items=parsed, scale_min=lo, scale_max=hi,
        min_label=str(scale.get("min_label", "")), max_label=str(scale.get("max_label", "")),
        comments=comments, max_rounds=max_rounds, round_length=round_length, gap=gap,
        start=start, stop=stop, min_panel=min_panel,
        reminders=_reminders(raw.get("reminders"), f"{where}.reminders", round_length,
                             DEFAULT_DELPHI_REMINDERS))


def _parse_channel(entry, i) -> ChannelSpec:
    where = f"notifications.channels[{i}]"
    if not isinstance(entry, dict):
        raise _error(f"{where} must be a mapping with a type")
    ctype = entry.get("type")
    if ctype not in CHANNEL_KEYS:
        raise _error(f"{where}.type must be one of {', '.join(CHANNEL_KEYS)} (got {ctype!r})")
    for key in entry:
        if key != "type" and not str(key).endswith("_env") and _INLINE_SECRET.search(str(key)):
            raise _error(
                f"{where}.{key}: credentials are read from environment variables only, never "
                f"from the config file. Use {key}_env: <VARIABLE_NAME> and set that variable "
                "on the server")
    _unknown(entry, CHANNEL_KEYS[ctype], where)
    opts = dict(entry)
    for key, value in entry.items():
        if str(key).endswith("_env") and not (isinstance(value, str) and
                                              re.match(r"^[A-Z_][A-Z0-9_]*$", value)):
            raise _error(f"{where}.{key} must be the NAME of an environment variable "
                         "(capital letters, digits and _), not its value")
    for key, default in CHANNEL_ENV_DEFAULTS.get(ctype, {}).items():
        opts.setdefault(key, default)
    if ctype == "smtp":
        if not isinstance(entry.get("host"), str) or not entry["host"]:
            raise _error(f"{where}.host is required (the SMTP server's name)")
        if not isinstance(entry.get("from"), str) or "@" not in entry["from"]:
            raise _error(f"{where}.from is required: the sender address, e.g. "
                         "\"Study team <study@example.org>\"")
        sec = entry.get("security", "starttls")
        if sec not in ("starttls", "ssl", "none"):
            raise _error(f"{where}.security must be starttls, ssl or none")
        opts["security"] = sec
        port = entry.get("port", 465 if sec == "ssl" else 587)
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise _error(f"{where}.port must be a port number")
        opts["port"] = port
        if ("username_env" in entry) != ("password_env" in entry):
            raise _error(f"{where}: give both username_env and password_env, or neither")
    elif ctype == "twilio":
        has_from = "from_number" in entry
        has_service = "messaging_service_sid_env" in entry
        if has_from == has_service:
            raise _error(f"{where} needs exactly one of from_number or "
                         "messaging_service_sid_env")
        if has_from and not (isinstance(entry["from_number"], str)
                             and PHONE_RE.match(entry["from_number"])):
            raise _error(f"{where}.from_number must be an E.164 number such as +15550100")
    elif ctype == "prolific":
        if "study_id" in entry and not isinstance(entry["study_id"], str):
            raise _error(f"{where}.study_id must be text")
    if "timeout" in entry and (not isinstance(entry["timeout"], (int, float))
                               or isinstance(entry["timeout"], bool) or entry["timeout"] <= 0):
        raise _error(f"{where}.timeout must be a positive number of seconds")
    return ChannelSpec(ctype, opts)


PHONE_RE = re.compile(r"^\+[1-9]\d{6,14}$")
EMAIL_RE = re.compile(r"^[^@\s<>\"',;]{1,64}@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$")


def missing_env(channel: ChannelSpec) -> List[str]:
    """Environment variables this channel needs that are not set."""
    names = [v for k, v in channel.options.items() if k.endswith("_env")]
    return [n for n in names if not os.environ.get(n)]


def _parse_notify(raw, config, config_dir) -> Optional[NotifySpec]:
    if raw is None:
        return None
    where = "notifications"
    if not isinstance(raw, dict):
        raise _error(f"{where} must be a mapping")
    _unknown(raw, NOTIFY_KEYS, where)
    dry_run = raw.get("dry_run", False)
    if not isinstance(dry_run, bool):
        raise _error(f"{where}.dry_run must be true or false")
    channels_raw = raw.get("channels") or []
    if not isinstance(channels_raw, list):
        raise _error(f"{where}.channels must be a list")
    channels = [_parse_channel(c, i) for i, c in enumerate(channels_raw)]
    types = [c.type for c in channels]
    if len(set(types)) != len(types):
        raise _error(f"{where}.channels lists the same channel type twice")
    base_url = raw.get("base_url")
    real = any(c.type != "log" for c in channels) and not dry_run
    if base_url is None:
        if real:
            raise _error(f"{where}.base_url is required: the public address participants "
                         "open links on, e.g. https://study.example.org")
        base_url = f"http://localhost:{config.get('port', 8000)}"
    if not isinstance(base_url, str) or not re.match(r"^https?://[^\s/]+", base_url):
        raise _error(f"{where}.base_url must be an http(s) address")
    contact = raw.get("contact") or {}
    if not isinstance(contact, dict):
        raise _error(f"{where}.contact must be a mapping")
    _unknown(contact, CONTACT_KEYS, f"{where}.contact")
    consent = contact.get("consent")
    question = value = None
    if channels:
        if not isinstance(consent, dict) or not isinstance(consent.get("question"), str) \
                or "value" not in consent:
            raise _error(
                f"{where}.contact.consent is required when channels are configured: name the "
                "consent question that allows contact and the answer that means yes, e.g. "
                "{question: contact_consent, value: \"Yes\"}. Nobody is messaged without it")
        _unknown(consent, {"question", "value"}, f"{where}.contact.consent")
        question, value = consent["question"], consent["value"]
        if isinstance(value, bool):
            raise _error(f"{where}.contact.consent.value is true/false: YAML reads a bare "
                         "Yes/No as a boolean, so quote it (\"Yes\")")
        _check_consent_question(config, config_dir, question, value)
    delete_after = contact.get("delete_after_study", True)
    if not isinstance(delete_after, bool):
        raise _error(f"{where}.contact.delete_after_study must be true or false")
    templates = {k: dict(v) for k, v in DEFAULT_TEMPLATES.items()}
    tpl_raw = raw.get("templates") or {}
    if not isinstance(tpl_raw, dict):
        raise _error(f"{where}.templates must be a mapping")
    for kind, tpl in tpl_raw.items():
        if kind not in TEMPLATE_KINDS:
            raise _error(f"{where}.templates.{kind}: unknown message kind; use "
                         f"{', '.join(TEMPLATE_KINDS)}")
        if not isinstance(tpl, dict) or set(tpl) - {"subject", "body"}:
            raise _error(f"{where}.templates.{kind} must have subject and/or body")
        for part, text in tpl.items():
            if not isinstance(text, str):
                raise _error(f"{where}.templates.{kind}.{part} must be text")
            try:
                fields = {f for _l, f, _s, _c in string.Formatter().parse(text) if f is not None}
            except ValueError as exc:
                raise _error(f"{where}.templates.{kind}.{part}: {exc}")
            bad = fields - TEMPLATE_FIELDS
            if bad:
                raise _error(f"{where}.templates.{kind}.{part} uses unknown placeholder(s) "
                             f"{', '.join('{' + b + '}' for b in sorted(bad))}; known: "
                             f"{', '.join('{' + f + '}' for f in sorted(TEMPLATE_FIELDS))}")
            templates[kind][part] = text
    return NotifySpec(dry_run=dry_run, base_url=base_url.rstrip("/"), channels=channels,
                      consent_question=question, consent_value=value,
                      delete_after_study=delete_after, templates=templates)


def _check_consent_question(config, config_dir, question, value):
    """The consent question must be asked on a phase page, before the end of
    the regular flow, and ``value`` must be one of its options."""
    try:
        from potato.server_utils.config_module import phase_page_schemes
        pages = phase_page_schemes(config, config_dir)
    except Exception:
        pages = None
    if pages is None:
        return  # a file this check cannot see; the server reports it
    for schemes in pages.values():
        for scheme in schemes:
            if isinstance(scheme, dict) and scheme.get("name") == question:
                labels = scheme.get("labels")
                if isinstance(labels, list) and labels:
                    names = [str(l.get("name")) if isinstance(l, dict) else str(l)
                             for l in labels]
                    vals = value if isinstance(value, list) else [value]
                    if any(str(v) not in names for v in vals):
                        raise _error(f"notifications.contact.consent.value {value!r} is not an "
                                     f"option of {question!r} ({', '.join(names)})")
                return
    raise _error(f"notifications.contact.consent.question {question!r} is not asked on any "
                 "phase page. Add it to the consent page (or another page before the end) "
                 "so participants are asked before any contact details are collected")


def parse_schedule_config(config: dict, config_dir: Optional[str] = None) -> Optional[ScheduleSpec]:
    raw = (config or {}).get("schedule")
    notify_raw = (config or {}).get("notifications")
    if raw is None:
        if notify_raw is not None:
            raise _error("notifications: needs a schedule: block; messages are sent for "
                         "scheduled sessions only")
        return None
    if not isinstance(raw, dict):
        raise _error("schedule must be a mapping")
    _unknown(raw, SCHEDULE_KEYS, "schedule")
    if config_dir is None:
        config_dir = (os.path.dirname(os.path.abspath(config["config_file"]))
                      if config.get("config_file") else (config.get("task_dir") or "."))
    tz = raw.get("timezone", "UTC")
    if not timeutil.valid_timezone(tz):
        raise _error(f"schedule.timezone {tz!r} is not an IANA time zone name such as "
                     "Europe/Berlin or America/New_York")
    seed = raw.get("seed", "")
    if not isinstance(seed, (str, int)) or isinstance(seed, bool):
        raise _error("schedule.seed must be text")
    poll = raw.get("poll_seconds", 30)
    if not isinstance(poll, (int, float)) or isinstance(poll, bool) or not 1 <= poll <= 3600:
        raise _error("schedule.poll_seconds must be a number of seconds from 1 to 3600")
    scheduler = raw.get("scheduler", True)
    if not isinstance(scheduler, bool):
        raise _error("schedule.scheduler must be true or false")
    spec = ScheduleSpec(
        timezone=tz, seed=str(seed), poll_seconds=float(poll), scheduler=scheduler,
        waves=_parse_waves(raw.get("waves"), config_dir),
        esm=_parse_esm(raw.get("experience_sampling"), config_dir),
        delphi=_parse_delphi(raw.get("delphi"), config_dir),
        notify=_parse_notify(notify_raw, config, config_dir),
        study=str(config.get("annotation_task_name") or "the study"))
    if not spec.session_kinds:
        raise _error("schedule needs at least one of waves, experience_sampling or delphi")
    return spec


def validate_schedule_config(config: dict, config_dir: Optional[str] = None) -> None:
    """Hook for ``validate_yaml_structure``: raise on any problem."""
    spec = parse_schedule_config(config, config_dir)
    if spec is None or spec.notify is None:
        return
    if not spec.notify.dry_run:
        import logging
        for channel in spec.notify.channels:
            for name in missing_env(channel):
                logging.getLogger(__name__).warning(
                    "notifications: the %s channel reads %s, which is not set in this "
                    "environment; its messages will fail until it is", channel.type, name)
