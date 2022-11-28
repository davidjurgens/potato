"""
Driver to run a flask server.
"""
import os
import re
import sys
import logging
import random
import json
from collections import deque, defaultdict, Counter, OrderedDict
from itertools import zip_longest
import string
import threading

import numpy as np
import pandas as pd
from tqdm import tqdm
from sklearn.pipeline import Pipeline
import krippendorff

import flask
from flask import Flask, render_template, request, current_app
from bs4 import BeautifulSoup

from potato.create_task_cli import create_task_cli, yes_or_no
from potato.server_utils.annotation_state_utils import (
    get_span_annotations_for_user_on,
    get_total_annotations,
    get_annotations_for_user_on,
    save_all_annotations,
    update_annotation_state,
)
from potato.app import create_app, db
from potato.db_utils.user_manager import UserManager
from potato.server_utils.arg_utils import arguments
from potato.server_utils.config_module import init_config, config
from potato.server_utils.front_end import generate_site, generate_surveyflow_pages
from potato.server_utils.prestudy import convert_labels
from potato.server_utils.schemas.span import render_span_annotations
from potato.server_utils.user_state_utils import (
    lookup_user_state,
    save_user_state,
    load_user_state,
    move_to_prev_instance,
    move_to_next_instance,
    go_to_id,
)
import potato.state as state

POTATO_HOME = os.environ.get("POTATO_HOME")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
logging.basicConfig()

random.seed(0)

DEFAULT_PORT = 8000
user_dict = {}

user_story_pos = defaultdict(lambda: 0, dict())
user_response_dicts_queue = defaultdict(deque)


# path to save user information
DEFAULT_LABELS_PER_INSTANCE = 3


# This variable of tyep ActiveLearningState keeps track of information on active
# learning, such as which instances were sampled according to each strategy
active_learning_state = None

# Hacky nonsense
schema_label_to_color = {}

COLOR_PALETTE = [
    "rgb(179,226,205)",
    "rgb(253,205,172)",
    "rgb(203,213,232)",
    "rgb(244,202,228)",
    "rgb(230,245,201)",
    "rgb(255,242,174)",
    "rgb(241,226,204)",
    "rgb(204,204,204)",
    "rgb(102, 197, 204)",
    "rgb(246, 207, 113)",
    "rgb(248, 156, 116)",
    "rgb(220, 176, 242)",
    "rgb(135, 197, 95)",
    "rgb(158, 185, 243)",
    "rgb(254, 136, 177)",
    "rgb(201, 219, 116)",
    "rgb(139, 224, 164)",
    "rgb(180, 151, 231)",
    "rgb(179, 179, 179)",
]



if __name__ == "__main__":
    args = arguments()
    init_config(args)
    if config.get("verbose"):
        logger.setLevel(logging.DEBUG)
    if config.get("very_verbose"):
        logger.setLevel(logging.NOTSET)

    app = create_app(os.path.join(POTATO_HOME, config["db_path"]))

else:
    app = Flask(__name__)

user_manager = UserManager(db)


class ActiveLearningState:
    """
    A class for maintaining state on active learning.
    """

    def __init__(self):
        self.id_to_selection_type = {}
        self.id_to_update_round = {}
        self.cur_round = 0

    def update_selection_types(self, id_to_selection_type):
        self.cur_round += 1

        for iid, st in id_to_selection_type.items():
            self.id_to_selection_type[iid] = st
            self.id_to_update_round[iid] = self.cur_round


