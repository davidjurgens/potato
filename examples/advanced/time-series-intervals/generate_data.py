"""Write the synthetic signals for the time-series-intervals example.

    python examples/advanced/time-series-intervals/generate_data.py

media/psg-synthetic.edf
    Five minutes of a made-up polysomnogram, EDF+ with three 100 Hz channels
    (EEG Fpz-Cz, EOG, EMG chin) and a 10 Hz respiration channel. The EEG
    drifts from alpha (wake) through spindles to slow waves. Its EDF+
    annotation signal holds a hypnogram (one "Sleep stage ..." entry per
    stretch) and one "Arousal" point annotation, which the example turns into
    pre-annotations.
media/accel-synthetic.csv
    Two minutes of a three-axis accelerometer at 25 Hz: still, walking, still.
media/accel-synthetic_events.tsv
    A BIDS events file marking the walking bout, read as a pre-annotation.

Nothing here is real data.
"""

import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "..", "..")))

from potato.science.converters.edf import write_edf  # noqa: E402

rng = np.random.default_rng(7)
media = os.path.join(HERE, "media")
os.makedirs(media, exist_ok=True)

# --- PSG --------------------------------------------------------------------
fs, dur = 100, 300
t = np.arange(0, dur, 1 / fs)
eeg = 8 * rng.standard_normal(t.size)
wake = t < 60
eeg[wake] += 25 * np.sin(2 * np.pi * 10 * t[wake])                # alpha
light = (t >= 60) & (t < 180)
eeg[light] += 20 * np.sin(2 * np.pi * 6 * t[light])               # theta
for s in (100, 130, 160, 285):                                    # spindles
    m = (t >= s) & (t < s + 1.2)
    eeg[m] += 35 * np.sin(2 * np.pi * 13 * t[m]) * np.hanning(m.sum())
deep = (t >= 180) & (t < 270)
eeg[deep] += 90 * np.sin(2 * np.pi * 1.2 * t[deep])               # slow waves
eog = 6 * rng.standard_normal(t.size)
for s in (12, 31, 47):                                            # eye movements
    m = (t >= s) & (t < s + 0.6)
    eog[m] += 120 * np.sin(np.pi * (t[m] - s) / 0.6)
emg = (12 - 8 * (t > 60)) * rng.standard_normal(t.size)
burst = (t >= 200) & (t < 203)                                    # arousal
emg[burst] *= 5
eeg[burst] += 30 * np.sin(2 * np.pi * 9 * t[burst])
tr = np.arange(0, dur, 1 / 10)
resp = 0.4 * np.sin(2 * np.pi * 0.25 * tr) + 0.02 * rng.standard_normal(tr.size)

write_edf(
    os.path.join(media, "psg-synthetic.edf"),
    [{"label": "EEG Fpz-Cz", "unit": "uV", "fs": fs, "data": eeg, "physical_min": -250, "physical_max": 250},
     {"label": "EOG", "unit": "uV", "fs": fs, "data": eog, "physical_min": -250, "physical_max": 250},
     {"label": "EMG chin", "unit": "uV", "fs": fs, "data": emg, "physical_min": -150, "physical_max": 150},
     {"label": "Resp", "unit": "a.u.", "fs": 10, "data": resp, "physical_min": -1, "physical_max": 1}],
    record_duration=1.0,
    annotations=[(0, 60, "Sleep stage W"), (60, 30, "Sleep stage 1"), (90, 90, "Sleep stage 2"),
                 (180, 90, "Sleep stage 3"), (270, 30, "Sleep stage 2"), (200.5, 0, "Arousal")])

# --- accelerometer -------------------------------------------------------------
fa = 25
ta = np.arange(0, 120, 1 / fa)
walk = (ta >= 40) & (ta < 80)
ax = 0.02 * rng.standard_normal(ta.size) + walk * 0.35 * np.sin(2 * np.pi * 1.8 * ta)
ay = 0.02 * rng.standard_normal(ta.size) + walk * 0.20 * np.sin(2 * np.pi * 1.8 * ta + 1.0)
az = 1 + 0.02 * rng.standard_normal(ta.size) + walk * 0.45 * np.abs(np.sin(2 * np.pi * 1.8 * ta))
with open(os.path.join(media, "accel-synthetic.csv"), "w") as f:
    f.write("time,ax (g),ay (g),az (g)\n")
    for row in zip(ta, ax, ay, az):
        f.write("%.2f,%.4f,%.4f,%.4f\n" % row)
with open(os.path.join(media, "accel-synthetic_events.tsv"), "w") as f:
    f.write("onset\tduration\ttrial_type\tchannel\n40\t40\twalking\tn/a\n")
print("wrote", sorted(os.listdir(media)))
