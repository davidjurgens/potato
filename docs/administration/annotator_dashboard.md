# Annotator Progress Dashboard

A lightweight, **read-only** progress page that annotators can view while they
work. Unlike the [Admin Dashboard](admin_dashboard.md) — which requires an admin
API key and exposes per-annotator data, configuration, and management actions —
the annotator dashboard shows only:

- **Project progress**: total items, items started, total annotations, overall
  completion percentage.
- **Personal progress**: the logged-in annotator's own annotated/assigned counts
  and completion percentage.
- *(optional)* **Active annotators**: a count only — never names.

It never exposes other annotators' identities, behavioral analytics,
configuration, or any action that mutates state.

The feature is **disabled by default**. When enabled, a **Progress** link appears
in the annotation navbar and the page is served at `/progress`.

## Configuration

Add an `annotator_dashboard` block to your config:

```yaml
annotator_dashboard:
  enabled: true                 # master switch (default: false)
  show_project_progress: true   # project-wide aggregate (default: true)
  show_personal_progress: true  # the logged-in user's own stats (default: true)
  show_active_annotators: false # count of active annotators, no names (default: false)
```

A shorthand is also accepted to enable everything with defaults:

```yaml
annotator_dashboard: true
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `false` | Master switch. When false, `/progress` behaves as if it does not exist. |
| `show_project_progress` | `true` | Show project-wide totals and completion. |
| `show_personal_progress` | `true` | Show the requesting annotator's own counts. |
| `show_active_annotators` | `false` | Show a count (no names) of annotators currently in the annotation phase. |

## Usage

When enabled, annotators see a **Progress** button (chart icon) in the top
navigation bar during annotation. Clicking it opens `/progress`, which displays
progress bars and stat cards and links back to annotating. The page fetches its
numbers from `/progress/api/summary` (also read-only).

## Privacy & security

- Both `/progress` and `/progress/api/summary` require a normal annotation
  session (a logged-in annotator). They do **not** use the admin API key.
- The personal section only ever reflects the requesting user. The API response
  contains no other annotator's identifier and no action/mutation affordances.
- Project numbers are computed by the same shared helper
  (`potato/server_utils/progress_stats.py`) used by the admin Overview tab, so
  the two views always agree.

## Example

A runnable example lives at `examples/advanced/annotator-progress/`:

```bash
python potato/flask_server.py start examples/advanced/annotator-progress/config.yaml -p 8000
```

Log in, annotate a few items, then click **Progress** in the navbar.

## Related

- [Admin Dashboard](admin_dashboard.md) — full monitoring and management (admin key required)
- [Behavioral Tracking](../advanced/behavioral_tracking.md)
