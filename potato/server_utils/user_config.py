"""
UserConfig
"""
import os
import json


class UserConfig:
    """
    A class for maintaining state on which users are allowed to use the system.
    """

    def __init__(self, user_config_path="potato/user_config.json"):
        self.allow_all_users = False
        self.user_config_path = user_config_path
        self.userlist = []
        self.usernames = set()
        self.users = {}
        self.required_user_info_keys = ["username", "password"]

        if os.path.isfile(self.user_config_path):
            print("Loading users from" + self.user_config_path)
            with open(self.user_config_path, "rt") as file_p:
                for line in file_p.readlines():
                    single_user = json.loads(line.strip())
                    self.add_single_user(single_user)

    # Jiaxin: this function will be depreciate since we will save
    # the full user dict with password
    def add_user(self, username):
        """
        Add user.
        """
        if username in self.usernames:
            print("Duplicate user in list: %s" % username)
        self.usernames.add(username)

    def add_single_user(self, single_user):
        """
        Add a single user to the full user dict.
        """
        for key in self.required_user_info_keys:
            if key not in single_user:
                print("Missing %s in user info" % key)
                return "Missing %s in user info" % key
        if single_user["username"] in self.users:
            print("Duplicate user in list: %s" % single_user["username"])
            return "Duplicate user in list: %s" % single_user["username"]
        self.users[single_user["username"]] = single_user
        self.userlist.append(single_user["username"])
        return "Success"

    def save_user_config(self):
        """
        Dump user config to file.
        """
        if self.user_config_path:
            with open(self.user_config_path, "wt") as file_p:
                for k in self.userlist:
                    file_p.writelines(json.dumps(self.users[k]) + "\n")
            print("user info file saved at:", self.user_config_path)
        else:
            print("WARNING: user_config_path not specified, user registration info are not saved")

    def is_valid_username(self, username):
        """
        Check if a user name is in the current user list.
        """
        return username in self.users

    # TODO: Currently we are just doing simple plaintext verification,
    # but we will need ciphertext verification in the long run
    def is_valid_password(self, username, password):
        """
        Check if the password is correct for a given (username, password) pair.
        """
        return self.is_valid_username(username) and self.users[username]["password"] == password

    def is_valid_user(self, username):
        """
        Check if username is a valid user.
        """
        return self.allow_all_users or username in self.usernames
