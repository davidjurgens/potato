"""
A SAML identity provider for tests: a real key and certificate, and real
XML signatures, so the service provider's checks run exactly as they would
against Shibboleth or Okta. Nothing here is mocked.
"""

from __future__ import annotations

import base64
import datetime as dt
import uuid
import zlib
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse
from xml.sax.saxutils import escape

SAMLP = "urn:oasis:names:tc:SAML:2.0:protocol"
SAML = "urn:oasis:names:tc:SAML:2.0:assertion"


def _iso(moment: dt.datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class TestIdP:
    entity_id = "https://idp.test/idp"
    sso_url = "https://idp.test/sso"
    slo_url = "https://idp.test/slo"

    def __init__(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "idp.test")])
        now = dt.datetime.now(dt.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - dt.timedelta(days=1))
                .not_valid_after(now + dt.timedelta(days=30))
                .sign(key, hashes.SHA256()))
        self.key_pem = key.private_bytes(serialization.Encoding.PEM,
                                         serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()).decode()
        self.cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
        self.cert_b64 = "".join(self.cert_pem.strip().splitlines()[1:-1])

    def metadata_xml(self, slo: bool = False) -> str:
        logout = (f'<md:SingleLogoutService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect" '
                  f'Location="{self.slo_url}"/>') if slo else ""
        return f"""<?xml version="1.0"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" entityID="{self.entity_id}">
  <md:IDPSSODescriptor protocolSupportEnumeration="{SAMLP}">
    <md:KeyDescriptor use="signing">
      <ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
        <ds:X509Data><ds:X509Certificate>{self.cert_b64}</ds:X509Certificate></ds:X509Data>
      </ds:KeyInfo>
    </md:KeyDescriptor>
    {logout}
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
                            Location="{self.sso_url}"/>
  </md:IDPSSODescriptor>
</md:EntityDescriptor>"""

    @staticmethod
    def request_id_from_redirect(location: str) -> str:
        """The ID of the AuthnRequest carried in a redirect to the IdP."""
        raw = parse_qs(urlparse(location).query)["SAMLRequest"][0]
        xml = zlib.decompress(base64.b64decode(raw), -15).decode()
        from lxml import etree
        return etree.fromstring(xml.encode()).get("ID")

    def assertion(self, *, in_response_to: Optional[str], acs: str, audience: str,
                  name_id: str, attributes: Optional[Dict[str, List[str]]] = None,
                  minutes_valid: float = 5, offset_minutes: float = 0,
                  assertion_id: Optional[str] = None,
                  name_id_format: str = "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified") -> str:
        now = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=offset_minutes)
        later = now + dt.timedelta(minutes=minutes_valid)
        irt = f' InResponseTo="{in_response_to}"' if in_response_to else ""
        attrs = "".join(
            f'<saml:Attribute Name="{escape(k)}">' + "".join(
                f"<saml:AttributeValue>{escape(v)}</saml:AttributeValue>" for v in vals)
            + "</saml:Attribute>" for k, vals in (attributes or {}).items())
        statement = f"<saml:AttributeStatement>{attrs}</saml:AttributeStatement>" if attrs else ""
        return (
            f'<saml:Assertion xmlns:saml="{SAML}" ID="{assertion_id or "_a" + uuid.uuid4().hex}" '
            f'Version="2.0" IssueInstant="{_iso(now)}">'
            f"<saml:Issuer>{self.entity_id}</saml:Issuer>"
            f"<saml:Subject><saml:NameID Format=\"{name_id_format}\">"
            f"{escape(name_id)}</saml:NameID>"
            f'<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
            f'<saml:SubjectConfirmationData NotOnOrAfter="{_iso(later)}" Recipient="{acs}"{irt}/>'
            f"</saml:SubjectConfirmation></saml:Subject>"
            f'<saml:Conditions NotBefore="{_iso(now - dt.timedelta(minutes=1))}" '
            f'NotOnOrAfter="{_iso(later)}"><saml:AudienceRestriction>'
            f"<saml:Audience>{audience}</saml:Audience></saml:AudienceRestriction></saml:Conditions>"
            f'<saml:AuthnStatement AuthnInstant="{_iso(now)}" SessionIndex="_s{uuid.uuid4().hex}">'
            f"<saml:AuthnContext><saml:AuthnContextClassRef>"
            f"urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport"
            f"</saml:AuthnContextClassRef></saml:AuthnContext></saml:AuthnStatement>"
            f"{statement}</saml:Assertion>")

    def sign(self, assertion_xml: str) -> str:
        from onelogin.saml2.constants import OneLogin_Saml2_Constants as C
        from onelogin.saml2.utils import OneLogin_Saml2_Utils
        signed = OneLogin_Saml2_Utils.add_sign(
            assertion_xml, self.key_pem, self.cert_pem,
            sign_algorithm=C.RSA_SHA256, digest_algorithm=C.SHA256)
        return signed.decode() if isinstance(signed, bytes) else signed

    def response(self, assertion_xml: str, *, acs: str,
                 in_response_to: Optional[str], sign_response: bool = False) -> str:
        """A samlp:Response around an (already signed or not) assertion, base64.

        ``sign_response`` signs the Response element itself, as Shibboleth
        does by default, instead of (or as well as) the assertion."""
        if assertion_xml.startswith("<?xml"):
            assertion_xml = assertion_xml.split("?>", 1)[1]
        irt = f' InResponseTo="{in_response_to}"' if in_response_to else ""
        xml = (f'<samlp:Response xmlns:samlp="{SAMLP}" xmlns:saml="{SAML}" '
               f'ID="_r{uuid.uuid4().hex}" Version="2.0" '
               f'IssueInstant="{_iso(dt.datetime.now(dt.timezone.utc))}" '
               f'Destination="{acs}"{irt}>'
               f"<saml:Issuer>{self.entity_id}</saml:Issuer>"
               f'<samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/>'
               f"</samlp:Status>{assertion_xml}</samlp:Response>")
        if sign_response:
            xml = self.sign(xml)
        return base64.b64encode(xml.encode()).decode()


    # -- single logout (HTTP-Redirect binding) ----------------------------

    @staticmethod
    def message_from_redirect(location: str, kind: str = "SAMLRequest"):
        """(xml element, query params) of the message in a redirect to the IdP."""
        params = {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}
        xml = zlib.decompress(base64.b64decode(params[kind]), -15).decode()
        from lxml import etree
        return etree.fromstring(xml.encode()), params

    def _redirect_params(self, kind: str, xml: str, sign: bool, lowercase: bool = False) -> str:
        """The query string carrying ``xml``, signed as the binding specifies.

        ``lowercase`` percent-encodes as ADFS does (``%2f``, not ``%2F``)."""
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        from onelogin.saml2.constants import OneLogin_Saml2_Constants as C
        from onelogin.saml2.utils import OneLogin_Saml2_Utils as U

        def esc(value):
            return U.escape_url(value, lowercase_urlencoding=lowercase)
        query = f"{kind}={esc(U.deflate_and_base64_encode(xml))}"
        if sign:
            query += f"&SigAlg={esc(C.RSA_SHA256)}"
            key = serialization.load_pem_private_key(self.key_pem.encode(), password=None)
            signature = key.sign(query.encode(), padding.PKCS1v15(), hashes.SHA256())
            query += f"&Signature={esc(base64.b64encode(signature).decode())}"
        return query

    def logout_request(self, *, destination: str, name_id: str,
                       session_index: Optional[str] = None, sign: bool = True,
                       lowercase: bool = False,
                       name_id_format: str = "urn:oasis:names:tc:SAML:1.1:nameid-format:unspecified") -> str:
        """An IdP-initiated LogoutRequest, as a query string for the SP's /saml/sls."""
        now = dt.datetime.now(dt.timezone.utc)
        index = f"<samlp:SessionIndex>{session_index}</samlp:SessionIndex>" if session_index else ""
        xml = (f'<samlp:LogoutRequest xmlns:samlp="{SAMLP}" xmlns:saml="{SAML}" '
               f'ID="_l{uuid.uuid4().hex}" Version="2.0" IssueInstant="{_iso(now)}" '
               f'Destination="{destination}" NotOnOrAfter="{_iso(now + dt.timedelta(minutes=5))}">'
               f"<saml:Issuer>{self.entity_id}</saml:Issuer>"
               f'<saml:NameID Format="{name_id_format}">{escape(name_id)}</saml:NameID>'
               f"{index}</samlp:LogoutRequest>")
        return self._redirect_params("SAMLRequest", xml, sign, lowercase)

    def logout_response(self, *, destination: str, in_response_to: str, sign: bool = True,
                        status: str = "urn:oasis:names:tc:SAML:2.0:status:Success") -> str:
        """The IdP's answer to the SP's LogoutRequest, as a query string."""
        now = dt.datetime.now(dt.timezone.utc)
        xml = (f'<samlp:LogoutResponse xmlns:samlp="{SAMLP}" xmlns:saml="{SAML}" '
               f'ID="_lr{uuid.uuid4().hex}" Version="2.0" IssueInstant="{_iso(now)}" '
               f'Destination="{destination}" InResponseTo="{in_response_to}">'
               f"<saml:Issuer>{self.entity_id}</saml:Issuer>"
               f'<samlp:Status><samlp:StatusCode Value="{status}"/></samlp:Status>'
               f"</samlp:LogoutResponse>")
        return self._redirect_params("SAMLResponse", xml, sign)
