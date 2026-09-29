"""
Codebook Lab — an offline experiment harness for testing codebook design
choices against a fixed set of must-get-right ("platinum") examples.

Pipeline (see cli.py for the orchestration):
  1. Generate N variants of a seed codebook (variant_generator.py), some
     related, some improved, some worsened.
  2. Score every variant against the platinum set, per label and overall
     (scorer.py).
  3. Build hybrid codebook(s) by taking, for each label, the structured
     fields from whichever variant scored best on that label
     (hybridizer.py).
  4. Score the hybrid(s) the same way, so you can see whether they beat
     every single variant (report.py prints the comparison).

This package is deliberately independent of the live Solo Mode / codebook
DB — everything runs on in-memory codebook snapshots and plain files, so
an experiment run touches no project state.
"""
