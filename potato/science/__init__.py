"""Support for scientific data formats (signals, spectra, astronomy, clinical).

Nothing here is imported at server boot. Each format's reader lives in
``potato.science.converters`` and imports its third-party library only when a
file of that format is first read.
"""
