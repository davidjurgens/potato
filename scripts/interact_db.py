"""
Module Doc String
"""

from sqlalchemy import select
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from potato.db_utils.models.users import User
from potato.db_utils.models.user_annotation_state import UserAnnotationState




def main():
    """ Driver """
    db_path = "/home/repos/potato/example-projects/dialogue_analysis/database.db"

    engine = create_engine("sqlite:///" + db_path)
    with Session(engine) as sess:
        user_query = select(User)
        users = sess.execute(user_query).scalars().all()

        user_state_query = select(UserAnnotationState)
        user_states = sess.execute(user_state_query).scalars().all()
        print(users)
        print(user_states)
        breakpoint()
        print("test")

if __name__ == "__main__":
    main()

