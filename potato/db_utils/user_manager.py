"""
Interface for user db.
"""
from typing import Mapping
from potato.db_utils.models.user import User


class UserManager:
    def __init__(self, db):
        self.db = db
        self.allow_all_users = False
        self.required_info = ["username", "email", "password"]

    def add_single_user(self, new_user: Mapping):
        """
        Add a single user.
        """
        for key in self.required_info:
            if key not in new_user:
                raise ValueError("Missing %s in user info." % key)

        if self._get_user(new_user["username"]) is not None:
            raise ValueError("User %s already exists!" % new_user["username"])

        user = User(
            username=new_user["username"],
            email=new_user["email"],
            password=new_user["password"],
        )
        self.db.session.add(user)
        self.db.session.commit()

    def username_is_available(self, username: str):
        """
        Check if username already exists.
        """
        return self._get_user(username) is None

    def is_valid_password(self, username: str, password: str):
        """
        Check if password is correct.
        """
        user = self._get_user(username)
        return user is not None and user.password == password

    def is_valid_user(self, username: str):
        """
        Check if username is a valid user.
        """
        return self.allow_all_users or self._get_user(username) is not None

    def set_allow_all_users(self, value):
        """
        Setter for allow_all_users.
        """
        self.allow_all_users = value

    def _get_user(self, username: str):
        """
        Get users in database.
        """
        return User.query.filter_by(username=username).first()

    def _get_all_users(self):
        """
        Get all users in the database.
        """
        return User.query.all()
