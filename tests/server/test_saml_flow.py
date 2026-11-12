"""
SAML sign-in through the real routes, against a test IdP that signs with a
real key (tests/helpers/saml_idp.py).

Each refusal case is a response an attacker or a broken IdP could deliver.
The service provider must start the session only for a signed assertion,
meant for this SP, inside its validity window, answering the request this
browser started.
"""

import os

import pytest
import requests

pytest.importorskip("onelogin.saml2", reason="SAML needs python3-saml (the saml extra)")

from tests.helpers.flask_test_setup import FlaskTestServer  # noqa: E402
from tests.helpers.saml_idp import TestIdP  # noqa: E402
from tests.helpers.test_utils import (  # noqa: E402
    cleanup_test_directory,
    create_test_config,
    create_test_data_file,
    create_test_directory,
)

SCHEMES = [{"annotation_type": "radio", "name": "sentiment",
            "description": "Sentiment", "labels": ["positive", "negative"]}]
EPPN = "urn:oid:1.3.6.1.4.1.5923.1.1.1.6"


@pytest.fixture(scope="module")
def idp():
    return TestIdP()


@pytest.fixture(scope="module")
def server(idp):
    test_dir = create_test_directory("saml_flow")
    metadata = os.path.join(test_dir, "idp-metadata.xml")
    with open(metadata, "w") as handle:
        handle.write(idp.metadata_xml())
    data = create_test_data_file(test_dir, [{"id": "a", "text": "One."},
                                            {"id": "b", "text": "Two."}])
    config = create_test_config(
        test_dir, SCHEMES, data_files=[data], require_password=False,
        secret_key="saml-test-secret",
        authentication={
            "method": "saml",
            "saml": {"display_name": "Test University",
                     "idp_metadata_file": metadata,
                     "user_identity_attribute": EPPN,
                     "required_attribute": {"name": "affiliation",
                                            "values": ["member"]}},
        })
    srv = FlaskTestServer(config_file=config)
    if not srv.start():
        pytest.fail("server did not start")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


def _start(server, idp):
    """Begin a sign-in: (session, request id, acs url, audience)."""
    s = requests.Session()
    r = s.get(f"{server.base_url}/saml/login", allow_redirects=False, timeout=10)
    assert r.status_code == 302, r.text[:300]
    assert r.headers["Location"].startswith(idp.sso_url)
    return (s, idp.request_id_from_redirect(r.headers["Location"]),
            f"{server.base_url}/saml/acs", f"{server.base_url}/saml/metadata")


def _post(s, server, saml_response):
    return s.post(f"{server.base_url}/saml/acs", data={"SAMLResponse": saml_response},
                  allow_redirects=False, timeout=10)


def _signed_in(s, server):
    page = s.get(f"{server.base_url}/annotate", allow_redirects=False, timeout=10)
    return page.status_code == 200 and 'id="instance_id"' in page.text


def _good(idp, request_id, acs, audience, name="ada@uni.test", **kw):
    return idp.sign(idp.assertion(
        in_response_to=request_id, acs=acs, audience=audience, name_id="opaque-123",
        attributes={EPPN: [name], "affiliation": ["member", "staff"]}, **kw))


def test_the_login_page_offers_the_institution(server):
    page = requests.get(f"{server.base_url}/", timeout=10).text
    assert "Test University" in page and "/saml/login" in page


def test_a_signed_answer_to_our_request_signs_in(server, idp):
    s, rid, acs, aud = _start(server, idp)
    r = _post(s, server, idp.response(_good(idp, rid, acs, aud), acs=acs, in_response_to=rid))
    assert r.status_code == 302, r.text[:500]
    assert _signed_in(s, server)
    from potato.user_state_management import get_user_state_manager
    assert get_user_state_manager().has_user("ada@uni.test")   # the ePPN, not the NameID


def test_a_signed_response_around_an_unsigned_assertion_signs_in(server, idp):
    # Shibboleth's default: the Response is signed, the Assertion is not.
    s, rid, acs, aud = _start(server, idp)
    assertion = idp.assertion(in_response_to=rid, acs=acs, audience=aud, name_id="x",
                              attributes={EPPN: ["shib@uni.test"], "affiliation": ["member"]})
    r = _post(s, server, idp.response(assertion, acs=acs, in_response_to=rid,
                                      sign_response=True))
    assert r.status_code == 302, r.text[:500]
    assert _signed_in(s, server)


