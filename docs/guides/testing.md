# Testing

The single entry point for running and writing Potato tests. Per-directory
READMEs under `tests/` go deeper on each tier; start here.

## Running tests

```bash
pip install -r requirements-test.txt

pytest                       # everything (slow — selenium included)
pytest tests/unit/ -v        # fast, isolated, mocked        (~404 files)
pytest tests/server/ -v      # real Flask instance over HTTP  (~190 files)
pytest tests/selenium/ -v    # real browser                   (~170 files)
```

Day to day, run `pytest tests/unit/` — it is the tier that gives feedback in
seconds. Run the tier that matches your change before opening a PR.

### Narrowing the run

```bash
pytest tests/server/test_backend_state.py -v                       # one file
pytest tests/server/test_backend_state.py::TestBackendState::test_health_check   # one test
pytest tests/selenium/ -m core                                     # core regressions only (~25% of the suite)
pytest tests/selenium/ -m "not redundant"                          # skip duplicated coverage
pytest -m "not selenium"                                           # skip all browser tests
pytest -n 4 --ignore=tests/selenium/archived                       # parallel
pytest --cov=potato --cov-report=html:test-results/coverage        # coverage
```

Markers are declared in `pytest.ini`: `selenium`, `slow`, `integration`, `unit`,
`serial` (must not run in parallel), `core`, `redundant`.

!!! warning "The 30-second timeout is global"
    `pytest.ini` sets `timeout = 30` with `timeout_func_only = true`. A test that
    legitimately needs longer must say so explicitly with
    `@pytest.mark.timeout(120)` rather than being left to fail intermittently.

## Which tier to write in

| Tier | Location | Use it when | Cost |
|------|----------|-------------|------|
| Unit | `tests/unit/` | Testing one function or class; dependencies can be mocked | < 1s |
| Server | `tests/server/` | Testing an HTTP endpoint, workflow, or state manager end to end | 1–10s |
| Selenium | `tests/selenium/` | Testing rendering, JS behaviour, or anything a user clicks | 10–60s |

Prefer the cheapest tier that can actually catch the bug. A schema that renders
wrong HTML is a unit test; a schema whose annotations fail to persist is a
Selenium test, because only the browser exercises the save/restore path.

## Writing tests

### Unit

```python
import pytest
from unittest.mock import patch, MagicMock

class TestMyFunction:
    @pytest.fixture(autouse=True)
    def mock_config(self):
        mock_config = MagicMock()
        mock_config.get.return_value = {}
        with patch('potato.flask_server.config', mock_config):
            yield mock_config

    def test_function_behavior(self, mock_config):
        from potato.module import my_function
        assert my_function(input) == expected
```

### Server

`FlaskTestServer` starts a real server on a free port; drive it with `requests`.

```python
import requests
from tests.helpers.flask_test_setup import FlaskTestServer
from tests.helpers.test_utils import TestConfigManager

class TestFeature:
    @pytest.fixture(scope="class", autouse=True)
    def flask_server(self, request):
        schemes = [{"annotation_type": "radio", "name": "test", ...}]
        with TestConfigManager("my_test", schemes) as test_config:
            server = FlaskTestServer(port=9007, config_file=test_config.config_path)
            if not server.start():
                pytest.fail("Failed to start server")
            yield server
            server.stop()

    def test_endpoint(self, flask_server):
        session = requests.Session()
        session.post(f"{flask_server.base_url}/register", data={"email": "u", "pass": "p"})
        session.post(f"{flask_server.base_url}/auth", data={"email": "u", "pass": "p"})
        assert session.get(f"{flask_server.base_url}/annotate").status_code == 200
```

See `tests/server/README.md`, `tests/server/QUICK_REFERENCE.md`, and
`tests/server/test_template.py`.

### Selenium

Inherit `BaseSeleniumTest` — it handles authentication for you.

```python
from tests.selenium.test_base import BaseSeleniumTest
from selenium.webdriver.common.by import By

class TestUIFeature(BaseSeleniumTest):
    def test_ui_interaction(self):
        self.driver.get(f"{self.server.base_url}/annotate")
        assert self.wait_for_element(By.ID, "instance-text").is_displayed()
```

See `tests/selenium/README.md`.

## Two rules that cause real bugs when broken

