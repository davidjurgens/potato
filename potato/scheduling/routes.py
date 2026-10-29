"""
HTTP routes for scheduled sessions, resume links and the admin page.

Participants
    ``GET  /``, ``GET /annotate`` (gate)  a participant who has finished the
                                     regular flow is sent to enrolment, to their
                                     open session, or to the status page
    ``GET|POST /schedule/enrol``     time zone and (with consent) contact details
    ``GET  /schedule``               status: the open session, or when the next
                                     one opens, in the participant's time zone
    ``GET|POST /schedule/session/<id>``  a wave, prompt or Delphi round
    ``POST /schedule/started/<id>``  first interaction (the latency clock)
    ``GET  /s/<token>``              resume link from a message
    ``GET|POST /schedule/stop/<token>``  stop messages, delete contact details
    ``POST /schedule/contact/delete``  the same, from the status page

Admin (admin key or RBAC, like every admin page)
    ``GET  /admin/schedule``         schedules, notifications, compliance
    ``GET  /admin/api/schedule``     the same as JSON (no addresses)
    ``POST /admin/api/schedule/contact/<participant>/delete``
    ``POST /admin/api/schedule/delphi/close_round``
    ``POST /admin/api/schedule/tick``  run the notification loop once now
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from flask import jsonify, redirect, render_template, request, session, url_for

from potato.scheduling import timeutil
from potato.scheduling.delphi import format_number
from potato.scheduling.config import EMAIL_RE, PHONE_RE
from potato.scheduling.manager import get_manager, install
from potato.scheduling.questions import parse_answers, view_model

logger = logging.getLogger(__name__)

_GATED_ENDPOINTS = ("home", "annotate")


#: The live config, captured at registration for the admin-key check.
_registered_config: dict = {}


def register_scheduling_routes(app, config) -> None:
    """Called from configure_routes(). Builds the manager (and starts its
    thread) when the config has a ``schedule`` block; registers the routes
    either way so a link to a stopped study says so rather than 404ing."""
    global _registered_config
    _registered_config = config
    try:
        install(app, config)
    except Exception:
        # Validation already refused a bad block at boot; anything here is a
        # runtime problem (an unwritable output directory). Log it loudly and
        # leave the rest of the server running.
        logger.exception("Could not start scheduled sessions")
        app.extensions.pop("potato_scheduling", None)
    if "schedule_status" in app.view_functions:
        return
    app.before_request(_gate)
    app.add_url_rule("/schedule", "schedule_status", schedule_status, methods=["GET"])
    app.add_url_rule("/schedule/enrol", "schedule_enrol", schedule_enrol,
                     methods=["GET", "POST"])
    app.add_url_rule("/schedule/session/<path:session_id>", "schedule_session",
                     schedule_session, methods=["GET", "POST"])
    app.add_url_rule("/schedule/started/<path:session_id>", "schedule_started",
                     schedule_started, methods=["POST"])
    app.add_url_rule("/s/<token>", "schedule_resume", schedule_resume, methods=["GET"])
    app.add_url_rule("/schedule/stop/<token>", "schedule_stop", schedule_stop,
                     methods=["GET", "POST"])
    app.add_url_rule("/schedule/contact/delete", "schedule_contact_delete",
                     schedule_contact_delete, methods=["POST"])
    app.add_url_rule("/admin/schedule", "admin_schedule", admin_schedule, methods=["GET"])
    app.add_url_rule("/admin/api/schedule", "admin_api_schedule", admin_api_schedule,
                     methods=["GET"])
    app.add_url_rule("/admin/api/schedule/contact/<path:participant>/delete",
                     "admin_api_schedule_contact_delete", admin_api_schedule_contact_delete,
                     methods=["POST"])
    app.add_url_rule("/admin/api/schedule/delphi/close_round",
                     "admin_api_schedule_close_round", admin_api_schedule_close_round,
                     methods=["POST"])
    app.add_url_rule("/admin/api/schedule/tick", "admin_api_schedule_tick",
                     admin_api_schedule_tick, methods=["POST"])


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------

def _user_state(username):
    from potato.user_state_management import get_user_state_manager
    usm = get_user_state_manager()
    if usm is None or not usm.has_user(username):
        return None
    return usm.get_user_state(username)


def _eligible(user_state, username) -> bool:
    """Finished the regular flow as a participant: not screened out, not
    failed out of training, not blocked by attention checks."""
    from potato.server_utils.phase_flow import screened_out
    if screened_out(user_state):
        return False
    try:
        ts = user_state.get_training_state()
        if ts is not None and ts.is_failed():
            return False
    except Exception:
        pass
    try:
        from potato.quality_control import get_quality_control_manager
        qc = get_quality_control_manager()
        if qc is not None and qc.is_user_blocked(username):
            return False
    except Exception:
        pass
    return True


def _done(user_state) -> bool:
    from potato.phase import UserPhase
    return user_state.get_phase() == UserPhase.DONE


def _page(template: str, status: int = 200, **ctx):
    m = get_manager()
    ctx.setdefault("study", m.spec.study if m else "")
    return render_template(f"scheduling/{template}", **ctx), status


def _message(title: str, text: str, status: int = 200, icon: str = "info", **ctx):
    return _page("message.html", status, title=title, text=text, icon=icon, **ctx)


def _same_origin() -> bool:
    from potato.server_utils.origin_check import is_same_origin
    return is_same_origin()


def _participant_context():
    """``(manager, username, participant_row)`` or a response to return."""
    m = get_manager()
    if m is None:
        return None, _message("No schedule", "This study has no scheduled sessions.", 404)
    username = session.get("username")
    if not username:
        return None, redirect(url_for("home"))
    p = m.participant(username)
    if p is None:
        us = _user_state(username)
        if us is not None and _done(us) and _eligible(us, username):
            return None, redirect(url_for("schedule_enrol"))
        return None, redirect(url_for("home"))
    return (m, username, p), None


def _times(epoch, tz):
    return {"epoch": int(epoch), "local": timeutil.format_local(epoch, tz),
            "iso": timeutil.iso_local(epoch, tz)}


def _session_view(s: dict, tz: str) -> Dict[str, Any]:
    return {"id": s["id"], "kind": s["kind"], "title": s.get("title") or s["name"],
            "name": s["name"], "status": s["status"], "day": s.get("day"),
            "opens": _times(s["opens_at"], tz), "closes": _times(s["closes_at"], tz)}


def _gate():
    """Send a participant who has finished the regular flow to the schedule."""
    if request.method != "GET" or request.endpoint not in _GATED_ENDPOINTS:
        return None
    m = get_manager()
    username = session.get("username")
    if m is None or not username:
        return None
    try:
        us = _user_state(username)
        if us is None or not _done(us) or not _eligible(us, username):
            return None
        if m.participant(username) is None:
            return redirect(url_for("schedule_enrol"))
        live = m.open_session(username)
        if live is not None:
            return redirect(url_for("schedule_session", session_id=live["id"]))
        return redirect(url_for("schedule_status"))
    except Exception:
        logger.exception("Schedule gate failed for %s; serving the page unchanged", username)
        return None


def _plan_summary(m) -> list:
    """Plain-language list of what enrolment commits the participant to."""
    out = []
    for w in m.spec.waves:
        when = ("now" if not w.offset and w.at is None else
                f"{timeutil.format_span(w.offset)} from now" if w.at is None else
                f"{int(w.offset // 86400)} days from now at {w.at[0]:02d}:{w.at[1]:02d}")
        out.append(f"{w.title}: opens {when}, open for {timeutil.format_span(w.window)}")
    if m.spec.esm:
        e = m.spec.esm
        (h0, m0), (h1, m1) = e.window
        count = (f"{e.per_day} short surveys a day at random times" if e.mode == "signal"
                 else "short surveys at fixed times each day")
        out.append(f"{e.title}: {count} between {h0:02d}:{m0:02d} and {h1:02d}:{m1:02d} "
                   f"for {e.days} days; each stays open {timeutil.format_span(e.expires_after)}")
    if m.spec.delphi:
        d = m.spec.delphi
        out.append(f"{d.title}: up to {d.max_rounds} rounds of rating, each open "
                   f"{timeutil.format_span(d.round_length)}")
    return out


def _secret_time(m, s: dict) -> bool:
    """A signal-contingent prompt's time is not shown before it arrives."""
    return s["kind"] == "prompt" and bool(m.spec.esm) and m.spec.esm.mode == "signal"