def load_all_data(config):
    # Hacky nonsense
    global re_to_highlights

    # Where to look in the JSON item object for the text to annotate
    text_key = config["item_properties"]["text_key"]
    id_key = config["item_properties"]["id_key"]

    # Keep the data in the same order we read it in
    state.instance_id_to_data = OrderedDict()

    data_files = config["data_files"]
    logger.debug("Loading data from %d files" % (len(data_files)))

    for data_fname in data_files:

        fmt = data_fname.split(".")[-1]
        if fmt not in ["csv", "tsv", "json", "jsonl"]:
            raise Exception("Unsupported input file format %s for %s" % (fmt, data_fname))

        logger.debug("Reading data from " + data_fname)

        if fmt in ["json", "jsonl"]:
            with open(data_fname, "rt") as f:
                for line_no, line in enumerate(f):
                    item = json.loads(line)

                    # fix the encoding
                    # item[text_key] = item[text_key].encode("latin-1").decode("utf-8")

                    instance_id = item[id_key]

                    # TODO: check for duplicate instance_id
                    state.instance_id_to_data[instance_id] = item

        else:
            sep = "," if fmt == "csv" else "\t"
            # Ensure the key is loaded as a string form (prevents weirdness
            # later)
            df = pd.read_csv(data_fname, sep=sep, dtype={id_key: str, text_key: str})
            for _, row in df.iterrows():

                item = {}
                for c in df.columns:
                    item[c] = row[c]
                instance_id = row[id_key]

                # TODO: check for duplicate instance_id
                state.instance_id_to_data[instance_id] = item
            line_no = len(df)

        logger.debug("Loaded %d instances from %s" % (line_no, data_fname))

    # TODO Setup automatic test questions for each annotation schema,
    # currently we are doing it similar to survey flow to allow multilingual test questions
    if "surveyflow" in config and config["surveyflow"]["on"]:
        for test_file in config["surveyflow"].get("testing", []):
            with open(test_file, "r") as r:
                for line in r:
                    line = json.loads(line.strip())
                    for l in line["choices"]:
                        item = {
                            "id": line["id"] + "_testing_" + l,
                            "text": line["text"].replace("[test_question_choice]", l),
                        }
                        # currently we simply move all these test questions to the end of the instance list
                        state.instance_id_to_data.update({item["id"]: item})
                        state.instance_id_to_data.move_to_end(item["id"], last=True)

    # insert survey questions into state.instance_id_to_data
    for page in config.get("pre_annotation_pages", []):
        # TODO Currently we simply remove the language type before,
        # but we need a more elegant way for this in the future
        item = {"id": page, "text": page.split("-")[-1][:-5]}
        state.instance_id_to_data.update({page: item})
        state.instance_id_to_data.move_to_end(page, last=False)

    for it in ["prestudy_failed_pages", "prestudy_passed_pages"]:
        for page in config.get(it, []):
            # TODO Currently we simply remove the language type before -,
            # but we need a more elegant way for this in the future
            item = {"id": page, "text": page.split("-")[-1][:-5]}
            state.instance_id_to_data.update({page: item})
            state.instance_id_to_data.move_to_end(page, last=False)

    for page in config.get("post_annotation_pages", []):
        item = {"id": page, "text": page.split("-")[-1][:-5]}
        state.instance_id_to_data.update({page: item})
        state.instance_id_to_data.move_to_end(page, last=True)

    # Generate the text to display in state.instance_id_to_data
    for inst_id in state.instance_id_to_data:
        state.instance_id_to_data[inst_id]["displayed_text"] = get_displayed_text(
            state.instance_id_to_data[inst_id][config["item_properties"]["text_key"]]
        )

    # TODO: make this fully configurable somehow...
    re_to_highlights = defaultdict(list)
    if "keyword_highlights_file" in config:
        kh_file = config["keyword_highlights_file"]
        logger.debug("Loading keyword highlighting from %s" % (kh_file))

        with open(kh_file, "rt") as f:
            # TODO: make it flexible based on keyword
            df = pd.read_csv(kh_file, sep="\t")
            for i, row in df.iterrows():
                regex = r"\b" + row["Word"].replace("*", "[a-z]*?") + r"\b"
                re_to_highlights[regex].append((row["Schema"], row["Label"]))

        logger.debug(
            "Loaded %d regexes to map to %d labels for dynamic highlighting"
            % (len(re_to_highlights), i)
        )

    # Load the annotation assignment info if automatic task assignment is on.
    # Jiaxin: we are simply saving this as a json file at this moment
    if "automatic_assignment" in config and config["automatic_assignment"]["on"]:

        # path to save task assignment information
        task_assignment_path = os.path.join(
            config["output_annotation_dir"], config["automatic_assignment"]["output_filename"]
        )

        if os.path.exists(task_assignment_path):
            # load the task assignment if it has been generated and saved
            with open(task_assignment_path, "r") as r:
                state.task_assignment = json.load(r)
        else:
            # Otherwise generate a new task assignment dict
            state.task_assignment = {
                "assigned": {},
                "unassigned": {},
                "testing": {"test_question_per_annotator": 0, "ids": []},
                "prestudy_ids": [],
                "prestudy_passed_users": [],
                "prestudy_failed_users": [],
            }
            # Setting test_question_per_annotator if it is defined in automatic_assignment,
            # otherwise it is default to 0 and no test question will be used
            if "test_question_per_annotator" in config["automatic_assignment"]:
                state.task_assignment["testing"]["test_question_per_annotator"] = config[
                    "automatic_assignment"
                ]["test_question_per_annotator"]

            for it in ["pre_annotation", "prestudy_passed", "prestudy_failed", "post_annotation"]:
                if it + "_pages" in config:
                    state.task_assignment[it + "_pages"] = config[it + "_pages"]
                    for p in config[it + "_pages"]:
                        state.task_assignment["assigned"][p] = 0

            for _id in state.instance_id_to_data:
                if _id in state.task_assignment["assigned"]:
                    continue
                # add test questions to the assignment dict
                if re.search("testing", _id):
                    state.task_assignment["testing"]["ids"].append(_id)
                    continue
                if re.search("prestudy", _id):
                    state.task_assignment["prestudy_ids"].append(_id)
                    continue
                # set the total labels per instance, if not specified, default to 3
                state.task_assignment["unassigned"][_id] = (
                    config["automatic_assignment"]["labels_per_instance"]
                    if "labels_per_instance" in config["automatic_assignment"]
                    else DEFAULT_LABELS_PER_INSTANCE
                )