@pytest.mark.parametrize("case", [
    "unsigned", "tampered", "wrong_audience", "expired", "not_yet_valid",
    "other_request", "no_in_response_to", "unsolicited", "not_a_member", "wrapped",
])
def test_refused(server, idp, case):
    s, rid, acs, aud = _start(server, idp)
    if case == "unsigned":
        body = idp.response(idp.assertion(in_response_to=rid, acs=acs, audience=aud,
                                          name_id="x", attributes={EPPN: ["eve@uni.test"],
                                                                   "affiliation": ["member"]}),
                            acs=acs, in_response_to=rid)
    elif case == "tampered":
        signed = _good(idp, rid, acs, aud).replace("ada@uni.test", "eve@uni.test")
        body = idp.response(signed, acs=acs, in_response_to=rid)
    elif case == "wrong_audience":
        body = idp.response(_good(idp, rid, acs, "https://other-sp.test/metadata"),
                            acs=acs, in_response_to=rid)
    elif case == "expired":
        body = idp.response(_good(idp, rid, acs, aud, offset_minutes=-30),
                            acs=acs, in_response_to=rid)
    elif case == "not_yet_valid":
        body = idp.response(_good(idp, rid, acs, aud, offset_minutes=30),
                            acs=acs, in_response_to=rid)
    elif case == "other_request":
        body = idp.response(_good(idp, "_someone_elses", acs, aud), acs=acs,
                            in_response_to="_someone_elses")
    elif case == "no_in_response_to":
        # Signed and otherwise valid, but answering no request: python3-saml
        # alone accepts it.
        body = idp.response(_good(idp, None, acs, aud), acs=acs, in_response_to=None)
    elif case == "unsolicited":
        # IdP-initiated: a browser that never visited /saml/login, holding a
        # signed response that answers no request.
        s = requests.Session()
        body = idp.response(_good(idp, None, acs, aud), acs=acs, in_response_to=None)
    elif case == "not_a_member":
        assertion = idp.sign(idp.assertion(
            in_response_to=rid, acs=acs, audience=aud, name_id="x",
            attributes={EPPN: ["guest@uni.test"], "affiliation": ["affiliate"]}))
        body = idp.response(assertion, acs=acs, in_response_to=rid)
    elif case == "wrapped":
        # The signed assertion for someone else, plus an unsigned one naming
        # the attacker first: the SP must not read the unsigned one.
        evil = idp.assertion(in_response_to=rid, acs=acs, audience=aud, name_id="x",
                             attributes={EPPN: ["mallory@uni.test"], "affiliation": ["member"]})
        body = idp.response(evil + _good(idp, rid, acs, aud).split("?>", 1)[-1],
                            acs=acs, in_response_to=rid)
    r = _post(s, server, body)
    assert r.status_code == 403, (case, r.status_code)
    assert not _signed_in(s, server)


def test_the_sp_publishes_its_metadata(server):
    r = requests.get(f"{server.base_url}/saml/metadata", timeout=10)
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("application/samlmetadata+xml")
    assert f'entityID="{server.base_url}/saml/metadata"' in r.text
    assert f'Location="{server.base_url}/saml/acs"' in r.text


def test_a_password_cannot_sign_in_as_an_sso_identity(server, idp):
    s, rid, acs, aud = _start(server, idp)
    _post(s, server, idp.response(_good(idp, rid, acs, aud, name="grace@uni.test"),
                                  acs=acs, in_response_to=rid))
    other = requests.Session()
    other.post(f"{server.base_url}/auth", data={"email": "grace@uni.test", "pass": "x"},
               timeout=10)
    assert not _signed_in(other, server)


def test_without_a_logout_service_sign_out_stays_local(server, idp):
    """This IdP's metadata names no SingleLogoutService, so /logout ends the
    Potato session and goes home, as before single logout existed."""
    s, rid, acs, audience = _start(server, idp)
    assert _post(s, server, idp.response(_good(idp, rid, acs, audience), acs=acs,
                                         in_response_to=rid)).status_code == 302
    assert _signed_in(s, server)
    r = s.get(f"{server.base_url}/logout", allow_redirects=False, timeout=10)
    assert r.status_code == 302 and not r.headers["Location"].startswith(idp.slo_url)
    assert not _signed_in(s, server)
    assert "SingleLogoutService" not in s.get(f"{server.base_url}/saml/metadata", timeout=10).text
