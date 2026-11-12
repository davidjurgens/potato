"""
Scheduled sessions (potato/scheduling): config validation, planning across
time zones and DST, signed links, the notification loop (idempotent, survives
restarts, respects consent), the channels (SMTP against an in-process fake
server, Twilio and Prolific against mocked HTTP), Delphi statistics and the
schedule export.

Nothing here sends a real message.
"""

from __future__ import annotations

import csv
import json
import os
import random
import shutil
import socket
import threading
from datetime import date, datetime, timezone
from unittest import mock

import pytest

from potato.scheduling import delphi as dm
from potato.scheduling import links, planner, timeutil
from potato.scheduling.config import ReminderRule, parse_schedule_config
from potato.scheduling.manager import SchedulingManager, session_status
from potato.scheduling.notify import SendError
from potato.scheduling.store import ScheduleStore
from potato.server_utils.config_module import ConfigValidationError
from tests.helpers.test_utils import create_test_directory

NY = "America/New_York"
# 2026-10-28 13:00 UTC = 09:00 EDT. US DST ends 2026-11-01.
ENROL = datetime(2026, 10, 28, 13, 0, tzinfo=timezone.utc).timestamp()

QUESTIONS = [{"name": "mood", "annotation_type": "likert", "description": "Mood?", "size": 5,
              "required": True},
             {"name": "who", "annotation_type": "multiselect", "description": "Who?",
              "labels": ["alone", "family", "friends"]}]
CONSENT_PAGE = [{"name": "contact_ok", "annotation_type": "radio", "description": "Contact?",
                 "labels": ["Yes", "No"]}]


def base_config(task_dir, **schedule):
    sched = {"timezone": "UTC", "scheduler": False,
             "waves": [{"name": "w2", "offset": "7d", "at": "09:00", "window": "48h",
                        "questions": QUESTIONS,
                        "reminders": [{"at": "open"}, {"before_close": "12h"}]}]}
    sched.update(schedule)
    return {
        "annotation_task_name": "Panel",
        "task_dir": task_dir,
        "output_annotation_dir": os.path.join(task_dir, "out"),
        "phases": {"order": ["consent"],
                   "consent": {"type": "consent", "annotation_schemes": CONSENT_PAGE}},
        "schedule": sched,
        "notifications": {"base_url": "https://study.example.org",
                          "channels": [{"type": "log"}],
                          "contact": {"consent": {"question": "contact_ok", "value": "Yes"}}},
    }


@pytest.fixture
def task_dir():
    d = create_test_directory("scheduling_unit")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def manager(config, now=ENROL):
    spec = parse_schedule_config(config, config["task_dir"])
    clock = {"t": now}
    m = SchedulingManager(config, spec, clock=lambda: clock["t"])
    m._clock = clock
    return m


# --------------------------------------------------------------------------
# Durations, clocks, zones
# --------------------------------------------------------------------------

class TestTimeutil:
    def test_durations(self):
        assert timeutil.parse_duration("90m") == 5400
        assert timeutil.parse_duration("48h") == 172800
        assert timeutil.parse_duration("2w") == 14 * 86400
        assert timeutil.parse_duration(30) == 30
        for bad in ("7 days", "-1h", True, None, "h"):
            with pytest.raises(ValueError):
                timeutil.parse_duration(bad)

    def test_unquoted_yaml_clock_is_base_60(self):
        import yaml
        value = yaml.safe_load("at: 10:30")["at"]
        assert value == 630           # what PyYAML hands over
        assert timeutil.parse_clock(value) == (10, 30)
        assert timeutil.parse_clock("09:05") == (9, 5)
        with pytest.raises(ValueError):
            timeutil.parse_clock("25:00")

    def test_local_clock_time_survives_dst(self):
        before = timeutil.local_to_epoch(date(2026, 10, 30), 9, 0, NY)
        after = timeutil.local_to_epoch(date(2026, 11, 2), 9, 0, NY)
        assert timeutil.iso_utc(before) == "2026-10-30T13:00:00Z"   # EDT, UTC-4
        assert timeutil.iso_utc(after) == "2026-11-02T14:00:00Z"    # EST, UTC-5
        assert timeutil.format_local(after, NY) == "Mon 2 Nov 2026, 09:00 EST"


# --------------------------------------------------------------------------
# Config validation
# --------------------------------------------------------------------------