def get_agreement_score(user_list, schema_name, return_type="overall_average"):
    """
    Get the final agreement score for selected users and schemas.
    """
    if user_list == "all":
        user_list = state.user_to_annotation_state.keys()

    name2alpha = {}
    if schema_name == "all":
        for i in range(len(config["annotation_schemes"])):
            schema = config["annotation_schemes"][i]
            alpha = cal_agreement(user_list, schema["name"])
            name2alpha[schema["name"]] = alpha

    alpha_list = []
    if return_type == "overall_average":
        for name in name2alpha:
            alpha = name2alpha[name]
            if isinstance(alpha, dict):
                average_alpha = sum([it[1] for it in list(alpha.items())]) / len(alpha)
                alpha_list.append(average_alpha)
            elif isinstance(alpha, (np.floating, float)):
                alpha_list.append(alpha)
            else:
                continue
        if len(alpha_list) > 0:
            return round(sum(alpha_list) / len(alpha_list), 2)
        return "N/A"

    return name2alpha


def cal_agreement(user_list, schema_name, schema_type=None, selected_keys=None):
    """
    Calculate the krippendorff's alpha for selected users and schema.
    """
    # get the schema_type/annotation_type from the config file
    for i in range(len(config["annotation_schemes"])):
        schema = config["annotation_schemes"][i]
        if schema["name"] == schema_name:
            schema_type = schema["annotation_type"]
            break

    # obtain the list of keys for calculating IAA and the user annotations
    union_keys = set()
    user_annotation_list = []
    for user in user_list:
        if user not in state.user_to_annotation_state:
            print("%s not found in state.user_to_annotation_state" % user)
        user_annotated_ids = state.user_to_annotation_state[user].instance_id_to_labeling.keys()
        union_keys = union_keys | user_annotated_ids
        user_annotation_list.append(state.user_to_annotation_state[user].instance_id_to_labeling)

    if len(user_annotation_list) < 2:
        print("Cannot calculate agreement score for less than 2 users")
        return None

    # only calculate the agreement for selected keys when selected_keys is specified
    if selected_keys is None:
        selected_keys = list(union_keys)

    if len(selected_keys) == 0:
        print(
            "Cannot calculate agreement score when annotators work on different sets of instances"
        )
        return None

    if schema_type in ["radio", "likert"]:
        distance_metric_dict = {"radio": "nominal", "likert": "ordinal"}
        # initialize agreement data matrix
        l = []
        for _ in range(len(user_annotation_list)):
            l.append([np.nan] * len(selected_keys))

        for i, _selected_key in enumerate(selected_keys):
            for j in range(len(l)):
                if _selected_key in user_annotation_list[j]:
                    l[j][i] = convert_labels(
                        user_annotation_list[j][_selected_key][schema_name], schema_type
                    )
        alpha = krippendorff.alpha(
            np.array(l), level_of_measurement=distance_metric_dict[schema_type]
        )
        return alpha

    # When multiple labels are annotated for each instance, calculate the IAA for each label
    if schema_type == "multiselect":
        # collect the label list from configuration file
        if isinstance(schema["labels"][0], dict):
            labels = [it["name"] for it in schema["labels"]]
        elif isinstance(schema["labels"][0], str):
            labels = schema["labels"]
        else:
            print("Unknown label type in schema['labels']")
            return None

        # initialize agreement data matrix for each label
        l_dict = {}
        for l in labels:
            l_dict[l] = []
            for i in range(len(user_annotation_list)):
                l_dict[l].append([np.nan] * len(selected_keys))

        # consider binary agreement for each label in the multi-label schema
        for i, _selected_key in enumerate(selected_keys):
            for j in range(len(user_annotation_list)):
                if (_selected_key in user_annotation_list[j]) and (
                    schema_name in user_annotation_list[j][_selected_key]
                ):
                    annotations = convert_labels(
                        user_annotation_list[j][_selected_key][schema_name], schema_type
                    )
                    for l in labels:
                        l_dict[l][j][i] = 1
                        if l not in annotations:
                            l_dict[l][j][i] = 0

        alpha_dict = {}
        for key in labels:
            alpha_dict[key] = krippendorff.alpha(
                np.array(l_dict[key]), level_of_measurement="nominal"
            )
        return alpha_dict


def cal_amount(user):
    count = 0
    lines = user_dict[user]["user_data"]
    for key in lines:
        if lines[key]["annotated"]:
            count += 1
    return count


def find_start_id(user):
    """
    path = user_dict[user]["path"]
    # if not os.path.exists(path):
    #    initialize_user_data(path, user_dict[user]['user_id'])
    user_data = {}
    user_dict[user]["start_id"] = len(all_data["annotated_data"])
    lines = user_dict[user]["user_data"]
    for i in range(len(lines), 0):
        line = lines[str(i)]
        if not line["annotated"]:
            user_dict[user]["start_id"] = line["id"]
            return line["id"]
    # user_dict[user]['user_data'] = user_data
    """
    raise RuntimeError("This function is deprecated?")


