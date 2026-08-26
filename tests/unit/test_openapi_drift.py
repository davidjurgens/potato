"""
Drift guards for the generated OpenAPI spec.

`docs/api-reference/openapi.json` is the authoritative index of Potato's HTTP
surface. It exists because the hand-written reference could not keep up:
`docs/api-reference/api_reference.md` describes roughly 84 endpoints against
400+ registered rules, and the gap widened with every release. Generating the
index removes the maintenance burden — but only if something fails when routes
move and the checked-in artifact does not.

Two things this guards that are easy to get wrong:

1. **Config-gated blueprints.** Most of the agent-evaluation surface (datasets,
   arena, automation, curation, corpus map, the live-agent families) is only
   registered when a config flag or display type is present. `create_app()` alone
   therefore sees a fraction of the API. `OPTIONAL_BLUEPRINTS` names the rest, and
   a rename that breaks one of those imports would otherwise silently shrink the
   published spec rather than fail.

2. **Duplicate operation ids.** Flask lets one endpoint serve several rules, which
   emits the same `operationId` twice and makes the document invalid OpenAPI —
   caught only by a real validator, not by eyeballing the JSON.
"""

import importlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "docs" / "api-reference" / "openapi.json"
GENERATOR = REPO_ROOT / "scripts" / "generate_openapi.py"

REGENERATE = "Regenerate with: python scripts/generate_openapi.py"


@pytest.fixture(scope="module")
def checked_in():
    assert SPEC_PATH.exists(), f"{SPEC_PATH} is missing. {REGENERATE}"
    return json.loads(SPEC_PATH.read_text(encoding="utf-8"))


def _operations(spec):
    return [
        (path, method, operation)
        for path, item in spec["paths"].items()
        for method, operation in item.items()
    ]


