"""What Potato is running, in enough detail to identify a build.

``potato --version`` is the first thing anyone runs to check an install, and
until this existed it exited 2 with an argparse usage block, because ``mode``
and ``config_file`` are both required positionals. It read as a broken install
rather than a missing flag, and `potato --version || pip install
potato-annotation` — a real line in real documentation — always took the
install branch, dropping a released wheel on top of an editable checkout.

A version number alone is not enough to identify a build. ``2.8.2`` has covered
hundreds of commits, and the people who most need to report a version are
running from a checkout somewhere in between two releases. So an editable or
in-tree install also reports its commit.

Two version numbers exist and they can disagree. ``potato.__version__`` is what
the source in front of you says; ``importlib.metadata`` is what the installed
distribution's metadata says, and that metadata is only rewritten on install.
An editable checkout that has moved on since ``pip install -e .`` reports the
older number forever, which is the same trap as a non-editable install
shadowing your edits — silent, and expensive to work out from the symptoms. So
when they disagree, both are printed and the disagreement is named.

Nothing here imports the server, and the git calls only run when there is a
``.git`` directory to run them in.
"""

import json
import os
import re
import subprocess
from typing import Optional

#: The name on PyPI. Not the import name, which is ``potato``.
DISTRIBUTION = "potato-annotation"

_GIT_TIMEOUT_S = 5


#: Fallback reader for `__version__`, used when the package cannot be imported.
_VERSION_RE = re.compile(r"""^__version__\s*=\s*['"]([^'"]+)['"]""", re.M)

#: What to say when neither route works. A wrong number would be worse than an
#: honest gap in a bug report.
UNKNOWN_VERSION = "unknown"


def source_version() -> str:
    """The version the source tree declares.

    Two routes, because the import route fails in more situations than it
    looks like it should, and on some machines it is the one that never runs:

    * `python potato/flask_server.py` puts `potato/` itself on sys.path, so
      `potato` resolves to a namespace package with no `__init__.py` and the
      import raises. That is how CLAUDE.md says to run from source.
    * A leftover `site-packages/potato/` directory with no `__init__.py` does
      the same thing from every other directory, permanently, while every
      SUBMODULE still imports fine through the editable finder. So
      `potato.version_info` loads from the checkout in the same shell where
      `potato.__version__` does not exist.

    Reading the file next to this one works in both, and `version_from_init_file`
    is public so a test can check the two routes still agree.
    """
    try:
        from potato import __version__
        return __version__
    except Exception:
        return version_from_init_file()


def version_from_init_file() -> str:
    """`__version__` read out of `potato/__init__.py` beside this module.

    Split out so a test can compare it against the import route. Only one of
    the two runs at a time, so nothing else would notice them diverging -- a
    computed `__version__`, or a quoting change the regex stops matching, would
    silently turn this into ``unknown`` on exactly the machines that need it.
    """
    init = os.path.join(os.path.dirname(os.path.abspath(__file__)), "__init__.py")
    try:
        with open(init, "r", encoding="utf-8") as fh:
            match = _VERSION_RE.search(fh.read())
    except OSError:
        return UNKNOWN_VERSION
    return match.group(1) if match else UNKNOWN_VERSION


def installed_distributions() -> list:
    """Every visible ``potato-annotation``, as ``{version, location}``.

    Deliberately a list. More than one can be visible at a time -- a working
    checkout on ``sys.path`` in front of a released wheel in site-packages is
    the ordinary way to end up there -- and then the answer to "what version is
    this" depends on the directory you asked from. That is the shape of a whole
    class of confusing bug reports, so it is reported rather than resolved
    silently.

    First in the list is the one that wins, because that is the order
    ``sys.path`` is searched in.

    Raises rather than returning ``[]`` when the scan itself fails. An empty
    list is a real answer -- "running from a source tree, nothing installed" --
    and the report says exactly that, so returning it for an unreadable
    metadata directory printed a definite conclusion on no evidence.
    ``version_report`` catches and says the read failed instead.
    """
    from importlib.metadata import distributions

    found = []
    for dist in distributions():
        try:
            name = (dist.metadata["Name"] or "").strip().lower()
        except Exception:
            # One unreadable sibling distribution says nothing about whether
            # Potato is installed, so skip it rather than abandoning the scan.
            continue
        if name.replace("_", "-") != DISTRIBUTION:
            continue
        location = getattr(dist, "_path", None)
        found.append({
            "version": dist.version,
            "location": str(location) if location else None,
        })
    return found


