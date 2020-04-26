import socketserver
import os
import sys
import numpy as np
from flask import Flask, render_template, request, url_for, jsonify

import yaml

from os.path import basename

import logging

# import requests
import random
import time
import json
import gzip
from datetime import datetime
from collections import deque, defaultdict
from argparse import ArgumentParser

# import choix
# import networkx as nx


domain_file_path = ""
file_list = []
file_list_size = 0
default_port = 8000
user_dict = {}

file_to_read_from = ""
MAX_STORY_LENGTH = 99999  # No limit
NUM_STORIES_TO_READ = 999999999  # No limit

all_data = {}

user_story_set = {}
user_story_pos = defaultdict(lambda: 0, dict())
user_file_written_map = defaultdict(dict)
user_current_story_dict = {}
user_response_dicts_queue = defaultdict(deque)

curr_user_story_similarity = {}

minimum_list = 30

SHOW_PATH = False
SHOW_SIMILARITY = False
FIRST_LOAD = True
# QUESTION_START = True
closed = False

config = None

app = Flask(__name__)

def choose_file(files):
    chosen_file_id = random.randint(0, len(files) - 1)
    return files[chosen_file_id]


def generate_pairs(line):
    tuples = []
    for i in range(4):
        if line[4] != line[i]:
            tuples.append((line[4], line[i]))
            if line[5] != line[i]:
                tuples.append((line[i], line[5]))
    return tuples


def load_all_data(config):
    global annotate_state # formerly known as user_state
    global all_data
    global logger
    
    # Where to look in the JSON item object for the text to annotate
    text_key = config['item_properties']['text_key']
    
    items_to_annotate = []

    data_files = config['data_files']
    logger.debug('Loading data from %d files' % (len(data_files)))

    for data_fname in data_files:
        logger.debug('Reading data from ' + data_fname)
        with open(data_fname, "rt") as f:
            for line_no, line in enumerate(f):
                item = json.loads(line)

                # fix the encoding            
                # item[text_key] = item[text_key].encode("latin-1").decode("utf-8")           

                items_to_annotate.append(item)
                
        logger.debug('Loaded %d instances from %s' % (line_no, data_fname))
    all_data["items_to_annotate"] = items_to_annotate


    # This keeps track of what was done in the past so we can rewind and make
    # sense of what has happened
    state_filename = config['annotation_state_file']
    if os.path.exists(state_filename):
        logger.info("Loading prior annotation state from %s" % state_filename)
        # REMINDER: we probably want to make this some kind of multi-file
        # directory so we can cache stuff for the curriculum learning (e.g.,
        # internal train splits, etc.)
        with open(config.annotation_state_file, 'rt') as f:
            annotate_state = json.load(f)
    else:
        logger.info("No prior annotate state seen; starting annotation from scratch")
            

    
    
def old_load_user_data():
    def initialize_user_data(path, user_id):
        with open(path, "w") as w:
            i = 0
            for line in annotated_data:
                new_line = {"id": i, "line": line, "annotated": False}
                for it in line["annotations"]:
                    if int(it["user"]) == int(user_id):
                        new_line["annotated"] = True
                        new_line["label"] = it["label"]
                i += 1
                w.writelines(json.dumps(new_line) + "\n")
                
    id2user = {}
    # load user data
    for user in user_dict:
        path = user_dict[user]["path"]
        if not os.path.exists(path):
            initialize_user_data(path, user_dict[user]["user_id"])
        user_data = {}
        user_dict[user]["start_id"] = len(all_data["annotated_data"])
        story = []
        ism = ""

        with open(path, "r") as r:
            lines = r.readlines()
            flag = True
            for line in lines:
                line = json.loads(line.strip())
                user_data[str(line["id"])] = line
                if flag and "label" not in line:
                    user_dict[user]["start_id"] = line["id"]
                    story = all_data["annotated_data"][
                        int(user_dict[user]["start_id"])
                    ]["text"].split("<SPLIT_TOKEN>")
                    flag = False

            user_dict[user]["start_id"] = len(lines) - 1
            story = all_data["annotated_data"][int(user_dict[user]["start_id"])][
                "text"
            ].split("<SPLIT_TOKEN>")
            user_dict[user]["user_data"] = user_data

        user_dict[user]["current_display"] = {
            "id": user_dict[user]["start_id"],
            "story": story,
            "ism": ism,
            "annotated_amount": cal_amount(user),
        }

        user_dict[user]["QUESTION_START"] = True
        # user_dict[user]['last_question'] = ''
        # user_dict[user]['last_score'] = 0.0

    for user in user_dict:
        print(user, user_dict[user]["start_id"])

    # # load old text data
    # text_data = []
    # with open(args.text_data_path, "r") as r:
    #     lines = r.readlines()
    #     for line in lines:
    #         text_data.append(line.strip())

    # all_data["all_text_data"] = text_data

    # initialize user data file
    # text_amount = len(text_data)

    # combine_bws()
    # compute_ranking()


def cal_amount(user):
    count = 0
    lines = user_dict[user]["user_data"]
    for key in lines:
        if lines[key]["annotated"]:
            count += 1
    return count