# This was used to merge annotated instances in previous annotations.  For
# example, you had some annotations from google sheet, and want to merge it with
# the current annotation procedure
def merge_annotation():
    """
    global user_dict
    global all_data
    global args

    with open("merged_annotation.json", "w") as w:
        for i in range(len(all_data["annotated_data"])):
            line = all_data["annotated_data"][i]
            annotations = []
            for user in user_dict:
                if "label" in user_dict[user]["user_data"][str(i)]:
                    annotations.append(
                        {
                            "label": int(user_dict[user]["user_data"][str(i)]["label"]),
                            "user": int(user_dict[user]["user_id"]),
                        }
                    )
            line["annotations"] = annotations
            w.writelines(json.dumps(line) + "\n")
    """
    raise RuntimeError("This function is deprecated?")


def write_data(username):
    """
    global user_dict
    # global closed
    global all_data
    global args

    path = user_dict[username]["path"]
    with open(path, "w") as w:
        for line in user_dict[username]["user_data"]:
            line = json.dumps(user_dict[username]["user_data"][line])
            w.writelines(line + "\n")
    """
    raise RuntimeError("This function is deprecated?")


@app.route("/")
def home():
    if config["__debug__"]:
        print("debug user logging in")
        return annotate_page("debug_user", action="home")
    if "login" in config:
        if config["login"]["type"] == "url_direct":
            url_argument = (
                config["login"]["url_argument"] if "url_argument" in config["login"] else "username"
            )
            username = request.args.get(url_argument)
            print("url direct logging in with %s" % url_argument)
            return annotate_page(username, action="home")

    print("password logging in")
    return render_template("home.html", title=config["annotation_task_name"])


@app.route("/login", methods=["GET", "POST"])
def login():
    if config["__debug__"]:
        action = "login"
        username = "debug_user"
        password = "debug"
    elif "login" in config and config["login"]["type"] == "url_direct":
        action = request.form.get("action")
        username = request.form.get("email")
        password = "require_no_password"
    else:
        # Jiaxin: currently we are just using email as the username
        action = request.form.get("action")
        username = request.form.get("email")
        password = request.form.get("pass")

    if action == "login":

        with current_app.app_context():
            if (
                config["__debug__"]
                or ("login" in config and config["login"]["type"] == "url_direct")
                or user_manager.is_valid_password(username, password)
            ):
                # if surveyflow is setup, jump to the page before annotation
                print("%s login successful" % username)
                return annotate_page(username)

        return render_template(
            "home.html",
            title=config["annotation_task_name"],
            login_email=username,
            login_error="Invalid username or password",
        )
    print("unknown action at home page")
    return render_template("home.html", title=config["annotation_task_name"])


@app.route("/signup", methods=["GET", "POST"])
def signup():
    # TODO: add in logic for checking/hashing passwords, safe password
    # management, etc. For now just #yolo and log in people regardless.
    action = request.form.get("action")

    # Jiaxin: currently we are just using email as the username
    username = request.form.get("email")
    email = request.form.get("email")
    password = request.form.get("pass")
    print(action, username, password)

    if action == "signup":
        single_user = {"username": username, "email": email, "password": password}
        with current_app.app_context():
            try:
                user_manager.add_single_user(single_user)
            except ValueError as err:
                # TODO: return to the signup page and display error message
                return render_template(
                    "home.html",
                    title=config["annotation_task_name"],
                    login_error=str(err) + " Please try again or log in",
                )

        return render_template(
            "home.html",
            title=config["annotation_task_name"],
            login_email=username,
            login_error="User registration success for " + username + ", please login now",
        )

    print("unknown action at home page")
    return render_template(
        "home.html",
        title=config["annotation_task_name"],
        login_email=username,
        login_error="Invalid username or password",
    )


@app.route("/newuser")
def new_user():
    return render_template("newuser.html")


def get_cur_instance_for_user(username):
    user_state = lookup_user_state(username)

    return user_state.current_instance()


def previous_response(user, file_path):
    global user_story_pos
    global user_response_dicts_queue
    user_story_pos[user] -= 1

    with open(file_path, "r") as f:
        responses = f.readlines()[:-1]

    user_response_dicts_queue[user].pop()

    with open(file_path, "w") as f:
        for line in responses:
            f.write(line)


def get_displayed_text(text):
    # automatically unfold the text list when input text is a list (e.g. best-worst-scaling).
    if "list_as_text" in config and config["list_as_text"]:
        if isinstance(text, str):
            try:
                text = eval(text)
            except:
                text = str(text)
        if isinstance(text, list):
            if config["list_as_text"]["text_list_prefix_type"] == "alphabet":
                prefix_list = list(string.ascii_uppercase)
                text = [prefix_list[i] + ". " + text[i] for i in range(len(text))]
            elif config["list_as_text"]["text_list_prefix_type"] == "number":
                text = [str(i) + ". " + text[i] for i in range(len(text))]
            text = "<br>".join(text)

        # unfolding dict into different sections
        elif isinstance(text, dict):
            block = []
            if config["list_as_text"].get("horizontal"):
                for key in text:
                    block.append(
                        '<div name="instance_text" style="float:left;width:%s;padding:5px;" class="column"> <legend> %s </legend> %s </div>'
                        % ("%d" % int(100 / len(text)) + "%", key, text[key])
                    )
                text = '<div class="row" style="display: table"> %s </div>' % ("".join(block))
            else:
                for key in text:
                    block.append(
                        '<div name="instance_text"> <legend> %s </legend> %s <br/> </div>'
                        % (key, text[key])
                    )
                text = "".join(block)
        else:
            text = text
    return text


