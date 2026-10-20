# 3D Medical Volumes (DICOM & NIfTI)

Segmenting CT and MR volumes: a DICOM series or a NIfTI file is shown in three
linked views (axial, coronal, sagittal), and annotators paint label masks,
draw boxes and polygons on slices, and fill the slices between painted ones by
interpolation. Masks export as a NIfTI label volume or a DICOM SEG, and an
RTSTRUCT on the item can provide the starting masks.

```yaml
annotation_schemes:
  - annotation_type: volume_annotation
    name: ct_segmentation
    description: Outline the lesion and the bone ring
    source_field: volume          # item field naming the volume
    labels:
      - {name: Lesion, color: "#e6553a", key_value: "1"}
      - {name: Bone, color: "#3a8ee6", key_value: "2"}
    default_window: Soft tissue
    display_tags: [Modality, BodyPartExamined, SliceThickness]
```

```json
{"id": "case_001", "volume": "case_001_ct"}
{"id": "case_002", "volume": "case_002.nii.gz"}
```

`volume` is relative to `media_directory`: a directory holding one DICOM
series, or a `.nii` / `.nii.gz` file. It needs the `volumes` extra:

```bash
pip install 'potato-annotation[volumes]'     # pydicom, nibabel, highdicom
```

Runnable example, with a generated CT phantom as both a DICOM series and
NIfTI plus an RTSTRUCT:
[`examples/image/ct-volume/`](https://github.com/davidjurgens/potato/tree/master/examples/image/ct-volume)
(run `generate_volume.py` in it first).

---

## Configuration

| Key | Default | Description |
|---|---|---|
| `labels` | required | Names, or `{name, color, key_value}` |
| `source_field` | `volume` | Item field holding the volume path |
| `tools` | all | Any of `navigate`, `brush`, `eraser`, `box`, `polygon` (`navigate` is always added) |
| `views` | all three | Any of `axial`, `coronal`, `sagittal` |
| `default_window` | first preset | Name of the window preset to start in |
| `window_presets` | none | Extra presets, `{name, center, width}`, listed first. A NIfTI file has no modality header, so CT or MR presets for NIfTI data come from here |
| `brush_size` | `2` | Starting brush radius, in voxels of the finest axis |
| `prefill_rtstruct_field` | none | Item field naming an RTSTRUCT whose ROIs become the starting masks |
| `display_tags` | none | DICOM header keywords shown under the views |
| `allow_identifying_tags` | none | Identifying keywords from `display_tags` that may be shown (see below) |

### Patient information in DICOM headers

DICOM headers usually carry the patient's name, ID, birth date and
institution. Annotators see only the keywords listed in `display_tags`, and a
keyword the DICOM de-identification basic profile (PS3.15) removes, such as
`PatientName`, `PatientID`, `PatientBirthDate`, `InstitutionName`,
`AccessionNumber`, dates, UIDs, and the study and series descriptions, is
shown only if it is also listed in `allow_identifying_tags`. The server
enforces this per schema, so a request cannot ask for other tags.

The raw files are not served: `/media/` refuses DICOM files (recognised by
content, with or without a `.dcm` suffix) and NIfTI files, signed in or not,
so the header cannot be downloaded around the filter. Set
`serve_raw_medical_files: true` at the top level of the config to allow
downloads. The slice images and the volume description need a signed-in
user.

Three things the filter cannot cover:

- **File and directory names** reach the browser, in the item data and in
  error messages. PACS exports often name directories after the patient's
  name or record number, so use pseudonymous names (`case_001/`).
- **Pixels.** A series marked `BurnedInAnnotation` YES (common for
  ultrasound and secondary captures) may have patient details written into
  the image, and is refused when loaded. Pixels in a series without that
  flag are not inspected.
- **The files on disk** stay as uploaded. De-identify them before upload
  when the people running the server must not have identifying data either.

A DICOM SEG export copies the patient and study modules from the source
images, as DICOM requires; a NIfTI export carries none.

## Using it

- **Slices.** Scroll over a view, use the slider under it, or <kbd>&uarr;</kbd>
  / <kbd>&darr;</kbd> (and Page Up / Page Down) on the focused view. The
  yellow crosshair shows where the other two views cut this one.
- **Navigate** (<kbd>n</kbd>): click a point to move the other views to it.
- **Brush** (<kbd>b</kbd>) and **Eraser** (<kbd>e</kbd>) paint and erase the
  selected label. A stroke on the coronal or sagittal view writes into every
  axial slice it crosses.
- **Box** (<kbd>x</kbd>) and **Polygon** (<kbd>p</kbd>): drag a box; click
  polygon points, then double-click or <kbd>Enter</kbd> to close
  (<kbd>Esc</kbd> cancels). They are listed under the views, where a click
  jumps to the slice and **Remove** deletes one.
- **Labels**: click one, or press its `key_value`.
- **Window**: pick a preset, or right-drag on an image (left and right
  change the width, up and down the centre).
- **Interpolate** (<kbd>i</kbd>): fills the slices between painted axial
  slices of the selected label. Paint the first and last slice and one or
  more in between where the shape changes; the filled slices are ordinary
  mask and can be painted over. **Undo** (<kbd>Ctrl</kbd>+<kbd>Z</kbd>)
  removes them. Two outlines that do not overlap blend to nothing in the
  middle; those slices stay empty and the status line names them. A blended
  slice smaller than a tenth of the smaller painted outline counts as empty
  too, instead of leaving a few stray pixels.

Views are drawn in radiological convention: the patient's right is on the
viewer's left. Every volume is put in one orientation (RAS) when read, so
the views are anatomical whatever order the scanner wrote the slices in. For
an oblique acquisition the three views are the planes of the nearest
orthogonal grid, not true axial, coronal and sagittal planes.

## Inputs

- **DICOM**: a directory holding one series, either classic (one file per
  slice) or one multi-frame (enhanced) file, whose per-frame position,
  orientation, spacing and rescale come from its functional groups. Slices
  are ordered by position along the slice normal. Refused, with the reason: a
  directory with two series, or with more than one multi-frame file; missing
  or duplicated slices; slices with different orientations (a localizer left
  in the series); a gantry tilt over 0.5°, which `dcm2niix` resamples away;
  and `BurnedInAnnotation` YES. A DICOM SEG exported from a multi-frame
  source refers to that file's frames in the file's own order.
- **NIfTI**: `.nii` and `.nii.gz`, 3D (a 4D file with one volume is read as
  3D).
- **RTSTRUCT**: closed planar contours on axial slices of the series. ROIs
  are matched to labels by name (case-insensitive); unmatched ROIs are
  listed in the status line. Contours on planes that do not fall on a slice
  are skipped with a warning in the server log. The prefilled masks are
  shown at once and saved with the annotator's first save, so opening an
  item does not count as answering it.

## What is stored

One JSON value per item:

```json
{"volume": "case_001_ct", "shape": [512, 512, 120], "labels": ["Lesion", "Bone"],
 "masks": {"Lesion": {"57": [261800, 14, 498, ...], "58": [...]}},
 "shapes": [{"label": "Lesion", "axis": "axial", "index": 57, "type": "box",
             "points": [[201.5, 310.0, 57], [240.0, 280.25, 57]]}]}
```

Coordinates are voxel indices `(i, j, k)` in the volume's canonical RAS
orientation. Each mask slice is an axial slice `k`, flattened row by row (row
`j`, column `i`) and run-length encoded as alternating counts of 0s and 1s,
starting with 0s.

## Export

```bash
python -m potato.export -c config.yaml -f volume_nifti -o out/
python -m potato.export -c config.yaml -f dicom_seg -o out/
```

- `volume_nifti`: per annotator, `<item>__<schema>.nii.gz`, a uint8 label
  volume in the source file's voxel order and affine (0 is background, 1 the
  first label), `labels__<schema>.json` mapping values to names, and
  `<item>__<schema>__shapes.json` with the boxes and polygons. Works for both
  input kinds.
- `dicom_seg`: per annotator, `<item>__<schema>.dcm`, a binary DICOM
  Segmentation with one segment per label that has voxels, referencing the
  source series. DICOM sources only.

## Agreement

The agreement report scores `volume_annotation` by 3D Dice per label between
each pair of annotators of an item: 2|A∩B| / (|A| + |B|). A pair where
neither painted a label is left out for that label rather than counted as
agreeing. Boxes and polygons are not scored.

## Limits

- The server renders each slice on request; very large volumes (thousands of
  slices of 1024×1024) load slowly the first time. The three most recently
  used volumes are kept in memory.
- Masks are binary per label; overlapping labels in a NIfTI export resolve
  to the later label in the scheme's list.
- No 4D (time series) volumes, no fused PET/CT, no oblique reformats.

## Related

- [Deep Zoom & Tiling](deep_zoom.md), including whole-slide images
- [Image Annotation](image_annotation.md)
- [Export Formats](../../data-export/export_formats.md)
