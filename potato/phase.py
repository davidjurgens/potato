from __future__ import annotations
from enum import Enum

class UserPhase(Enum):
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
        '''Converts a string to a UserPhase enum'''
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
        return self.value