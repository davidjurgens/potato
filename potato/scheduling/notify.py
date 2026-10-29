"""
Notification channels.

Each channel turns ``(address, subject, body)`` into one delivered message
and returns a short provider reference, or raises :class:`SendError`.

``log``       writes the message to the server log and the notification log
              (with the full text, so a test or a pilot can follow the links).
              Delivers nothing. The address is the participant id.
``smtp``      email through an SMTP server (``smtplib``), with STARTTLS, SSL
              or neither, and a login when ``username_env``/``password_env``
              are set.
``twilio``    SMS through the Twilio Messages API (form POST, basic auth with
              the account SID and auth token).
``prolific``  a message to the participant's Prolific inbox through the
              Prolific messages API (``POST /api/v1/messages/``), addressed
              by Prolific participant id. No contact details are needed.

``notifications.dry_run: true`` keeps every channel's addressing and
rendering but replaces the delivery with a log line, so a full study can be
piloted without sending anything.

Credentials are read from the environment at send time, from the variable
names the config gives (``password_env: POTATO_SMTP_PASSWORD``).
"""

from __future__ import annotations

import logging
import os
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Optional

from potato.scheduling.config import ChannelSpec

logger = logging.getLogger(__name__)

TWILIO_API = "https://api.twilio.com/2010-04-01"
SMS_LIMIT = 1600  # Twilio's maximum body length


class SendError(Exception):
    """Delivery failed. ``retry`` says whether trying again may help."""

    def __init__(self, message: str, retry: bool = True):
        super().__init__(message)
        self.retry = retry


def _env(channel: ChannelSpec, key: str, required: bool = True) -> Optional[str]:
    name = channel.options.get(key)
    if not name:
        return None
    value = os.environ.get(name)
    if required and not value:
        raise SendError(f"environment variable {name} is not set", retry=False)
    return value


class Channel:
    type = "base"

    def __init__(self, spec: ChannelSpec):
        self.spec = spec

    def send(self, address: str, subject: str, body: str) -> str:  # pragma: no cover
        raise NotImplementedError


class LogChannel(Channel):
    type = "log"

    def send(self, address, subject, body):
        logger.info("[notification:log] to participant %s: %s\n%s", address, subject, body)
        return "logged"


class SmtpChannel(Channel):
    type = "smtp"

    def send(self, address, subject, body):
        import smtplib
        opts = self.spec.options
        user = _env(self.spec, "username_env")
        password = _env(self.spec, "password_env")
        msg = EmailMessage()
        msg["From"] = opts["from"]
        msg["To"] = address
        msg["Subject"] = subject
        msg["Message-ID"] = make_msgid(domain=opts["from"].rsplit("@", 1)[-1].strip("> "))
        msg.set_content(body)
        timeout = float(opts.get("timeout", 20))
        try:
            if opts["security"] == "ssl":
                server = smtplib.SMTP_SSL(opts["host"], opts["port"], timeout=timeout)
            else:
                server = smtplib.SMTP(opts["host"], opts["port"], timeout=timeout)
            try:
                server.ehlo()
                if opts["security"] == "starttls":
                    server.starttls()
                    server.ehlo()
                if user:
                    server.login(user, password)
                refused = server.send_message(msg)
            finally:
                try:
                    server.quit()
                except Exception:
                    pass
        except smtplib.SMTPRecipientsRefused as exc:
            raise SendError(f"recipient refused: {list(exc.recipients.values())[:1]}",
                            retry=False)
        except smtplib.SMTPAuthenticationError as exc:
            raise SendError(f"SMTP login refused ({exc.smtp_code})", retry=False)
        except (smtplib.SMTPException, OSError) as exc:
            raise SendError(f"SMTP error: {exc}")
        if refused:
            raise SendError("recipient refused", retry=False)
        return msg["Message-ID"]


class TwilioChannel(Channel):
    type = "twilio"

    def send(self, address, subject, body):
        import requests
        sid = _env(self.spec, "account_sid_env")
        token = _env(self.spec, "auth_token_env")
        data = {"To": address, "Body": body[:SMS_LIMIT]}
        if self.spec.options.get("messaging_service_sid_env"):
            data["MessagingServiceSid"] = _env(self.spec, "messaging_service_sid_env")
        else:
            data["From"] = self.spec.options["from_number"]
        url = f"{TWILIO_API}/Accounts/{sid}/Messages.json"
        try:
            resp = requests.post(url, data=data, auth=(sid, token),
                                 timeout=float(self.spec.options.get("timeout", 20)))
        except requests.RequestException as exc:
            raise SendError(f"Twilio request failed: {exc}")
        if resp.status_code >= 400:
            try:
                payload = resp.json()
                detail = f"{payload.get('code')}: {payload.get('message')}"
            except ValueError:
                detail = resp.text[:200]
            # 4xx other than rate limiting will fail the same way again.
            raise SendError(f"Twilio {resp.status_code} {detail}",
                            retry=resp.status_code == 429 or resp.status_code >= 500)
        try:
            return str(resp.json().get("sid") or "accepted")
        except ValueError:
            return "accepted"


class ProlificChannel(Channel):
    type = "prolific"

    def __init__(self, spec, study_id_for=None):
        super().__init__(spec)
        self.study_id_for = study_id_for

    def send(self, address, subject, body, study_id: Optional[str] = None):
        from potato.crowdsourcing.prolific_api import ProlificAPIError, ProlificClient
        token = _env(self.spec, "token_env")
        study = self.spec.options.get("study_id") or study_id
        if not study:
            raise SendError("no Prolific study id: set study_id on the channel, or have "
                            "participants arrive with STUDY_ID in the study URL", retry=False)
        client = ProlificClient(token, timeout=float(self.spec.options.get("timeout", 30)))
        text = f"{subject}\n\n{body}" if subject else body
        try:
            client._post("/messages/", {"recipient_id": address, "body": text,
                                        "study_id": study})
        except ProlificAPIError as exc:
            code = getattr(exc, "status_code", None) or 0
            raise SendError(f"Prolific: {exc}", retry=code == 429 or code >= 500 or code == 0)
        return "sent"


CHANNELS = {"log": LogChannel, "smtp": SmtpChannel, "twilio": TwilioChannel,
            "prolific": ProlificChannel}


def build_channel(spec: ChannelSpec) -> Channel:
    return CHANNELS[spec.type](spec)