def _crowd(user_state, username) -> Dict[str, str]:
    meta = getattr(user_state, "crowd_metadata", None) or {}
    return {"provider": meta.get("provider"), "worker_id": meta.get("worker_id") or username,
            "study_id": meta.get("study_id")} if meta.get("provider") else {}


def _normalise_phone(text: str) -> str:
    return re.sub(r"[\s\-().]", "", text or "")


# --------------------------------------------------------------------------
# Participant routes
# --------------------------------------------------------------------------

def schedule_enrol():
    m = get_manager()
    if m is None:
        return _message("No schedule", "This study has no scheduled sessions.", 404)
    username = session.get("username")
    if not username:
        return redirect(url_for("home"))
    us = _user_state(username)
    if us is None or not _done(us):
        return redirect(url_for("home"))
    if not _eligible(us, username):
        return redirect(url_for("done"))
    if m.participant(username) is not None:
        return redirect(url_for("schedule_status"))
    consent = m.consent_given(us)
    notify = m.spec.notify
    ctx = {
        "consent": consent,
        "has_channels": bool(notify and notify.channels),
        "wants_email": consent and bool(notify) and notify.wants("email"),
        "wants_phone": consent and bool(notify) and notify.wants("phone"),
        "prolific": consent and bool(notify) and notify.wants("prolific")
        and _crowd(us, username).get("provider") == "prolific",
        "default_tz": m.spec.timezone, "timezones": timeutil.timezone_names(),
        "plan": _plan_summary(m), "errors": {}, "values": {},
    }
    if request.method == "GET":
        return _page("enrol.html", **ctx)
    if not _same_origin():
        return _message("Refused", "That form came from another site.", 403, icon="error")
    form = request.form
    tz = (form.get("timezone") or "").strip()
    detected = (form.get("timezone_detected") or "").strip()
    email = (form.get("email") or "").strip() if ctx["wants_email"] else ""
    phone = _normalise_phone(form.get("phone") or "") if ctx["wants_phone"] else ""
    errors = {}
    if not timeutil.valid_timezone(tz):
        errors["timezone"] = "Choose your time zone from the list."
    if email and not EMAIL_RE.match(email):
        errors["email"] = "This does not look like an email address."
    if phone and not PHONE_RE.match(phone):
        errors["phone"] = "Write the number with its country code, for example +44 7700 900123."
    if errors:
        ctx.update(errors=errors, values={"timezone": tz, "email": email,
                                          "phone": form.get("phone") or ""})
        return _page("enrol.html", 400, **ctx)
    source = "browser" if detected and detected == tz else "chosen"
    # Contact details are accepted only on a yes to the consent question,
    # whatever the form sent.
    m.enrol(username, tz, source, consent=consent, email=email or None, phone=phone or None,
            crowd=_crowd(us, username))
    live = m.open_session(username)
    if live is not None:
        return redirect(url_for("schedule_session", session_id=live["id"]))
    return redirect(url_for("schedule_status", enrolled=1))


