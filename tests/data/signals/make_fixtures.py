"""Write test fixtures with independent writers: pyedflib (EDF+/BDF+) and wfdb."""
import os, sys
import numpy as np
out = sys.argv[1]
import pyedflib
def sig(fs, n, f, amp):
    t = np.arange(n) / fs
    return amp * np.sin(2 * np.pi * f * t)
for kind, ext, ft, dmin, dmax in (("edf", ".edf", pyedflib.FILETYPE_EDFPLUS, -32768, 32767),
                                  ("bdf", ".bdf", pyedflib.FILETYPE_BDFPLUS, -8388608, 8388607)):
    path = os.path.join(out, f"pyedflib_{kind}plus{ext}")
    w = pyedflib.EdfWriter(path, 2, file_type=ft)
    hdr = [dict(label="Fz", dimension="uV", sample_frequency=128, physical_min=-500, physical_max=500,
                digital_min=dmin, digital_max=dmax, transducer="", prefilter=""),
           dict(label="Resp", dimension="mV", sample_frequency=8, physical_min=-2, physical_max=2,
                digital_min=dmin, digital_max=dmax, transducer="", prefilter="")]
    w.setSignalHeaders(hdr)
    a = sig(128, 128 * 20, 3.0, 200.0)
    b = sig(8, 8 * 20, 0.25, 1.5)
    w.writeSamples([a, b])
    w.writeAnnotation(2.0, 5.0, "Sleep stage W")
    w.writeAnnotation(9.5, -1, "Arousal")
    w.close()
    print(path, os.path.getsize(path))
import wfdb
fs = 250
n = fs * 10
t = np.arange(n) / fs
ecg = 0.05 * np.sin(2 * np.pi * 1.0 * t)
beats = np.arange(100, n, 200)
for b in beats:
    ecg[b - 3:b + 3] += 1.2
sig2 = np.column_stack([ecg, 0.5 * np.sin(2 * np.pi * 0.3 * t)])
wfdb.wrsamp("rec1", fs=fs, units=["mV", "mV"], sig_name=["MLII", "V5"], p_signal=sig2,
            fmt=["16", "16"], write_dir=out)
syms = ["N"] * len(beats)
syms[4] = "V"
samples = list(beats)
aux = [""] * len(beats)
# Rhythm: (N at 0, (AFIB at 5 s
samples = [0] + samples[:6] + [1250] + samples[6:]
syms = ["+"] + syms[:6] + ["+"] + syms[6:]
aux = ["(N"] + aux[:6] + ["(AFIB"] + aux[6:]
wfdb.wrann("rec1", "atr", np.array(samples), symbol=syms, aux_note=aux, write_dir=out, fs=fs)
print(sorted(os.listdir(out)))