class TestArtifactIsCurrent:
    """
    Checked in a subprocess, deliberately.

    `create_app()` is not idempotent within a single process: the route
    decorators in `routes.py` bind to the module-global `app` at import time, so
    only the *first* app built in a process sees them, while every later one sees
    just the routes `configure_routes()` adds via `add_url_rule`. `/logout` is the
    visible case — three rules on the first build, one on the second.

    Generation therefore only means anything from a clean interpreter, which is
    how `scripts/generate_openapi.py` actually runs. Building the spec inline
    here would compare against whatever state earlier tests left behind.
    """

    @pytest.mark.timeout(180)
    def test_spec_matches_the_live_app(self):
        result = subprocess.run(
            [sys.executable, str(GENERATOR), "--check"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"The checked-in OpenAPI spec no longer matches the Flask url_map.\n"
            f"{result.stdout}{result.stderr}"
        )

    @pytest.mark.timeout(180)
    def test_generation_is_deterministic(self, tmp_path):
        """
        A generator whose output depended on iteration order would make the
        staleness check above fail at random and train people to ignore it.
        """
        def build():
            script = (
                "import json;"
                "from potato.server_utils.openapi_spec import build_openapi_spec;"
                "s=build_openapi_spec(); s['info']['version']='-';"
                "print(json.dumps(s, sort_keys=True))"
            )
            out = subprocess.run(
                [sys.executable, "-c", script],
                cwd=str(REPO_ROOT), capture_output=True, text=True,
            )
            assert out.returncode == 0, out.stderr
            return out.stdout

        assert build() == build()


class TestSpecIsValid:
    def test_operation_ids_are_unique(self, checked_in):
        """One endpoint can serve several rules; ids must still be unique."""
        ids = [op["operationId"] for _, _, op in _operations(checked_in)]
        duplicates = {i for i in ids if ids.count(i) > 1}
        assert not duplicates, (
            f"Duplicate operationIds make this invalid OpenAPI: {sorted(duplicates)[:10]}"
        )

    def test_path_parameters_are_declared(self, checked_in):
        """Every {placeholder} in a path needs a matching parameter object."""
        problems = []
        for path, method, operation in _operations(checked_in):
            required = set(re.findall(r"\{([^}]+)\}", path))
            declared = {p["name"] for p in operation.get("parameters", [])}
            missing = required - declared
            if missing:
                problems.append(f"{method.upper()} {path}: {sorted(missing)}")
        assert not problems, "Undeclared path parameters:\n  " + "\n  ".join(problems[:10])

    def test_every_operation_declares_responses(self, checked_in):
        missing = [
            f"{m.upper()} {p}" for p, m, op in _operations(checked_in)
            if not op.get("responses")
        ]
        assert not missing, f"Operations without responses: {missing[:10]}"

    def test_passes_a_real_openapi_validator(self, checked_in):
        validator = pytest.importorskip(
            "openapi_spec_validator",
            reason="openapi-spec-validator not installed",
        )
        validator.validate(checked_in)


class TestOptionalBlueprintsStillImport:
    """
    Config-gated blueprints are imported by module path. A rename or a moved
    module would drop a whole family of endpoints from the published spec, and
    without this guard the only symptom is a quietly smaller artifact.
    """

    def test_every_optional_blueprint_imports(self):
        from potato.server_utils.openapi_spec import OPTIONAL_BLUEPRINTS

        broken = []
        for module_path, attr, _gate in OPTIONAL_BLUEPRINTS:
            try:
                module = importlib.import_module(module_path)
            except Exception as exc:
                broken.append(f"{module_path}: {type(exc).__name__}: {exc}")
                continue
            if not hasattr(module, attr):
                broken.append(f"{module_path} has no attribute {attr!r}")

        assert not broken, (
            "Optional blueprints that no longer import — their endpoints are "
            "silently missing from the published API spec:\n  " + "\n  ".join(broken)
        )

    def test_spec_records_no_unavailable_blueprints(self, checked_in):
        unavailable = checked_in["info"].get("x-potato-unavailable-blueprints")
        assert not unavailable, (
            f"The spec was generated with blueprints that failed to import, so it "
            f"is incomplete: {unavailable}. {REGENERATE}"
        )

    def test_config_gated_operations_are_marked(self, checked_in):
        """The gate annotation is the only way a reader learns an endpoint is optional."""
        gated = [
            op for _, _, op in _operations(checked_in)
            if "x-potato-requires-config" in op
        ]
        assert len(gated) > 50, (
            f"Only {len(gated)} operations carry x-potato-requires-config; the "
            f"optional blueprints are probably not being collected."
        )


class TestAuthAnnotations:
    def test_auth_decorators_are_detected(self, checked_in):
        """
        Auth is applied by per-blueprint decorators rather than a central table,
        and is recovered by an AST scan. If that scan breaks it returns nothing
        rather than erroring, so assert it found a plausible amount.
        """
        annotated = [
            op for _, _, op in _operations(checked_in) if "x-potato-auth" in op
        ]
        assert len(annotated) > 100, (
            f"Only {len(annotated)} operations record auth; the decorator scan in "
            f"openapi_spec.scan_auth_decorators() has probably stopped matching."
        )

    def test_admin_endpoints_are_marked_admin(self, checked_in):
        from potato.server_utils.openapi_spec import AUTH_DECORATORS

        for _path, _method, operation in _operations(checked_in):
            for decorator in operation.get("x-potato-auth", []):
                assert decorator in AUTH_DECORATORS, (
                    f"Unknown auth decorator {decorator!r} in the spec; add it to "
                    f"AUTH_DECORATORS so its meaning is documented."
                )

    def test_authenticated_operations_document_401(self, checked_in):
        from potato.server_utils.openapi_spec import AUTH_DECORATORS

        missing = []
        for path, method, op in _operations(checked_in):
            auth = op.get("x-potato-auth")
            if not auth:
                continue
            levels = {AUTH_DECORATORS[a] for a in auth}
            # A debug-only endpoint is not gated on identity: it either does not
            # exist (403) or is wide open. There is nothing to answer 401 with.
            expected = "403" if levels == {"debug-only"} else "401"
            if expected not in op.get("responses", {}):
                missing.append(f"{method.upper()} {path} (wanted {expected})")
        assert not missing, f"Guarded operations missing their auth response: {missing[:10]}"
