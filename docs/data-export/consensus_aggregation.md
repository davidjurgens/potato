# Consensus aggregation

The `consensus` export combines the work of several annotators on each item
into a consensus, the way citizen-science projects such as Zooniverse
aggregate volunteers' classifications. It reports:

- **vote fractions** for `radio`, `select`, `likert` and `multiselect`
  questions, with the top answer and a `retired` / `needs_review` flag;
- **summary statistics** for `slider` and `number` questions;
- **point clusters** for `image_annotation` points (the `landmark` tool);
- **consensus boxes** for `image_annotation` bounding boxes.

Polygons, polylines, ellipses, freeform shapes, masks and keypoint sets are not
aggregated. The export counts them and names them in a warning.

## Running it

```bash
python -m potato.export -c config.yaml -f consensus -o consensus_out
```

Parameters come from the `consensus_aggregation` block of the config, and
`--option key=value` overrides them for one run:

```bash
python -m potato.export -c config.yaml -f consensus -o consensus_out \
    --option agreement_threshold=0.9 --option eps=8 --option eps_unit=pixels
```

The export is also available from the admin export API under the format name
`consensus` (see [Export formats](export_formats.md#exporting-via-admin-api)).

## Configuration

```yaml
consensus_aggregation:
  agreement_threshold: 0.8   # share of classifiers the top answer needs
  min_classifiers: 2         # fewer classifiers than this -> needs_review
  schemes: [T0, T1, T2]      # optional; default every scheme that can be aggregated
  points:
    eps: 0.02                # cluster radius
    eps_unit: fraction       # fraction | pixels
    min_samples: 2           # points within eps (itself included) to form a cluster
  boxes:
    iou_threshold: 0.5       # least IoU between any two boxes in a group
```

| Key | Default | `--option` name | Meaning |
|---|---|---|---|
| `agreement_threshold` | `0.8` | `agreement_threshold` (or `threshold`) | Greater than 0, at most 1. See [Status](#status) |
| `min_classifiers` | `2` | `min_classifiers` | Whole number, at least 1 |
| `schemes` | all supported | `schemes` (comma-separated) | Names of schemes to aggregate; each must be declared in the config |
| `points.eps` | `0.02` | `eps` | Greater than 0; at most 1 when `eps_unit` is `fraction` |
| `points.eps_unit` | `fraction` | `eps_unit` | `fraction`: distances use x as a share of the image width and y as a share of its height. `pixels`: distances in image pixels |
| `points.min_samples` | `2` | `min_samples` | Whole number, at least 1 |
| `boxes.iou_threshold` | `0.5` | `iou_threshold` | Greater than 0, at most 1 |

Every key is optional. A value out of range stops the server at startup (and
`potato validate`) with a message naming the key. An unknown `--option` name
makes the export fail with the list of known names.

`panoptes_aggregation` uses `eps: 5` pixels and `min_samples: 3` by default.
Potato's defaults suit a handful of annotators per item; with many volunteers,
raise `min_samples`.

## Questions

For each item and question:

- `n_classifiers`: annotators who answered this question on this item;
- per answer, `count` (annotators who gave it) and `fraction`
  (`count / n_classifiers`). Every option the scheme declares is listed, with a
  count of 0 if nobody chose it;
- `top_answer`, `top_count`, `top_fraction`, and `tied` when more than one
  answer shares the top count.

For a single-answer question the fractions add up to 1. For `multiselect`,
each fraction is the share of classifiers who ticked that box, so the
fractions can add up to more than 1. An annotator who saved the question with
no box ticked counts as a classifier with no votes.

A `radio` or `likert` answer saved with several options by a server older than
the [GH #167](https://github.com/davidjurgens/potato/issues/167) fix resolves to
the one the annotator settled on, the same way the tabular exports resolve it.

### Status

- `needs_review` when there are fewer than `min_classifiers` classifiers;
- `radio`, `select`, `likert`: `retired` when the top answer's fraction is at
  least `agreement_threshold` and no other answer ties it;
- `multiselect`: `retired` when every option is decided, meaning it was ticked
  by at least `agreement_threshold` of the classifiers or left unticked by at
  least that share.

The `reason` column says why an item needs review: too few classifiers, a tie,
the top fraction, or which multiselect options are undecided.

This flag reflects agreement only. Potato does not retire items from
assignment based on it; use it to choose the items to re-queue or adjudicate.

### Slider and number

One row per item and question with `n`, `mean`, `median`, `sd` (sample
standard deviation, `n - 1`; empty for one value), `min` and `max`.

## Points

Each label's points on an item, from all annotators together, are clustered
with DBSCAN:

- a point is a core point when at least `min_samples` points, itself
  included, lie within `eps` of it;
- a cluster is a connected group of core points plus the other points within
  `eps` of one of them. A point next to two clusters joins the one found
  first, scanning points in the order the annotations were loaded;
- the remaining points are noise.

This is the algorithm scikit-learn's `DBSCAN` implements, which
`panoptes_aggregation`'s `point_reducer_dbscan` calls. Potato's version uses
numpy only, and the tests check it against scikit-learn on random data and,
when it is installed, against `panoptes_aggregation` itself.

For each cluster: the centre (the mean, as image fractions `x`, `y` and as
pixels `x_px`, `y_px`), `size` (points), `n_annotators` and `annotators`,
`spread` (root mean squared distance from the centre, in fractions and in
pixels), and the sample variances `var_x`, `var_y` and covariance `cov_xy`,
which match the `clusters_var_x`, `clusters_var_y` and `clusters_var_x_y`
columns of the Zooniverse reducer (in pixels when the image size is known).

Clustering does not stop one annotator's two points from landing in one
cluster; compare `size` with `n_annotators` to spot it.

### Image size

Potato stores marks as fractions of the image, so `eps_unit: fraction` works
for every item. Pixel output and `eps_unit: pixels` need the image size, taken
in this order from the item's `image_width` / `image_height` (or `width` /
`height`) fields, then from the image file when the export can open it.
Remote images are not downloaded. With `eps_unit: pixels`, an item of unknown
size gets a row saying it was skipped, and the export warns.

## Boxes

The boxes of one label on one item are put into groups that hold at most one
box per annotator, with every pair of boxes in a group overlapping by at least
`iou_threshold`:

1. For each remaining box, start a group with it and add the other
   annotators' remaining boxes in order of IoU with it, highest first, when the
   new box's IoU with every box already in the group meets the threshold.
2. Keep the largest such group (ties: the larger summed IoU with the first box,
   then the earlier box).
3. Remove its boxes and repeat. A box that overlaps nothing is a group of one.

The consensus box is the median of the members' left, top, right and bottom
edges. Each group reports `support` (annotators in it), `n_classifiers`
(annotators who drew anything on the item for this scheme), `support_fraction`,
and `mean_iou` and `min_iou` of the members against the consensus box.

IoU does not change when the image is stretched, so grouping needs no image
size; pixel columns are filled when the size is known.

This is not a port of `panoptes_aggregation`'s box reducers. Its
`rectangle_reducer` runs DBSCAN on each box's x, y, width and height, in
pixels; `shape_reducer_dbscan` with `metric_type: IoU` runs DBSCAN with
`1 - IoU` as the distance, which can join boxes that do not overlap one
another through a chain of boxes that do.

## Output files

| File | One row per | Written when |
|---|---|---|
| `consensus_questions.csv` | item and question | a radio, select, likert or multiselect scheme exists |
| `consensus_votes.csv` | item, question and answer | as above |
| `consensus_numeric.csv` | item and question | a slider or number scheme exists |
| `consensus_points.csv` | item, scheme, label and cluster | an image_annotation scheme exists |
| `consensus_boxes.csv` | item, scheme, label and box group | as above |
| `consensus.json` | everything above, nested, plus the settings used | always |

A label whose points are all noise still gets one row in
`consensus_points.csv`, with an empty `cluster` and a `note`, so that the item
does not seem to be missing. `label_points`, `label_annotators` and
`label_noise` repeat on each row of a label.

The export fails with a reason when the project has no scheme of a supported
type or no annotations.

## Example

`examples/image/zooniverse-aggregation/` is an invented penguin-count workflow
imported from Zooniverse exports, with five volunteers' classifications:

```bash
python -m potato.export -c examples/image/zooniverse-aggregation/config.yaml \
    -f consensus -o consensus_out
```

## Troubleshooting

**Every point is noise.** `eps` is too small or `min_samples` too large for
the number of annotators. With `eps_unit: fraction`, `0.02` is 20 pixels on a
1000-pixel-wide image.

**"The image size of N item(s) ... is unknown".** Add `image_width` and
`image_height` to the data file, keep the images where the export can read
them (a path under the task's media directory), or use `eps_unit: fraction`.
Projects imported from Zooniverse get both fields when a classification
recorded the image size.

**A question never appears.** Its type is not one of those listed above, or
`schemes` leaves it out.

## Related

- [Coming from Zooniverse](../guides/coming-from-zooniverse.md)
- [Export formats](export_formats.md)
- [Reliability (Krippendorff's alpha)](export_formats.md#reliability-reliability)
- [Image annotation](../annotation-types/multimedia/image_annotation.md)
