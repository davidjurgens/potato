"""
SAML backend pieces the route tests do not isolate: replay, configuration,
and the public URL behind a proxy. The full exchange is driven in
tests/server/test_saml_flow.py.
"""

import base64

import pytest

pytest.importorskip("onelogin.saml2", reason="SAML needs python3-saml (the saml extra)")

from potato.auth_backends.saml_backend import (  # noqa: E402
    SAMLBackend,
    SAMLError,
    request_data_from_flask,
)
from potato.server_utils.config_module import (  # noqa: E402
    ConfigValidationError,
    validate_authentication_config,
)
from tests.helpers.saml_idp import TestIdP  # noqa: E402

BASE = "https://annotate.example.edu"
ACS = f"{BASE}/saml/acs"
AUDIENCE = f"{BASE}/saml/metadata"


@pytest.fixture(scope="module")
def idp():
    return TestIdP()


@pytest.fixture
def backend(idp):
    return SAMLBackend({"method": "saml", "saml": {
        "idp": {"entity_id": idp.entity_id, "sso_url": idp.sso_url,
                "x509cert": idp.cert_b64}}})


def _acs_request(saml_response):
    return {"https": "on", "http_host": "annotate.example.edu", "server_port": "443",
            "script_name": "/saml/acs", "get_data": {}, "post_data": {"SAMLResponse": saml_response}}


def test_an_assertion_is_accepted_once(backend, idp):
    rid = "_req1"
    body = idp.response(idp.sign(idp.assertion(in_response_to=rid, acs=ACS, audience=AUDIENCE,
                                               name_id="ada")), acs=ACS, in_response_to=rid)
    user, _attrs = backend.process_response(_acs_request(body), BASE, rid)
    assert user == "ada"
    with pytest.raises(SAMLError, match="already been used"):
        backend.process_response(_acs_request(body), BASE, rid)


def test_the_name_id_identifies_by_default_and_an_attribute_when_named(backend, idp):
    assert backend.extract_user_id("opaque", {"mail": ["a@b"]}) == "opaque"
    backend.saml_config["user_identity_attribute"] = "mail"
    assert backend.extract_user_id("opaque", {"mail": ["a@b"]}) == "a@b"
    with pytest.raises(SAMLError):
        backend.extract_user_id("opaque", {})


def test_the_request_signing_key_turns_on_signed_requests(backend):
    settings = backend.settings(BASE)
    assert settings["strict"] is True
    # The Response or the Assertion may carry the signature (Shibboleth signs
    # the Response); strict mode refuses a response with neither.
    assert settings["security"]["wantAssertionsSigned"] is False
    assert settings["security"]["rejectDeprecatedAlgorithm"] is True
    assert settings["security"]["authnRequestsSigned"] is False
    assert settings["sp"]["assertionConsumerService"]["url"] == ACS


class _FakeRequest:
    url_root = "http://10.0.0.5:8000/"
    script_root = ""
    path = "/saml/acs"
    args = {}
    form = {"SAMLResponse": "x"}
    query_string = b""


def test_behind_a_proxy_the_public_url_comes_from_sp_base_url():
    data, base = request_data_from_flask(_FakeRequest(), "https://annotate.example.edu/round1")
    assert base == "https://annotate.example.edu/round1"
    assert data["https"] == "on" and data["server_port"] == "443"
    assert data["script_name"] == "/round1/saml/acs"
    data, base = request_data_from_flask(_FakeRequest(), None)
    assert base == "http://10.0.0.5:8000" and data["https"] == "off"


def _auth(**saml):
    return {"authentication": {"method": "saml", "saml": saml}, "secret_key": "k"}


@pytest.mark.parametrize("saml,match", [
    ({}, "exactly one of"),
    ({"idp_metadata_url": "https://a", "idp_metadata_file": "b"}, "exactly one of"),
    ({"idp_metadata_url": "http://idp.test/metadata"}, "must be https"),
    ({"idp": {"entity_id": "x"}}, "missing: sso_url, x509cert"),
    ({"idp_metadata_file": "m.xml", "sp_cert_file": "c.pem"}, "go together"),
    ({"idp_metadata_file": "m.xml", "required_attribute": {"name": "a"}}, "list of values"),
    ({"idp_metadata_file": "m.xml", "idp_metdata": "typo"}, "unknown keys: idp_metdata"),
    ({"idp_metadata_file": "m.xml", "want_assertions_encrypted": True}, "needs sp_cert_file"),
])
def test_config_refusals(saml, match):
    with pytest.raises(ConfigValidationError, match=match):
        validate_authentication_config(_auth(**saml))


def test_a_complete_config_validates():
    validate_authentication_config(_auth(idp_metadata_url="https://idp.test/metadata",
                                         user_identity_attribute="mail"))


