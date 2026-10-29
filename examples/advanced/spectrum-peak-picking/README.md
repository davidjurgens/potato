# Spectrum peak picking

Peak picking and integration on synthetic 1H NMR and IR spectra, with
suggested peaks from automatic detection.

```bash
python potato/flask_server.py start examples/advanced/spectrum-peak-picking/config.yaml -p 8000
```

- `media/spectra/*.jdx`: 1H NMR spectra of ethyl acetate and ethanol as
  JCAMP-DX, XYDATA in DIFDUP compression, x in Hz at 400.13 MHz (the server
  converts to ppm).
- `media/spectra/ethyl_benzoate_ir.csv`: an IR transmittance spectrum as two
  columns.
- `generate_spectra.py` writes all three. The data is invented: Lorentzian
  lines at textbook positions, not measured spectra.

The answer for each item is the `peaks` scheme's JSON (peaks with
`source: auto` or `manual`, integrated regions, rejected suggestions). Export
one row per peak with
`python -m potato.export --config examples/advanced/spectrum-peak-picking/config.yaml --format peak_table --output out/`.

See [docs/annotation-types/science/spectra.md](../../../docs/annotation-types/science/spectra.md).
