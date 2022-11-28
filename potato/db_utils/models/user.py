"""
SQLAlchemy model for users.
"""

from potato.db import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

    # TODO: This means each user and only have a single annotation-state across
    # every project/task/server, etc.
    # Either we keep project-specific users (ie, users have to create an
    # account per project) or have a mapping from users to projects,
    # and map users to annotation states per project.
    annotation_state = db.relationship(
        "UserAnnotationState", backref="user", uselist=False, lazy=True
    )

    def __repr__(self):
        return f"<User {self.username}: {self.email}>"