### Test files must live under `tests/`

Config and data files created by tests must stay inside the `tests/` tree —
`tests/output/` for scratch files. Potato's path-security validation rejects
paths outside `task_dir`, so tests that write to `/tmp` fail in some
environments and pass in others.

```python
from tests.helpers.test_utils import create_test_directory, TestConfigManager

test_dir = create_test_directory("my_test")          # correct
# config_file = "/tmp/test_config.yaml"              # forbidden
```

`tests/helpers/test_utils.py` provides `create_test_directory`,
`create_test_data_file`, `create_test_config`, `create_span_annotation_config`,
`create_comprehensive_annotation_config`, and the `TestConfigManager` context
manager (which cleans up on exit).

### Never test annotation persistence with `driver.refresh()`

Browsers restore form state across a refresh. A test that refreshes and then
reads `input.getAttribute('value')` passes even when the server never stored
anything — this has produced false-positive tests repeatedly.

The correct pattern:

1. Make the annotation, wait for the 1.5s debounce.
2. Verify server-side via `GET /get_annotations?instance_id=<id>`.
3. Navigate **away and back** (Next, then Previous) — or destroy the browser.
4. Assert on **visual state** (tile highlighting, CSS classes, checked state),
   not just hidden input values.

Four JS functions must handle every annotation input type, and a new schema that
misses one will silently fail to persist:

| Function | Responsibility |
|----------|----------------|
| `syncAnnotationsFromDOM()` | DOM inputs → `currentAnnotations` |
| `saveAnnotations()` | `currentAnnotations` → `/updateinstance` |
| `clearAllFormInputs()` | Reset inputs when switching instances |
| `populateInputValues()` | Restore visual state from `currentAnnotations` |

## Drift tests

Several artifacts are generated from the code, and `tests/unit/` fails the build
if a checked-in copy no longer matches what the code produces. This is how the
docs stay honest — see [Machine-Readable Specs](../api-reference/machine_readable.md).

| Test | Guards |
|------|--------|
| `test_config_schema_drift.py` | `potato-config.schema.json` matches the schema and display registries; every shipped example config validates |
| `test_openapi_drift.py` | `openapi.json` matches the live Flask `url_map`; optional blueprints still import |
| `test_docs_nav_drift.py` | Every `docs/**/*.md` page appears in the mkdocs nav |
| `test_display_registry_docs.py` | The display reference table matches the registry |

If one fails, regenerate rather than editing the artifact by hand:

```bash
python scripts/generate_config_schema.py
python scripts/generate_openapi.py
python scripts/generate_llms_full.py
```

## When to write a test

- **Bug fixes** — reproduce the bug first, so the test fails before the fix.
  Test the root cause, not the symptom.
- **New features** — cover the expected behaviour.
- **Config interactions** — especially CLI-arg-versus-config-file precedence.
  A recurring bug class: an argparse default of `True`/`False` silently
  overrides the config file, so defaults must be `None`.
- **Data format handling** — string *and* list inputs, nested structures.
- **Integration points** — registry completeness, API contracts.

New annotation schema types have their own checklist covering unit tests,
Selenium persistence tests, docs, and an example project — see the
[Developer Guide](developer-guide.md).

## Known pre-existing failures

These fail on a clean checkout and are not caused by your change:

- `test_adjudication_demo.py::test_queue_items_have_three_annotators`
- `test_mace_demo.py::test_reliable_higher_than_biased`
- three tests in `tests/server/test_solo_mode/test_refinement_pipeline.py`
  (need a live VLLM model)
- `test_visual_ai_endpoints.py` (YOLO output parsing)
- `test_span_overlay_visual_verification.py` (colour fallback, delete, and
  label-after-navigation cases)

## Deeper references

| Document | Covers |
|----------|--------|
| `tests/README.md` | Index, bug/test regression table |
| `tests/TESTING_STRATEGY.md` | Testing pyramid and coverage targets |
| `tests/unit/README.md` | Unit test fixtures and mocking |
| `tests/server/README.md` | Server integration testing in depth |
| `tests/server/QUICK_REFERENCE.md` | Copy-paste server test patterns |
| `tests/selenium/README.md` | Browser testing, waits, and debugging |
| `tests/integration/README.md` | Cross-component integration tests |