@app.route("/annotate", methods=["GET", "POST"])
def annotate_page(username=None, action=None):
    """
    Parses the input received from the user's annotation and takes some action
    based on what was clicked/typed. This method is the main switch for changing
    the state of the server for this user.
    """
    # use the provided username when the username is given
    if not username:
        if config["__debug__"]:
            username = "debug_user"
        else:
            username_from_last_page = request.form.get("email")
            if username_from_last_page is None:
                return render_template(
                    "error.html",
                    error_message="Please login to annotate or you are using the wrong link",
                )
            username = username_from_last_page

    # Check if the user is authorized. If not, go to the login page
    # if not user_manager.username_is_available(username):
    #    return render_template("home.html")

    # Based on what the user did to the instance, update the annotate state for
    # this instance. All of the instances clicks/checks/text are stored in the
    # request.form object, which has the name of the HTML element and its value.
    #
    # If the user actually changed the annotate state (as opposed to just moving
    # through instances), then save the state of the annotations.
    #
    # NOTE: I *think* this is safe from race conditions since the flask server
    # is running in a single thread, but it's probably good to check on this at
    # some point if we scale to having lots of concurrent users.
    if "instance_id" in request.form:
        did_change = update_annotation_state(username, request.form)

        if did_change:

            # Check if we need to run active learning to re-order instances. We
            # do this before saving the user state in case the order does change.o
            #
            # NOTE: In a perfect world, this would be done in a separate process
            # that is synchronized and users get their next instance from some
            # centrally managed queue so we don't block while doing all this
            # training. However, such advanced wizardry is beyond this MVP and
            # will have to wait
            if (
                "active_learning_config" in config
                and config["active_learning_config"]["enable_active_learning"]
            ):

                # Check to see if we've hit the threshold for the number of
                # annotations needed
                al_config = config["active_learning_config"]

                # How many total annotations do we need to have
                update_rate = al_config["update_rate"]
                total_annotations = get_total_annotations()

                if total_annotations % update_rate == 0:
                    actively_learn()

            save_user_state(username)

            # Save everything in a separate thread to avoid I/O issues
            th = threading.Thread(target=save_all_annotations)
            th.start()

    # AJYL: Note that action can still be None, if "src" not in request.form.
    # Not sure if this is intended.
    action = request.form.get("src") if action is None else action

    if action == "home":
        result_code = load_user_state(username)
        if result_code == "all instances have been assigned":
            return render_template(
                "error.html",
                error_message="Sorry that you come a bit late. We have collected enough responses for our study. However, prolific sometimes will recruit more participants than we expected. We are sorry for the inconvenience!",
            )

    elif action == "prev_instance":
        move_to_prev_instance(username)

    elif action == "next_instance":
        move_to_next_instance(username)

    elif action == "go_to":
        go_to_id(username, request.form.get("go_to"))

    else:
        print('unrecognized action request: "%s"' % action)

    instance = get_cur_instance_for_user(username)

    id_key = config["item_properties"]["id_key"]

    # directly display the prepared displayed_text
    instance_id = instance[id_key]
    text = instance["displayed_text"]

    # also save the displayed text in the metadata dict
    # state.instance_id_to_data[instance_id]['displayed_text'] = text

    # If the user has labeled spans within this instance before, replace the
    # current instance text with pre-annotated mark-up. We do this here before
    # the render_template call so that we can directly insert the span-marked-up
    # HTML into the template.
    #
    # NOTE: This currently requires a very tight (and kludgy) binding between
    # the UI code for how Potato represents span annotations and how the
    # back-end displays these. Future work when we are better programmers will
    # pass this info to client side for rendering, rather than doing
    # pre-rendering here. This also means that any changes to the UI code for
    # rendering need to be updated here too.
    #
    # NOTE2: We have to this here to account for any keyword highlighting before
    # the instance text gets marked up in the post-processing below
    span_annotations = get_span_annotations_for_user_on(username, instance_id)
    if span_annotations is not None and len(span_annotations) > 0:
        # Mark up the instance text where the annotated spans were
        text = render_span_annotations(text, span_annotations)

    # If the admin has specified that certain keywords need to be highlighted,
    # post-process the selected instance so that it now also has colored span
    # overlays for keywords.
    #
    # NOTE: this code is probably going to break the span annotation's
    # understanding of the instance. Need to check this...
    updated_text, schema_labels_to_highlight = text, set()
    if "keyword_highlights_file" in config:
        updated_text, schema_labels_to_highlight = post_process(config, text)

    # Fill in the kwargs that the user wanted us to include when rendering the page
    kwargs = {}
    for _kw in config["item_properties"].get("kwargs", []):
        kwargs[_kw] = instance[_kw]

    all_statistics = lookup_user_state(username).generate_user_statistics()

    # TODO: Display plots for agreement scores instead of only the overall score
    # in the statistics sidebar
    # all_statistics['Agreement'] = get_agreement_score('all', 'all', return_type='overall_average')
    # print(all_statistics)

    # Set the html file as surveyflow pages when the instance is a not an
    # annotation page (survey pages, prestudy pass or fail page)
    if instance_id in config.get("non_annotation_pages", []):
        html_file = instance_id
    # otherwise set the page as the normal annotation page
    else:
        html_file = config["site_file"]

    # Flask will fill in the things we need into the HTML template we've created,
    # replacing {{variable_name}} with the associated text for keyword arguments
    rendered_html = render_template(
        html_file,
        username=username,
        # This is what instance the user is currently on
        instance=text,
        instance_obj=instance,
        instance_id=lookup_user_state(username).get_instance_cursor(),
        finished=lookup_user_state(username).get_instance_cursor(),
        total_count=lookup_user_state(username).get_assigned_instance_count(),
        alert_time_each_instance=config["alert_time_each_instance"],
        statistics_nav=all_statistics,
        **kwargs
    )

    with open("debug-pre.html", "wt") as outf:
        outf.write(rendered_html)

    # UGHGHGHGH the tempalte does unusual escaping, which makes it a PAIN to do
    # the replacement later
    # m = re.search('<div name="instance_text">(.*?)</div>', rendered_html,
    #              flags=(re.DOTALL|re.MULTILINE))
    # text = m.group(1)

    # For whatever reason, doing this before the render_template causes the
    # embedded HTML to get escaped, so we just do a wholesale replacement here.
    rendered_html = rendered_html.replace(text, updated_text)

    with open("debug-pre.html", "wt") as outf:
        outf.write(rendered_html)

    # Parse the page so we can programmatically reset the annotation state
    # to what it was before
    soup = BeautifulSoup(rendered_html, "html.parser")

    # Highlight the schema's labels as necessary
    for schema, label in schema_labels_to_highlight:

        name = schema + ":::" + label
        label_elem = soup.find("label", {"for": name})

        # Update style to match the current color
        c = get_color_for_schema_label(schema, label)

        # Jiaxin: sometimes label_elem is None
        if label_elem:
            label_elem["style"] = "background-color: %s" % c

    # If the user has annotated this before, walk the DOM and fill out what they
    # did
    annotations = get_annotations_for_user_on(username, instance_id)
    if annotations is not None:
        # Reset the state
        for schema, labels in annotations.items():
            for label, value in labels.items():
                name = schema + ":::" + label
                # select input, select and textarea tags
                input_field = soup.find_all(["input", "select", "textarea"], {"name": name})[0]
                if input_field is None:
                    print("No input for ", name)
                    continue
                input_field["checked"] = True
                input_field["value"] = value
                # set the input value for textarea input
                if input_field.name == "textarea":
                    input_field.string = value
                # find the right option and set it as selected if the current
                # annotation schema is a select box
                if label == "select-one":
                    option = input_field.findChildren("option", {"value": value})[0]
                    option["selected"] = "selected"

    rendered_html = str(soup)  # soup.prettify()

    with open("debug.html", "wt") as outf:
        outf.write(rendered_html)

    return rendered_html


