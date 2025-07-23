"""
User Phase Management System

This module defines the phases that users progress through during the annotation process.
Each phase represents a distinct stage in the annotation workflow, from initial login
to completion of the annotation task.

The phase system supports multi-page phases where users may need to complete multiple
pages within a single phase type (e.g., multiple instruction pages).
"""

from __future__ import annotations
from enum import Enum

class UserPhase(Enum):
    """
    Enumeration of user phases in the annotation workflow.

    Each phase represents a distinct stage that users must complete before
    proceeding to the next phase. The phases are processed in order:
    LOGIN -> CONSENT -> PRESTUDY -> INSTRUCTIONS -> TRAINING -> ANNOTATION -> POSTSTUDY -> DONE

    Attributes:
        LOGIN: Initial authentication phase
        CONSENT: User consent and agreement phase
        PRESTUDY: Pre-study questions or screening phase
        INSTRUCTIONS: Task instructions and guidelines phase
        TRAINING: Practice/training examples phase
        ANNOTATION: Main annotation task phase
        POSTSTUDY: Post-study questions or feedback phase
        DONE: Completion phase
    """
    LOGIN = 'login'
    CONSENT = 'consent'
    PRESTUDY = 'prestudy'
    INSTRUCTIONS = 'instructions'
    TRAINING = 'training'
    ANNOTATION =  'annotation'
    POSTSTUDY = 'poststudy'
    DONE = 'done'

    #@classmethod
    #def list(cls):
    #    return list(map(lambda c: c.value, cls))

    def fromstr(phase: str) -> UserPhase:
        """
        Convert a string representation to a UserPhase enum value.

        This method provides a safe way to convert string inputs (e.g., from
        configuration files or API requests) to UserPhase enum values.

        Args:
            phase: String representation of the phase (case-insensitive)

        Returns:
            UserPhase: The corresponding enum value

        Raises:
            ValueError: If the string doesn't match any known phase

        Example:
            >>> UserPhase.fromstr("annotation")
            <UserPhase.ANNOTATION: 'annotation'>
        """
        phase = phase.lower()
        if phase == "login":
            return UserPhase.LOGIN
        elif phase == "consent":
            return UserPhase.CONSENT
        elif phase == "prestudy":
            return UserPhase.PRESTUDY
        elif phase == "instructions":
            return UserPhase.INSTRUCTIONS
        elif phase == "training":
            return UserPhase.TRAINING
        elif phase == "annotation":
            return UserPhase.ANNOTATION
        elif phase == "poststudy":
            return UserPhase.POSTSTUDY
        else:
            raise ValueError(f"Unknown phase: {phase}")

    def __str__(self) -> str:
        """
        Return the string representation of the phase.

        Returns:
            str: The phase name as a string
        """
        return self.value