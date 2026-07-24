"""Publishing targets: turn a :class:`PublishBundle` into a shareable artifact.

Three targets, all consuming the same bundle:

- :func:`write_archive` — a self-contained ``.zip``/``.tar.gz`` (data splits, README,
  LICENSE, metadata, the Paper Mode LaTeX report, and any media). No account needed;
  also the payload uploaded to Zenodo.
- :func:`push_to_huggingface` — push the splits + card to the Hub as a Dataset.
- :func:`deposit_to_zenodo` — create a Zenodo deposition from the archive and return
  a DOI.

External SDKs are imported lazily so the core install never needs them.
"""

import json
import logging
import os
import shutil
import tempfile
from typing import Any, Dict, List, Optional

from potato.publish.bundle import PublishBundle, write_split

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------- metadata --


def zenodo_metadata(bundle: PublishBundle) -> Dict[str, Any]:
    """Build a ``.zenodo.json`` metadata mapping from the bundle's metadata."""
    md = bundle.metadata
    creators = []
    for a in md.authors:
        creator: Dict[str, Any] = {"name": a.name or "Unknown"}
        if a.affiliation:
            creator["affiliation"] = a.affiliation
        if a.orcid:
            creator["orcid"] = a.orcid
        creators.append(creator)
    if not creators:
        creators = [{"name": "Unknown"}]

    meta: Dict[str, Any] = {
        "title": md.pretty_name or "Potato Annotation Dataset",
        "upload_type": "dataset",
        "description": (md.description
                        or "Annotations exported from the Potato annotation tool."),
        "creators": creators,
        "version": md.version,
    }
    if md.keywords:
        meta["keywords"] = md.keywords
    if md.license:
        # Zenodo expects an Open Definition license id; SPDX ids mostly line up.
        meta["license"] = md.license
    related = [{"identifier": link, "relation": "isSupplementTo",
               "scheme": "url"} for link in md.related_links]
    if related:
        meta["related_identifiers"] = related
    return {"metadata": meta}


def _license_text(license_id: str) -> str:
    if not license_id:
        return ("No license specified. Add one before redistributing this "
                "dataset (e.g. CC-BY-4.0).\n")
    return (f"This dataset is released under the {license_id} license.\n\n"
            f"See https://spdx.org/licenses/ for the full license text "
            f"corresponding to the identifier '{license_id}'.\n")


# ----------------------------------------------------------------- archive --


def stage_bundle(bundle: PublishBundle, staging_dir: str,
                 data_format: str = "jsonl") -> List[str]:
    """Write all bundle artifacts into ``staging_dir``. Returns file paths."""
    os.makedirs(staging_dir, exist_ok=True)
    written: List[str] = []

    data_dir = os.path.join(staging_dir, "data")
    os.makedirs(data_dir, exist_ok=True)
    for name, rows in bundle.splits.items():
        written.append(write_split(rows, os.path.join(data_dir, name), data_format))

    # README / dataset card
    readme = os.path.join(staging_dir, "README.md")
    with open(readme, "w", encoding="utf-8") as f:
        f.write(bundle.card_markdown or "")
    written.append(readme)

    # LICENSE
    license_path = os.path.join(staging_dir, "LICENSE")
    with open(license_path, "w", encoding="utf-8") as f:
        f.write(_license_text(getattr(bundle.metadata, "license", "")))
    written.append(license_path)

    # machine-readable metadata
    zen = os.path.join(staging_dir, ".zenodo.json")
    with open(zen, "w", encoding="utf-8") as f:
        json.dump(zenodo_metadata(bundle), f, indent=2, ensure_ascii=False)
    written.append(zen)

    # Paper Mode LaTeX report (paper.tex/paper.bib/tables/*.csv/summary.json)
    if bundle.stats and bundle.stats.get("schemes") is not None:
        try:
            from potato.paper.latex import render_report
            report_dir = os.path.join(staging_dir, "paper_report")
            render_report(bundle.stats, report_dir)
            written.append(report_dir)
        except Exception as e:                     # report is a bonus, never fatal
            logger.warning("Could not render Paper Mode report into archive: %s", e)
            bundle.warnings.append(f"Paper report omitted from archive: {e}")

    # media
    if bundle.media_files:
        media_dir = os.path.join(staging_dir, "media")
        os.makedirs(media_dir, exist_ok=True)
        for src in bundle.media_files:
            try:
                shutil.copy2(src, os.path.join(media_dir, os.path.basename(src)))
            except OSError as e:
                logger.warning("Could not copy media %s: %s", src, e)
    return written


