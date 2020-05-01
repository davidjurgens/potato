import socketserver
import os
import sys
import numpy as np
from flask import Flask, render_template, request, url_for, jsonify

import pandas as pd

import yaml
import re
from os.path import basename

from os import path

from bs4 import BeautifulSoup


import html

import logging

# import requests
import random
import time
import json
import gzip
from datetime import datetime
from collections import deque, defaultdict
import collections
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

user_to_annotation_state = {}

curr_user_story_similarity = {}

minimum_list = 30

SHOW_PATH = False
SHOW_SIMILARITY = False
FIRST_LOAD = True
# QUESTION_START = True
closed = False

config = None


# Hacky nonsense
schema_label_to_color = {}

COLOR_PALETTE = ['rgb(179,226,205)', 'rgb(253,205,172)', 'rgb(203,213,232)', 'rgb(244,202,228)', 'rgb(230,245,201)', 'rgb(255,242,174)', 'rgb(241,226,204)', 'rgb(204,204,204)', 'rgb(102, 197, 204)', 'rgb(246, 207, 113)', 'rgb(248, 156, 116)', 'rgb(220, 176, 242)', 'rgb(135, 197, 95)', 'rgb(158, 185, 243)', 'rgb(254, 136, 177)', 'rgb(201, 219, 116)', 'rgb(139, 224, 164)', 'rgb(180, 151, 231)', 'rgb(179, 179, 179)']

app = Flask(__name__)

class UserAnnotationState:
    
    def __init__(self, instance_id_to_data):
        self.instance_id_to_labeling = {}

        self.instance_id_to_data = instance_id_to_data
        
        # NOTE: this might be dumb but at the moment, we cache the order in
        # which this user will walk the instances. This might not work if we're
        # annotating a ton of things with a lot of people, but hopefully it's
        # not too bad. The underlying motivation is to programmatically change
        # this ordering later
        self.instance_id_ordering = list(instance_id_to_data.keys())

        self.instance_cursor = 0

    def current_instance(self):
        #print("current_instance(): cursor is now ", self.instance_cursor)        
        inst_id = self.instance_id_ordering[self.instance_cursor]
        instance = instance_id_to_data[inst_id]
        return instance

    def go_back(self):
        if self.instance_cursor > 0:
            self.instance_cursor -= 1

    def go_forward(self):
        old_cur = self.instance_cursor 
        #print("current cursor: %d/%d, updating to %d/%d" % \
        #      (self.instance_cursor, len(self.instance_id_to_data) - 1,
        #       min(self.instance_cursor + 1,  len(self.instance_id_to_data) - 1),
        #       len(self.instance_id_to_data) - 1))
        if self.instance_cursor < len(self.instance_id_to_data) - 1:
            self.instance_cursor += 1
        #print("go_forward(): cursor %d -> %d" % (old_cur, self.instance_cursor))
        
    def get_annotations(self, instance_id):
        if instance_id not in self.instance_id_to_labeling:
            return None
        else:
            # NB: Should this be a view/copy?
            return self.instance_id_to_labeling[instance_id]

    def get_annotation_count(self):
        return len(self.instance_id_to_labeling)
        
    def set_annotation(self, instance_id, schema_to_labels):
        old_annotation = defaultdict(list)
        if instance_id in self.instance_id_to_labeling:
            old_annotation = self.instance_id_to_labeling[instance_id]

        # Avoid updating with no entries
        if len(schema_to_labels) > 0:
            self.instance_id_to_labeling[instance_id] = schema_to_labels
        elif instance_id in self.instance_id_to_labeling:
            del self.instance_id_to_labeling[instance_id]
        
        return old_annotation != schema_to_labels

    def update(self, id_key, annotation_order, annotated_instances):
        self.instance_id_to_labeling = {}
        for inst in annotated_instances:

            inst_id = inst['id']
            annotation = inst['annotation']
            
            self.instance_id_to_labeling[inst_id] = annotation
        
        self.instance_id_ordering = annotation_order

        # Set the current item to be the one after the last thing that was
        # annotated
        self.instance_cursor = min(len(self.instance_id_to_labeling),
                                   len(self.instance_id_ordering)-1)

        #print("update(): user had annotated %d instances, so setting cursor to %d" % 
        #      (len(self.instance_id_to_labeling), self.instance_cursor))
        
    
