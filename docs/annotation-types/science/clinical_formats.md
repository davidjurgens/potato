# Clinical and Pathology Formats

Potato reads and writes three clinical file formats:

- **DICOM SEG** and **DICOM SR** from [`volume_annotation`](../multimedia/volume_annotation.md):
  a segmentation object with one coded segment per label, and a measurement
  report (TID 1500) with each segment's volume and the annotator as observer.
- **QuPath GeoJSON** and **ASAP XML** for regions on whole-slide images in
  the [deep-zoom viewer](../multimedia/deep_zoom.md#whole-slide-images): import
  as pre-annotations, export the annotators' regions back.

Potato does not embed OHIF or Cornerstone3D. Both are full viewer
applications rather than components that fit inside an annotation page, so
the volume viewer is Potato's own. Open the exported SEG and SR in any
viewer or PACS that reads DICOM Segmentation and Structured Report objects.

## Installation

```bash
pip install 'potato-annotation[volumes]'   # pydicom, nibabel, highdicom
pip install 'potato-annotation[wsi]'       # openslide, for .svs/.ndpi/.mrxs slides
```

All of these libraries are loaded only when an export or import needs them.

## DICOM SEG and SR

### Coded concepts per label

Each segment in a SEG has a segmented property category and type, and each
finding in the SR has a finding type and category. Give them per label under
`dicom:`:

```yaml
annotation_schemes:
  - annotation_type: volume_annotation
    name: ct_segmentation
    description: Outline the lesion and the bone ring
    source_field: volume
    labels:
      - name: Lesion
        color: "#e6553a"
        dicom:
          category: {code: "49755003", scheme: SCT, meaning: Morphologically Altered Structure}
          type: {code: "52988006", scheme: SCT, meaning: Lesion}
          anatomic_region: {code: "39607008", scheme: SCT, meaning: Lung}
      - {name: Bone, color: "#3a8ee6"}
```

| Key | Default | Notes |
|---|---|---|
| `dicom.category` | SCT `85756007` "Tissue" | Segmented property category (SEG) and finding category (SR) |
| `dicom.type` | SCT `85756007` "Tissue" | Segmented property type (SEG) and finding type (SR) |
| `dicom.anatomic_region` | none | Anatomic region sequence on the segment |

Each code is a mapping of `code` (the code value), `scheme` (the coding
scheme designator: `SCT` for SNOMED CT, `DCM` for DICOM's own codes) and
`meaning`. `scheme` is at most 16 characters and `meaning` at most 64. A
label without `dicom:` gets the generic "Tissue" code for both: a SEG is valid
with it, but a reader learns nothing from it, so set real codes for labels
that mean something specific. The codes are checked at startup: a missing
key, an unknown key or a value that is too long stops the server with a
message naming the label.

Potato does not look codes up or check them against SNOMED CT; it writes what
the config says.

### Export

```bash
python -m potato.export -c config.yaml -f dicom_seg -o out/seg
python -m potato.export -c config.yaml -f dicom_sr -o out/sr
```

Both work on DICOM sources only (a NIfTI volume has no DICOM images to
reference; use `volume_nifti` for those). Per annotator and item:

- `dicom_seg` writes `<user>/<item>__<schema>.dcm`, a binary DICOM
  Segmentation. One segment per label that has voxels, numbered in label
  order from 1, labelled with the label's name, carrying its codes, with the
  label name as tracking ID and a new tracking UID. It references the source
  series and copies the source's patient and study modules, as DICOM
  requires.
- `dicom_sr` writes the same SEG and, beside it,
  `<user>/<item>__<schema>__sr.dcm`.

The SR is a **Comprehensive 3D SR** (SOP class 1.2.840.10008.5.1.4.1.1.88.34)
whose content is a **TID 1500 Measurement Report**:

- the observation context (TID 1001) has a person observer (TID 1003): the
  annotator's Potato username as the person name (`ada` becomes `ada^`, a
  one-component name) and as the login name;
- procedure reported is SCT `363679005` "Imaging procedure";
- one TID 1411 **Volumetric ROI Measurements** group per segment, with the
  segment as the referenced segment (by SEG instance UID, segment number and
  source series), the segment's tracking ID and UID, the label's type and
  category codes as finding type and category, and one measurement: SCT
  `118565006` "Volume" in UCUM `mm3`, computed as the number of voxels times
  the voxel volume (the absolute determinant of the volume's affine);
- the SEG and the source images are listed as evidence;
- completion flag COMPLETE, verification flag UNVERIFIED.

The SEG and SR are written together because the SR names the SEG by its SOP
Instance UID. Running `dicom_seg` into the same folder afterwards replaces
the SEG with one that has a new UID, and the report then references an
object that no longer exists; export the pair again with `dicom_sr`.

### Reading the files back

```python
import highdicom as hd
import pydicom

seg = hd.seg.Segmentation.from_dataset(pydicom.dcmread("out/sr/ada/case_1__ct_segmentation.dcm"))
report = hd.sr.srread("out/sr/ada/case_1__ct_segmentation__sr.dcm")
for group in report.content.get_volumetric_roi_measurement_groups():
    (volume,) = group.get_measurements()
    print(group.tracking_identifier, volume.value, volume.unit.value)
```

### Privacy

A SEG and an SR copy the patient and study modules (name, ID, birth date,
study date, accession number) from the source images, so they identify the
patient exactly as much as the series does. De-identify the series before it
reaches Potato if the exports leave the hospital. The annotator's username is
in the SR as the observer.

## Pathology regions: QuPath GeoJSON and ASAP XML

### Coordinates

Both formats store regions in the slide's full-resolution pixels (level 0),
origin at the top-left, y down. Potato stores image regions as fractions of
the slide's level-0 size, so importing divides by the slide's width and
height and exporting multiplies by them. Magnification, microns per pixel and
the level an annotator was viewing do not enter into it.

### Import

```bash
potato import -i case_01.geojson --image-dir /data/slides -o case-project
potato import -i regions/ -f qupath_geojson --image-dir /data/slides -o review
potato import -i case_01.xml --image-dir /data/slides -o case-project     # ASAP
```

| Option | Notes |
|---|---|
| `-i` | One region file, or a folder of them |
| `-f qupath_geojson` / `-f asap_xml` | Auto-detected when omitted; `qupath` and `asap` also work |
| `--image-dir` | Folder holding the slides. Without it, slides are looked for beside the region files only |
| `-o` | The project folder to write |

Neither format names its slide, so a region file is paired with the slide
that has its stem: `case_01.geojson` (or `case_01.svs.geojson`) with
`case_01.svs`, `.ndpi`, `.mrxs`, `.tif` or any image Pillow reads. A slide
that resolves outside `--image-dir` and the input folder (through a symbolic
link, say) is not used. A region file without a slide is left out with a
warning.

The project has one item per slide, shown in the deep-zoom viewer with the
regions as pre-annotations: every annotator starts from them, and nothing is
stored as anyone's work until they save. Slides are not copied:
`media_directory` in the generated config is the absolute path of the slide
folder, since slides are often gigabytes and an MRXS slide is a folder of
files. Edit it if the project moves to another machine.

The slide's level-0 size is read with openslide for slide formats and with
Pillow for other images, and stored on the item as `image_width` and
`image_height`.

### Export

```bash
python -m potato.export -c config.yaml -f qupath_geojson -o out/qupath
python -m potato.export -c config.yaml -f asap_xml -o out/asap
```

One file per annotator and slide: `<user>/<slide stem>.geojson` or
`<user>/<slide stem>.xml`. Import the `.geojson` into QuPath with the slide
open, or load the `.xml` in ASAP with the slide open. The
exporters work for any `image_annotation` scheme, not only imported projects.
When an item has no `image_width`/`image_height`, the slide's size is read
from the file in `media_directory`; an item whose size cannot be read is not
written, and the export says which.

Labels become QuPath classifications, `{"name": ..., "color": [r, g, b]}`,
and ASAP groups (`PartOfGroup`, with a `Group` entry per label). Colours come
from the scheme's label colours. Exported QuPath features have
`objectType: annotation`; an imported feature keeps its `id`, `name` and
object type, and an imported ASAP annotation keeps its `Name`.

### Shapes

| Potato | QuPath GeoJSON | ASAP `Type` |
|---|---|---|
| bbox | Polygon, 4 corners | Rectangle |
| polygon, freeform | Polygon | Polygon |
| ellipse | Polygon, 36 points | Polygon, 36 points |
| polyline | LineString | Measurement, 2-point lines only |
| landmark | Point | Dot |
| keypoint set | MultiPoint | PointSet |
| brush mask | not written | not written |

On import:

- An upright four-corner QuPath polygon becomes a bbox, since QuPath writes
  its rectangles that way. Any other polygon stays a polygon.
- A MultiPolygon becomes one polygon per part, marked as one instance; a
  MultiLineString one polyline per part; a MultiPoint one landmark per point.
- Polygon holes are dropped (Potato polygons have no holes); the import
  counts them and warns.
- ASAP `Spline` is read as the polygon through its control points, with a
  warning. ASAP coordinates are sorted by `Order`, and a decimal comma
  (`1024,5`) is read as a decimal point.
- QuPath detections and cells import like annotations, keeping their object
  type. Only the first 50,000 regions of a slide are read.
- A region with no classification (QuPath) or `PartOfGroup="None"` (ASAP) is
  labelled `Unclassified`. On export a region labelled `Unclassified` gets no
  classification and `PartOfGroup="None"`, so it round-trips.
- Regions reaching outside the slide are kept and counted in a warning. If
  every region of a file is outside, the file belongs to another slide or was
  written at another level.

Round trips keep every vertex to 0.001 pixel. What does not survive: an
ellipse comes back as a polygon, a polyline of more than two points is left
out of ASAP (it has no open polyline type), and keypoint order is lost.

### Example

`examples/image/whole-slide/regions/` holds four regions on the example's
synthetic slide (two tissue outlines, a box over a nuclei cluster, an
artifact point) as `synthetic_tissue.geojson` and as `synthetic_tissue.xml`:

```bash
python examples/image/whole-slide/generate_slide.py      # only if media/ is empty
potato import -i examples/image/whole-slide/regions/synthetic_tissue.geojson \
    --image-dir examples/image/whole-slide/media -o qupath-project
python potato/flask_server.py start qupath-project/config.yaml -p 8000
```

`examples/image/ct-volume/config.yaml` shows `dicom:` codes on a label; its
header has the `dicom_seg` and `dicom_sr` export commands.

## Troubleshooting

**`needs highdicom: pip install 'potato-annotation[volumes]'`.** The DICOM
exporters are listed but not usable until the extra is installed.

**`N item(s) are not DICOM series`.** SEG and SR reference DICOM images; a
NIfTI item has none. Export it with `volume_nifti`.

**`label 'X' dicom.type.meaning is required`.** Every code needs `code`,
`scheme` and `meaning`.

**`no slide named case_01.* in ...`.** The slide is not in `--image-dir` or
beside the region file, or its name does not match the region file's stem.

**`its size could not be read`.** Install the `wsi` extra for slide formats;
without openslide only the slides Pillow can open as TIFF (such as SVS) are
measured.

**Regions land in the wrong place in QuPath.** Check the file was exported
for the same slide (same stem) and that the slide was not cropped or
re-saved at another resolution after annotation.

**A file over 256 MB is refused.** Large QuPath exports are usually cell
detections; export annotations only, or split the file.

## Related

- [3D Medical Volumes](../multimedia/volume_annotation.md)
- [Deep Zoom and Tiling](../multimedia/deep_zoom.md), including whole-slide images
- [Image Annotation](../multimedia/image_annotation.md)
- [Computer vision format matrix](../../data-export/format_matrix.md)
- [Export Formats](../../data-export/export_formats.md)
- [Import CLI](../../tools/import_cli.md)
