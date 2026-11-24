"""Authentication backends for Potato annotation platform.

Each backend needs an optional extra (``authlib`` for OAuth, python3-saml
for SAML). The backends load on first use, so importing one backend, or
this package, does not need the packages of the others.
"""

__all__ = ["OAuthBackend"]


def __getattr__(name):
    if name == "OAuthBackend":
        from potato.auth_backends.oauth_backend import OAuthBackend
        return OAuthBackend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