def write_archive(bundle: PublishBundle, output_path: str,
                  archive_format: str = "zip",
                  data_format: str = "jsonl") -> str:
    """Package the bundle into a single archive file. Returns its path.

    ``output_path`` is the archive path *without* extension (the extension is added
    from ``archive_format``: ``zip`` or ``gztar``).
    """
    archive_format = "gztar" if archive_format in ("tar.gz", "gztar", "tgz") \
        else "zip"
    with tempfile.TemporaryDirectory() as tmp:
        root_name = os.path.basename(output_path) or "dataset"
        staging = os.path.join(tmp, root_name)
        stage_bundle(bundle, staging, data_format)
        base = shutil.make_archive(output_path, archive_format,
                                   root_dir=tmp, base_dir=root_name)
    return base


# ------------------------------------------------------------ huggingface --


def push_to_huggingface(bundle: PublishBundle, repo_id: str,
                        token: Optional[str] = None,
                        private: bool = False,
                        commit_message: str = "Publish dataset from Potato"
                        ) -> Dict[str, Any]:
    """Push the bundle's splits and card to the HuggingFace Hub as a Dataset."""
    if not repo_id or "/" not in repo_id:
        raise ValueError("repo_id must look like 'org/dataset-name'")
    try:
        from datasets import Dataset, DatasetDict
        from huggingface_hub import DatasetCard
    except ImportError as e:
        raise ImportError(
            "HuggingFace publishing needs: pip install "
            "huggingface_hub>=0.20.0 datasets>=2.14.0") from e

    token = token or os.environ.get("HF_TOKEN")
    dd = DatasetDict({name: Dataset.from_list(rows)
                      for name, rows in bundle.splits.items() if rows})
    dd.push_to_hub(repo_id, token=token, private=private,
                   commit_message=commit_message)

    warnings: List[str] = []
    try:
        DatasetCard(bundle.card_markdown).push_to_hub(repo_id, token=token)
    except Exception as e:                          # card is non-fatal
        warnings.append(f"Dataset card push failed: {e}")
        logger.warning("Dataset card push failed: %s", e)

    return {
        "repo_id": repo_id,
        "url": f"https://huggingface.co/datasets/{repo_id}",
        "splits": {n: len(r) for n, r in bundle.splits.items()},
        "private": private,
        "warnings": warnings,
    }


# ---------------------------------------------------------------- zenodo --


def deposit_to_zenodo(bundle: PublishBundle, token: Optional[str] = None,
                      sandbox: bool = True, publish: bool = False,
                      archive_dir: Optional[str] = None) -> Dict[str, Any]:
    """Create a Zenodo deposition from the bundle's archive and set its metadata.

    By default targets the Zenodo *sandbox* and leaves the deposition as an
    unpublished draft (``publish=False``) so nothing is minted accidentally. When
    ``publish=True`` the deposition is published and a DOI returned.
    """
    import requests   # part of the core install

    token = token or os.environ.get("ZENODO_TOKEN")
    if not token:
        raise ValueError("A Zenodo token is required (ZENODO_TOKEN or the "
                         "'token' option).")
    base = "https://sandbox.zenodo.org" if sandbox else "https://zenodo.org"
    api = f"{base}/api/deposit/depositions"
    auth = {"params": {"access_token": token}}

    # 1. create an empty deposition
    r = requests.post(api, json={}, timeout=60, **auth)
    r.raise_for_status()
    dep = r.json()
    dep_id = dep["id"]
    bucket = dep["links"]["bucket"]

    # 2. build and upload the archive
    workdir = archive_dir or tempfile.mkdtemp(prefix="zenodo_")
    archive_base = os.path.join(workdir, (bundle.metadata.pretty_name or "dataset")
                                .replace("/", "_").replace(" ", "_") or "dataset")
    archive_path = write_archive(bundle, archive_base, "zip",
                                 data_format=str(
                                     bundle.config.get("__data_format__", "jsonl")))
    fname = os.path.basename(archive_path)
    with open(archive_path, "rb") as fp:
        up = requests.put(f"{bucket}/{fname}", data=fp, timeout=600, **auth)
    up.raise_for_status()

    # 3. attach metadata
    meta = requests.put(f"{api}/{dep_id}", json=zenodo_metadata(bundle),
                        timeout=60, **auth)
    meta.raise_for_status()

    result: Dict[str, Any] = {
        "deposition_id": dep_id,
        "sandbox": sandbox,
        "draft_url": dep["links"].get("html", ""),
        "published": False,
    }

    # 4. optionally publish → DOI
    if publish:
        pub = requests.post(f"{api}/{dep_id}/actions/publish", timeout=120, **auth)
        pub.raise_for_status()
        published = pub.json()
        result["published"] = True
        result["doi"] = published.get("doi", "")
        result["url"] = published.get("links", {}).get("html", "")
    else:
        result["doi"] = dep.get("metadata", {}).get("prereserve_doi", {}).get("doi", "")
    return result