def load_all_data(config):
    global annotate_state # formerly known as user_state
    global all_data
    global logger
    global instance_id_to_data

    # Hacky nonsense
    global re_to_highlights
    
    # Where to look in the JSON item object for the text to annotate
    text_key = config['item_properties']['text_key']
    id_key = config['item_properties']['id_key']
    
    items_to_annotate = []

    instance_id_to_data = {}
    
    data_files = config['data_files']
    logger.debug('Loading data from %d files' % (len(data_files)))

    for data_fname in data_files:
        logger.debug('Reading data from ' + data_fname)
        with open(data_fname, "rt") as f:
            for line_no, line in enumerate(f):
                item = json.loads(line)

                # fix the encoding            
                # item[text_key] = item[text_key].encode("latin-1").decode("utf-8")           

                instance_id = item[id_key]

                # TODO: check for duplicate instance_id                
                instance_id_to_data[instance_id] = item
                    
                items_to_annotate.append(item)
                
        logger.debug('Loaded %d instances from %s' % (line_no, data_fname))
    all_data["items_to_annotate"] = items_to_annotate                       

    # TODO: make this fully configurable somehow...
    if 'keyword_highlights_file' in config:
        kh_file = config['keyword_highlights_file']
        logger.debug("Loading keyword highlighting from %s" % (kh_file))

        re_to_highlights = defaultdict(list)
        
        with open(kh_file, 'rt') as f:
            # TODO: make it flexible based on keyword
            df = pd.read_csv(kh_file, sep='\t')
            for i, row in df.iterrows():
                regex = r'\b' + row['Word'].replace("*", "[a-z]*?") + r'\b'
                re_to_highlights[regex].append((row['Schema'], row['Label']))

        logger.debug('Loaded %d regexes to map to %d labels for dynamic highlighting' \
                     % (len(re_to_highlights), i))
                
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


def move_to_prev_instance(username):
    user_state = lookup_user_state(username)
    user_state.go_back()
    

def move_to_next_instance(username):
    user_state = lookup_user_state(username)
    user_state.go_forward()
    

def update_annotation_state(username, form):
    user_state = lookup_user_state(username)

    instance_id = request.form['instance_id']

    schema_to_labels = defaultdict(list)
    
    for key in form:
        # Look for the marker that indicates an annotation label
        if '|||' not in key:
            continue

        cols = key.split('|||')
        annotation_schema = cols[0]
        annotation_label = cols[1]

        schema_to_labels[annotation_schema].append(annotation_label)

    # print("-- for user %s, instance %s -> %s" % (username, instance_id, str(schema_to_labels)))
    did_change = user_state.set_annotation(instance_id, schema_to_labels)
    return did_change
    
    
def get_annotations_for_user_on(username, instance_id):
    user_state = lookup_user_state(username)
    annotations = user_state.get_annotations(instance_id)
    return annotations

    
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


def lookup_user_state(username):
    global user_to_annotation_state
    
    if username not in user_to_annotation_state:
        logger.debug("Previously unknown user \"%s\"; creating new annotation state" % (username))
        user_state = UserAnnotationState(instance_id_to_data)
        user_to_annotation_state[username] = user_state
    else:
        user_state = user_to_annotation_state[username]

    return user_state

def save_user_state(username, save_order=False):
    global user_to_annotation_state
    global config
    global instance_id_to_data
    
    # Figure out where this user's data would be stored on disk
    user_state_dir = config['user_state_dir']

    # NB: Do some kind of sanitizing on the username to improve security
    user_dir = path.join(user_state_dir, username)

    user_state = lookup_user_state(username)
    
    if not os.path.exists(user_dir):        
        os.makedirs(user_dir)
        logger.debug("Created state directory for user \"%s\"" % (username))        
    
    annotation_order_fname = path.join(user_dir, "annotation_order.txt")
    if not os.path.exists(annotation_order_fname) or save_order:
        with open(annotation_order_fname, 'wt') as outf:
            for inst in user_state.instance_id_ordering:
                outf.write(inst + '\n')
                
    annotated_instances_fname = path.join(user_dir, "annotated_instances.jsonl")
    with open(annotated_instances_fname, 'wt') as outf:
        for inst_id, data in user_state.instance_id_to_labeling.items():
            output = {'id': inst_id, 'annotation': data }
            json.dump(output, outf)
            outf.write('\n')
            
    
    

