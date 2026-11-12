# Contributing to Potato

Bug fixes, new annotation types, documentation corrections and example projects
are all welcome. Most of what Potato does now exists because someone needed an
annotation type that did not.

There is no Contributor License Agreement to sign. Some projects ask you to
sign one so they can relicense your code later; Potato does not. You keep the
copyright in what you write, and opening a pull request offers it under
[GPLv3+](LICENSE), the licence the rest of the repository uses. Participation is
covered by the [Code of Conduct](CODE_OF_CONDUCT.md).

You do not need to open an issue before writing code. For anything that touches
the annotation-type registry or adds a whole subsystem, a short issue up front
usually saves a round of review.

If you have not contributed to an open-source project before, the changes that
land most easily here are a documentation correction, a new example config under
`examples/`, or a fix for a bug you hit yourself. GitHub's
[fork-and-pull-request guide](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests)
covers the mechanics that this file assumes.

This file covers enough to get a change written and sent. The
[full contributor guide](docs/guides/contributing.md) has the rest: the
checklist for adding an annotation type, documentation conventions, and what
reviewers look at.

## Setup

Fork the repository on GitHub first, then clone your fork. You will not have
push access to `davidjurgens/potato` itself, and a pull request comes from your
fork.

```bash
git clone https://github.com/YOUR-USERNAME/potato.git
cd potato
python -m venv .venv && source .venv/bin/activate

pip install -r requirements.txt        # runtime dependencies
pip install -r requirements-test.txt   # pytest and browser-test tooling
pip install -e .                       # install Potato from this checkout
```

CI runs Python 3.11. Match it if you can.

**The `-e` matters.** Without it, pip copies Potato into `site-packages` and
that copy shadows your checkout: the server runs, your edits do nothing, and
nothing warns you. `python -c "import potato; print(potato.__path__)"`, run from
outside the repository, should print your checkout.

## Run something

Examples set `task_dir: .`, so run them from the repository root:

```bash
python potato/flask_server.py start examples/classification/single-choice/config.yaml -p 8000
```

While working on the interface, skip the login, consent and instruction screens:

```bash
python potato/flask_server.py start <config.yaml> -p 8000 --debug --debug-phase annotation
```

`--debug` disables admin authentication, so keep it off anything reachable from
outside your machine.

## Where things live

| Area | Path |
|------|------|
| Server startup, CLI | `potato/flask_server.py` |
| Routes | `potato/routes.py` |
| Item and user state | `potato/item_state_management.py`, `potato/user_state_management.py` |
| Config loading and validation | `potato/server_utils/config_module.py` |
| Annotation types | `potato/server_utils/schemas/` |
| Display types | `potato/server_utils/displays/` |
| AI endpoints | `potato/ai/` |
| Frontend | `potato/static/`, `potato/templates/` |

Two things to know before adding anything. A route needs an `add_url_rule` in
`configure_routes()` as well as an `@app.route` decorator, or it returns 404
under a real `potato start` while working fine in tests. And the annotation
screen renders through a different code path from the phase screens an annotator
sees around it (consent, instructions, training, surveys), so a change to the
shared template has to be wired into both. The
[full guide](docs/guides/contributing.md#where-things-live) explains both.

## Sending the change

Branch from `master`, push to your fork, and open the pull request against
`master`:

```bash
git checkout -b fix/short-description
# ... work ...
git commit -m "fix(span): keep offsets stable when labels are re-rendered"
git push origin fix/short-description
```

GitHub then offers a "Compare & pull request" button on your fork.

Keep the change focused. A bug fix and a refactor in one pull request take
several times as long to review as the same work split in two.

- [ ] Run the test tier that matches your change — `pytest tests/unit/` for
      logic, `tests/server/` for endpoints and state, `tests/selenium/` for
      anything a user clicks. See the [Testing guide](docs/guides/testing.md).
- [ ] Check failures against the
      [known pre-existing failures](docs/guides/testing.md#known-pre-existing-failures);
      several tests fail on a clean checkout.
- [ ] Regenerate anything derived from code you changed:
      `scripts/generate_config_schema.py`, `scripts/generate_openapi.py`,
      `scripts/generate_llms_full.py`.
- [ ] Say what you changed, why, and how you checked it.

Commit messages follow `type(scope): summary` (`feat(deploy):`, `fix(ci):`,
`docs:`). Matching it is appreciated; nothing gets bounced over a prefix.

CI runs on your pull request automatically. It checks that the checked-in
generated files (the config JSON Schema, the OpenAPI spec, `llms-full.txt`)
still match what the code produces, runs the fast tests that guard those files,
and builds the documentation site with `mkdocs build --strict`, where a broken
link fails the build. It does not run the full test suite, because the browser
tests are too slow, so your local run is what stands behind the change.

New features are expected to come with a docs page and a runnable example under
`examples/`. That is a project expectation, not a gate on a first contribution:
a one-line fix needs no documentation, and if the prose around a fix is more
than you want to take on, say so in the PR.

## Reporting bugs

Open an issue at
[github.com/davidjurgens/potato/issues](https://github.com/davidjurgens/potato/issues)
with the config that triggered it (credentials removed), what you expected, what
happened, and the server console output.

Questions about *using* Potato rather than developing it: the
[FAQ](docs/faq.md), the [documentation](https://potatoannotator.readthedocs.io/),
or jurgens@umich.edu.