class TestConfig:
    def test_example_like_config_parses(self, task_dir):
        spec = parse_schedule_config(base_config(task_dir), task_dir)
        assert spec.waves[0].at == (9, 0) and spec.waves[0].window == 172800
        assert [r.key for r in spec.waves[0].reminders] == ["open", "before_close:43200"]

    @pytest.mark.parametrize("key", ["password", "auth_token", "account_sid", "token",
                                     "username", "api_key"])
    def test_inline_credentials_are_refused(self, task_dir, key):
        cfg = base_config(task_dir)
        channel = {"type": "smtp", "host": "smtp.example.org", "from": "a@example.org"}
        channel[key] = "hunter2"
        cfg["notifications"]["channels"].append(channel)
        with pytest.raises(ConfigValidationError, match="environment variables only"):
            parse_schedule_config(cfg, task_dir)

    def test_env_key_must_be_a_variable_name_not_a_value(self, task_dir):
        cfg = base_config(task_dir)
        cfg["notifications"]["channels"].append(
            {"type": "smtp", "host": "h", "from": "a@example.org",
             "username_env": "me@example.org", "password_env": "SMTP_PW"})
        with pytest.raises(ConfigValidationError, match="NAME of an environment variable"):
            parse_schedule_config(cfg, task_dir)

    def test_channels_need_a_declared_consent_question(self, task_dir):
        cfg = base_config(task_dir)
        del cfg["notifications"]["contact"]
        with pytest.raises(ConfigValidationError, match="contact.consent is required"):
            parse_schedule_config(cfg, task_dir)

    def test_consent_question_must_be_asked_on_a_page(self, task_dir):
        cfg = base_config(task_dir)
        cfg["notifications"]["contact"]["consent"]["question"] = "nope"
        with pytest.raises(ConfigValidationError, match="not asked on any phase page"):
            parse_schedule_config(cfg, task_dir)
        cfg["notifications"]["contact"]["consent"] = {"question": "contact_ok", "value": "Sure"}
        with pytest.raises(ConfigValidationError, match="not an option"):
            parse_schedule_config(cfg, task_dir)

    def test_yaml_boolean_consent_value_is_refused(self, task_dir):
        cfg = base_config(task_dir)
        cfg["notifications"]["contact"]["consent"]["value"] = True
        with pytest.raises(ConfigValidationError, match="quote it"):
            parse_schedule_config(cfg, task_dir)

    def test_real_channel_needs_base_url(self, task_dir):
        cfg = base_config(task_dir)
        del cfg["notifications"]["base_url"]
        cfg["notifications"]["channels"].append(
            {"type": "twilio", "from_number": "+15005550006"})
        with pytest.raises(ConfigValidationError, match="base_url is required"):
            parse_schedule_config(cfg, task_dir)
        cfg["notifications"]["dry_run"] = True
        assert parse_schedule_config(cfg, task_dir).notify.base_url.startswith("http://localhost")

    def test_reminder_must_fit_in_window(self, task_dir):
        cfg = base_config(task_dir)
        cfg["schedule"]["waves"][0]["reminders"] = [{"before_close": "48h"}]
        with pytest.raises(ConfigValidationError, match="shorter than the window"):
            parse_schedule_config(cfg, task_dir)

    def test_at_needs_whole_days(self, task_dir):
        cfg = base_config(task_dir)
        cfg["schedule"]["waves"][0]["offset"] = "36h"
        with pytest.raises(ConfigValidationError, match="whole number of days"):
            parse_schedule_config(cfg, task_dir)

    def test_signal_prompts_must_fit_the_window(self, task_dir):
        cfg = base_config(task_dir, waves=None, experience_sampling={
            "days": 2, "daily_window": "09:00-12:00", "signal": {"per_day": 5, "min_gap": "60m"},
            "expires_after": "30m", "questions": QUESTIONS})
        del cfg["schedule"]["waves"]
        with pytest.raises(ConfigValidationError, match="do not fit"):
            parse_schedule_config(cfg, task_dir)

    def test_unknown_keys_are_refused(self, task_dir):
        cfg = base_config(task_dir)
        cfg["schedule"]["waves"][0]["windw"] = "1h"
        with pytest.raises(ConfigValidationError, match="unknown key"):
            parse_schedule_config(cfg, task_dir)

    def test_notifications_without_schedule(self, task_dir):
        cfg = base_config(task_dir)
        del cfg["schedule"]
        with pytest.raises(ConfigValidationError, match="needs a schedule"):
            parse_schedule_config(cfg, task_dir)

    def test_validate_yaml_structure_runs_the_hook(self):
        """The block is checked at boot and by `potato validate`: an inline
        token in the shipped example's config stops validation."""
        import copy
        import yaml
        from potato.server_utils import config_module
        example = os.path.join("examples", "advanced", "two-wave-panel")
        cfg = yaml.safe_load(open(os.path.join(example, "config.yaml")))
        config_module.validate_yaml_structure(copy.deepcopy(cfg), example, example)
        cfg["notifications"]["channels"].append({"type": "prolific", "token": "x"})
        with pytest.raises(ConfigValidationError, match="environment variables only"):
            config_module.validate_yaml_structure(cfg, example, example)


# --------------------------------------------------------------------------
# Planning
# --------------------------------------------------------------------------

