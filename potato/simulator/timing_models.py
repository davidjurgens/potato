"""
Timing models for simulated annotation behavior.

This module provides realistic timing distributions for simulated
annotations, supporting various statistical distributions.
"""

import random
import time
from typing import Optional

from .config import TimingConfig


class TimingModel:
    """Model for generating realistic annotation timing.

    Supports multiple distribution types:
    - uniform: Random time uniformly distributed between min and max
    - normal: Gaussian distribution with configurable mean and std
    - exponential: Exponential distribution for realistic variability
    """

    def __init__(self, config: TimingConfig):
        """Initialize timing model.

        Args:
            config: TimingConfig with distribution parameters
        """
        self.config = config

    def get_annotation_time(self) -> float:
        """Generate annotation time based on configured distribution.

        Returns:
            Annotation time in seconds
        """
        if self.config.distribution == "uniform":
            return random.uniform(
                self.config.annotation_time_min, self.config.annotation_time_max
            )

        elif self.config.distribution == "normal":
            time_val = random.gauss(
                self.config.annotation_time_mean, self.config.annotation_time_std
            )
            # Clamp to min/max
            return max(
                self.config.annotation_time_min,
                min(self.config.annotation_time_max, time_val),
            )

        elif self.config.distribution == "exponential":
            # Exponential distribution with mean at annotation_time_mean
            rate = 1.0 / self.config.annotation_time_mean
            time_val = random.expovariate(rate)
            # Clamp to min/max
            return max(
                self.config.annotation_time_min,
                min(self.config.annotation_time_max, time_val),
            )

        # Default fallback
        return self.config.annotation_time_mean

    def get_fast_response_time(self) -> float:
        """Generate a suspiciously fast response time.

        Used for testing quality control fast-response detection.

        Returns:
            Fast response time in seconds (below threshold)
        """
        return random.uniform(0.1, self.config.fast_response_threshold * 0.9)

    def should_respond_fast(self, fast_response_rate: float) -> bool:
        """Determine if this should be a fast response.

        Args:
            fast_response_rate: Probability of fast response (0-1)

        Returns:
            True if this should be a fast response
        """
        return random.random() < fast_response_rate

    def wait(self, duration: Optional[float] = None) -> float:
        """Wait for the specified or generated duration.

        Args:
            duration: Specific duration in seconds, or None to generate

        Returns:
            The actual duration waited
        """
        if duration is None:
            duration = self.get_annotation_time()
        time.sleep(duration)
        return duration

    def get_response_time(self, fast_response_rate: float = 0.0) -> float:
        """Get response time, possibly fast for QC testing.

        Args:
            fast_response_rate: Probability of suspiciously fast response

        Returns:
            Response time in seconds
        """
        if self.should_respond_fast(fast_response_rate):
            return self.get_fast_response_time()
        return self.get_annotation_time()


class NoWaitTimingModel(TimingModel):
    """Timing model that records times but doesn't wait.

    Useful for fast testing where we want to track timing statistics
    but don't want to actually delay execution.
    """

    def wait(self, duration: Optional[float] = None) -> float:
        """Record but don't actually wait.

        Args:
            duration: Duration to record (or generate)

        Returns:
            The duration that would have been waited
        """
        if duration is None:
            duration = self.get_annotation_time()
        return duration
