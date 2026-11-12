"""
SAML single logout through the real routes, against the test IdP
(tests/helpers/saml_idp.py), which signs the Redirect-binding messages with a
real key.

Signing out of Potato sends a LogoutRequest naming this browser's IdP session
and records the answer. A logout the IdP starts ends the session only when it
is signed and names this browser's session.
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
NAME_ID = "opaque-123"


@pytest.fixture(scope="module")
def idp():
    return TestIdP()


@pytest.fixture(scope="module")
def server(idp):
    test_dir = create_test_directory("saml_logout")
    metadata = os.path.join(test_dir, "idp-metadata.xml")
    with open(metadata, "w") as handle:
        handle.write(idp.metadata_xml(slo=True))
    data = create_test_data_file(test_dir, [{"id": "a", "text": "One."}])
    config = create_test_config(
        test_dir, SCHEMES, data_files=[data], require_password=False,
        secret_key="saml-logout-secret",
        authentication={"method": "saml",
                        "saml": {"idp_metadata_file": metadata,
                                 "user_identity_attribute": EPPN}})
    srv = FlaskTestServer(config_file=config)
    if not srv.start():
        pytest.fail("server did not start")
    yield srv
    srv.stop()
    cleanup_test_directory(test_dir)


def signed_in_session(server, idp, user="ada@uni.test"):
    """A browser session signed in through the IdP, and the SessionIndex it got."""
    s = requests.Session()
    r = s.get(f"{server.base_url}/saml/login", allow_redirects=False, timeout=10)
    request_id = idp.request_id_from_redirect(r.headers["Location"])
    acs, audience = f"{server.base_url}/saml/acs", f"{server.base_url}/saml/metadata"
    assertion = idp.assertion(in_response_to=request_id, acs=acs, audience=audience,
                              name_id=NAME_ID, attributes={EPPN: [user]})
    from lxml import etree
    index = etree.fromstring(assertion.encode()).find(
        ".//{urn:oasis:names:tc:SAML:2.0:assertion}AuthnStatement").get("SessionIndex")
    r = s.post(acs, data={"SAMLResponse": idp.response(idp.sign(assertion), acs=acs,
                                                      in_response_to=request_id)},
               allow_redirects=False, timeout=10)
    assert r.status_code == 302, r.text[:300]
    assert signed_in(s, server)
    return s, index


def signed_in(s, server):
    page = s.get(f"{server.base_url}/annotate", allow_redirects=False, timeout=10)
    return page.status_code == 200 and 'id="instance_id"' in page.text


def sls(server):
    return f"{server.base_url}/saml/sls"


class TestSignOutEndsTheIdPSession:
    def test_logout_sends_a_request_naming_this_session(self, server, idp):
        s, index = signed_in_session(server, idp)
        r = s.get(f"{server.base_url}/logout", allow_redirects=False, timeout=10)
        assert r.status_code == 302 and r.headers["Location"].startswith(idp.slo_url)
        request, _params = idp.message_from_redirect(r.headers["Location"])
        ns = {"saml": "urn:oasis:names:tc:SAML:2.0:assertion",
              "samlp": "urn:oasis:names:tc:SAML:2.0:protocol"}
        assert request.tag.endswith("LogoutRequest")
        assert request.find("saml:NameID", ns).text == NAME_ID
        assert request.find("samlp:SessionIndex", ns).text == index
        # Potato's session is over before the IdP answers, or if it never does.
        assert not signed_in(s, server)

        answer = s.get(f"{sls(server)}?" + idp.logout_response(
            destination=sls(server), in_response_to=request.get("ID")), timeout=10)
        assert answer.status_code == 200
        assert "signed out of this task and of your institution" in answer.text

    @pytest.mark.parametrize("case", ["unsigned", "other request", "failed"])
    def test_an_answer_that_does_not_confirm_says_so(self, server, idp, case):
        s, _index = signed_in_session(server, idp)
        r = s.get(f"{server.base_url}/logout", allow_redirects=False, timeout=10)
        request, _ = idp.message_from_redirect(r.headers["Location"])
        kwargs = {"destination": sls(server), "in_response_to": request.get("ID")}
        if case == "unsigned":
            kwargs["sign"] = False
        elif case == "other request":
            kwargs["in_response_to"] = "_not-the-one-we-sent"
        else:
            kwargs["status"] = "urn:oasis:names:tc:SAML:2.0:status:Responder"
        answer = s.get(f"{sls(server)}?" + idp.logout_response(**kwargs), timeout=10)
        assert answer.status_code == 200
        assert "did not confirm" in answer.text
        assert not signed_in(s, server)


class TestALogoutTheIdPStarts:
    def test_a_signed_request_for_this_session_ends_it_and_is_answered(self, server, idp):
        s, index = signed_in_session(server, idp)
        query = idp.logout_request(destination=sls(server), name_id=NAME_ID,
                                   session_index=index)
        r = s.get(f"{sls(server)}?{query}", allow_redirects=False, timeout=10)
        assert r.status_code == 302 and r.headers["Location"].startswith(idp.slo_url)
        response, _ = idp.message_from_redirect(r.headers["Location"], "SAMLResponse")
        sent, _ = idp.message_from_redirect(f"{sls(server)}?{query}")
        assert response.get("InResponseTo") == sent.get("ID")
        status = response.find(".//{urn:oasis:names:tc:SAML:2.0:protocol}StatusCode")
        assert status.get("Value").endswith(":Success")
        assert not signed_in(s, server)

    def test_a_request_encoded_in_lower_case_verifies(self, server, idp):
        # ADFS percent-encodes in lower case and signs those bytes; rebuilding
        # the query from the parsed values (upper case) breaks the signature.
        s, index = signed_in_session(server, idp)
        query = idp.logout_request(destination=sls(server), name_id=NAME_ID,
                                   session_index=index, lowercase=True)
        assert "%2f" in query or "%3d" in query
        # Sent with http.client: requests (urllib3) upper-cases percent
        # escapes before sending, which a browser does not.
        import http.client
        from urllib.parse import urlparse
        target = urlparse(server.base_url)
        conn = http.client.HTTPConnection(target.hostname, target.port, timeout=10)
        cookie = "; ".join(f"{c.name}={c.value}" for c in s.cookies)
        conn.request("GET", f"/saml/sls?{query}", headers={"Cookie": cookie})
        response = conn.getresponse()
        assert response.status == 302, response.read()[:300]
        set_cookie = response.getheader("Set-Cookie") or ""
        conn.close()
        # The session cookie comes back emptied: Potato's session ended.
        assert "session=;" in set_cookie.replace(" ", "") or "Expires=Thu, 01 Jan 1970" in set_cookie

    def test_a_captured_request_does_not_work_twice(self, server, idp):
        s, index = signed_in_session(server, idp)
        query = idp.logout_request(destination=sls(server), name_id=NAME_ID,
                                   session_index=index)
        assert s.get(f"{sls(server)}?{query}", allow_redirects=False, timeout=10).status_code == 302
        r = s.get(f"{sls(server)}?{query}", allow_redirects=False, timeout=10)
        assert r.status_code == 400 and "already been used" in r.text

    @pytest.mark.parametrize("case", ["another user", "another session"])
    def test_a_request_for_someone_else_leaves_this_session(self, server, idp, case):
        s, index = signed_in_session(server, idp)
        name_id, session_index = NAME_ID, index
        if case == "another user":
            name_id = "someone-else"
        else:
            session_index = "_s-another-device"
        query = idp.logout_request(destination=sls(server), name_id=name_id,
                                   session_index=session_index)
        r = s.get(f"{sls(server)}?{query}", allow_redirects=False, timeout=10)
        assert r.status_code == 302      # still answered, so the IdP can carry on
        assert signed_in(s, server)

    @pytest.mark.parametrize("case", ["unsigned", "tampered"])
    def test_an_unverified_request_is_refused(self, server, idp, case):
        s, index = signed_in_session(server, idp)
        query = idp.logout_request(destination=sls(server), name_id=NAME_ID,
                                   session_index=index, sign=(case != "unsigned"))
        if case == "tampered":
            other = idp.logout_request(destination=sls(server), name_id="someone-else")
            # The other request's message with this one's signature.
            query = other.split("&SigAlg=")[0] + "&SigAlg=" + query.split("&SigAlg=")[1]
        r = s.get(f"{sls(server)}?{query}", allow_redirects=False, timeout=10)
        assert r.status_code == 400
        # The page must not claim a sign-out that did not happen.
        assert "still signed in" in r.text and "You are logged out" not in r.text
        assert signed_in(s, server)


def test_the_metadata_advertises_the_logout_service(server):
    xml = requests.get(f"{server.base_url}/saml/metadata", timeout=10).text
    assert "SingleLogoutService" in xml and f"{server.base_url}/saml/sls" in xml