def schedule_status():
    ctx, response = _participant_context()
    if response is not None:
        return response
    m, username, p = ctx
    tz = p["timezone"]
    sessions = m.sessions(username)
    live = m.open_session(username)
    nxt = m.next_session(username)
    just = request.args.get("done") or ""
    finished = next((s for s in sessions if s["id"] == just and s["status"] == "answered"), None)
    completion = ""
    if finished and finished["kind"] == "wave":
        w = m.wave_spec(finished["name"])
        completion = w.completion_code if w else ""
    # Signal-contingent prompts are not announced in advance: the page shows
    # the day's window, never the next random time.
    next_view = None
    if nxt is not None:
        next_view = _session_view(nxt, tz)
        if _secret_time(m, nxt):
            (h0, m0), (h1, m1) = m.spec.esm.window
            day = timeutil.local_date(nxt["opens_at"], tz)
            next_view["window_text"] = (f"between {h0:02d}:{m0:02d} and {h1:02d}:{m1:02d} on "
                                        f"{day.strftime('%a')} {day.day} {day.strftime('%b')}")
    visible = []
    for s in sessions:
        if s["kind"] == "prompt" and s["status"] == "upcoming":
            continue
        visible.append(_session_view(s, tz))
    prompts = [s for s in sessions if s["kind"] == "prompt"]
    flags = m.contact_flags(username)
    return _page(
        "status.html", tz=tz, live=_session_view(live, tz) if live else None,
        next=next_view, sessions=visible, finished=finished, completion=completion,
        enrolled=request.args.get("enrolled") == "1",
        prompt_counts={k: sum(1 for s in prompts if s["status"] == k)
                       for k in ("answered", "expired", "missed", "upcoming")},
        has_prompts=bool(prompts), contact=flags, consent=bool(p["contact_consent"]),
        withdrawn=bool(p.get("withdrawn_at")),
        channels=json.loads(p.get("channels") or "[]"),
        delphi_stop=m.store.meta("delphi_stop_reason") if m.spec.delphi else None)