class TestPlanner:
    def test_wave_at_clock_time_keeps_local_time_across_dst(self, task_dir):
        spec = parse_schedule_config(base_config(task_dir), task_dir)
        s = planner.plan(spec, ENROL, NY, "p1")[0]
        # Oct 28 + 7 days = Nov 4, after the change: 09:00 EST is 14:00 UTC.
        assert timeutil.iso_utc(s.opens_at) == "2026-11-04T14:00:00Z"
        assert timeutil.iso_local(s.opens_at, NY) == "2026-11-04T09:00:00-05:00"
        assert s.closes_at - s.opens_at == 48 * 3600

    def test_wave_offset_without_at_is_elapsed_time(self, task_dir):
        cfg = base_config(task_dir)
        del cfg["schedule"]["waves"][0]["at"]
        spec = parse_schedule_config(cfg, task_dir)
        s = planner.plan(spec, ENROL, NY, "p1")[0]
        assert s.opens_at - ENROL == 7 * 86400
        # Seven elapsed days across the change is 08:00 on the local clock.
        assert timeutil.iso_local(s.opens_at, NY) == "2026-11-04T08:00:00-05:00"

    def _esm(self, task_dir, **esm):
        block = {"days": 3, "start_day": 1, "daily_window": "09:00-21:00",
                 "signal": {"per_day": 5, "min_gap": "90m"}, "expires_after": "30m",
                 "questions": QUESTIONS}
        block.update(esm)
        cfg = base_config(task_dir, experience_sampling=block)
        del cfg["schedule"]["waves"]
        return parse_schedule_config(cfg, task_dir)

    def test_signal_prompts_are_random_spaced_and_inside_the_window(self, task_dir):
        spec = self._esm(task_dir)
        prompts = planner.plan(spec, ENROL, NY, "p1")
        assert len(prompts) == 15
        by_day = {}
        for p in prompts:
            by_day.setdefault(p.day, []).append(p)
        for day, ps in by_day.items():
            opens = [p.opens_at for p in ps]
            assert all(b - a >= 5400 for a, b in zip(opens, opens[1:]))
            for p in ps:
                local = datetime.fromtimestamp(p.opens_at, tz=timeutil.zone(NY))
                close = datetime.fromtimestamp(p.closes_at, tz=timeutil.zone(NY))
                assert 9 <= local.hour and (close.hour, close.minute) <= (21, 0)
                assert p.closes_at - p.opens_at == 1800
        # Same seed and participant: same plan; another participant: different.
        again = planner.plan(spec, ENROL, NY, "p1")
        other = planner.plan(spec, ENROL, NY, "p2")
        assert [p.opens_at for p in again] == [p.opens_at for p in prompts]
        assert [p.opens_at for p in other] != [p.opens_at for p in prompts]

    def test_signal_window_is_local_on_the_dst_day(self, task_dir):
        # Day 4 after Oct 28 is Nov 1, the day the clocks go back.
        spec = self._esm(task_dir, days=1, start_day=4)
        prompts = planner.plan(spec, ENROL, NY, "p1")
        assert {timeutil.local_date(p.opens_at, NY) for p in prompts} == {date(2026, 11, 1)}
        for p in prompts:
            local = datetime.fromtimestamp(p.opens_at, tz=timeutil.zone(NY))
            assert local.utcoffset().total_seconds() == -5 * 3600
            assert 9 <= local.hour < 21

    def test_signal_offsets_are_uniform_over_arrangements(self):
        """The spacing trick must not crowd prompts at the window's edges."""
        from potato.scheduling.config import EsmSpec
        esm = EsmSpec(days=1, start_day=0, window=((9, 0), (21, 0)), mode="signal",
                      per_day=2, min_gap=3600, expires_after=1800)
        rng = random.Random(1)
        firsts = [planner.prompt_offsets(esm, rng)[0] for _ in range(4000)]
        slack = 12 * 3600 - 1800 - 3600
        # The first of two sorted uniforms has mean slack/3.
        assert abs(sum(firsts) / len(firsts) - slack / 3) < slack * 0.03

    def test_interval_every_and_fixed_times(self, task_dir):
        cfg_every = base_config(task_dir, experience_sampling={
            "days": 1, "start_day": 1, "daily_window": "09:00-21:00",
            "interval": {"every": "3h"}, "expires_after": "1h", "questions": QUESTIONS})
        del cfg_every["schedule"]["waves"]
        prompts = planner.plan(parse_schedule_config(cfg_every, task_dir), ENROL, NY, "p")
        assert [timeutil.iso_local(p.opens_at, NY)[11:16] for p in prompts] == \
            ["09:00", "12:00", "15:00", "18:00"]
        cfg_times = base_config(task_dir, experience_sampling={
            "days": 1, "start_day": 1, "interval": {"times": ["20:00", "10:30"]},
            "expires_after": "45m", "questions": QUESTIONS})
        del cfg_times["schedule"]["waves"]
        prompts = planner.plan(parse_schedule_config(cfg_times, task_dir), ENROL, NY, "p")
        assert [timeutil.iso_local(p.opens_at, NY)[11:16] for p in prompts] == ["10:30", "20:00"]

    def test_prompts_already_past_at_enrolment_are_left_out(self, task_dir):
        cfg = base_config(task_dir, experience_sampling={
            "days": 1, "start_day": 0, "interval": {"times": ["08:00", "20:00"]},
            "expires_after": "30m", "questions": QUESTIONS})
        del cfg["schedule"]["waves"]
        prompts = planner.plan(parse_schedule_config(cfg, task_dir), ENROL, NY, "p")
        assert [timeutil.iso_local(p.opens_at, NY)[11:16] for p in prompts] == ["20:00"]