def find_start_id(user):
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


def go_back(user):
    user_dict[user]["start_id"] = max(user_dict[user]["start_id"] - 1, 0)
    story = all_data["annotated_data"][int(user_dict[user]["start_id"])]["text"].split(
        "<SPLIT_TOKEN>"
    )
    ism = ""
    if user_dict[user]["user_data"][str(user_dict[user]["start_id"])]["annotated"]:
        ism = user_dict[user]["user_data"][str(user_dict[user]["start_id"])]["label"]
    user_dict[user]["current_display"] = {
        "id": user_dict[user]["start_id"],
        "story": story,
        "ism": ism,
        "annotated_amount": user_dict[user]["current_display"]["annotated_amount"],
    }


def go_ahead(user):
    user_dict[user]["start_id"] = min(
        user_dict[user]["start_id"] + 1, len(all_data["annotated_data"]) - 1
    )
    story = all_data["annotated_data"][int(user_dict[user]["start_id"])]["text"].split(
        "<SPLIT_TOKEN>"
    )
    ism = ""
    if user_dict[user]["user_data"][str(user_dict[user]["start_id"])]["annotated"]:
        ism = user_dict[user]["user_data"][str(user_dict[user]["start_id"])]["label"]
    user_dict[user]["current_display"] = {
        "id": user_dict[user]["start_id"],
        "story": story,
        "ism": ism,
        "annotated_amount": user_dict[user]["current_display"]["annotated_amount"],
    }


def go_to_id(user, id):
    if int(id) >= len(all_data["annotated_data"]) or int(id) < 0:
        print("illegal id:", id)
        return
    user_dict[user]["start_id"] = int(id)
    story = all_data["annotated_data"][int(user_dict[user]["start_id"])]["text"].split(
        "<SPLIT_TOKEN>"
    )
    ism = ""
    if user_dict[user]["user_data"][str(user_dict[user]["start_id"])]["annotated"]:
        ism = user_dict[user]["user_data"][str(user_dict[user]["start_id"])]["label"]
    user_dict[user]["current_display"] = {
        "id": user_dict[user]["start_id"],
        "story": story,
        "ism": ism,
        "annotated_amount": user_dict[user]["current_display"]["annotated_amount"],
    }


def merge_annotation():
    global user_dict
    global closed
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


def write_data(username):
    global user_dict
    global closed
    global all_data
    global args

    path = user_dict[username]["path"]
    with open(path, "w") as w:
        for line in user_dict[username]["user_data"]:
            line = json.dumps(user_dict[username]["user_data"][line])
            w.writelines(line + "\n")


@app.route("/")
def home():
    return render_template("home.html")


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


@app.route("/user/namepoint", methods=["GET", "POST"])
def user_name_endpoint():
    global curr_user_story_similarity
    global user_file_written_map
    global user_story_pos
    global user_response_dicts_queue
    global user_dict
    global closed
    global all_data

    print("----TRACE----made it here to user_name_endpoint")
    
    reading_user_response = False
    # story_dict = get_story_dict()
    name_dict = {}
    name_types = ["firstname", "lastname"]
    True_user = False
    while not True_user:
        try:
            # consider first name as user id, last name as password
            firstname = request.form.get("firstname")
            lastname = request.form.get("lastname")
            name_dict["firstname"] = firstname
            name_dict["lastname"] = lastname

            # TODO: assign each annotator an ID
            # name_dict["user_id"] = user_dict[firstname]["user_id"]
            break
        except BaseException as ex:
            print(repr(ex))
            raise

    username = firstname

    ism = request.form.get("label")
    src = request.form.get("src")
    print(ism)
    print("src:", src)

    print("----TRACE----made past the label get thing")
    
    if src == "home":
        print("session recovered")
        print(user_dict[username]["current_display"]["ism"])
        print(user_dict[username]["current_display"]["story"])
    elif src == "back":
        go_back(username)
    elif src == "go":
        go_ahead(username)
        print(user_dict[username]["current_display"]["ism"])
    elif src == "go_to":
        go_to_id(username, request.form.get("go_to"))
        print(user_dict[username]["current_display"]["ism"])
    elif ism == None:
        print("ISM IS NULLLLLLL")
        # user_dict[username]['user_data'][str(user_dict[username]['start_id'])]["annotated"] = False
        # del user_dict[username]['user_data'][str(user_dict[username]['start_id'])]["label"]
        # user_dict[username]['current_display']['ism'] = ""
        # write_data(username)
        # merge_annotation()

    else:
        user_dict[username]["user_data"][str(user_dict[username]["start_id"])][
            "label"
        ] = int(ism)
        user_dict[username]["user_data"][str(user_dict[username]["start_id"])][
            "annotated"
        ] = True
        user_dict[username]["current_display"]["ism"] = ism
        user_dict[username]["current_display"]["annotated_amount"] = cal_amount(
            username
        )
        print(ism)
        write_data(username)
        merge_annotation()

    print(user_dict[username]["current_display"]["story"][0])
    print(user_dict[username]["current_display"]["story"][1])
    return render_template(
        "user_likert.html",
        firstname=firstname,
        lastname=lastname,
        target_comment=user_dict[username]["current_display"]["story"][0]
        .encode()
        .decode("unicode_escape")
        .encode("latin-1")
        .decode("utf-8"),
        observer_comment=user_dict[username]["current_display"]["story"][1]
        .encode()
        .decode("unicode_escape")
        .encode("latin-1")
        .decode("utf-8"),
        is_match=user_dict[username]["current_display"]["ism"],
        id=user_dict[username]["start_id"],
        amount=len(all_data["annotated_data"]),
        annotated_amount=user_dict[username]["current_display"]["annotated_amount"],
    )