def schedule_session(session_id):
    ctx, response = _participant_context()
    if response is not None:
        return response
    m, username, p = ctx
    tz = p["timezone"]
    s = m.session(username, session_id)
    if s is None:
        return _message("No such session", "This session is not part of your schedule.", 404)
    view = _session_view(s, tz)
    if s["status"] == "upcoming":
        # A normal page, not an error: participants open it from old links.
        return _page("status_closed.html", 200, s=view, reason="upcoming", tz=tz)
    if s["status"] == "answered":
        return redirect(url_for("schedule_status", done=s["id"]))
    if s["status"] in ("expired", "missed"):
        nxt = m.next_session(username)
        if nxt is not None and _secret_time(m, nxt):
            nxt = None
        return _page("status_closed.html", 200, s=view, reason="closed", tz=tz,
                     next=_session_view(nxt, tz) if nxt else None)
    errors: Dict[str, str] = {}
    values: Dict[str, Any] = {}
    if request.method == "POST":
        if not _same_origin():
            return _message("Refused", "That form came from another site.", 403, icon="error")
        if s["kind"] == "round":
            answers, errors = m.parse_delphi_answers(request.form)
        else:
            answers, errors = parse_answers(m.questions_for(s), request.form)
        if not errors:
            if m.submit(username, session_id, answers):
                return redirect(url_for("schedule_status", done=s["id"]))
            return _page("status_closed.html", 409, s=view, reason="closed", tz=tz, next=None)
        values = {k: request.form.getlist(k) for k in request.form}
    else:
        m.record_opened(username, session_id)
    status = 400 if errors else 200
    if s["kind"] == "round":
        rv = m.delphi_round_view(username, int(s["name"]))
        d = m.spec.delphi
        return _page("delphi_round.html", status, s=view, round=int(s["name"]),
                     items=rv["items"], scale=rv["scale"], min_label=d.min_label,
                     max_label=d.max_label, comments=d.comments, intro=d.intro,
                     min_panel=d.min_panel, errors=errors, values=values,
                     fmt=format_number)
    intro = ""
    if s["kind"] == "wave":
        w = m.wave_spec(s["name"])
        intro = w.intro if w else ""
    elif m.spec.esm:
        intro = m.spec.esm.intro
    multi = {q["name"] for q in m.questions_for(s) if q["annotation_type"] == "multiselect"}
    saved = {k: (v if k in multi else (v[0] if v else None)) for k, v in values.items()}
    return _page("session.html", status, s=view, intro=intro,
                 questions=view_model(m.questions_for(s), saved), errors=errors)