# --------------------------------------------------------------------------
# Links
# --------------------------------------------------------------------------

class TestLinks:
    KEY = b"k" * 64

    def test_round_trip_tamper_and_expiry(self):
        token = links.make_token(self.KEY, "resume", "user|with|pipes", "wave:w2", 2000, 3)
        claims, problem = links.read_token(self.KEY, token, 1000)
        assert problem is None
        assert claims == {"purpose": "resume", "participant": "user|with|pipes",
                          "session": "wave:w2", "expires_at": 2000, "epoch": 3}
        body, tag = token.split(".")
        forged = links._b64(links._unb64(body).replace(b"user", b"usex")) + "." + tag
        assert links.read_token(self.KEY, forged, 1000) == (None, "invalid")
        assert links.read_token(b"x" * 64, token, 1000) == (None, "invalid")
        assert links.read_token(self.KEY, token, 2000)[1] == "expired"

    def test_key_persists_across_restarts(self, task_dir):
        private = os.path.join(task_dir, ".potato", "scheduling")
        first = links.load_key(private)
        assert links.load_key(private) == first
        assert oct(os.stat(os.path.join(private, "link.key")).st_mode & 0o777) == "0o600"
        with mock.patch.dict(os.environ, {links.ENV_KEY: "from-env-" + "x" * 30}):
            assert links.load_key(private) == ("from-env-" + "x" * 30).encode()


# --------------------------------------------------------------------------
# Manager: enrolment, notifications, the loop
# --------------------------------------------------------------------------

