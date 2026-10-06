"""Somewhere an image-only host can fetch the project from.

Render, Fly, Railway and ECS pull a published image and run it; there is no SSH
and nothing to upload into. The container entrypoint fetches the project as a
tarball from ``POTATO_BUNDLE_URL`` instead (see ``docker-entrypoint.sh``). This
module puts the tarball somewhere fetchable and returns the variables that
point at it.

The store is the backup sink's own storage, so a deployment that backs up to a
HuggingFace Dataset or an S3 bucket needs no second account:

* HuggingFace: ``_bundle/<sha>.tar.gz`` in the backup dataset, fetched with the
  token as a bearer header. Never expires.
* S3: a presigned GET URL. It expires (seven days at most), which matters only
  on a host with no disk, where every restart fetches again; ``plan()`` warns.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Dict, Optional

from potato.deploy.backup_options import BackupOptions
from potato.server_utils.backup import REMOTE_BUNDLE_DIR

#: SigV4 presigned URLs cannot outlive this.
S3_MAX_EXPIRY_SECONDS = 7 * 24 * 3600


class BundleStoreError(RuntimeError):
    pass


@dataclass
class BundleLocation:
    url: str
    sha256: str
    token: Optional[str] = None
    expires_seconds: Optional[int] = None

    def env(self) -> Dict[str, str]:
        env = {"POTATO_BUNDLE_URL": self.url, "POTATO_BUNDLE_SHA256": self.sha256}
        if self.token:
            env["POTATO_BUNDLE_TOKEN"] = self.token
        return env


def file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class HuggingFaceBundleStore:
    kind = "hf"

    def __init__(self, repo_id: str, token: str):
        self.repo_id = repo_id
        self.token = token

    def describe(self) -> str:
        return f"HuggingFace dataset {self.repo_id} ({REMOTE_BUNDLE_DIR}/)"

    def url_for(self, sha: str) -> str:
        return (f"https://huggingface.co/datasets/{self.repo_id}/resolve/main/"
                f"{REMOTE_BUNDLE_DIR}/{sha}.tar.gz")

    def put(self, tarball: str, sha: str) -> BundleLocation:
        from potato.deploy.providers.huggingface import _hf_api

        api = _hf_api(self.token)
        api.create_repo(self.repo_id, repo_type="dataset", private=True,
                        exist_ok=True)
        api.upload_file(path_or_fileobj=tarball,
                        path_in_repo=f"{REMOTE_BUNDLE_DIR}/{sha}.tar.gz",
                        repo_id=self.repo_id, repo_type="dataset",
                        commit_message=f"Deploy bundle {sha[:12]}")
        return BundleLocation(url=self.url_for(sha), sha256=sha, token=self.token)


class S3BundleStore:
    kind = "s3"

    def __init__(self, bucket: str, prefix: str = "", region: Optional[str] = None,
                 endpoint_url: Optional[str] = None,
                 expires_seconds: int = S3_MAX_EXPIRY_SECONDS):
        self.bucket = bucket
        self.prefix = (prefix or "").strip("/")
        self.region = region
        self.endpoint_url = endpoint_url
        self.expires_seconds = min(expires_seconds, S3_MAX_EXPIRY_SECONDS)

    def describe(self) -> str:
        return f"s3://{self.bucket}/{self.key_for('<sha>')}"

    def key_for(self, sha: str) -> str:
        return "/".join(p for p in (self.prefix, REMOTE_BUNDLE_DIR, f"{sha}.tar.gz") if p)

    def client(self):
        try:
            import boto3
        except ImportError as exc:
            raise BundleStoreError(
                "Storing the bundle in S3 needs boto3: "
                "pip install 'potato-annotation[deploy-aws]'") from exc
        kwargs = {}
        if self.region:
            kwargs["region_name"] = self.region
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        return boto3.client("s3", **kwargs)

    def put(self, tarball: str, sha: str) -> BundleLocation:
        client = self.client()
        key = self.key_for(sha)
        client.upload_file(tarball, self.bucket, key)
        url = client.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=self.expires_seconds)
        return BundleLocation(url=url, sha256=sha,
                              expires_seconds=self.expires_seconds)


def store_for(options: BackupOptions):
    """The store a deployment's backup already provides, HF preferred.

    HF wins because its URL never expires; a host with no disk re-fetches on
    every restart.
    """
    if "hf" in options.kinds and options.hf_repo and options.hf_token:
        return HuggingFaceBundleStore(options.hf_repo, options.hf_token)
    if "s3" in options.kinds and options.s3_bucket:
        return S3BundleStore(options.s3_bucket, options.s3_prefix or "",
                             options.s3_region, options.s3_endpoint)
    return None


def publish(manifest, store, workdir: str) -> BundleLocation:
    """Pack the bundle deterministically, upload it, return where it went."""
    from potato.deploy.bundle import bundle_tarball

    os.makedirs(workdir, exist_ok=True)
    tarball = bundle_tarball(manifest, os.path.join(workdir, "bundle.tar.gz"))
    return store.put(tarball, file_sha256(tarball))