def get_color_for_schema_label(schema, label):
    global schema_label_to_color

    t = (schema, label)
    if t in schema_label_to_color:
        return schema_label_to_color[t]
    c = COLOR_PALETTE[len(schema_label_to_color)]
    schema_label_to_color[t] = c
    return c


def post_process(config, text):
    global schema_label_to_color

    schema_labels_to_highlight = set()

    all_words = list(set(re.findall(r"\b[a-z]{4,}\b", text)))
    all_words = [w for w in all_words if not w.startswith("http")]
    random.shuffle(all_words)

    all_schemas = list([x[0] for x in re_to_highlights.values()])

    # Grab the highlights
    for regex, labels in re_to_highlights.items():

        search_from = 0

        regex = re.compile(regex, re.I)

        while True:
            try:
                match = regex.search(text, search_from)
            except BaseException as e:
                print(repr(e))
                break

            if match is None:
                break

            start = match.start()
            end = match.end()

            # we're going to replace this instance with a color coded one
            if len(labels) == 1:
                schema, label = labels[0]

                schema_labels_to_highlight.add((schema, label))

                c = get_color_for_schema_label(schema, label)

                pre = '<span style="background-color: %s">' % c

                replacement = pre + match.group() + "</span>"

                text = text[:start] + replacement + text[end:]

                # Be sure to count all the junk we just added when searching again
                search_from += end + (len(replacement) - len(match.group()))

            # slightly harder, but just to get the MVP out
            elif len(labels) == 2:

                colors = []

                for schema, label in labels:
                    schema_labels_to_highlight.add((schema, label))
                    c = get_color_for_schema_label(schema, label)
                    colors.append(c)

                matched_word = match.group()

                first_half = matched_word[: int(len(matched_word) / 2)]
                last_half = matched_word[int(len(matched_word) / 2) :]

                pre = '<span style="background-color: %s;">'

                replacement = (
                    (pre % colors[0])
                    + first_half
                    + "</span>"
                    + (pre % colors[1])
                    + last_half
                    + "</span>"
                )

                text = text[:start] + replacement + text[end:]

                # Be sure to count all the junk we just added when searching again
                search_from += end + (len(replacement) - len(matched_word))

            # Gotta make this hard somehow...
            else:
                search_from = end

    # Pick a few random words to highlight
    #
    # NOTE: we do this after the label assignment because if we somehow screw up
    # and wrongly flag a valid word, this coloring is embedded within the outer
    # (correct) <span> tag, so the word will get labeled correctly
    num_false_labels = random.randint(0, 1)

    for i in range(min(num_false_labels, len(all_words))):

        # Pick a random word
        to_highlight = all_words[i]

        # Pick a random schema and label
        schema, label = random.choice(all_schemas)
        schema_labels_to_highlight.add((schema, label))

        # Figure out where this word occurs
        c = get_color_for_schema_label(schema, label)

        search_from = 0
        regex = r"\b" + to_highlight + r"\b"
        regex = re.compile(regex, re.I)

        while True:
            try:
                match = regex.search(text, search_from)
            except BaseException as e:
                print(repr(e))
                break
            if match is None:
                break

            start = match.start()
            end = match.end()

            pre = '<span style="background-color: %s">' % c

            replacement = pre + match.group() + "</span>"
            text = text[:start] + replacement + text[end:]

            # Be sure to count all the junk we just added when searching again
            search_from += end + (len(replacement) - len(match.group()))

    return text, schema_labels_to_highlight