def load_user_state(username):
    global user_to_annotation_state
    global config
    global instance_id_to_data
    global logger
    
    # Figure out where this user's data would be stored on disk
    user_state_dir = config['user_state_dir']

    # NB: Do some kind of sanitizing on the username to improve securty
    user_dir = path.join(user_state_dir, username)

    # User has annotated before
    if os.path.exists(user_dir):
        logger.debug("Found known user \"%s\"; loading annotation state" % (username))

        annotation_order_fname = path.join(user_dir, "annotation_order.txt")
        annotation_order = []
        with open(annotation_order_fname, 'rt') as f:
            for line in f:
                annotation_order.append(line[:-1])
                
        annotated_instances_fname = path.join(user_dir, "annotated_instances.jsonl")
        annotated_instances = []
        with open(annotated_instances_fname, 'rt') as f:
            for line in f:
                annotated_instances.append(json.loads(line))

        id_key = config['item_properties']['id_key']
                
        user_state = UserAnnotationState(instance_id_to_data)
        user_state.update(id_key, annotation_order, annotated_instances)

        # Make sure we keep track of the user throughout the program
        user_to_annotation_state[username] = user_state
        
        logger.info("Loaded %d annotations for known user \"%s\"" %
                     (user_state.get_annotation_count(), len(instance_id_to_data)))

    # New user, so initialize state
    else:

        logger.debug("Previously unknown user \"%s\"; creating new annotation state" % (username))
        user_state = UserAnnotationState(instance_id_to_data)
        user_to_annotation_state[username] = user_state
        
        
        
def get_cur_instance_for_user(username):
    global user_to_annotation_state
    global instance_id_to_data
    global logger
    
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


@app.route("/user/namepoint", methods=["GET", "POST"])
def user_name_endpoint():
    
    firstname = request.form.get("firstname")
    lastname = request.form.get("lastname")

    username = firstname + '_' + lastname
    
    if 'instance_id' in request.form:
        did_change = update_annotation_state(username, request.form)
        if did_change:
            save_user_state(username)
            
    print("--REQUESTS FORM: ", json.dumps(request.form))
    
    ism = request.form.get("label")
    action = request.form.get("src")
    #print("label: \"%s\"" % ism)
    # print("action: \"%s\"" % action)
    
    if action == "home":
        load_user_state(username)
        # gprint("session recovered")
    elif action == "prev_instance":
        #print("moving to prev instance")
        move_to_prev_instance(username)
    elif action == "next_instance":
        #print("moving to next instance")
        move_to_next_instance(username)
    elif action == "go_to":
        go_to_id(username, request.form.get("go_to"))
    elif ism == None:
        print("ISM IS NULLLLLLL")
    else:
        print('unrecognized action request: "%s"' % action)

    instance = get_cur_instance_for_user(username)

    text_key = config['item_properties']['text_key']
    id_key = config['item_properties']['id_key']

    text = instance[text_key]
    instance_id = instance[id_key]

    updated_text, schema_labels_to_highlight = post_process(config, text)        
    
    rendered_html = render_template(
        config['site_file'],
        firstname=firstname,
        lastname=lastname,
        # This is what instance the user is currently on
        instance=text,
        instance_id=instance_id,
        finished=lookup_user_state(username).get_annotation_count(),
        total_count=len(instance_id_to_data),
        #amount=len(all_data["annotated_data"]),
        #annotated_amount=user_dict[username]["current_display"]["annotated_amount"],
    )    


    # UGHGHGHGH the tempalte does unusual escaping, which makes it a PAIN to do
    # the replacement later
    m = re.search('<div name="instance_text">([^<]+)</div>', rendered_html)
    text = m.group(1)

    # For whatever reason, doing this before the render_template causes the
    # embedded HTML to get escaped, so we just do a wholesale replacement here.
    rendered_html = rendered_html.replace(text, updated_text)    

    soup = BeautifulSoup(rendered_html, 'html.parser')
    
    # Parse the page so we can programmatically reset the annotation state
    # to what it was before
    

    # Highlight the schema's labels as necessary
    for schema, label in schema_labels_to_highlight:
        name = schema + "|||" + label
        # print(name)
        label_elem = soup.find("label", {"for":name}) # .next_sibling

        # Update style to match the current color
        c = get_color_for_schema_label(schema, label)
        label_elem['style'] = ("background-color: %s"  % c)        
    
    # If the user has annotated this before, wall the DOM and fill out what they
    # did
    annotations = get_annotations_for_user_on(username, instance_id)
    if annotations is not None:

        # print('Saw previous annotations for %s: %s' % (instance_id, annotations))
               
        # Reset the state
        for schema, labels in annotations.items():
            for label in labels:
                name = schema + "|||" + label
                input_field = soup.find("input", {"name":name})
                if input_field is None:
                    print('No input for ', name)
                input_field['checked'] = True
                


    rendered_html = str(soup) # soup.prettify()
    
    return rendered_html


