# Grid Labeling

The grid page labels many items at once for a single radio, multiselect or
triage scheme. The annotator selects a run of tiles, presses a label, and saves the
page. It suits short texts and images that take a second each to judge, which
is where one-item-per-page navigation spends more time loading than labeling.

The grid is an alternative view, not a separate task. Its items come from the
annotator's own assignment and its saves go through the same endpoint as the
normal page, so assignment strategies, the per-item annotator cap, quality
control and agreement treat grid labels like any others, and an item labelled
in the grid shows as answered on the normal page.

## Configuration

```yaml
grid_view:
  enabled: true
  scheme: sentiment     # a top-level radio, multiselect or triage scheme
  page_size: 24         # items per page, 1 to 200
```

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `false` | Serve the grid at `/annotate/grid` |
| `scheme` | required | The radio, multiselect or triage scheme the grid labels |
| `page_size` | `24` | Items per page |

The scheme must be a top-level `radio`, `multiselect` or `triage`. For a triage
scheme the grid's buttons are the scheme's own labels and keys (Keep, Discard
and Unsure on 1, 2 and 3 unless the scheme sets others), and a decision made in
the grid shows on the normal page as if it had been made there. A study with other
schemes as well can still use the grid for this one; the others are answered on
the normal page.

## Using it

Open `/annotate/grid` once logged in, or use the **Grid** link in the
annotation page's header. The grid page links back to the normal one ("One at
a time").

| Action | Mouse | Keyboard |
|---|---|---|
| Select a tile | Click | Arrow keys move, Space selects |
| Select a range | Shift-click | Shift with an arrow key |
| Add or remove one tile | Ctrl- or Cmd-click | Space |
| Select every tile | | A |
| Apply a label | Click the label | Its key, shown on the button (1 to 9 for radio and multiselect) |
| Remove all labels (multiselect) | Clear | |

For a radio scheme a label replaces whatever the tile had. For a multiselect
scheme a label is added to the selected tiles, or removed if every selected tile
already has it.

**Save and load more** stores each labelled tile and loads the next page. Tiles
left unlabelled are not saved and come back on a later page. If a save fails,
the tile is outlined in red with the reason on hover, the others stay saved, and
pressing Save again retries.

Tiles show the item's text (clamped to six lines) or, when the item's text field
holds an image path or URL, the image.

## Attention checks and gold items

If the study uses `attention_checks` or `gold_standards`, the grid places them
among the tiles at the configured frequency: with `frequency: 3`, a check after
every three regular items, counted from the annotator's last check. They are
assigned and scored exactly as on the normal page, so failing them warns and
then blocks the annotator, and a blocked annotator who opens the grid is sent to
the annotation page, which explains the block. Handing a check out resets the
count, so a page can open with a check: the grid errs towards more checks, never
fewer.

## Limits

- One scheme per grid. Span, image-region and free-text schemes are answered on
  the normal page.
- The grid shows only items the annotator has not answered. To revise an
  answer, use the normal page.
- Timing is per page, not per item. The page measures its own active time (the
  gaps between the annotator's clicks and keys, each capped at five minutes,
  as on the normal page), and each save gives every item it saves an equal
  share. The [Throughput tab](../administration/admin_dashboard.md) counts
  those shares, so a grid annotator's items per hour are comparable with the
  normal page's, but a grid item's own time is an average over its page.

## Example

```bash
python potato/flask_server.py start examples/classification/grid-view/config.yaml -p 8000
# then open http://localhost:8000/annotate/grid
```

## Related

- [Task Assignment](task_assignment.md)
- [Quality Control](../workflow/quality_control.md)
- [Pocket Mode](pocket_mode.md)
