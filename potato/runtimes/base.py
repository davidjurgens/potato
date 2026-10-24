"""
What a runtime adapter tells the shared runtime-phase layer.

A runtime phase page (``type: jspsych``, ``type: osweb``, ...) runs a study
written for another experiment runtime inside a Potato phase. The shared
layer (``potato.runtimes.phase`` / ``routes`` / ``store``) owns the page, the
CSP, the run record, the gate that stops a participant skipping the task, the
data routes and the export. An adapter owns only what differs between
runtimes:

* which config key names the author's study file, and what other keys exist;
* which runtime files to load, committed (``static/...``) or fetched
  (``potato vendor fetch``);
* the boot script that starts the runtime and hands its data to
  ``window.potatoRuntime`` (``static/runtime-bridge.js``);
* any CSP relaxation the runtime cannot work without, stated in its docs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, FrozenSet, List, Optional, Tuple


@dataclass(frozen=True)
class Asset:
    """One file the page loads before the study.

    ``source`` is ``"static"`` (a path under ``potato/static/``) or the name of
    a fetchable bundle (``potato.vendoring``), with ``path`` inside it.
    """
    source: str
    path: str
    module: bool = False


class RuntimeAdapter:
    #: The phase ``type`` value.
    kind: str = ""
    #: Human name, for messages and docs.
    label: str = ""
    #: The config key that names the author's study file, or None for a
    #: built-in task that has none (the headphone check).
    main_key: Optional[str] = "timeline"
    #: Extensions the study file may have.
    main_extensions: Tuple[str, ...] = (".js",)
    #: The study file is loaded as ``<script type="module">``.
    main_is_module: bool = False
    #: The study file is data the boot script fetches, not a script the page
    #: loads (an ``.osexp``, a lab.js JSON, an ``.h5p`` directory, ...).
    main_is_data: bool = False
    #: The study is a directory (an unzipped export) rather than one file;
    #: its files are served from the main route as ``main/<path>``.
    main_is_dir: bool = False
    #: Extensions served from a directory study.
    dir_extensions: FrozenSet[str] = frozenset()
    #: Mimetype the main route serves a single-file study with.
    main_mimetype: str = "text/javascript"
    #: Config keys this runtime adds to the shared ones.
    extra_keys: FrozenSet[str] = frozenset()
    #: Static path of the boot script.
    boot_script: str = ""
    #: Extra extensions the asset route serves for this runtime (on top of
    #: the shared media list), e.g. ``.osexp`` or ``.xlsx`` conditions files.
    extra_asset_extensions: FrozenSet[str] = frozenset()
    #: Extra CSP sources this runtime needs, by directive. Every relaxation is
    #: documented on the runtime's docs page.
    csp_additions: Dict[str, Tuple[str, ...]] = {}

    def csp_for(self, spec: Dict[str, Any]) -> Dict[str, Tuple[str, ...]]:
        """CSP additions for one page (default: ``csp_additions``)."""
        return dict(self.csp_additions)

    def validate(self, where: str, entry: Dict[str, Any]) -> None:
        """Raise ConfigValidationError for a bad runtime-specific key."""

    def spec_extras(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        """Runtime-specific values kept in the page spec at boot."""
        return {}

    def assets(self, spec: Dict[str, Any]) -> Tuple[List[Asset], List[Asset]]:
        """(stylesheets, scripts) to load, in order, before the boot script."""
        return [], []

    def required_bundles(self, entry: Dict[str, Any]) -> List[str]:
        """Fetchable bundles this page needs installed."""
        return []

    def entry_file(self, spec: Dict[str, Any]) -> Optional[str]:
        """For a directory study, the file inside it the page loads (a module
        or script), or None when the boot script fetches what it needs."""
        return None

    def normalize(self, name: str, entry: Dict[str, Any]) -> None:
        """Adjust a raw phase entry before validation (fill in defaults,
        derive an ``exit_when``)."""

    def answer_schemes(self, name: str, entry: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Pseudo-questions this page answers, so page rules may test them
        (``headphones_passed``). Validation treats them as asked on the page."""
        return []

    def stimulus(self, spec: Dict[str, Any], user_state, index: int) -> Optional[bytes]:
        """A WAV the server makes for trial ``index`` of the current run, or
        None (the route then answers 404). For a task whose answer the browser
        must not know (the headphone check): the server picks the answer and
        keeps it in the participant's state."""
        return None

    def finalize_trials(self, spec: Dict[str, Any], trials: List[Dict[str, Any]],
                        user_state) -> List[Dict[str, Any]]:
        """The finished run's trials as stored and summarized. The default
        keeps what the browser sent; the headphone check replaces the
        browser's target and correctness with its own record."""
        return trials

    def summarize(self, spec: Dict[str, Any], trials: List[Dict[str, Any]]) -> Dict[str, Any]:
        """``{question: value}`` derived from a finished run, stored on the
        flow record and visible to ``show_when`` / ``exit_when``."""
        return {}

    def client_extras(self, spec: Dict[str, Any]) -> Dict[str, Any]:
        """Runtime-specific values for the page's JSON config block."""
        return {}
