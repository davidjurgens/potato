# Bioacoustics: call boxes on a spectrogram

Two synthetic 6-second recordings (22.05 kHz WAV) with tones and frequency
sweeps at known times and frequencies:

| Recording | Call | Time (s) | Frequency (kHz) |
|---|---|---|---|
| `site_a_0600` | whistle | 0.5–1.1 | 3 |
| | upsweep | 1.8–2.4 | 2 → 5 |
| | trill (8 pulses) | 3.0–3.8 | 6 |
| | downsweep | 4.5–5.0 | 7 → 4 |
| `site_b_0615` | upsweep | 0.8–1.3 | 1.5 → 3.5 |
| | whistle | 2.2–2.9 | 8 |
| | trill (6 pulses) | 4.0–4.6 | 4.5 |

The boxes come from the Raven selection tables in `source/`, which have two
mistakes to fix: `site_a_0600` is missing the downsweep, and the trill in
`site_b_0615` is labelled a whistle.

```bash
python potato/flask_server.py start examples/audio/bioacoustics-boxes/config.yaml -p 8000
```

Drag on the spectrogram to draw a box; keys `1`–`4` choose the call type.
Export the corrected boxes with `-f raven` or `-f audacity_labels`; see
`docs/guides/bioacoustics.md`.