def parse_story_pair_from_file(filepath):
    with open(filepath, "r") as f:
        lines = f.readlines()
    lines = [l.strip("\n").split("\t") for l in lines]
    return lines


@app.route("/files/<path:filename>")
def get_file(filename):
    """Make files available for annotation access from a folder."""
    try:
        return flask.send_from_directory("../data/files/", filename)
    except FileNotFoundError:
        flask.abort(404)


def get_class(kls):
    """
    Returns an instantiated class object from a fully specified name.
    """
    parts = kls.split(".")
    module = ".".join(parts[:-1])
    m = __import__(module)
    for comp in parts[1:]:
        m = getattr(m, comp)
    return m


def actively_learn():
    if "active_learning_config" not in config:
        logger.warning(
            "the server is trying to do active learning " + "but this hasn't been configured"
        )
        return

    al_config = config["active_learning_config"]

    # Skip if the user doesn't want us to do active learning
    if "enable_active_learning" in al_config and not al_config["enable_active_learning"]:
        return

    if "classifier_name" not in al_config:
        raise Exception('active learning enabled but no classifier is set with "classifier_name"')

    if "vectorizer_name" not in al_config:
        raise Exception('active learning enabled but no vectorizer is set with "vectorizer_name"')

    if "resolution_strategy" not in al_config:
        raise Exception("active learning enabled but resolution_strategy is not set")

    # This specifies which schema we need to use in active learning (separate
    # classifiers for each). If the user doesn't specify these, we use all of
    # them.
    schema_used = []
    if "active_learning_schema" in al_config:
        schema_used = al_config["active_learning_schema"]

    cls_kwargs = al_config.get("classifier_kwargs", {})
    cls_kwargs = al_config.get("classifier_kwargs", {})
    vectorizer_kwargs = al_config.get("vectorizer_kwargs", {})
    strategy = al_config["resolution_strategy"]

    # Collect all the current labels
    instance_to_labels = defaultdict(list)
    for uas in state.user_to_annotation_state.values():
        for iid, annotation in uas.instance_id_to_labeling.items():
            instance_to_labels[iid].append(annotation)

    # Resolve all the mutiple-annotations to a single one using the provided
    # strategy to get training data
    instance_to_label = {}
    schema_seen = set()
    for iid, annotations in instance_to_labels.items():
        resolved = resolve(annotations, strategy)

        # Prune to just the schema we care about
        if len(schema_used) > 0:
            resolved = {k: resolved[k] for k in schema_used}

        for s in resolved:
            schema_seen.add(s)
        instance_to_label[iid] = resolved

    # Construct a dataframe for easy processing
    texts = []
    # We'll train one classifier for each scheme
    scheme_to_labels = defaultdict(list)
    text_key = config["item_properties"]["text_key"]
    for iid, schema_to_label in instance_to_label.items():
        # get the text
        text = state.instance_id_to_data[iid][text_key]
        texts.append(text)
        for s in schema_seen:
            # In some cases where the user has not selected anything but somehow
            # this is considered annotated, we include some dummy label
            label = schema_to_label.get(s, "DUMMY:NONE")

            # HACK: this needs to get fixed for multilabel data and possibly
            # number data
            label = list(label.keys())[0]
            scheme_to_labels[s].append(label)

    scheme_to_classifier = {}

    # Train a classifier for each scheme
    for scheme, labels in scheme_to_labels.items():

        # Sanity check we have more than 1 label
        label_counts = Counter(labels)
        if len(label_counts) < 2:
            logger.warning(
                (
                    "In the current data, data labeled with %s has only a"
                    + "single unique label, which is insufficient for "
                    + "active learning; skipping..."
                )
                % scheme
            )
            continue

        # Instantiate the classifier and the tokenizer
        cls = get_class(al_config["classifier_name"])(**cls_kwargs)
        vectorizer = get_class(al_config["vectorizer_name"])(**vectorizer_kwargs)

        # Train the classifier
        clf = Pipeline([("vectorizer", vectorizer), ("classifier", cls)])
        logger.info("training classifier for %s..." % scheme)
        clf.fit(texts, labels)
        logger.info("done training classifier for %s" % scheme)
        scheme_to_classifier[scheme] = clf

    # Get the remaining unlabeled instances and start predicting
    unlabeled_ids = [iid for iid in state.instance_id_to_data if iid not in instance_to_label]
    random.shuffle(unlabeled_ids)

    perc_random = al_config["random_sample_percent"] / 100

    # Split to keep some of the data random
    random_ids = unlabeled_ids[int(len(unlabeled_ids) * perc_random) :]
    unlabeled_ids = unlabeled_ids[: int(len(unlabeled_ids) * perc_random)]
    remaining_ids = []

    # Cap how much inference we need to do (important for big datasets)
    if "max_inferred_predictions" in al_config:
        max_insts = al_config["max_inferred_predictions"]
        remaining_ids = unlabeled_ids[max_insts:]
        unlabeled_ids = unlabeled_ids[:max_insts]

    # For each scheme, use its classifier to label the data
    scheme_to_predictions = {}
    unlabeled_texts = [state.instance_id_to_data[iid][text_key] for iid in unlabeled_ids]
    for scheme, clf in scheme_to_classifier.items():
        logger.info("Inferring labels for %s" % scheme)
        preds = clf.predict_proba(unlabeled_texts)
        scheme_to_predictions[scheme] = preds

    # Figure out which of the instances to prioritize, keeping the specified
    # ratio of random-vs-AL-selected instances.
    ids_and_confidence = []
    logger.info("Scoring items by model confidence")
    for i, iid in enumerate(tqdm(unlabeled_ids)):
        most_confident_pred = 0
        mp_scheme = None
        for scheme, all_preds in scheme_to_predictions.items():

            preds = all_preds[i, :]
            mp = max(preds)
            if mp > most_confident_pred:
                most_confident_pred = mp
                mp_scheme = scheme
        ids_and_confidence.append((iid, most_confident_pred, mp_scheme))

    # Sort by confidence
    ids_and_confidence = sorted(ids_and_confidence, key=lambda x: x[1])

    # Re-order all of the unlabeled instances
    new_id_order = []
    id_to_selection_type = {}
    for (al, rand_id) in zip_longest(ids_and_confidence, random_ids, fillvalue=None):
        if al:
            new_id_order.append(al[0])
            id_to_selection_type[al[0]] = "%s Classifier" % al[2]
        if rand_id:
            new_id_order.append(rand_id)
            id_to_selection_type[rand_id] = "Random"

    # These are the IDs that weren't in the random sample or that we didn't
    # reorder with active learning
    new_id_order.extend(remaining_ids)

    # Update each user's ordering, preserving the order for any item that has
    # any annotation so that it stays in the front of the users' queues even if
    # they haven't gotten to it yet (but others have)
    already_annotated = list(instance_to_labels.keys())
    for annotation_state in state.user_to_annotation_state.values():
        annotation_state.reorder_remaining_instances(new_id_order, already_annotated)

    logger.info("Finished reording instances")


