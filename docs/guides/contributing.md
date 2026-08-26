# Contributing

Potato is an academic open-source project, and most of what it does now came
from someone needing an annotation type that did not exist yet. Bug fixes, new
annotation types, documentation corrections and example projects are all
welcome.

There is no Contributor License Agreement to sign. Some projects ask you to sign
one so they can relicense your code later; Potato does not. You keep the
copyright in what you write, and opening a pull request offers it under
[GPLv3+](https://github.com/davidjurgens/potato/blob/master/LICENSE), the
licence the rest of the repository uses. Participation is covered by the
[Code of Conduct](https://github.com/davidjurgens/potato/blob/master/CODE_OF_CONDUCT.md).

You do not need to open an issue before writing code, though one is welcome if
you want a sanity check on an approach first. For anything that touches the
schema registry or adds a subsystem, a short description up front usually saves
a round of review.

If you have not contributed to an open-source project before, the changes that
land most easily are a documentation correction, a new example config under
`examples/`, or a fix for a bug you hit yourself. GitHub's
[fork-and-pull-request guide](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests)
covers the mechanics this guide assumes.

## Getting set up

Fork the repository on GitHub first and clone your fork, since a pull request
comes from your own copy:

```bash
git clone https://github.com/YOUR-USERNAME/potato.git
cd potato
python -m venv .venv && source .venv/bin/activate

pip install -r requirements.txt        # runtime dependencies
pip install -r requirements-test.txt   # pytest and browser-test tooling
pip install -e .                       # install Potato from this checkout
```

`setup.py` declares `python_requires>=3.7`; CI runs 3.11, so match that if you
can.

!!! warning "The editable install is not optional"
    Without `-e`, pip copies Potato into `site-packages` and that copy shadows
    your checkout. The server starts, your edits do nothing, and nothing warns
    you. If a change appears to have no effect, run
    `python -c "import potato; print(potato.__path__)"` from outside the
    repository: it should print your checkout, and if it prints a
    `site-packages` path, remove that copy with `pip uninstall potato-annotation`
    and reinstall with `-e`.

Optional extras pull in dependencies for specific features, none of which are
needed to run a basic task:

| Extra | Installs support for |
|-------|----------------------|
| `ai` | OpenAI, Anthropic, Gemini and Ollama endpoints |
| `formats` | PDF, DOCX, Markdown and spreadsheet ingestion |
| `preview` | Headless-browser screenshots for `potato preview` |
| `export` | Parquet output |
| `huggingface` | Hugging Face dataset push and pull |

Install them with `pip install -e ".[ai,formats]"`.

### Run something

Every example is a self-contained project with `config.yaml` at its root, and
most set `task_dir: .`, so run them from the repository root:

```bash
python potato/flask_server.py start examples/classification/single-choice/config.yaml -p 8000
```

If you see `ConfigSecurityError: Path '..' resolves to ... outside the project
directory`, you are in the wrong working directory rather than looking at a bug.

When you are working on the annotation interface itself, skip the login,
consent and instruction screens:

```bash
python potato/flask_server.py start <config.yaml> -p 8000 --debug --debug-phase annotation
```

`--debug` also turns on auto-reload and drops admin authentication, so never
use it on anything reachable from outside your machine.

To check that a config parses and renders without booting a server:

```bash
python -m potato.preview_cli config.yaml
python -m potato.preview_cli config.yaml --format html > preview.html
```

## Where things live

| Area | Path | What it holds |
|------|------|---------------|
| Server startup | `potato/flask_server.py` | App creation, data loading, CLI entry |
| Routes | `potato/routes.py` | Annotation workflow and admin endpoints |
| Item state | `potato/item_state_management.py` | Items and assignment strategies |
| User state | `potato/user_state_management.py` | Per-user progress, phases, annotations |
| Config | `potato/server_utils/config_module.py` | Loading, validation, path security |
| Annotation types | `potato/server_utils/schemas/` | One module per type, plus `registry.py` |
| Display types | `potato/server_utils/displays/` | How an item is shown, separate from how it is annotated |
| AI endpoints | `potato/ai/` | Model backends for label suggestions |
| Frontend | `potato/static/`, `potato/templates/` | `annotation.js`, `span-manager.js`, Jinja templates |

Two things to know before you add anything:

- **Routes have to be registered twice.** A live `potato start` serves the app
  built by `create_app()`, so a handler that only carries an `@app.route`
  decorator returns 404 in production while working fine in some tests. Add a
  matching `add_url_rule` in `configure_routes()`.
- **Annotation pages and phase pages render through different paths.**
  Annotation pages go through `render_page_with_annotations()`; consent,
  instructions, training and survey pages go through `get_current_page_html()`.
  A new conditional `<script>` or template variable in `base_template_v2.html`
  has to be wired into both, or the feature silently does nothing on half the
  workflow.

## Adding an annotation type

This is the most common substantial contribution and the one with the longest
checklist: a working type also has to persist its annotations and appear in the
generated config schema.

**1. Write the generator.** Create `potato/server_utils/schemas/my_schema.py`
with a function taking the scheme dict and returning `(html, keybindings)`:

```python
def generate_my_schema_layout(annotation_scheme):
    ...
    return html, keybindings
```

**2. Register it.** In `potato/server_utils/schemas/registry.py`, import the
generator inside `_register_builtin_schemas()` and add a `SchemaDefinition`:

```python
SchemaDefinition(
    name="my_schema",
    generator=generate_my_schema_layout,
    required_fields=["name", "description"],
    optional_fields=["every", "other", "key", "the", "generator", "reads"],
    supports_keybindings=False,
    description="One line describing the type",
),
```

Declare every key the generator reads. `optional_fields` is the only source for
the published JSON Schema and for the per-type table in
`docs/configuration/config_reference.md`, so an undeclared key does not exist as
far as editors, agents, or the spec are concerned, and a user's editor will
underline a working option as invalid. Keys handled by shared helpers
(`label_requirement`, `layout`, `display_logic` and friends) belong in
`registry.UNIVERSAL_OPTIONAL_FIELDS` instead, and keys the server writes onto a
scheme at runtime (`annotation_id`,
`_allocated_keys`) belong in `INTERNAL_SCHEME_FIELDS` and must stay out of the
per-type lists. `tests/unit/test_schema_registry_field_coverage.py` reads your
module and fails on any key you read but did not declare.

You do not need to touch `valid_types` in `config_module.py`. It comes from
`schema_registry.get_supported_types()`. (Display types are a separate registry
with its own list; adding one of those is a different checklist.)

Set `single_select=True` only if your type emits several inputs carrying
*different* `label_name` values for one logical answer, the way `radio` and
`likert` do. Types that emit one fixed `label_name` and simply overwrite it must
leave it `False`; setting it wrongly deletes real annotations.

**3. Export it** from `potato/server_utils/schemas/__init__.py`, following the
existing lines.

**4. Test it in two tiers.** A unit test in `tests/unit/test_my_schema.py` for
the generated HTML, and a Selenium test in
`tests/selenium/test_my_schema_ui.py` for what a user does with it.

Persistence tests are easy to get wrong. Browsers cache form state across a
refresh, so a test that calls `driver.refresh()` and then reads a hidden input's
value passes even when the server stored nothing. Navigate away and back
instead:

1. Annotate instance N and wait out the 1.5s save debounce.
2. Click Next, then Previous.
3. Assert on *visible* state — tile highlighting, checked boxes, CSS classes —
   not just hidden input values.
4. Optionally confirm server-side through `/get_annotations?instance_id=<id>`.

Four functions in `annotation.js` have to handle your inputs, or annotations
will render and then vanish: `syncAnnotationsFromDOM()`, `saveAnnotations()`,
`clearAllFormInputs()` and `populateInputValues()`. Reusing an existing input
pattern — a hidden input carrying `data-modified` / `data-server-set` — is
usually less work than teaching all four about a new one.

See the [Testing guide](testing.md) for tier conventions and the rule that test
files must live under `tests/`.

**5. Document it and ship an example.** A page under
`docs/annotation-types/<category>/my_schema.md`, an entry for it in the
`mkdocs.yml` nav, and a runnable example at
`examples/<category>/my-schema-example/` with `config.yaml` at its root and
sample data in `data/`. Example configs open with the schema modeline so
editors can validate them:

```yaml
# yaml-language-server: $schema=https://potatoannotator.readthedocs.io/en/latest/schemas/potato-config.schema.json
```

MkDocs publishes every file under `docs/` whether the nav references it or not,
so an unlisted page is live, indexed, and reachable only by guessing its URL.
`tests/unit/test_docs_nav_drift.py` checks that every page is listed.

**6. Regenerate the derived artifacts.** Several checked-in files are generated
from the code, and CI compares them against a fresh run:

```bash
python scripts/generate_config_schema.py      # potato/schemas/potato-config.schema.json
python scripts/generate_config_reference.py   # docs/configuration/config_reference.md
python scripts/generate_llms_full.py          # after any docs change
```

**7. Look at it.** Add your type to the `SCHEMAS` dict in
`scripts/screenshot_batch2.py` and run:

```bash
python scripts/screenshot_batch2.py --schemas my_schema --output-dir screenshots/verify
```

Open the `_full.png` and `_form.png` output and check for invisible controls,
right-shifted layouts, overlapping labels, and grid types that fail to use the
full width. No test in the suite checks for any of that.

## Documentation and examples

Anything a user can configure needs a docs page, a nav entry, and at least one
complete YAML example. Changing an existing option means updating the affected
pages in the same PR.

That said, this is a project expectation rather than a gate on your first
contribution. A one-line bug fix needs no new documentation. If you fix
something real and the prose around it is beyond what you want to take on, say
so in the PR and it can be picked up in review — a fix with missing docs is
better than no fix.

House conventions when you do write docs:

- Lowercase-with-hyphens filenames.
- YAML examples in YAML, not JSON-shaped YAML.
- Cross-reference with relative paths: `[Quality Control](quality_control.md)`.
- Screenshots in `docs/img/screenshots/` with descriptive names.
- Run `python scripts/generate_llms_full.py` afterwards, or
  `test_llms_full_is_current` fails.

## Code style

PEP 8, meaningful names, docstrings on public functions and classes, and
comments where the logic is not obvious. There is no formatter or linter in CI,
so the standard is the surrounding file: match the conventions of the module you
are editing rather than reformatting it.

## Opening a pull request

Branch from `master`, push the branch to your fork, and open the pull request
against `master`:

```bash
git checkout -b fix/span-offset-drift
# ... work ...
git commit -m "fix(span): keep offsets stable when labels are re-rendered"
git push origin fix/span-offset-drift
```

GitHub then offers a "Compare & pull request" button on your fork.

Keep the change focused. A bug fix and a refactor in one pull request take
several times as long to review as the same work split in two.

Commit messages in this repository follow the `type(scope): summary` convention
(`feat(deploy):`, `fix(ci):`, `docs:`), and matching it is appreciated, but no
PR gets bounced over a prefix. Explain why the change is right rather than
restating the diff.

Before you open the PR:

- [ ] Run the test tier that matches your change: `pytest tests/unit/` for
      logic, `tests/server/` for endpoints and state, `tests/selenium/` for
      anything a user clicks. The full suite is slow and includes browser tests.
- [ ] Check your failures against the
      [known pre-existing failures](testing.md#known-pre-existing-failures) —
      several tests fail on a clean checkout and are not your doing.
- [ ] Regenerate any derived artifacts you invalidated (see above).
- [ ] Say in the description what you changed, why, and how you checked it.
      Screenshots for anything visual.

CI runs on every pull request, but not the full suite: browsers and wall clock
make that impractical. It checks that the checked-in generated files (the config
JSON Schema, the OpenAPI spec, `llms-full.txt`) still match what the code
produces, runs the fast tests that guard them, and builds the docs with
`mkdocs build --strict`, where a broken relative link fails the build.
Everything else is on your local run and on review.

Review is done by the maintainers, who are academics with teaching loads, so
turnaround varies. What gets looked at first:

- Does it work for cases beyond the one that prompted it: list inputs as well
  as strings, multiple annotators, an empty dataset?
- Does the state survive a round trip? Anything storing annotations gets checked
  against the navigate-away-and-back behaviour above.
- Is user-supplied content sanitized? Instance text renders through
  `sanitize_html`; `| safe` in a template without it is an XSS hole.
- Are file paths validated? Config paths go through `validate_path_security()`
  so a task cannot read outside its directory.
- Is a new config key declared where the generated schema can see it?

## Reporting bugs and requesting features

File issues at
[github.com/davidjurgens/potato/issues](https://github.com/davidjurgens/potato/issues).
The things that make a bug report actionable are the config that triggered it
(with any credentials removed), what you expected, what happened instead, your
Python version and OS, and the server console output. Browser-console output
helps for anything visual.

For a feature request, describe the annotation problem you are trying to solve
rather than only the mechanism you have in mind — the problem is often solvable
with a type that already exists, and when it is not, it tells us what the new
one has to do.

For questions about using Potato rather than developing it, start with the
[FAQ](../faq.md) and the [Getting Started guide](getting-started.md), or email
jurgens@umich.edu.

## Related documentation

| Document | Covers |
|----------|--------|
| [Developer Guide](developer-guide.md) | Architecture, REST API, extension points |
| [Testing](testing.md) | Test tiers, fixtures, drift guards, known failures |
| [Configuration Reference](../configuration/config_reference.md) | Every config key, generated from the registry |
| [Schemas and Templates](../annotation-types/schemas_and_templates.md) | Gallery of annotation types |
