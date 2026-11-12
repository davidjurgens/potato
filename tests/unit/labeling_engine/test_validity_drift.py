"""
The drift monitor's confidence sequence: valid at every step at once, and
quick to notice a real rise in the error rate.
"""

import numpy as np

from potato.labeling_engine.audit.drift import confidence_sequence, monitor


def test_sequence_covers_the_truth_at_every_step():
    rng = np.random.default_rng(0)
    alpha, trials, n = 0.1, 300, 400
    misses = 0
    for _ in range(trials):
        p = 0.08
        xs = (rng.random(n) < p).astype(float)
        cs = confidence_sequence(xs, alpha)
        if any(not (lo <= p <= hi) for lo, hi in cs):
            misses += 1
    # Uniformly over time, not per step: at most alpha of whole paths miss.
    assert misses / trials <= alpha + 3 * np.sqrt(alpha * (1 - alpha) / trials)


def test_a_per_step_interval_would_false_alarm():
    """The guard: an ordinary 90% interval checked at every step misses far
    more often than 10% over a long run."""
    rng = np.random.default_rng(1)
    trials, n, p = 200, 400, 0.08
    misses = 0
    for _ in range(trials):
        xs = (rng.random(n) < p).astype(float)
        for t in range(10, n):
            m = xs[:t].mean()
            se = np.sqrt(max(m * (1 - m), 1e-9) / t)
            if not (m - 1.645 * se <= p <= m + 1.645 * se):
                misses += 1
                break
    assert misses / trials > 0.3


def test_monitor_flags_a_shift_and_not_a_steady_rate():
    rng = np.random.default_rng(2)
    steady = (rng.random(300) < 0.04).astype(int)
    assert monitor(steady, error=0.1, confidence=0.9)["breach"] is False
    shifted = np.concatenate([(rng.random(100) < 0.04), (rng.random(300) < 0.3)]).astype(int)
    m = monitor(shifted, error=0.1, confidence=0.9)
    assert m["breach"] and m["breach_at"] > 100
