# Codebook Example

Demonstrates the **universal codebook**: a `multiselect` scheme whose
labels come from the project codebook (`codebook: true`) instead of
static YAML, with `codebook_mode: open` so you can add / rename /
recolor / move / delete codes while coding.

```bash
python potato/flask_server.py start \
  examples/advanced/codebook-example/config.yaml -p 8000
```

## What to try

- Open the **Codebook** tray (right edge) and add a new theme with the
  "Add a code…" composer — it's usable on the current item immediately.
- Check a theme, click **Next** then **Previous**: your selection (and
  any code you added) persists.
- Codes you add survive navigation because the tray reconciles the form
  against the live codebook on each page load.

See [docs/advanced/codebook.md](../../../docs/advanced/codebook.md).