def resolve(annotations, strategy):
    if strategy == "random":
        return random.choice(annotations)
    raise Exception('Unknonwn annotation resolution strategy: "%s"' % (strategy))


def run_create_task_cli():
    """
    Run create_task_cli().
    """
    if yes_or_no("Launch task creation process?"):
        if yes_or_no("Launch on command line?"):
            create_task_cli()
        else:
            # Probably need to launch the Flask server to accept form inputs
            raise Exception("Gui-based design not supported yet.")


def run_server():
    """
    Run Flask server.
    """
    # Creates the templates we'll use in flask by mashing annotation
    # specification on top of the proto-templates
    generate_site(config)
    if "surveyflow" in config and config["surveyflow"]["on"]:
        generate_surveyflow_pages(config)

    # Generate the output directory if it doesn't exist yet
    if not os.path.exists(config["output_annotation_dir"]):
        os.makedirs(config["output_annotation_dir"])

    # Loads the training data
    load_all_data(config)

    # load users with annotations to state.user_to_annotation_state
    users_with_annotations = [
        f
        for f in os.listdir(config["output_annotation_dir"])
        if os.path.isdir(config["output_annotation_dir"] + f)
    ]
    for user in users_with_annotations:
        load_user_state(user)

    # TODO: load previous annotation state
    # load_annotation_state(config)

    flask_logger = logging.getLogger("werkzeug")
    flask_logger.setLevel(logging.ERROR)

    port = args.port or config.get("port", DEFAULT_PORT)
    print("running at:\nlocalhost:" + str(port))
    app.run(debug=args.very_verbose, host="0.0.0.0", port=port)


def main():
    if len(sys.argv) == 1:
        # Run task configuration script if no arguments are given.
        return run_create_task_cli()

    run_server()


if __name__ == "__main__":
    main()