def test_the_request_cookie_crosses_sites_only_over_https():
    # The IdP returns the browser with a cross-site POST, so over https the
    # cookie must be SameSite=None (which browsers only keep when Secure).
    import flask
    from potato import routes
    from unittest.mock import MagicMock, patch
    backend = MagicMock()
    backend.saml_config = {"sp_base_url": BASE}
    backend.login_redirect.return_value = ("https://idp.test/sso?x", "_req")
    authenticator = MagicMock()
    authenticator.get_saml_backend.return_value = backend
    app = flask.Flask(__name__)
    app.secret_key = "k"
    with app.test_request_context("/saml/login"), \
            patch.object(routes, "UserAuthenticator") as ua, \
            patch.object(routes, "app", app):
        ua.get_instance.return_value = authenticator
        cookie = routes.saml_login().headers["Set-Cookie"]
    assert "Secure" in cookie and "SameSite=None" in cookie and "HttpOnly" in cookie
    # A __Host- cookie on / with no Domain: a sibling subdomain cannot plant
    # its own copy, which would carry the attacker's request id.
    assert cookie.startswith("__Host-potato_saml_request=")
    assert "Path=/;" in cookie and "Domain" not in cookie


TRANSIENT = "urn:oasis:names:tc:SAML:2.0:nameid-format:transient"


def test_a_transient_name_id_is_not_an_identity(backend, idp):
    # It changes on every sign-in: the same annotator would be a new user
    # each time and their work would split across ids.
    rid = "_req_transient"
    body = idp.response(idp.sign(idp.assertion(
        in_response_to=rid, acs=ACS, audience=AUDIENCE, name_id="_9f3c1a",
        name_id_format=TRANSIENT)), acs=ACS, in_response_to=rid)
    with pytest.raises(SAMLError, match="cannot identify you"):
        backend.process_response(_acs_request(body), BASE, rid)
    # With a stable attribute named, the transient NameID does not matter.
    backend.saml_config["user_identity_attribute"] = "eppn"
    rid = "_req_transient2"
    body = idp.response(idp.sign(idp.assertion(
        in_response_to=rid, acs=ACS, audience=AUDIENCE, name_id="_9f3c1b",
        name_id_format=TRANSIENT, attributes={"eppn": ["ada@uni.test"]})),
        acs=ACS, in_response_to=rid)
    assert backend.process_response(_acs_request(body), BASE, rid)[0] == "ada@uni.test"


def test_an_unset_identity_attribute_warns_at_load(caplog):
    validate_authentication_config(_auth(idp_metadata_url="https://idp.test/metadata"))
    assert "user_identity_attribute is not set" in caplog.text


def test_encryption_is_advertised_only_when_asked_for(idp, tmp_path):
    cert, key = tmp_path / "sp.crt", tmp_path / "sp.key"
    cert.write_text(idp.cert_pem)
    key.write_text(idp.key_pem)
    common = {"idp": {"entity_id": idp.entity_id, "sso_url": idp.sso_url,
                      "x509cert": idp.cert_b64},
              "sp_cert_file": str(cert), "sp_key_file": str(key)}
    plain = SAMLBackend({"method": "saml", "saml": dict(common)}).metadata(BASE)
    assert 'use="encryption"' not in plain
    asked = SAMLBackend({"method": "saml", "saml": dict(
        common, want_assertions_encrypted=True)}).metadata(BASE)
    assert 'use="encryption"' in asked


class TestSingleLogoutSettings:
    @staticmethod
    def _backend(test_idp, slo_url=None, **saml):
        manual = {"entity_id": test_idp.entity_id, "sso_url": test_idp.sso_url,
                  "x509cert": test_idp.cert_b64}
        if slo_url:
            manual["slo_url"] = slo_url
        return SAMLBackend({"method": "saml", "saml": {"idp": manual, **saml}})

    def test_on_when_the_idp_has_a_logout_service(self, idp):
        backend = self._backend(idp, slo_url=idp.slo_url)
        assert backend.slo_enabled()
        assert backend.settings(BASE)["sp"]["singleLogoutService"]["url"] == f"{BASE}/saml/sls"
        assert "SingleLogoutService" in backend.metadata(BASE)

    def test_off_without_one_or_when_turned_off(self, idp):
        assert not self._backend(idp).slo_enabled()
        assert "SingleLogoutService" not in self._backend(idp).metadata(BASE)
        off = self._backend(idp, slo_url=idp.slo_url, single_logout=False)
        assert not off.slo_enabled() and "singleLogoutService" not in off.settings(BASE)["sp"]

    def test_the_session_identifiers_come_back_with_the_sign_in(self, backend, idp):
        login, _rid = backend.login_redirect(
            {"https": "on", "http_host": "annotate.example.edu", "server_port": "443",
             "script_name": "/saml/login", "get_data": {}, "post_data": {}}, BASE)
        rid = idp.request_id_from_redirect(login)
        body = idp.response(idp.sign(idp.assertion(
            in_response_to=rid, acs=ACS, audience=AUDIENCE, name_id="opaque-9")),
            acs=ACS, in_response_to=rid)
        user, _attrs, session = backend.process_response(_acs_request(body), BASE, rid,
                                                         with_session=True)
        assert user == "opaque-9" and session["name_id"] == "opaque-9"
        assert session["session_index"].startswith("_s")