def schedule_started(session_id):
    m = get_manager()
    username = session.get("username")
    if m is None or not username:
        return jsonify({"error": "not signed in"}), 401
    if not _same_origin():
        return jsonify({"error": "Cross-origin request rejected"}), 403
    recorded = m.record_first_answer(username, session_id)
    return jsonify({"recorded": recorded})


def schedule_resume(token):
    m = get_manager()
    if m is None:
        return _message("No schedule", "This study has no scheduled sessions.", 404)
    claims, problem = m.read_link(token)
    if problem == "invalid" or claims is None or claims["purpose"] != "resume":
        return _message("This link does not work",
                        "The link is not valid for this study. Use the newest message you "
                        "received, or the study link you were given.", 403, icon="error")
    p = m.participant(claims["participant"])
    if problem == "expired":
        s = m.session(claims["participant"], claims["session"]) if claims["session"] else None
        text = "This link has expired."
        if s is not None:
            text = (f"This link was for {s.get('title') or s['name']}, which closed on "
                    f"{timeutil.format_local(s['closes_at'], p['timezone'])}.")
        return _message("This link has expired", text, 410)
    from potato.user_state_management import get_user_state_manager
    if not get_user_state_manager().has_user(claims["participant"]):
        return _message("This link does not work", "This participant is not known here.",
                        404, icon="error")
    if session.get("username") != claims["participant"]:
        session.clear()
        session["username"] = claims["participant"]
    session.permanent = True
    if claims["session"]:
        return redirect(url_for("schedule_session", session_id=claims["session"]))
    return redirect(url_for("schedule_status"))


def schedule_stop(token):
    m = get_manager()
    if m is None:
        return _message("No schedule", "This study has no scheduled sessions.", 404)
    claims, problem = m.read_link(token)
    if claims is None or claims["purpose"] != "stop" or problem == "invalid":
        return _message("This link does not work",
                        "The link is not valid. If you still receive messages, reply to the "
                        "study team.", 403, icon="error")
    # GET only shows the button: mail scanners open links, and a GET that
    # deleted data would unsubscribe people who never clicked.
    if request.method == "GET":
        return _page("stop.html", token=token, done=False)
    if not _same_origin():
        return _message("Refused", "That form came from another site.", 403, icon="error")
    m.stop_messages(claims["participant"], "participant stopped messages")
    return _page("stop.html", token=token, done=True)


def schedule_contact_delete():
    ctx, response = _participant_context()
    if response is not None:
        return response
    m, username, _p = ctx
    if not _same_origin():
        return _message("Refused", "That form came from another site.", 403, icon="error")
    m.stop_messages(username, "participant stopped messages")
    return redirect(url_for("schedule_status", stopped=1))


# --------------------------------------------------------------------------
# Admin routes
# --------------------------------------------------------------------------

def _admin_ok(permission=None) -> bool:
    """The shared admin key, or an RBAC role holding ``permission``.

    Not ``from potato.routes import validate_admin_api_key``: under
    ``python -m potato start`` that module is not the one that registered the
    routes, so importing it re-runs its decorators against the running app and
    raises (see potato/media/routes.py). That import used to sit in a bare
    ``except`` and refused every admin request.
    """
    from potato.server_utils.admin_key import validate_admin_api_key
    key = request.headers.get("X-API-Key") or session.get("admin_api_key")
    if validate_admin_api_key(key, _registered_config):
        return True
    try:
        from potato.server_utils.rbac import Permission, get_rbac_manager
        return get_rbac_manager().check(permission or Permission.VIEW_ADMIN_DASHBOARD,
                                        request, session)
    except Exception:
        return False


