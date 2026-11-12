"""boto3 plumbing shared by the AWS providers.

boto3 is optional (``pip install 'potato-annotation[deploy-aws]'``) and imported
only when a provider actually talks to AWS, so listing providers or planning a
deploy never needs it.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from potato.deploy.providers.base import ProviderError

INSTALL_HINT = "pip install 'potato-annotation[deploy-aws]'"


def boto3_session(profile: Optional[str] = None, region: Optional[str] = None):
    try:
        import boto3
    except ImportError as exc:
        raise ProviderError(f"The AWS providers need boto3. Install with: {INSTALL_HINT}") from exc
    try:
        return boto3.Session(profile_name=profile or None, region_name=region or None)
    except Exception as exc:  # botocore.exceptions.ProfileNotFound and friends
        raise ProviderError(f"Could not load AWS credentials: {exc}") from exc


def error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None) or {}
    return str((response.get("Error") or {}).get("Code") or "")


def is_not_found(exc: Exception) -> bool:
    code = error_code(exc)
    return code in ("NotFoundException", "ResourceNotFoundException",
                    "InvalidInstanceID.NotFound", "InvalidAllocationID.NotFound",
                    "InvalidVolume.NotFound", "InvalidGroup.NotFound",
                    "ClusterNotFoundException", "ServiceNotFoundException",
                    "FileSystemNotFound", "NoSuchEntity", "NoSuchBucket")


class AWSClient:
    """A boto3 client whose errors arrive as ProviderError with the AWS message.

    ``call`` is the only way the providers reach AWS, which makes it the one
    seam tests stub.
    """

    def __init__(self, service: str, *, region: Optional[str] = None,
                 profile: Optional[str] = None, client: Any = None):
        self.service = service
        self.region = region
        self._client = client if client is not None else \
            boto3_session(profile, region).client(service)

    def call(self, method: str, **kwargs) -> Any:
        try:
            return getattr(self._client, method)(**kwargs)
        except ProviderError:
            raise
        except Exception as exc:
            if error_code(exc) in ("UnrecognizedClientException", "InvalidClientTokenId",
                                   "ExpiredToken", "ExpiredTokenException",
                                   "AuthFailure"):
                raise ProviderError(
                    f"AWS rejected the credentials ({error_code(exc)}). Run "
                    "`aws sso login` or `aws configure`, or set AWS_PROFILE.") from exc
            if error_code(exc) in ("AccessDeniedException", "AccessDenied",
                                   "UnauthorizedOperation"):
                raise ProviderError(
                    f"AWS denied {self.service}:{method}: {exc}\n"
                    "The credentials need the permissions listed in "
                    "docs/deployment/deploy-aws.md.") from exc
            raise ProviderError(f"AWS {self.service}.{method} failed: {exc}") from exc

    def raw(self):
        return self._client


def caller_identity(profile: Optional[str] = None,
                    region: Optional[str] = None) -> str:
    """``arn (account N)`` for whatever credentials boto3 resolves."""
    sts = AWSClient("sts", region=region or "us-east-1", profile=profile)
    identity = sts.call("get_caller_identity")
    return f"{identity.get('Arn')} (account {identity.get('Account')})"


def wait_until(predicate: Callable[[], bool], *, timeout: int, interval: int = 5,
               sleep: Optional[Callable[[float], None]] = None) -> bool:
    import time

    sleep = sleep or time.sleep
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        sleep(interval)
    return False