def temp_choose_file_to_read_from():
    global file_list
    file_path = choose_file(file_list)
    return file_path


def parse_story_pair_from_file(filepath):
    with open(filepath, "r") as f:
        lines = f.readlines()
    lines = [l.strip("\n").split("\t") for l in lines]
    # random.shuffle(lines)
    return lines


def arguments():
    parser = ArgumentParser()
    parser.set_defaults(show_path=False, show_similarity=False)

    parser.add_argument("config_file")
    
    parser.add_argument("-p", "--port", action="store", type=int, dest="port",
                        help="The port to run on", default=8000)

    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Report verbose output", default=False)

    parser.add_argument("--veryVerbose", action="store_true", dest="very_verbose",
                        help="Report very verbose output", default=False)
    # parser.add_argument("-p", "--show_path", action="store_true", dest="show_path")
    # parser.add_argument("-s", "--show_sim", action="store_true", dest="show_similarity")

    return parser.parse_args()


def generate_site(config):
    global logger
    
    logger.info("Generating anntoation site at %s" % config['site_dir'])
    


    # Load the template
    html_template_file = config['html_template']
    logger.debug("Reading html annotation template %s" % html_template_file)
    # TODO: add file exists checking
    with open(html_template_file, 'rt') as f:
        html_template = ''.join(f.readlines())

    # Load the header we'll stuff in the template
    header_file = config['header_file']
    logger.debug("Reading html header %s" % header_file)
    # TODO: add file exists checking
    with open(header_file, 'rt') as f:
        header = ''.join(f.readlines())

    html_template = html_template.replace("{{ HEADER }}", header)


    # Grab the annotation schemes
    annotation_schemes = config['annotation_schemes']
    logger.debug("Saw %d annotation scheme(s)" % len(annotation_schemes))

    # The annotator schemes get stuff in a <table> for now, though this probably
    # should be made more flexible
    annotation_schematic = "<table><tr>\n"
    

    for annotation_scheme in annotation_schemes:
        annotation_schematic += "<td valign=\"top\" style=\"padding: 0 20px 0 0;\">\n"
        annotation_schematic += generate_schematic(annotation_scheme) + "\n"
        annotation_schematic += "</td>\n"
    annotation_schematic += "</tr></table>"

    html_template = html_template.replace("{{ annotation_schematic }}", annotation_schematic)
        
    output_html_fname = os.path.join(config['site_dir'], basename(html_template_file))
    with open(output_html_fname, 'wt') as outf:
        outf.write(html_template)

    logger.debug('writing annotation html to %s' % output_html_fname)

    

def generate_schematic(annotation_scheme):
    global logger
    
    # Figure out which kind of tasks we're doing and build the input frame        
    annotation_type = annotation_scheme['annotation_type']
    
    
    if annotation_type == "multiselect":      

        schematic = \
            '<form action="/action_page.php">' + \
            '  <fieldset>' + \
            ('  <legend>%s:</legend>' % annotation_scheme['name'])

        for label in annotation_scheme['labels']:
            
            schematic += \
                (('  <input type="checkbox" id="%s" name="%s" value="%s">' + \
                 '  <label for="%s">%s</label><br/>') % (label, label, label, label, label))

        schematic += '  </fieldset>\n</form>\n'

    else:
        logger.warning("unsupported annotation type: %s" % annotation_type)

    return schematic

    


def main():
    #global file_to_read_from
    #global default_port
    #global user_story_set
    #global NUM_STORIES_TO_READ
    #global SHOW_PATH
    #global SHOW_SIMILARITY
    #global user_dict
    #global all_data
    #global args
    global config
    global logger
    
    args = arguments()

    with open(args.config_file, 'rt') as f:
        config = yaml.safe_load(f)

    logger = logging.getLogger(config['server_name'])

    logger.setLevel(logging.INFO)
    logging.basicConfig()
    
    if args.verbose:        
        logger.setLevel(logging.DEBUG)

    if args.very_verbose:
        logger.setLevel(logging.NOTSET)

    generate_site(config)
    
    #with open("user_config.json", "r") as r:
    #    lines = r.readlines()
    #    for line in lines:
    #        line = json.loads(line)
    #        line["path"] = (
    #            args.user_data_path + "user_" + str(line["firstname"]) + ".json"
    #        )
    #        user_dict[str(line["firstname"])] = line

    load_all_data(config)

    flask_debug = True if args.verbose or args.very_verbose else False
    
    app.run(debug=flask_debug, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
