"""
Initialize DB with user_config.json file.
"""

import json
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from potato.db_utils.models import User

Base = declarative_base()


def init_user_db(db_path, users_path):
    """
    Populate DB with users.
    """
    json_users = []
    with open(users_path, "r") as file_p:
        for line in file_p:
            json_users.append(json.loads(line))

    users = [
        User(
            username=json_user["username"],
            email=json_user["email"],
            password=json_user["password"],
        ) for json_user in json_users
    ]

    engine = create_engine("sqlite:///" + db_path)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine, tables=[User.__table__])
    with Session(engine) as session:
        session.add_all(users)
        session.commit()



def main():
    """ Driver """
    db_path = "/home/repos/potato/potato/database.db"
    users_filepath = "/home/repos/potato/potato/user_config.json"
    init_user_db(db_path, users_filepath)


if __name__ == "__main__":
    main()