class TestManager:
    def test_enrol_plans_messages_and_keeps_contacts_apart(self, task_dir):
        cfg = base_config(task_dir)
        cfg["notifications"]["channels"].append(
            {"type": "smtp", "host": "smtp.example.org", "from": "s@example.org"})
        cfg["notifications"]["dry_run"] = True
        m = manager(cfg)
        assert m.enrol("p1", NY, "browser", consent=True, email="p1@example.org")
        assert not m.enrol("p1", "UTC", "browser", consent=True)   # once only
        rows = m.store.notifications()
        assert sorted((r["rule"], r["channel"]) for r in rows) == [
            ("before_close:43200", "log"), ("before_close:43200", "smtp"),
            ("open", "log"), ("open", "smtp")]
        # The address lives in the contact store and nowhere in the schedule store.
        assert m.contacts.get("p1")["email"] == "p1@example.org"
        with open(m.store.path, "rb") as fh:
            assert b"p1@example.org" not in fh.read()
        assert not m.contacts.path.startswith(cfg["output_annotation_dir"])
        assert m.store.participant("p1")["timezone"] == NY

    def test_no_consent_means_no_contact_and_no_messages(self, task_dir):
        cfg = base_config(task_dir)
        cfg["notifications"]["channels"].append(
            {"type": "smtp", "host": "smtp.example.org", "from": "s@example.org"})
        m = manager(cfg)
        m.enrol("p2", NY, "browser", consent=False, email="p2@example.org", phone="+15550100")
        assert m.contacts.get("p2") is None
        assert m.store.notifications() == []

    def test_tick_is_idempotent_and_survives_a_restart(self, task_dir):
        m = manager(base_config(task_dir))
        m.enrol("p1", NY, "browser", consent=True)
        opens = m.sessions("p1")[0]["opens_at"]
        first = m.tick(opens + 1)
        assert first["sent"] == 1
        assert m.tick(opens + 2)["sent"] == 0
        # A new manager on the same files (a restart) sends nothing again.
        m2 = manager(base_config(task_dir), now=opens + 3)
        assert m2.tick(opens + 3)["sent"] == 0
        sent = m2.store.notifications(status="sent")
        assert [r["rule"] for r in sent] == ["open"]
        assert "/s/" in sent[0]["preview"]

    def test_two_loops_on_one_store_send_each_message_once(self, task_dir):
        m1 = manager(base_config(task_dir))
        m1.enrol("p1", NY, "browser", consent=True)
        m2 = manager(base_config(task_dir))
        opens = m1.sessions("p1")[0]["opens_at"]
        calls = []
        real = m1.channels["log"].send

        def slow(*a, **k):
            calls.append(a)
            return real(*a, **k)

        m1.channels["log"].send = slow
        m2.channels["log"].send = slow
        # m2 read the due list just before m1 sent from it.
        snapshot = m2.store.due_notifications(opens + 1)
        m1.tick(opens + 1)
        with mock.patch.object(m2.store, "due_notifications", return_value=snapshot):
            assert m2.tick(opens + 1)["sent"] == 0
        sent = m1.store.notifications(status="sent")
        assert len(sent) == 1 and sent[0]["attempts"] == 1

    def test_interrupted_send_is_marked_failed_not_resent(self, task_dir):
        m = manager(base_config(task_dir))
        m.enrol("p1", NY, "browser", consent=True)
        opens = m.sessions("p1")[0]["opens_at"]
        row = m.store.due_notifications(opens + 1)[0]
        assert m.store.claim(row["id"], opens + 1)        # then the process dies
        summary = m.tick(opens + 1 + 601)
        assert summary["interrupted"] == 1 and summary["sent"] == 0
        assert m.store.notifications(status="failed")[0]["detail"].startswith("interrupted")

    def test_answered_session_skips_its_reminder(self, task_dir):
        m = manager(base_config(task_dir))
        m.enrol("p1", NY, "browser", consent=True)
        s = m.sessions("p1")[0]
        m._clock["t"] = s["opens_at"] + 60
        assert m.submit("p1", s["id"], {"mood": 4})
        m.tick(s["closes_at"] - 43200 + 1)
        reminder = [r for r in m.store.notifications() if r["rule"].startswith("before_close")][0]
        assert reminder["status"] == "skipped" and reminder["detail"] == "already answered"

    def test_retry_then_fail(self, task_dir):
        m = manager(base_config(task_dir))
        m.enrol("p1", NY, "browser", consent=True)
        opens = m.sessions("p1")[0]["opens_at"]
        # A failing channel registered under a real channel's name.
        from potato.scheduling.config import ChannelSpec
        fake = mock.Mock()
        fake.send.side_effect = SendError("SMTP error: connection refused")
        m.channels["smtp"] = fake
        m.spec.notify.channels.append(ChannelSpec("smtp", {"host": "h"}))
        m.contacts.set("p1", "p1@example.org", None)
        m.store.update_participant("p1", channels=json.dumps(["smtp"]))
        m.store.add_notifications([{"key": "x", "participant": "p1", "session_id": "wave:w2",
                                    "rule": "open", "template": "open", "channel": "smtp",
                                    "due_at": opens}])
        t = opens + 1
        for _ in range(3):
            m.tick(t)
            t += 3600
        row = m.store.notifications(status="failed")
        assert len(row) == 1 and row[0]["attempts"] == 3 and "connection refused" in row[0]["detail"]
        assert fake.send.call_count == 3

    def test_stop_messages_deletes_contact_skips_pending_and_revokes_links(self, task_dir):
        m = manager(base_config(task_dir))
        m.enrol("p1", NY, "browser", consent=True, email="p1@example.org")
        s = m.sessions("p1")[0]
        token = m.resume_link("p1", s["id"], s["closes_at"], 0).rsplit("/", 1)[1]
        assert m.read_link(token)[1] is None
        m.stop_messages("p1", "participant stopped messages")
        assert m.contacts.get("p1") is None
        assert {r["status"] for r in m.store.notifications()} == {"skipped"}
        assert m.read_link(token) == (None, "invalid")

    def test_contacts_deleted_when_the_study_ends(self, task_dir):
        m = manager(base_config(task_dir))
        m.enrol("p1", NY, "browser", consent=True, email="p1@example.org")
        s = m.sessions("p1")[0]
        m.tick(s["opens_at"] + 10)
        assert m.contacts.get("p1") is not None
        m.tick(s["closes_at"] + 1)
        assert m.contacts.get("p1") is None
        assert m.store.participant("p1")["contact_deleted_reason"] == "study ended"

    def test_statuses_and_latency(self, task_dir):
        cfg = base_config(task_dir, waves=None, experience_sampling={
            "days": 1, "start_day": 1, "interval": {"times": ["10:00", "14:00", "18:00"]},
            "expires_after": "30m", "questions": QUESTIONS})
        del cfg["schedule"]["waves"]
        m = manager(cfg)
        m.enrol("p1", NY, "browser", consent=True)
        a, b, c = m.sessions("p1")
        m.tick(a["opens_at"] + 30)                 # prompt a goes out 30 s late
        m._clock["t"] = a["opens_at"] + 120
        assert m.record_first_answer("p1", a["id"])
        m._clock["t"] = a["opens_at"] + 200
        assert m.submit("p1", a["id"], {"mood": 3})
        m._clock["t"] = b["opens_at"] + 10
        m.record_opened("p1", b["id"])             # opened, never submitted
        m._clock["t"] = b["closes_at"] + 1
        assert not m.submit("p1", b["id"], {"mood": 3})   # too late
        m._clock["t"] = c["closes_at"] + 1
        assert [s["status"] for s in m.sessions("p1")] == ["answered", "expired", "missed"]
        summary = m.admin_summary()["participants"][0]
        assert summary["compliance"] == pytest.approx(1 / 3)
        assert summary["median_latency"] == pytest.approx(90)   # from the message, not the window

    def test_status_function(self):
        s = {"opens_at": 10, "closes_at": 20}
        assert session_status(s, 5) == "upcoming"
        assert session_status(s, 15) == "open"
        assert session_status({**s, "first_answer_at": 12}, 15) == "started"
        assert session_status(s, 25) == "missed"
        assert session_status({**s, "opened_at": 12}, 25) == "expired"
        assert session_status({**s, "submitted_at": 19}, 25) == "answered"

    def test_consent_read_from_phase_answers(self, task_dir):
        m = manager(base_config(task_dir))
        state = mock.Mock()
        with mock.patch("potato.server_utils.phase_flow.collect_flow_answers",
                        return_value={"contact_ok": "Yes"}):
            assert m.consent_given(state)
        with mock.patch("potato.server_utils.phase_flow.collect_flow_answers",
                        return_value={"contact_ok": "No"}):
            assert not m.consent_given(state)


