"""
SAML 2.0 single sign-on (service-provider side), through python3-saml.

Annotators sign in at their institution's identity provider (Shibboleth,
ADFS, Okta, Azure AD/Entra, ...). Potato starts every sign-in itself
(SP-initiated) and accepts a response only if it answers that request:

* strict mode, with the response or the assertion signed by the IdP's
  certificate;
* ``InResponseTo`` equal to the request id kept in this browser's session,
  so an unsolicited (IdP-initiated) response, or one meant for another
  browser, is refused -- python3-saml alone accepts both;
* each assertion id accepted once, until its ``NotOnOrAfter``;
* audience, destination, recipient and validity windows as python3-saml
  checks them.

SSO identities are kept apart from local accounts, as in OAuthBackend, so a
password can never sign in as an account the IdP vouched for.

Needs the optional extra: ``pip install 'potato-annotation[saml]'`` (which
needs libxmlsec1 on the system).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from potato.authentication import AuthBackend, InMemoryAuthBackend

logger = logging.getLogger(__name__)

INSTALL_HINT = ("SAML sign-in needs python3-saml: pip install 'potato-annotation[saml]' "
                "(it needs libxmlsec1: brew install libxmlsec1, or apt-get install "
                "libxmlsec1-dev)")

POST_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
REDIRECT_BINDING = "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
UNSPECIFIED_NAMEID = "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified"
TRANSIENT_NAMEID = "urn:oasis:names:tc:SAML:2.0:nameid-format:transient"


class SAMLError(Exception):
    """A response Potato refuses. The message is safe to show the annotator."""


class _ReplayCache:
    """Assertion ids already used, each kept until its NotOnOrAfter."""

    def __init__(self):
        self._seen: Dict[str, float] = {}
        self._lock = threading.Lock()

    def claim(self, assertion_id: str, expires_at: Optional[float]) -> bool:
        now = time.time()
        with self._lock:
            for key in [k for k, until in self._seen.items() if until < now]:
                del self._seen[key]
            if assertion_id in self._seen:
                return False
            # Without a NotOnOrAfter the assertion is remembered for a day.
            self._seen[assertion_id] = expires_at or now + 86400
            return True


class SAMLBackend(AuthBackend):
    """Authentication through a SAML 2.0 identity provider."""

    def __init__(self, auth_config: Dict[str, Any]):
        try:
            import onelogin.saml2  # noqa: F401
        except ImportError as exc:
            raise ValueError(INSTALL_HINT) from exc
        self.auth_config = auth_config
        self.saml_config = dict(auth_config.get("saml") or {})
        self.auto_register = auth_config.get("auto_register", True)
        self.allow_local_login = auth_config.get("allow_local_login", False)
        self.users: Dict[str, Dict[str, Any]] = {}
        self._local = InMemoryAuthBackend()
        self._idp_settings: Optional[Dict[str, Any]] = None
        self._replay = _ReplayCache()

    # -- settings --------------------------------------------------------

    def _load_idp(self) -> Dict[str, Any]:
        """The IdP block of the python3-saml settings, loaded once."""
        if self._idp_settings is not None:
            return self._idp_settings
        from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser

        cfg = self.saml_config
        if cfg.get("idp_metadata_url"):
            parsed = OneLogin_Saml2_IdPMetadataParser.parse_remote(
                cfg["idp_metadata_url"], timeout=15,
                entity_id=cfg.get("idp_entity_id"))
            idp = parsed.get("idp") or {}
        elif cfg.get("idp_metadata_file"):
            with open(cfg["idp_metadata_file"], encoding="utf-8") as handle:
                parsed = OneLogin_Saml2_IdPMetadataParser.parse(
                    handle.read(), entity_id=cfg.get("idp_entity_id"))
            idp = parsed.get("idp") or {}
        else:
            manual = cfg.get("idp") or {}
            idp = {
                "entityId": manual.get("entity_id", ""),
                "singleSignOnService": {"url": manual.get("sso_url", ""),
                                        "binding": REDIRECT_BINDING},
                "x509cert": _read_cert(manual.get("x509cert", "")),
            }
            if manual.get("slo_url"):
                idp["singleLogoutService"] = {"url": manual["slo_url"],
                                              "binding": REDIRECT_BINDING}
        if not idp.get("entityId") or not (idp.get("singleSignOnService") or {}).get("url"):
            raise ValueError("authentication.saml: the IdP metadata names no entity id "
                             "or sign-on URL")
        if not (idp.get("x509cert") or idp.get("x509certMulti")):
            raise ValueError("authentication.saml: the IdP metadata has no signing "
                             "certificate, so no response could be verified")
        self._idp_settings = idp
        return idp

    def settings(self, base_url: str) -> Dict[str, Any]:
        """python3-saml settings for an SP whose public root is ``base_url``."""
        cfg = self.saml_config
        base = base_url.rstrip("/")
        sp: Dict[str, Any] = {
            "entityId": cfg.get("sp_entity_id") or f"{base}/saml/metadata",
            "assertionConsumerService": {"url": f"{base}/saml/acs",
                                         "binding": POST_BINDING},
            "NameIDFormat": cfg.get("name_id_format", UNSPECIFIED_NAMEID),
        }
        cert, key = _read_file(cfg.get("sp_cert_file")), _read_file(cfg.get("sp_key_file"))
        if cert and key:
            sp["x509cert"], sp["privateKey"] = cert, key
        if self.slo_enabled():
            sp["singleLogoutService"] = {"url": f"{base}/saml/sls", "binding": REDIRECT_BINDING}
        return {
            "strict": True,
            "debug": False,
            "sp": sp,
            "idp": self._load_idp(),
            "security": {
                "authnRequestsSigned": bool(cert and key),
                "logoutRequestSigned": bool(cert and key),
                "logoutResponseSigned": bool(cert and key),
                # Shibboleth signs the Response by default, not the
                # Assertion. In strict mode python3-saml still requires a
                # valid signature on one of the two and refuses a response
                # with neither.
                "wantAssertionsSigned": False,
                "wantMessagesSigned": False,
                "wantAssertionsEncrypted": bool(cfg.get("want_assertions_encrypted")),
                "wantNameId": not cfg.get("user_identity_attribute"),
                "wantAttributeStatement": False,
                "rejectDeprecatedAlgorithm": True,
                "signatureAlgorithm": "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256",
                "digestAlgorithm": "http://www.w3.org/2001/04/xmlenc#sha256",
                "requestedAuthnContext": False,
            },
        }

    # -- the exchange ----------------------------------------------------

    def login_redirect(self, request_data: Dict[str, Any], base_url: str,
                       return_to: Optional[str] = None) -> Tuple[str, str]:
        """URL to send the browser to, and the request id to keep in its session."""
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
        auth = OneLogin_Saml2_Auth(request_data, self.settings(base_url))
        url = auth.login(return_to=return_to)
        return url, auth.get_last_request_id()

    def process_response(self, request_data: Dict[str, Any], base_url: str,
                         request_id: Optional[str], with_session: bool = False):
        """Validate a POSTed response; return (user id, attributes) or raise SAMLError.

        With ``with_session`` also the IdP session's identifiers (NameID and
        its qualifiers, SessionIndex), which a single-logout request names.
        """
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
        if not request_id:
            # python3-saml accepts any response when no request id is given.
            raise SAMLError("This sign-in was not started here. Start again from "
                            "the sign-in page.")
        auth = OneLogin_Saml2_Auth(request_data, self.settings(base_url))
        auth.process_response(request_id=request_id)
        errors = auth.get_errors()
        if errors:
            logger.warning("SAML response refused: %s (%s)", errors,
                           auth.get_last_error_reason())
            raise SAMLError("Your institution's sign-in could not be verified.")
        if not auth.is_authenticated():
            raise SAMLError("Your institution's sign-in did not complete.")
        # A response without InResponseTo passes python3-saml's check.
        from lxml import etree
        root = etree.fromstring(auth.get_last_response_xml().encode("utf-8"))
        if root.get("InResponseTo") != request_id:
            raise SAMLError("This sign-in answers a different request. Start again "
                            "from the sign-in page.")
        assertion_id = auth.get_last_assertion_id()
        if not assertion_id or not self._replay.claim(
                assertion_id, auth.get_last_assertion_not_on_or_after()):
            raise SAMLError("This sign-in response has already been used.")

        attributes = {k: [str(v) for v in vals]
                      for k, vals in (auth.get_attributes() or {}).items()}
        attributes.update({k: [str(v) for v in vals]
                           for k, vals in (auth.get_friendlyname_attributes() or {}).items()
                           if k not in attributes})
        user_id = self.extract_user_id(auth.get_nameid(), attributes,
                                       name_id_format=auth.get_nameid_format())
        allowed, reason = self.check_restrictions(attributes)
        if not allowed:
            raise SAMLError(reason)
        if with_session:
            return user_id, attributes, {
                "name_id": auth.get_nameid(),
                "name_id_format": auth.get_nameid_format(),
                "name_id_nq": auth.get_nameid_nq(),
                "name_id_spnq": auth.get_nameid_spnq(),
                "session_index": auth.get_session_index(),
            }
        return user_id, attributes

    # -- single logout ---------------------------------------------------

    def slo_enabled(self) -> bool:
        """True when the IdP has a logout service and ``single_logout`` is not off."""
        if self.saml_config.get("single_logout") is False:
            return False
        try:
            service = self._load_idp().get("singleLogoutService") or {}
        except Exception:  # noqa: BLE001 - unreachable metadata: no SLO, not a crash
            return False
        return bool(service.get("url"))

    def logout_redirect(self, request_data: Dict[str, Any], base_url: str,
                        session_info: Dict[str, Any]) -> Tuple[str, str]:
        """URL that sends the browser to the IdP with a LogoutRequest, and its id."""
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
        auth = OneLogin_Saml2_Auth(request_data, self.settings(base_url))
        url = auth.logout(name_id=session_info.get("name_id"),
                          session_index=session_info.get("session_index"),
                          nq=session_info.get("name_id_nq"),
                          name_id_format=session_info.get("name_id_format"),
                          spnq=session_info.get("name_id_spnq"))
        return url, auth.get_last_request_id()

    def process_logout(self, request_data: Dict[str, Any], base_url: str,
                       request_id: Optional[str],
                       session_info: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """A message from the IdP at /saml/sls.

        Returns ``{"kind", "confirmed", "end_session", "redirect"}``:

        * ``kind: "response"`` answers a logout this SP started. ``confirmed``
          is True only for a signed Success that answers ``request_id``; the
          Potato session ended before the browser left, so an unconfirmed
          answer changes nothing here.
        * ``kind: "request"`` is a logout the IdP started. It must be signed:
          an unsigned one would let any page end an annotator's session.
          ``end_session`` is True when it names this browser's IdP session,
          and ``redirect`` carries the LogoutResponse back to the IdP.

        Raises SAMLError for a request that is unsigned or fails validation.
        """
        from onelogin.saml2.auth import OneLogin_Saml2_Auth
        from onelogin.saml2.logout_request import OneLogin_Saml2_Logout_Request
        from onelogin.saml2.utils import OneLogin_Saml2_Utils

        get_data = request_data.get("get_data") or {}
        signed = bool(get_data.get("Signature"))
        auth = OneLogin_Saml2_Auth(request_data, self.settings(base_url))
        if "SAMLResponse" in get_data:
            if not request_id:
                return {"kind": "response", "confirmed": False, "end_session": False,
                        "redirect": None}
            auth.process_slo(keep_local_session=True, request_id=request_id)
            errors = auth.get_errors()
            if errors:
                logger.warning("SAML logout response refused: %s (%s)", errors,
                               auth.get_last_error_reason())
            return {"kind": "response", "confirmed": signed and not errors,
                    "end_session": False, "redirect": None}
        if "SAMLRequest" not in get_data:
            raise SAMLError("This is not a logout message.")
        if not signed:
            raise SAMLError("This logout request is not signed, so it was not acted on.")
        redirect_to = auth.process_slo(keep_local_session=True)
        errors = auth.get_errors()
        if errors:
            logger.warning("SAML logout request refused: %s (%s)", errors,
                           auth.get_last_error_reason())
            raise SAMLError("This logout request could not be verified.")
        xml = OneLogin_Saml2_Utils.decode_base64_and_inflate(get_data["SAMLRequest"])
        # A captured request must not work twice, as an assertion must not.
        # Logout ids share the sign-in replay record (they cannot collide:
        # the prefix keeps the two kinds apart).
        from lxml import etree
        expires = etree.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml).get(
            "NotOnOrAfter")
        expires_at = OneLogin_Saml2_Utils.parse_SAML_to_time(expires) if expires else None
        if not self._replay.claim("logout:" + OneLogin_Saml2_Logout_Request.get_id(xml),
                                  expires_at):
            raise SAMLError("This logout request has already been used.")
        name_id = OneLogin_Saml2_Logout_Request.get_nameid(xml)
        indexes = OneLogin_Saml2_Logout_Request.get_session_indexes(xml)
        mine = session_info or {}
        end_session = bool(mine) and name_id == mine.get("name_id") and (
            not indexes or not mine.get("session_index") or mine["session_index"] in indexes)
        return {"kind": "request", "confirmed": True, "end_session": end_session,
                "redirect": redirect_to}

    def metadata(self, base_url: str) -> str:
        from onelogin.saml2.settings import OneLogin_Saml2_Settings
        settings = OneLogin_Saml2_Settings(self.settings(base_url), sp_validation_only=True)
        xml = settings.get_sp_metadata()
        errors = settings.validate_metadata(xml)
        if errors:
            raise ValueError(f"SP metadata is invalid: {errors}")
        return xml.decode("utf-8") if isinstance(xml, bytes) else xml

    # -- identity and restrictions --------------------------------------

    def extract_user_id(self, name_id: Optional[str], attributes: Dict[str, List[str]],
                        name_id_format: Optional[str] = None) -> str:
        field = self.saml_config.get("user_identity_attribute")
        if field:
            values = attributes.get(field) or []
            if not values or not values[0]:
                raise SAMLError("Your institution did not release the attribute this "
                                "task uses to identify you.")
            return values[0]
        if not name_id:
            raise SAMLError("Your institution's sign-in carried no identifier.")
        if name_id_format == TRANSIENT_NAMEID:
            # A transient NameID is new on every sign-in, so the same
            # annotator would become a new user each time and their work
            # would split across ids. Shibboleth sends one by default.
            logger.error("SAML sign-in refused: the IdP sent a transient NameID and "
                         "authentication.saml.user_identity_attribute is not set. Set "
                         "it to a stable attribute such as eduPersonPrincipalName "
                         "(urn:oid:1.3.6.1.4.1.5923.1.1.1.6).")
            raise SAMLError("This task cannot identify you from your institution's "
                            "sign-in. Ask the study's organiser to check its SAML "
                            "settings.")
        return name_id

    def check_restrictions(self, attributes: Dict[str, List[str]]) -> Tuple[bool, str]:
        rule = self.saml_config.get("required_attribute")
        if not rule:
            return True, ""
        wanted = {str(v).lower() for v in rule.get("values") or []}
        held = {str(v).lower() for v in attributes.get(rule.get("name", ""), [])}
        if wanted & held:
            return True, ""
        return False, "Your account is not authorized for this task."

    def sso_claims(self, attributes: Dict[str, List[str]]) -> List[str]:
        claims = ["provider:saml"]
        for name in self.saml_config.get("claim_attributes") or []:
            claims.extend(f"group:{value}" for value in attributes.get(name, []))
        return claims

    def get_login_providers(self) -> List[Dict[str, str]]:
        return [{
            "name": "saml",
            "display_name": self.saml_config.get("display_name") or "institution sign-in",
            "icon_class": "fas fa-university",
            "button_class": "oauth-btn-generic",
            "login_url": "/saml/login",
        }]

    # -- AuthBackend interface (as OAuthBackend) -------------------------

    def authenticate(self, username: str, password: Optional[str]) -> bool:
        if not self.allow_local_login or username in self.users:
            return False
        return self._local.authenticate(username, password)

    def add_user(self, username: str, password: Optional[str], **kwargs) -> str:
        # An identity the IdP vouched for, or a passwordless roster row.
        if "saml_attributes" in kwargs or "oauth_provider" in kwargs:
            self.users.setdefault(username, {}).update(kwargs)
            return "Success"
        if not self.allow_local_login:
            return ("This task signs in through single sign-on only. "
                    "Use the sign-in button above.")
        if username in self.users:
            return "Duplicate user"
        return self._local.add_user(username, password, **kwargs)

    def add_user_prehashed(self, username: str, hashed_password: str, **kwargs) -> str:
        if not self.allow_local_login:
            return "Local accounts are disabled"
        return self._local.add_user_prehashed(username, hashed_password, **kwargs)

    def is_valid_username(self, username: str) -> bool:
        return username in self.users or self._local.is_valid_username(username)

    def update_password(self, username: str, new_password: str) -> bool:
        if username in self.users or not self._local.is_valid_username(username):
            return False
        return self._local.update_password(username, new_password)

    def has_settable_password(self, username: str) -> bool:
        return username not in self.users and self._local.is_valid_username(username)

    def get_all_users(self) -> list:
        return list(self.users) + [u for u in self._local.users if u not in self.users]


def request_data_from_flask(request, sp_base_url: Optional[str]) -> Tuple[Dict[str, Any], str]:
    """python3-saml's request dict, and the SP's public root URL.

    Behind a proxy that ends TLS, Flask sees http and an internal host, and
    the destination check fails; ``sp_base_url`` names the public root.
    """
    public = urlparse(sp_base_url) if sp_base_url else urlparse(request.url_root)
    prefix = public.path.rstrip("/") if sp_base_url else request.script_root.rstrip("/")
    https = public.scheme == "https"
    port = public.port or (443 if https else 80)
    data = {
        "https": "on" if https else "off",
        "http_host": public.hostname + (f":{public.port}" if public.port else ""),
        "server_port": str(port),
        "script_name": prefix + request.path,
        "get_data": request.args.copy(),
        "post_data": request.form.copy(),
        # A Redirect-binding signature covers the query string as the IdP
        # encoded it; rebuilding it from the parsed values breaks on IdPs that
        # percent-encode in lower case (ADFS).
        "query_string": request.query_string.decode("latin-1"),
        "validate_signature_from_qs": True,
    }
    base = f"{public.scheme}://{data['http_host']}{prefix}"
    return data, base


def _read_file(path: Optional[str]) -> str:
    if not path:
        return ""
    with open(os.path.expanduser(path), encoding="utf-8") as handle:
        return handle.read()


def _read_cert(value: str) -> str:
    """A certificate given inline, or the path of a PEM file."""
    if value and os.path.isfile(os.path.expanduser(value)):
        return _read_file(value)
    return value or ""