def get_color_for_schema_label(schema, label):
    global schema_label_to_color

    t = (schema, label)
    if t in schema_label_to_color:
        return schema_label_to_color[t]
    else:
        c = COLOR_PALETTE[len(schema_label_to_color)]
        schema_label_to_color[t] = c
        return c

def post_process(config, text):
    global schema_label_to_color

    schema_labels_to_highlight = set()
    
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

            #print('Searching with %s at %d in [0, %d]' % (regex, search_from, len(text)))
            
            # print('Saw keyword', match.group())

            start = match.start()
            end = match.end()

            # we're going to replace this instance with a color coded one
            if len(labels) == 1:
                schema, label = labels[0]

                # print('%s -> %s:%s' % (match.group(), schema, label))
                
                schema_labels_to_highlight.add((schema, label))
                
                c = get_color_for_schema_label(schema, label)

                pre = "<span style=\"background-color: %s\">"  % c

                replacement = pre + match.group() + '</span>'

                text = text[:start] + replacement + text[end:]

                # print(text)
                
                # Be sure to count all the junk we just added when searching again
                search_from += end + (len(replacement) - len(match.group()))
                # print('\n%d -> %d\n%s' % (end, search_from, text[search_from:]))


            # slightly harder, but just to get the MVP out
            elif len(labels) == 2:

                colors = []
                
                for schema, label in labels:                
                    schema_labels_to_highlight.add((schema, label))
                    c = get_color_for_schema_label(schema, label)
                    colors.append(c)

                matched_word = match.group()

                first_half = matched_word[:int(len(matched_word)/2)]
                last_half = matched_word[int(len(matched_word)/2):]
            
                pre = "<span style=\"background-color: %s;\">" 

                replacement = (pre % colors[0]) + first_half + '</span>' \
                    + (pre % colors[1]) + last_half + '</span>'

                # replacement = '<span style="font-size: 0">' + replacement + '</span>'
                
                text = text[:start] + replacement + text[end:]

                # Be sure to count all the junk we just added when searching again
                search_from += end + (len(replacement) - len(matched_word))
            
            # Gotta make this hard somehow...
            else:
                search_from = end
                
    return text, schema_labels_to_highlight

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

    html_template = html_template.replace("{{annotation_schematic}}", annotation_schematic)

    if 'annotation_codebook_url' in config:
        annotation_codebook = config['annotation_codebook_url']
        html_template = html_template.replace("{{annotation_codebook}}", annotation_codebook)

    html_template = html_template.replace("{{annotation_task_name}}", config['annotation_task_name'])
    
    output_html_fname = os.path.join(config['site_dir'], basename(html_template_file))

    # Cache this path as a shortcut to figure out which page to render
    config['site_file'] = basename(html_template_file)

    # Write the file
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

        for label_data in annotation_scheme['labels']:

            label = label_data if isinstance(label_data, str) else label_data['name']

            tooltip = ''
            if isinstance(label_data, collections.Mapping):
                tooltip_text = ''
                if 'tooltip' in label_data:
                    tooltip_text = label_data['tooltip']
                    # print('direct: ', tooltip_text)
                elif 'tooltip_file' in label_data:                    
                    with open(label_data['tooltip_file'], 'rt') as f:
                        lines = f.readlines()
                    tooltip_text = ''.join(lines)
                    # print('file: ', tooltip_text)
                if len(tooltip_text) > 0:
                    tooltip  = 'data-toggle="tooltip" data-html="true" data-placement="top" title="%s"' \
                        % tooltip_text                        

            name = annotation_scheme['name'] + '|||' + label
            
            schematic += \
                (('  <input type="checkbox" id="%s" name="%s" value="%s">' + \
                 '  <label for="%s" %s>%s</label><br/>') \
                 % (label, name, name, name, tooltip, label))


        schematic += '  </fieldset>\n</form>\n'

    else:
        logger.warning("unsupported annotation type: %s" % annotation_type)

    return schematic

    


def main():
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

    # Creates the templates we'll use in flask by mashing annotation
    # specification on top of the proto-templates
    generate_site(config)

    # Loads the training data
    load_all_data(config)

    # TODO: load previous annotation state
    #load_annotation_state(config)

    flask_logger = logging.getLogger('werkzeug')
    flask_logger.setLevel(logging.ERROR)
    
    app.run(debug=args.very_verbose, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
