# Third-Party Components

Potato serves every browser library itself, so a study works without network
access and annotators' browsers contact only the Potato server. This page lists
the libraries that ship with Potato, the larger ones fetched on request, and the
optional Python packages behind the science features. See
[Air-gapped deployment](air_gap.md) for how offline use is checked.

## Browser libraries shipped with Potato

These files are committed under `potato/static/vendor/`. A library loads only on
pages that use it.

| Library | Version | Licence | Used by |
|---|---|---|---|
| Bootstrap | 5.3.3 | MIT | Every page |
| jQuery | 3.6.0 | MIT | Every page |
| Font Awesome Free | 6.7.2 | Icons CC BY 4.0, fonts SIL OFL 1.1, code MIT | Every page |
| Outfit (typeface) | — | SIL OFL 1.1 | Every page |
| Fabric.js | 5.3.1 | MIT | `image_annotation` |
| OpenSeadragon | 5.0.1 | BSD-3-Clause | Deep zoom, whole-slide images, `microscopy` |
| three.js | 0.160.0 | MIT | Point clouds and spatial annotation |
| D3 | 7.9.0 | ISC | Solo mode status charts |
| Plotly | 2.27.0 | MIT | Admin embedding view, `spectrum` display, light curves in `fits_cutout` |
| PDF.js | 3.11.174 | Apache-2.0 | PDF display |
| OpenLayers | 10.9.0 | BSD-2-Clause | `geo_annotation` |
| geotiff.js | 3.0.5 | MIT (bundled LERC decoder: Apache-2.0) | GeoTIFF layers in `geo_annotation` |
| 3Dmol.js | 2.5.5 | BSD-3-Clause | `protein_structure` display |
| igv.js | 3.8.9 | MIT (bundled DOMPurify: Apache-2.0 or MPL-2.0) | `genome_locus` display |
| jsPsych and 15 plugins, mouse-tracking extension | 8.3.0 (extension 1.2.0) | MIT | `type: jspsych` phases |
| KaTeX | 0.18.11 | MIT | `math:` rendering |
| OpenChemLib JS | 9.25.0 | BSD-3-Clause | `chemical_structure` editor, `molecule` display |
| uPlot | 1.6.32 | MIT | `time_series` display |

The legacy `header.html` page and the Simple-Likert example template use older
copies of Bootstrap 4 (4.1.3 and 4.4.1), slim jQuery 3.4.1 and Popper 1.16.0,
all MIT.

Libraries kept in their own directory have their licence file beside them:
3Dmol.js, geotiff.js, igv.js, KaTeX, OpenChemLib, OpenLayers, PDF.js and uPlot.

## Libraries fetched on request

These are too large to commit. `potato validate` names the command when a config
needs one, and `potato vendor fetch <name>` downloads it, checks it against the
npm registry's published integrity hash and stores it under the vendor
directory.

| Bundle | Version | Licence | Used by |
|---|---|---|---|
| `molstar` | 5.12.0 | MIT | `protein_structure` with the Mol* engine |
| `rdkit` (RDKit.js MinimalLib) | 2026.3.6 | BSD-3-Clause | InChI and InChIKey in `chemical_structure`; `molecule` display with `engine: rdkit` |

## Optional Python packages for science features

Each group is an install extra, imported only when a feature that needs it
runs. Without it, the feature gives a message naming the extra. The other
extras are listed in `setup.py`.

| Extra | Packages | Licences | Used by |
|---|---|---|---|
| `signals` | wfdb, pyarrow | MIT, Apache-2.0 | WFDB records and Parquet tables in `time_series` |
| `chemistry` | rdkit | BSD-3-Clause | Server-side grading of `chemical_structure` answer keys; InChIKey in the `chemistry` export |
| `spectra` | pyteomics, psims, lxml | Apache-2.0, Apache-2.0, BSD-3-Clause | mzML spectra |
| `microscopy` | zarr, tifffile, numpy | MIT, BSD-3-Clause, BSD-3-Clause | OME-Zarr and OME-TIFF in `microscopy` |
| `astro` | astropy | BSD-3-Clause | FITS images in `fits_cutout` |

```bash
pip install 'potato-annotation[signals,chemistry,spectra,microscopy,astro]'
```

## Data you supply

Some features read files that have their own terms. Potato does not include
them; supply your own copy:

- ontology files (OBO) for [ontology-backed labels](../annotation-types/science/ontology_labels.md);
- BirdNET models for [bioacoustics](../guides/bioacoustics.md);
- ITU-T P.808 reference clips for [listening tests](../annotation-types/multimedia/listening_tests.md);
- LexTALE item lists for the [vocabulary test](../annotation-types/measurement/vocabulary_test.md);
- the Comparative Agendas Project codebook and Manifesto Project data for
  [content analysis](../guides/content-analysis.md).

## Related

- [Air-gapped deployment](air_gap.md)
- [Changelog](https://github.com/davidjurgens/potato/blob/master/CHANGELOG.md)