# --------------------------------------------------------------------------
# Channels
# --------------------------------------------------------------------------

class FakeSMTP:
    """A minimal SMTP server on a local socket (smtpd is gone in 3.12)."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.messages = []
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        conn, _ = self.sock.accept()
        f = conn.makefile("rwb")

        def say(line):
            f.write(line.encode() + b"\r\n")
            f.flush()

        say("220 fake ESMTP")
        mail = {"rcpt": []}
        while True:
            line = f.readline()
            if not line:
                break
            cmd = line.decode().strip()
            up = cmd.upper()
            if up.startswith("EHLO") or up.startswith("HELO"):
                f.write(b"250-fake\r\n250 OK\r\n")
                f.flush()
            elif up.startswith("MAIL FROM"):
                mail["from"] = cmd
                say("250 OK")
            elif up.startswith("RCPT TO"):
                mail["rcpt"].append(cmd)
                say("250 OK")
            elif up == "DATA":
                say("354 go ahead")
                data = []
                while True:
                    dl = f.readline()
                    if dl in (b".\r\n", b".\n", b""):
                        break
                    data.append(dl)
                mail["data"] = b"".join(data).decode()
                self.messages.append(mail)
                mail = {"rcpt": []}
                say("250 queued")
            elif up == "QUIT":
                say("221 bye")
                break
            else:
                say("250 OK")
        conn.close()
        self.sock.close()


class TestChannels:
    def _spec(self, ctype, **opts):
        from potato.scheduling.config import _parse_channel
        return _parse_channel({"type": ctype, **opts}, 0)

    def test_smtp_against_an_in_process_server(self):
        from potato.scheduling.notify import SmtpChannel
        server = FakeSMTP()
        ch = SmtpChannel(self._spec("smtp", host="127.0.0.1", port=server.port,
                                    security="none", **{"from": "Study <study@example.org>"}))
        ref = ch.send("p1@example.org", "Wave 2 is open", "Start here: https://x/s/abc")
        server.thread.join(5)
        assert ref.startswith("<")
        msg = server.messages[0]
        assert "p1@example.org" in msg["rcpt"][0]
        assert "Subject: Wave 2 is open" in msg["data"]
        assert "Start here: https://x/s/abc" in msg["data"]

    def test_smtp_starttls_and_login_use_env_credentials(self):
        from potato.scheduling.notify import SmtpChannel
        ch = SmtpChannel(self._spec("smtp", host="smtp.example.org", username_env="T_SMTP_USER",
                                    password_env="T_SMTP_PW", **{"from": "s@example.org"}))
        fake = mock.MagicMock()
        fake.send_message.return_value = {}
        with mock.patch("smtplib.SMTP", return_value=fake) as cls, \
                mock.patch.dict(os.environ, {"T_SMTP_USER": "u", "T_SMTP_PW": "pw"}):
            ch.send("a@example.org", "s", "b")
        cls.assert_called_once_with("smtp.example.org", 587, timeout=20.0)
        fake.starttls.assert_called_once()
        fake.login.assert_called_once_with("u", "pw")

    def test_smtp_missing_env_fails_without_retry(self):
        from potato.scheduling.notify import SmtpChannel
        ch = SmtpChannel(self._spec("smtp", host="h", username_env="NOT_SET_X1",
                                    password_env="NOT_SET_X2", **{"from": "s@example.org"}))
        os.environ.pop("NOT_SET_X1", None)
        with pytest.raises(SendError) as exc:
            ch.send("a@example.org", "s", "b")
        assert not exc.value.retry and "NOT_SET_X1" in str(exc.value)

    def test_twilio_request(self):
        from potato.scheduling.notify import TwilioChannel
        ch = TwilioChannel(self._spec("twilio", from_number="+15005550006"))
        resp = mock.Mock(status_code=201)
        resp.json.return_value = {"sid": "SM123"}
        with mock.patch("requests.post", return_value=resp) as post, \
                mock.patch.dict(os.environ, {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "tok"}):
            assert ch.send("+447700900123", "ignored", "Your survey: https://x/s/t") == "SM123"
        url = post.call_args.args[0]
        assert url == "https://api.twilio.com/2010-04-01/Accounts/AC1/Messages.json"
        assert post.call_args.kwargs["auth"] == ("AC1", "tok")
        assert post.call_args.kwargs["data"] == {"To": "+447700900123", "From": "+15005550006",
                                                 "Body": "Your survey: https://x/s/t"}

    def test_twilio_client_error_is_not_retried(self):
        from potato.scheduling.notify import TwilioChannel
        ch = TwilioChannel(self._spec("twilio", from_number="+15005550006"))
        resp = mock.Mock(status_code=400)
        resp.json.return_value = {"code": 21211, "message": "Invalid 'To' Phone Number"}
        with mock.patch("requests.post", return_value=resp), \
                mock.patch.dict(os.environ, {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t"}):
            with pytest.raises(SendError) as exc:
                ch.send("+1", "", "b")
        assert not exc.value.retry and "21211" in str(exc.value)

    def test_prolific_message(self):
        from potato.scheduling.notify import ProlificChannel
        ch = ProlificChannel(self._spec("prolific"))
        resp = mock.Mock(status_code=201, content=b"{}")
        resp.json.return_value = {}
        with mock.patch("requests.request", return_value=resp) as req, \
                mock.patch.dict(os.environ, {"PROLIFIC_API_TOKEN": "ptok"}):
            ch.send("5f8a", "Round 2", "is open", study_id="60d0")
        method, url = req.call_args.args[:2]
        assert (method, url) == ("POST", "https://api.prolific.com/api/v1/messages/")
        assert req.call_args.kwargs["headers"] == {"Authorization": "Token ptok"}
        assert req.call_args.kwargs["json"] == {"recipient_id": "5f8a",
                                                "body": "Round 2\n\nis open", "study_id": "60d0"}


# --------------------------------------------------------------------------
# Delphi
# --------------------------------------------------------------------------

DELPHI = {"items": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}],
          "scale": {"min": 1, "max": 9}, "max_rounds": 4, "round_length": "1d",
          "min_panel": 3, "stop": {"iqr_at_most": 1, "changed_share_below": 0.2}}


class TestDelphi:
    def test_quantiles_match_the_inclusive_method(self):
        import statistics
        data = [1, 2, 4, 7, 8, 9]
        assert dm.quantile(data, 0.25) == statistics.quantiles(data, n=4, method="inclusive")[0]
        assert dm.quantile(data, 0.75) == statistics.quantiles(data, n=4, method="inclusive")[2]
        assert dm.quantile([5], 0.25) == 5

    def test_stats_and_settling(self):
        items = [{"id": "a"}, {"id": "b"}]
        r1 = {"a": {"p1": 2, "p2": 5, "p3": 8}, "b": {"p1": 7, "p2": 7, "p3": 8}}
        rows1 = dm.item_stats(items, r1, None, None, DELPHI["stop"])
        a, b = rows1
        assert (a["median"], a["q1"], a["q3"], a["iqr"]) == (5, 3.5, 6.5, 3)
        assert not a["settled"] and b["settled"]          # IQR 0.5 <= 1
        r2 = {"a": {"p1": 4, "p2": 5, "p3": 8}, "b": {"p1": 7, "p2": 7, "p3": 8}}
        rows2 = dm.item_stats(items, r2, r1, {r["item"]: r for r in rows1}, DELPHI["stop"])
        assert rows2[0]["changed_share"] == pytest.approx(1 / 3)
        assert not rows2[0]["settled"]
        assert dm.stop_decision(rows2, 2, 4, DELPHI["stop"]) == (False, "")
        assert dm.stop_decision(rows2, 4, 4, DELPHI["stop"])[0]

    def test_feedback_hides_small_panels_and_own_comments(self):
        items = [{"id": "a"}]
        stats = {"a": {"n": 2, "median": 5, "q1": 4, "q3": 6}}
        fb = dm.feedback(items, stats, {"a": {"rating": 3}}, {"a": [("p2", "too vague")]},
                         "p1", 3, "s")[0]
        assert not fb["shown"] and fb["median"] is None and fb["comments"] == []
        assert fb["own"] == 3
        stats["a"]["n"] = 3
        fb = dm.feedback(items, stats, {}, {"a": [("p1", "mine"), ("p2", "theirs")]},
                         "p1", 3, "s")[0]
        assert fb["shown"] and fb["comments"] == ["theirs"]

    def test_rounds_advance_and_stop_on_stability(self, task_dir):
        cfg = base_config(task_dir, delphi=DELPHI)
        del cfg["schedule"]["waves"]
        m = manager(cfg)
        for p in ("p1", "p2", "p3"):
            m.enrol(p, "UTC", "browser", consent=True)
        sess = m.store.sessions(kind="round")
        assert {s["participant"] for s in sess} == {"p1", "p2", "p3"}
        ratings1 = {"p1": (2, 7), "p2": (5, 7), "p3": (8, 8)}
        for p, (a, b) in ratings1.items():
            assert m.submit(p, "round:1", {"a": {"rating": a, "comment": f"{p} says"},
                                           "b": {"rating": b}})
        m._clock["t"] += 10
        assert m.close_round_now() == 1
        rounds = m.store.rounds()
        assert [r["status"] for r in rounds] == ["closed", "open"]
        view = m.delphi_round_view("p1", 2)["items"][0]["feedback"]
        assert view["median"] == 5 and view["own"] == 2
        assert sorted(view["comments"]) == ["p2 says", "p3 says"]
        # Nobody changes their mind in round 2: stable, so the study stops.
        for p, (a, b) in ratings1.items():
            assert m.submit(p, "round:2", {"a": {"rating": a}, "b": {"rating": b}})
        m._clock["t"] += 10
        m.close_round_now()
        assert m.store.meta("delphi_stop_reason") == "every item met a stopping criterion"
        assert len(m.store.rounds()) == 2

    def test_round_closes_on_time_and_late_joiner_gets_open_round(self, task_dir):
        cfg = base_config(task_dir, delphi={**DELPHI, "gap": "1h"})
        del cfg["schedule"]["waves"]
        m = manager(cfg)
        m.enrol("p1", "UTC", "browser", consent=True)
        r1 = m.store.rounds()[0]
        m.tick(r1["closes_at"] + 1)                    # nobody rated: round 2 scheduled
        r2 = m.store.rounds()[1]
        assert r2["opens_at"] == r1["closes_at"] + 3600
        m._clock["t"] = r2["opens_at"] + 5
        m.enrol("late", "UTC", "browser", consent=True)
        m.tick(r2["opens_at"] + 6)
        assert m.session("late", "round:2")["status"] == "open"
        assert m.session("late", "round:1") is None
        sent = {(n["participant"], n["session_id"]) for n in m.store.notifications(status="sent")}
        assert ("p1", "round:2") in sent and ("late", "round:2") not in sent


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------

class TestExport:
    def test_sessions_compliance_and_notifications(self, task_dir):
        from potato.export.base import ExportContext
        from potato.export.registry import export_registry
        cfg = base_config(task_dir)
        m = manager(cfg)
        m.enrol("p1", NY, "browser", consent=True, email="secret-addr@example.org")
        s = m.sessions("p1")[0]
        m.tick(s["opens_at"] + 5)
        m._clock["t"] = s["opens_at"] + 65
        m.record_first_answer("p1", s["id"])
        m.submit("p1", s["id"], {"mood": 4, "who": ["alone", "friends"]})
        ctx = ExportContext(config=cfg, annotations=[], items={}, schemas=[],
                            output_dir=cfg["output_annotation_dir"])
        out = os.path.join(task_dir, "export")
        result = export_registry.export("schedule", ctx, out)
        assert result.success, result.errors
        rows = list(csv.DictReader(open(os.path.join(out, "schedule_sessions.csv"))))
        assert [r["kind"] for r in rows] == ["enrolment", "wave"]
        wave = rows[1]
        assert wave["wave"] == "w2" and wave["status"] == "answered"
        assert wave["opens_at_local"] == "2026-11-04T09:00:00-05:00"
        assert wave["latency_seconds"] == "60.0"
        assert wave["answer.mood"] == "4" and wave["answer.who"] == "alone;friends"
        comp = list(csv.DictReader(open(os.path.join(out, "schedule_compliance.csv"))))
        assert comp[0]["compliance"] == "1.000"
        for name in os.listdir(out):
            assert "secret-addr" not in open(os.path.join(out, name)).read()

    def test_can_export_without_schedule(self, task_dir):
        from potato.export.base import ExportContext
        from potato.export.schedule_exporter import ScheduleExporter
        ctx = ExportContext(config={}, annotations=[], items={}, schemas=[], output_dir=task_dir)
        assert ScheduleExporter().can_export(ctx)[0] is False
