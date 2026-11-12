"""type: external: config checks and the link it builds."""

import pytest

from potato.runtimes.adapters.external import ADAPTER
from potato.runtimes.phase import validate_runtime_entry
from potato.server_utils.config_module import ConfigValidationError

BASE = {"type": "prestudy", "_kind": "external", "url": "https://x.org/s?p={participant}"}


@pytest.mark.parametrize("extra,match", [
    ({"url": "http://x.org/"}, "https://"),
    ({"url": "https://x.org/?p={user}"}, "unknown placeholder"),
    ({"return_params": ["ok", "bad name"]}, "query parameter names"),
    ({"new_tab": "yes"}, "true or false"),
])
def test_refused(extra, match):
    with pytest.raises(ConfigValidationError, match=match):
        validate_runtime_entry("g", dict(BASE, **extra))


def test_localhost_http_allowed_and_link_is_encoded():
    validate_runtime_entry("g", dict(BASE, url="http://localhost:8001/?p={participant}"))
    spec = ADAPTER.spec_extras(dict(BASE, url="https://x.org/?p={participant}&b={return_url}&c={condition.arm}"))
    link = ADAPTER.link(spec, "a b&c", "r1", "https://me/runtime/g/return?run=r1", {"arm": "x y"})
    assert link == ("https://x.org/?p=a%20b%26c&b=https%3A%2F%2Fme%2Fruntime%2Fg%2Freturn%3Frun%3Dr1"
                    "&c=x%20y")


@pytest.mark.parametrize("url", [
    "http://localhost.evil.example/x", "http://127.0.0.1.evil.example/", "http://localhostevil.com",
    "http://evil.example/?localhost", "ftp://localhost/", "https:///nohost",
])
def test_http_only_for_this_machine_by_hostname(url):
    with pytest.raises(ConfigValidationError, match="https://"):
        validate_runtime_entry("g", dict(BASE, url=url))


@pytest.mark.parametrize("url", ["http://localhost/", "http://localhost:8001/x",
                                 "http://127.0.0.1:9/", "http://[::1]:8000/"])
def test_loopback_http_is_allowed(url):
    validate_runtime_entry("g", dict(BASE, url=url))


SECRET = "s3cret-shared-with-otree"


def test_return_secret_must_be_long_enough():
    with pytest.raises(ConfigValidationError, match="return_secret"):
        validate_runtime_entry("g", dict(BASE, return_secret="short"))


def test_a_value_cannot_sign_for_another_parameter():
    """Without encoding, {a: "1&b=2"} and {a: "1", b: "2"} gave the same
    message, so one signature passed for both."""
    from potato.runtimes.adapters.external import return_signature
    assert (return_signature(SECRET, "r1", {"a": "1&b=2"})
            != return_signature(SECRET, "r1", {"a": "1", "b": "2"}))


def test_signature_is_hmac_over_run_id_and_sorted_params():
    import hashlib
    import hmac
    from potato.runtimes.adapters.external import return_signature
    want = hmac.new(SECRET.encode(), b"r1&code=AB12&payoff=4.50", hashlib.sha256).hexdigest()
    assert return_signature(SECRET, "r1", {"payoff": "4.50", "code": "AB12"}) == want


def test_signed_returns_are_checked():
    from potato.runtimes.adapters.external import return_signature
    spec = ADAPTER.spec_extras(dict(BASE, return_params=["payoff", "code"], return_secret=SECRET))
    good = {"payoff": "4.50", "code": "AB12"}
    sig = return_signature(SECRET, "r1", good)
    assert ADAPTER.return_problem(spec, "r1", {**good, "sig": sig, "run": "r1"}) is None
    assert ADAPTER.return_problem(spec, "r1", {**good, "sig": sig.upper()}) is None
    assert "not signed" in ADAPTER.return_problem(spec, "r1", good)
    assert "does not match" in ADAPTER.return_problem(spec, "r1", {**good, "payoff": "99", "sig": sig})
    assert "does not match" in ADAPTER.return_problem(spec, "r2", {**good, "sig": sig})
    assert "does not match" in ADAPTER.return_problem(spec, "r1", {"payoff": "4.50", "sig": sig})
    # Without a secret nothing is checked: the parameters are self-reported.
    plain = ADAPTER.spec_extras(dict(BASE, return_params=["payoff"]))
    assert ADAPTER.return_problem(plain, "r1", {"payoff": "99"}) is None


def test_the_secret_is_not_sent_to_the_page():
    spec = ADAPTER.spec_extras(dict(BASE, return_secret=SECRET))
    assert SECRET not in repr(ADAPTER.client_extras(spec))