def _summary_json(m) -> Dict[str, Any]:
    s = m.admin_summary()
    tzs = {p["participant"]: p["timezone"] for p in s["participants"]}

    def note(n):
        return {k: n.get(k) for k in ("participant", "session_id", "rule", "template",
                                     "channel", "status", "attempts", "detail")} | {
            "due_at": timeutil.iso_utc(n["due_at"]), "sent_at": timeutil.iso_utc(n.get("sent_at"))}

    return {
        "now": timeutil.iso_utc(s["now"]),
        "participants": [{
            **{k: p[k] for k in ("participant", "timezone", "consent", "withdrawn", "channels",
                                 "contact", "counts", "compliance", "median_latency")},
            "enrolled_at": timeutil.iso_utc(p["enrolled_at"]),
            "next_session": p["next"]["id"] if p["next"] else None,
            "next_opens_at": timeutil.iso_utc(p["next"]["opens_at"]) if p["next"] else None,
        } for p in s["participants"]],
        "sessions": [{"participant": x["participant"], "id": x["id"], "kind": x["kind"],
                      "status": x["status"], "opens_at": timeutil.iso_utc(x["opens_at"]),
                      "closes_at": timeutil.iso_utc(x["closes_at"]),
                      "opens_local": timeutil.iso_local(x["opens_at"], tzs.get(x["participant"], "UTC"))}
                     for x in s["sessions"]],
        "notifications": {"counts": s["counts"], "upcoming": [note(n) for n in s["upcoming"]],
                          "sent": [note(n) for n in s["sent"]],
                          "failed": [note(n) for n in s["failed"]]},
        "delphi": {"rounds": [{**r, "opens_at": timeutil.iso_utc(r["opens_at"]),
                               "closes_at": timeutil.iso_utc(r["closes_at"]),
                               "closed_at": timeutil.iso_utc(r.get("closed_at"))}
                              for r in s["rounds"]],
                   "stats": s["stats"], "stop_reason": s["delphi_stop"]},
    }


def admin_schedule():
    if not _admin_ok():
        return redirect(url_for("admin"))
    m = get_manager()
    if m is None:
        return _message("No schedule", "This config has no schedule: block.", 404)
    s = m.admin_summary()
    tzs = {p["participant"]: p["timezone"] for p in s["participants"]}
    return _page("admin.html", summary=s, tzs=tzs, utc=timeutil.iso_utc,
                 local=timeutil.format_local, span=timeutil.format_span,
                 has_delphi=bool(m.spec.delphi), items={i["id"]: i["text"] for i in
                                                        (m.spec.delphi.items if m.spec.delphi else [])},
                 dry_run=bool(m.spec.notify and m.spec.notify.dry_run),
                 channel_types=[c.type for c in (m.spec.notify.channels if m.spec.notify else [])])


def admin_api_schedule():
    if not _admin_ok():
        return jsonify({"error": "Admin API key required"}), 403
    m = get_manager()
    if m is None:
        return jsonify({"error": "no schedule configured"}), 404
    return jsonify(_summary_json(m))


def _admin_post_guard():
    from potato.server_utils.rbac import Permission
    if not _admin_ok(Permission.MANAGE_USERS):
        return jsonify({"error": "Admin API key required"}), 403
    if not _same_origin():
        return jsonify({"error": "Cross-origin request rejected"}), 403
    m = get_manager()
    if m is None:
        return jsonify({"error": "no schedule configured"}), 404
    return None


def admin_api_schedule_contact_delete(participant):
    refused = _admin_post_guard()
    if refused:
        return refused
    m = get_manager()
    had = m.delete_contact(participant, "deleted by an admin")
    if request.form.get("redirect") == "page":
        return redirect(url_for("admin_schedule"))
    return jsonify({"deleted": had})


def admin_api_schedule_close_round():
    refused = _admin_post_guard()
    if refused:
        return refused
    m = get_manager()
    if not m.spec.delphi:
        return jsonify({"error": "no delphi block"}), 404
    number = m.close_round_now()
    if request.form.get("redirect") == "page":
        return redirect(url_for("admin_schedule"))
    if number is None:
        return jsonify({"error": "no round is open"}), 409
    return jsonify({"closed": number})


def admin_api_schedule_tick():
    refused = _admin_post_guard()
    if refused:
        return refused
    summary = get_manager().tick()
    if request.form.get("redirect") == "page":
        return redirect(url_for("admin_schedule"))
    return jsonify(summary)