def distribution_version() -> Optional[str]:
    """The version the winning installed distribution declares, if any."""
    found = installed_distributions()
    return found[0]["version"] if found else None


def _direct_url() -> Optional[dict]:
    """The PEP 610 record pip writes for a non-index install."""
    try:
        from importlib.metadata import distribution
        dist = distribution(DISTRIBUTION)
        text = dist.read_text("direct_url.json")
    except Exception:
        return None
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def is_editable() -> Optional[bool]:
    """Whether this install points back at a working checkout.

    None when there is no PEP 610 record to read -- an install from an index
    has none, and so does an unreadable one. False would claim the install was
    checked and found not to be editable.
    """
    record = _direct_url()
    if record is None:
        return None
    return bool((record.get("dir_info") or {}).get("editable"))


def shadowing_namespace_dirs() -> list:
    """Directories making `potato` resolve as a namespace package, if any.

    A leftover directory called `potato` with no `__init__.py` -- the usual
    residue of an earlier non-editable install -- makes the top-level name
    resolve to a namespace package. `potato.__file__` is then None and
    `potato.__version__` does not exist, while every SUBMODULE still imports
    correctly through the editable finder. So `import potato.version_info`
    works in the same shell where `potato.__version__` raises, which reads as
    a broken package rather than a stray directory.

    Reported rather than removed: deleting things out of site-packages is not
    something a `--version` flag should do.
    """
    # Deliberately not guarded: `potato` failing to import is not the same
    # fact as "there is no shadowing directory", and this module is itself a
    # potato submodule, so the import cannot realistically fail here anyway.
    import potato

    return namespace_shadows(getattr(potato, "__file__", None),
                             getattr(potato, "__path__", []))


def namespace_shadows(module_file, search_paths) -> list:
    """The decision behind `shadowing_namespace_dirs`, over plain inputs.

    Separate so both arms can be driven. Against the real `potato` only one arm
    is reachable per machine, and a regular package's `__path__` always
    contains its own `__init__.py` -- so a test calling the real thing cannot
    tell a working `module_file` check from a missing one, and a mutation that
    removed it survived.
    """
    if module_file:
        return []
    return [os.path.abspath(path) for path in search_paths
            if not os.path.isfile(os.path.join(path, "__init__.py"))]


def repo_root() -> Optional[str]:
    """The git work tree the package lives in, if it lives in one."""
    path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return path if os.path.isdir(os.path.join(path, ".git")) else None


