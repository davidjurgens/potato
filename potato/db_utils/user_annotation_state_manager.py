"""
Interface for UserAnnotationState.
"""
from typing import Mapping
from potato.db_utils.models.user_annotation_state import UserAnnotationState


class UserAnnotationStateManager:
    def __init__(self, db):
        self.db = db

    def add(self, assigned_user_data):
        """
        Add user annotation state.
        """
        user_annotation_state = UserAnnotationState(assigned_user_data)
        self.db.session.add(user_annotation_state)
        self.db.session.commit()
        return user_annotation_state
