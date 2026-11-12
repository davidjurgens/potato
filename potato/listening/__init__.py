"""
Listening tests: MUSHRA (ITU-R BS.1534), BS.1116, and the ITU-T P.800 /
P.808 / P.835 / P.910 rating methods (ACR, DCR, CCR), plus ABX.

One ``listening_test`` scheme covers them all (``method:``). The parts:

* :mod:`potato.listening.plan` -- what one participant hears on one item: the
  conditions, the hidden reference and anchors, and their order, seeded per
  (participant, item, scheme) so it is the same on every visit and in the
  export without being stored.
* :mod:`potato.listening.anchors` -- low-pass anchors cut from a WAV
  reference (3.5 kHz and 7 kHz in BS.1534-3).
* :mod:`potato.listening.routes` -- the plan and audio routes. The browser is
  given ``/api/listening/audio/<schema>/<item>/<slot>`` and never a file name,
  so a condition's identity (which sample is the reference, which codec is
  which) is not on the page.
* ``static/listening-test.js`` -- the player: every stimulus decoded into one
  Web Audio context, switching between them at the same position, looping a
  region, and tracking what has been played.
* :mod:`potato.export.listening_exporter` -- ratings by condition, means with
  95% intervals, ABX accuracy, and the BS.1534-3 post-screening rule.
"""