def _git(root: str, *args: str) -> Optional[str]:
    """The command's output, or None if the command did not run.

    ``""`` means it ran and said nothing, which is a real answer -- a clean
    tree is what `git status --porcelain` says nothing about. Collapsing the
    two into None made `dirty` read False whenever git was missing or the
    directory was not a repository, so a report could state "no uncommitted
    changes" having never looked.
    """
    try:
        out = subprocess.run(
            ("git", "-C", root) + args,
            capture_output=True, text=True, timeout=_GIT_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def commit_info() -> Optional[dict]:
    """``{commit, branch, dirty, root}`` for an in-tree install.

    Returns None only when there is no git work tree to ask -- an ordinary
    installed copy. When there IS one and git will not answer, the result
    carries ``error`` instead of a commit, because "no commit shown" would
    otherwise mean either "not a checkout" or "git broke", and those send a
    reader to opposite conclusions about the build they are looking at.

    ``dirty`` is None when the working-tree status could not be read. False
    means git was asked and said the tree was clean.
    """
    root = repo_root()
    if not root:
        return None
    commit = _git(root, "rev-parse", "--short", "HEAD")
    if not commit:
        return {"root": root, "commit": None, "branch": None, "dirty": None,
                "error": f"git could not name the commit in {root}"}
    status = _git(root, "status", "--porcelain")
    return {
        "commit": commit,
        "branch": _git(root, "rev-parse", "--abbrev-ref", "HEAD") or None,
        # "" is a clean tree; None is git declining to say.
        "dirty": None if status is None else bool(status),
        "root": root,
    }


def version_report() -> str:
    """The text ``potato --version`` prints.

    One line for the normal case, plus a line for each thing that would
    otherwise have to be worked out from symptoms: which commit, and whether
    the two version numbers disagree.
    """
    source = source_version()
    lines = []

    detail = []
    # `is_editable()` has three states and only one of them belongs on this
    # line. None means there was no record to read, which is not the same as
    # "not editable" and is not worth a word.
    if is_editable() is True:
        detail.append("editable install")

    info = commit_info()
    if info and info.get("error"):
        # There IS a work tree and git would not answer. Silence here would
        # read exactly like an ordinary installed copy, which is the opposite
        # conclusion about what someone is running.
        detail.append(f"in a checkout, but {info['error']}")
    elif info:
        detail.append(f"commit {info['commit']}")
        if info["branch"] and info["branch"] != "HEAD":
            detail.append(f"branch {info['branch']}")
        if info["dirty"] is None:
            detail.append("working-tree status unreadable")
        elif info["dirty"]:
            detail.append("uncommitted changes")

    lines.append(f"potato {source}"
                 + (f" ({', '.join(detail)})" if detail else ""))

    shadows = shadowing_namespace_dirs()
    if shadows:
        lines.append(
            "  `potato` resolves as a namespace package here, so "
            "`potato.__version__` does not exist and the version above was "
            "read from the file instead. Submodules still import correctly, "
            "which is what makes this hard to see. Directories responsible:")
        lines.extend(f"    {path}" for path in shadows)

    # --version is what someone runs when the install is already suspect, so a
    # metadata read that throws must not be the thing that takes it down. The
    # version and commit above are already on the line.
    try:
        found = installed_distributions()
    except Exception as exc:
        lines.append(f"  could not read installed distribution metadata: {exc}")
        return "\n".join(lines)

    if not found:
        # Reached only when the scan SUCCEEDED and found nothing. The failure
        # path is the except above, because this sentence tells the reader
        # something definite and it must not be printed on no evidence.
        lines.append(
            f"  {DISTRIBUTION} is not installed as a distribution; this is "
            f"running from the source tree.")
    elif len(found) > 1:
        lines.append(
            f"  {len(found)} installed copies of {DISTRIBUTION} are visible, "
            f"so which one answers depends on the directory you run from:")
        for i, dist in enumerate(found):
            mark = "  <- wins here" if i == 0 else ""
            lines.append(f"    {dist['version']}  {dist['location'] or '?'}{mark}")
        lines.append(
            "  Remove the one you did not mean to have. A checkout shadowed by "
            "a released wheel runs the wheel from any other directory, which "
            "is the same edit-has-no-effect symptom as a non-editable install.")
    elif found[0]["version"] != source:
        # Deliberately does not say which of the two is the stale one. The
        # usual case is metadata left behind by an install the checkout has
        # since moved past, but checking out an older commit leaves the
        # metadata AHEAD, and this line cannot tell the difference. Naming the
        # wrong one would send someone to reinstall when they should be
        # checking out.
        lines.append(
            f"  the installed {DISTRIBUTION} metadata says "
            f"{found[0]['version']}, which does not match. The source above is "
            f"what is running; metadata is only rewritten on install, so the "
            f"two drift apart whenever the checkout moves without one. "
            f"`pip install -e .` brings them back into line.")

    return "\n".join(lines)
