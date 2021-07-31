import socketserver
import os
import sys
import numpy as np
import flask
from flask import Flask, render_template, request, url_for, jsonify

import pandas as pd

import yaml
import re
from os.path import basename

from os import path

from bs4 import BeautifulSoup

from tqdm import tqdm

import threading

import html

import logging

# import requests
import random
import time
import json
import gzip
from datetime import datetime
from collections import deque, defaultdict, Counter, OrderedDict
import collections
from argparse import ArgumentParser

from sklearn.pipeline import Pipeline

from itertools import zip_longest
import krippendorff

# import choix
# import networkx as nx


domain_file_path = ""
file_list = []
file_list_size = 0
default_port = 8000
user_dict = {}

file_to_read_from = ""
#MAX_STORY_LENGTH = 99999  # No limit
#NUM_STORIES_TO_READ = 999999999  # No limit

all_data = {}

#user_story_set = {}
user_story_pos = defaultdict(lambda: 0, dict())
#user_file_written_map = defaultdict(dict)
#user_current_story_dict = {}
user_response_dicts_queue = defaultdict(deque)

user_to_annotation_state = {}

# A global mapping from an instance's id to its data. This is filled by
# load_all_data()
instance_id_to_data = {}

# curr_user_story_similarity = {}

# minimum_list = 30

#SHOW_PATH = False
#SHOW_SIMILARITY = False
#FIRST_LOAD = True
# QUESTION_START = True
#closed = False

# Config is the Potation configuration the user has passed in as a .yaml file
config = None

# path to save user information
USER_CONFIG_PATH = 'potato/user_config.json'

#TODO: Move this to config.yaml files
#Items which will be displayed in the popup statistics sidebar
STATS_KEYS = {'Annotated instances':'Annotated instances','Total working time':'Total working time', 'Average time on each instance':'Average time on each instance', 'Agreement':'Agreement'}


# This variable of tyep ActiveLearningState keeps track of information on active
# learning, such as which instances were sampled according to each strategy
active_learning_state = None

# Hacky nonsense
schema_label_to_color = {}

COLOR_PALETTE = ['rgb(179,226,205)', 'rgb(253,205,172)', 'rgb(203,213,232)', 'rgb(244,202,228)', 'rgb(230,245,201)', 'rgb(255,242,174)', 'rgb(241,226,204)', 'rgb(204,204,204)', 'rgb(102, 197, 204)', 'rgb(246, 207, 113)',
                 'rgb(248, 156, 116)', 'rgb(220, 176, 242)', 'rgb(135, 197, 95)', 'rgb(158, 185, 243)', 'rgb(254, 136, 177)', 'rgb(201, 219, 116)', 'rgb(139, 224, 164)', 'rgb(180, 151, 231)', 'rgb(179, 179, 179)']

app = Flask(__name__)


class UserConfig:
    '''
    A class for maintaining state on which users are allowed to use the system
    '''


    def __init__(self, user_config_path='potato/user_config.json'):
        self.allow_all_users = False
        self.user_config_path = user_config_path
        self.userlist = []
        self.usernames = set()
        self.users = {}
        self.required_user_info_keys = ['username','password']

        if os.path.isfile(self.user_config_path):
            print('Loading users from' + self.user_config_path)
            with open(self.user_config_path, 'rt') as f:
                for line in f.readlines():
                    single_user = json.loads(line.strip())
                    result = self.add_single_user(single_user)
                    # print(single_user['username'], result)
        #else:
        #    print('user info file not found at:', self.user_config_path)


    #Jiaxin: this function will be depreciate since we will save the full user dict with password
    def add_user(self, username):
        if username in self.usernames:
            print("Duplicate user in list: %s" % username)
        self.usernames.add(username)

    #add a single user to the full user dict
    def add_single_user(self, single_user):
        for key in self.required_user_info_keys:
            if key not in single_user:
                print('Missing %s in user info' % key)
                return 'Missing %s in user info' % key
        if single_user['username'] in self.users:
            print("Duplicate user in list: %s" % single_user['username'])
            return "Duplicate user in list: %s" % single_user['username']
        self.users[single_user['username']] = single_user
        self.userlist.append(single_user['username'])
        return 'Success'

    def save_user_config(self):
        if self.user_config_path:
            with open(self.user_config_path, 'wt') as f:
                for k in self.userlist:
                    f.writelines(json.dumps(self.users[k]) + '\n')
            print('user info file saved at:', self.user_config_path)
        else:
            print('WARNING: user_config_path not specified, user registration info are not saved')

    #check if a user name is in the current user list
    def is_valid_username(self, username):
        return username in self.users

    #check if the password is correct for a given (username, password) pair
    #TODO: Currently we are just doing simple plaintext verification, but we will need ciphertext verification in the long run
    def is_valid_password(self, username, password):
        return self.is_valid_username(username) and self.users[username]['password'] == password

    def is_valid_user(self, username):
        return self.allow_all_users or username in self.usernames

class ActiveLearningState:
    '''
    A class for maintaining state on active learning.
    '''
    
    def __init__(self):
        self.id_to_selection_type = {}
        self.id_to_update_round = {}
        self.cur_round = 0    
        
    def update_selection_types(self, id_to_selection_type):
        self.cur_round += 1

        for iid, st in id_to_selection_type.items():
            self.id_to_selection_type[iid] = st
            self.id_to_update_round[iid] = self.cur_round

    
    
class UserAnnotationState:
    '''
    A class for maintaining state on which annotations users have completed.
    '''
    
    def __init__(self, instance_id_to_data):

        # This data structure keeps the annotations the user has completed so far
        self.instance_id_to_labeling = {}

        # This is a reference to the data
        #
        # NB: do we need this as a field?
        self.instance_id_to_data = instance_id_to_data

        # TODO: Put behavioral information of each instance with the labels together
        # however, that requires too many changes of the data structure
        # therefore, we contruct a separate dictionary to save all the behavioral information (e.g. time, click, ..)
        self.instance_id_to_behavioral_data = {}

        # NOTE: this might be dumb but at the moment, we cache the order in
        # which this user will walk the instances. This might not work if we're
        # annotating a ton of things with a lot of people, but hopefully it's
        # not too bad. The underlying motivation is to programmatically change
        # this ordering later
        self.instance_id_ordering = list(instance_id_to_data.keys())

        #initialize the mapping from instance id to order
        self.instance_id_to_order = self.generate_id_order_mapping(self.instance_id_ordering)

        self.instance_cursor = 0

    def generate_id_order_mapping(self,instance_id_ordering):
        id_order_mapping = {}
        for i in range(len(instance_id_ordering)):
            id_order_mapping[instance_id_ordering[i]] = i
        return id_order_mapping

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
        if self.instance_cursor < len(self.instance_id_to_data) - 1:
            self.instance_cursor += 1

    def go_to_id(self, id):
        old_cur = self.instance_cursor
        if id < len(self.instance_id_to_data) and id >= 0:
            self.instance_cursor = id

    def get_annotations(self, instance_id):
        if instance_id not in self.instance_id_to_labeling:
            return None
        else:
            # NB: Should this be a view/copy?
            return self.instance_id_to_labeling[instance_id]

    def get_annotation_count(self):
        return len(self.instance_id_to_labeling)

    def set_annotation(self, instance_id, schema_to_label_to_value, behavioral_data_dict):
        '''
        Based on a user's actions, updates the annotation for this particular instance. 
        '''
        
        old_annotation = defaultdict(dict)
        if instance_id in self.instance_id_to_labeling:
            old_annotation = self.instance_id_to_labeling[instance_id]
            
        # Avoid updating with no entries
        if len(schema_to_label_to_value) > 0:
            self.instance_id_to_labeling[instance_id] = schema_to_label_to_value
            
            # TODO: keep track of all the annotation behaviors instead of only
            # keeping the latest one each time when new annotation is updated,
            # we also update the behavioral_data_dict (currently done in the
            # update_annotation_state function)
            #
            #self.instance_id_to_behavioral_data[instance_id] = behavioral_data_dict
            
        elif instance_id in self.instance_id_to_labeling:
            del self.instance_id_to_labeling[instance_id]

        return old_annotation != schema_to_label_to_value

    # This is only used to update the entire list of annotations,
    # normally when loading all the saved data
    def update(self, id_key, annotation_order, annotated_instances):
        self.instance_id_to_labeling = {}
        for inst in annotated_instances:

            inst_id = inst['id']
            annotation = inst['annotation']
            behavior_dict = {}
            if 'behavioral_data' in inst:
                behavior_dict = inst['behavioral_data']
                #print(behavior_dict)

            self.instance_id_to_labeling[inst_id] = annotation
            self.instance_id_to_behavioral_data[inst_id] = behavior_dict

        self.instance_id_ordering = annotation_order
        self.instance_id_to_order = self.generate_id_order_mapping(self.instance_id_ordering)

        # Set the current item to be the one after the last thing that was
        # annotated
        #self.instance_cursor = min(len(self.instance_id_to_labeling),
        #                           len(self.instance_id_ordering)-1)
        if len(annotated_instances) > 0:
            self.instance_cursor = self.instance_id_to_order[annotated_instances[-1]['id']]
        else:
            annotation_order[0]

            # print("update(): user had annotated %d instances, so setting cursor to %d" %
        #      (len(self.instance_id_to_labeling), self.instance_cursor))


    def reorder_remaining_instances(self, new_id_order, preserve_order):

        # Preserve the ordering the user has seen so far for data they've
        # annotated. This also includes items that *other* users have annotated
        # to ensure all items get the same number of annotations (otherwise
        # these items might get re-ordered farther away)
        new_order = [ iid for iid in self.instance_id_ordering \
                         if iid in preserve_order ]

        # Now add all the other IDs
        for iid in new_id_order:
            if iid not in self.instance_id_to_labeling:
                new_order.append(iid)


        assert len(new_order) == len(self.instance_id_ordering)
                
        # Update the user's state
        self.instance_id_ordering = new_order
        self.instance_id_to_order = self.generate_id_order_mapping(self.instance_id_ordering)

    #parse the time string generated by front end, e.g., 'time_string': 'Time spent: 0d 0h 0m 5s '
    def parse_time_string(self, time_string):
        time_dict = {}
        items = time_string.strip().split(' ')
        if len(items) != 6:
            return None
        time_dict['day'] = int(items[2][:-1])
        time_dict['hour'] = int(items[3][:-1])
        time_dict['minute'] = int(items[4][:-1])
        time_dict['second'] = int(items[5][:-1])
        time_dict['total_seconds'] = time_dict['second'] + 60 * time_dict['minute'] + 3600 * time_dict['hour']

        return time_dict
    
    #calculate the amount of time a user have spend on annotation
    def total_working_time(self):
        total_working_seconds = 0
        #print('start calculating total working time')
        for inst_id in self.instance_id_to_behavioral_data:
            #print(self.instance_id_to_behavioral_data[inst_id])
            if 'time_string' in self.instance_id_to_behavioral_data[inst_id]:
                time_string = self.instance_id_to_behavioral_data[inst_id]['time_string']
                total_working_seconds += self.parse_time_string(time_string)['total_seconds'] if self.parse_time_string(time_string) else 0

        if total_working_seconds < 60:
            total_working_time_str = str(total_working_seconds) + ' seconds'
        elif total_working_seconds < 3600:
            total_working_time_str = str(int(total_working_seconds)/60) + ' minutes'
        else:
            total_working_time_str = str(int(total_working_seconds) / 3600) + ' hours'

        return (total_working_seconds,total_working_time_str)

    def generate_user_statistics(self):
        statistics = {}
        statistics['Annotated instances'] = len(self.instance_id_to_labeling)
        statistics['Total working time'] = self.total_working_time()[1]
        if statistics['Annotated instances'] != 0:
            statistics['Average time on each instance'] = '%s seconds' % str(round(self.total_working_time()[0] / statistics['Annotated instances'],1))
        else:
            statistics['Average time on each instance'] = 'N/A'

        return statistics

def load_all_data(config):
    global annotate_state  # formerly known as user_state
    global all_data
    global logger
    global instance_id_to_data

    # Hacky nonsense
    global re_to_highlights

    # Where to look in the JSON item object for the text to annotate
    text_key = config['item_properties']['text_key']
    id_key = config['item_properties']['id_key']

    items_to_annotate = []

    # Keep the data in the same order we read it in
    instance_id_to_data = OrderedDict()

    data_files = config['data_files']
    logger.debug('Loading data from %d files' % (len(data_files)))

    
    for data_fname in data_files:

        fmt = data_fname.split('.')[-1]
        if not (fmt == 'csv' or fmt == 'tsv' or fmt == 'json' or 'jsonl'):
            raise Exception("Unsupported input file format %s for %s" % (fmt, data_fname))
                
        logger.debug('Reading data from ' + data_fname)

        if fmt == 'json' or fmt == 'jsonl':        
            with open(data_fname, "rt") as f:
                for line_no, line in enumerate(f):
                    item = json.loads(line)

                    # fix the encoding
                    # item[text_key] = item[text_key].encode("latin-1").decode("utf-8")
                    
                    instance_id = item[id_key]

                    # TODO: check for duplicate instance_id
                    instance_id_to_data[instance_id] = item

                    items_to_annotate.append(item)
        else:
            sep = ',' if fmt == 'csv' else '\t'
            # Ensure the key is loaded as a string form (prevents weirdness
            # later)
            df = pd.read_csv(data_fname, sep=sep, dtype={id_key: str, text_key: str})
            for i, row in df.iterrows():

                item = { }
                for c in df.columns:
                    item[c] = row[c]
                instance_id = row[id_key]

                # TODO: check for duplicate instance_id
                instance_id_to_data[instance_id] = item                               
                items_to_annotate.append(item)
            line_no = len(df)
                
        logger.debug('Loaded %d instances from %s' % (line_no, data_fname))
    all_data["items_to_annotate"] = items_to_annotate

    # TODO: make this fully configurable somehow...
    re_to_highlights = defaultdict(list)
    if 'keyword_highlights_file' in config:
        kh_file = config['keyword_highlights_file']
        logger.debug("Loading keyword highlighting from %s" % (kh_file))

        with open(kh_file, 'rt') as f:
            # TODO: make it flexible based on keyword
            df = pd.read_csv(kh_file, sep='\t')
            for i, row in df.iterrows():
                regex = r'\b' + row['Word'].replace("*", "[a-z]*?") + r'\b'
                re_to_highlights[regex].append((row['Schema'], row['Label']))

        logger.debug('Loaded %d regexes to map to %d labels for dynamic highlighting'
                     % (len(re_to_highlights), i))


def convert_labels(annotation, schema_type):
    if schema_type == 'likert':
        return int(list(annotation.keys())[0][6:])
    elif schema_type == 'radio':
        return list(annotation.keys())[0]
    elif schema_type == 'multiselect':
        return list(annotation.keys())
    else:
        print("Unrecognized schema_type %s" % schema_type)
        return None

#get the final agreement score for selected users and schemas
def get_agreement_score(user_list, schema_name, return_type = 'overall_average'):
    global user_to_annotation_state
    global config

    if user_list == 'all':
        user_list = user_to_annotation_state.keys()

    name2alpha = {}
    if schema_name == 'all':
        for i in range(len(config['annotation_schemes'])):
            schema = config['annotation_schemes'][i]
            alpha = cal_agreement(user_list, schema['name'])
            name2alpha[schema['name']] = alpha

    alpha_list = []
    if return_type == 'overall_average':
        for name in name2alpha:
            alpha = name2alpha[name]
            if type(alpha) == dict:
                average_alpha = sum([it[1] for it in list(alpha.items())]) / len(alpha)
                alpha_list.append(average_alpha)
            elif type(alpha) == float:
                alpha_list.append(alpha)
            else:
                continue
        if len(alpha_list) > 0:
            return round(sum(alpha_list) / len(alpha_list), 2)
        else:
            return 'N/A'
    else:
        return name2alpha


# calculate the krippendorff's alpha for selected users and schema
def cal_agreement(user_list, schema_name, schema_type = None, selected_keys = None):
    global user_to_annotation_state
    global config

    #get the schema_type/annotation_type from the config file
    for i in range(len(config['annotation_schemes'])):
        schema = config['annotation_schemes'][i]
        if schema['name'] == schema_name:
            schema_type = schema['annotation_type']
            break

    #obtain the list of keys for calculating IAA and the user annotations
    union_keys = set()
    user_annotation_list = []
    for user in user_list:
        if user not in user_to_annotation_state:
            print('%s not found in user_to_annotation_state' % user)
        user_annotated_ids = user_to_annotation_state[user].instance_id_to_labeling.keys()
        union_keys = union_keys | user_annotated_ids
        user_annotation_list.append(user_to_annotation_state[user].instance_id_to_labeling)

    if len(user_annotation_list) < 2:
        # print('Cannot calculate agreement score for less than 2 users')
        return None

    #only calculate the agreement for selected keys when selected_keys is specified
    if selected_keys == None:
        selected_keys = list(union_keys)

    if len(selected_keys) == 0:
        print('Cannot calculate agreement score when annotators work on different sets of instances')
        return None


    if schema_type in ['radio', 'likert']:
        distance_metric_dict = {
            'radio': 'nominal',
            'likert': 'ordinal'
        }
        #initialize agreement data matrix
        l = []
        for i in range(len(user_annotation_list)):
            l.append([np.nan] * len(selected_keys))

        for i in range(len(selected_keys)):
            key = selected_keys[i]
            for j in range(len(l)):
                if key in user_annotation_list[j]:
                    l[j][i] = convert_labels(user_annotation_list[j][key][schema_name], schema_type)
                    # print([it[i] for it in l])
            # print(key, l1[-1],l2[-1])
            # print(l)
        alpha = krippendorff.alpha(np.array(l), level_of_measurement=distance_metric_dict[schema_type])
        return alpha


    # When multiple labels are annotated for each instance, calculate the IAA for each label
    elif schema_type == 'multiselect':
        #collect the label list from configuration file
        if type(schema['labels'][0]) == dict:
            labels = [it['name'] for it in schema['labels']]
        elif type(schema['labels'][0]) == str:
            labels = schema['labels']
        else:
            print('Unknown label type in schema[\'labels\']')
            return None

        #initialize agreement data matrix for each label
        l_dict = {}
        for l in labels:
            l_dict[l] = []
            for i in range(len(user_annotation_list)):
                l_dict[l].append([np.nan] * len(selected_keys))

        #consider binary agreement for each label in the multi-label schema
        for i in range(len(selected_keys)):
            key = selected_keys[i]
            for j in range(len(user_annotation_list)):
                if (key in user_annotation_list[j]) and (schema_name in user_annotation_list[j][key]):
                    annotations = convert_labels(user_annotation_list[j][key][schema_name], schema_type)
                    for l in labels:
                        # print(key,j,user_annotation_list[j][key]['annotation'])
                        if l not in annotations:
                            l_dict[l][j][i] = 0
                        else:
                            l_dict[l][j][i] = 1
                    # for l in user_annotation_list[j][key]['annotation'][project2]:
                    #    l_dict[l][j][i] = 1

        alpha_dict = {}
        for key in labels:
            # print(l_dict[key])
            alpha_dict[key] = krippendorff.alpha(np.array(l_dict[key]), level_of_measurement='nominal')
        return alpha_dict








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


def go_to_id(username, id):
    # go to specific item
    user_state = lookup_user_state(username)
    user_state.go_to_id(int(id))

def get_total_annotations():
    '''
    Returns the total number of unique annotations done across all users
    '''
    total = 0
    for username in get_users():
        user_state = lookup_user_state(username)
        total += user_state.get_annotation_count()

    return total



def update_annotation_state(username, form):
    '''
    Parses the state of the HTML form (what the user did to the instance) and
    updates the state of the instance's annotations accordingly.
    '''

    # Get what the user has already annotated, which might include this instance too
    user_state = lookup_user_state(username)

    instance_id = request.form['instance_id']

    schema_to_label_to_value = defaultdict(dict)

    behavioral_data_dict = {}
    
    did_change = False
    for key in form:
        # look for behavioral information regarding time, click, ...
        if key[:9] == 'behavior_':
            behavioral_data_dict[key[9:]] = form[key]
            continue

        # Look for the marker that indicates an annotation label
        if ':::' not in key:
            continue

        cols = key.split(':::')
        annotation_schema = cols[0]
        annotation_label = cols[1]
        annotation_value = form[key]

        #skip the input when it is an empty string (from a text-box)
        if annotation_value == '':
            continue

        schema_to_label_to_value[annotation_schema][annotation_label] = annotation_value
        
        #schema_to_labels[annotation_schema].append(annotation_label)

    # print("-- for user %s, instance %s -> %s" % (username, instance_id, str(schema_to_labels)))

    #for schema, labels in schema_to_labels.items():
    #    for label in labels:          
    #        did_change |= user_state.set_annotation(instance_id, schema, label, value, behavioral_data_dict)

    did_change = user_state.set_annotation(instance_id, schema_to_label_to_value, behavioral_data_dict)

    # update the behavioral information regarding time only when the annotations are changed
    if did_change:
        user_state.instance_id_to_behavioral_data[instance_id] = behavioral_data_dict
        # print('misc information updated')

    return did_change


def get_annotations_for_user_on(username, instance_id):
    user_state = lookup_user_state(username)
    annotations = user_state.get_annotations(instance_id)
    return annotations

# This was used to merge annotated instances in previous annotations.  For
# example, you had some annotations from google sheet, and want to merge it with
# the current annotation procedure
def merge_annotation():
    global user_dict
    #global closed
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
    #global closed
    global all_data
    global args

    path = user_dict[username]["path"]
    with open(path, "w") as w:
        for line in user_dict[username]["user_data"]:
            line = json.dumps(user_dict[username]["user_data"][line])
            w.writelines(line + "\n")


@app.route("/")
def home():
    global config
    
    if config['__debug__']:
        return annotate_page()
    else:
        return render_template("home.html", title=config['annotation_task_name'])


@app.route("/login", methods=['GET', 'POST'])
def login():
    global user_config
    global config


    if config['__debug__'] == True:
        action = 'login'
        usenrame = 'debug_user'
        password = 'debug'
    else:
        # Jiaxin: currently we are just using email as the username
        action = request.form.get("action")
        username = request.form.get("email")
        password = request.form.get("pass")
        
    if action == 'login':
        if config['__debug__'] or user_config.is_valid_password(username, password):
            return annotate_page()
        else:
            data = {
                'username':username,
                'pass':password,
                'Login_error': 'Invalid username or password'
            }
            return render_template("home.html", title=config['annotation_task_name'], login_email = username,  login_error = 'Invalid username or password')
    else:
        print('unknown action at home page')
        return render_template("home.html", title=config['annotation_task_name'])

@app.route("/signup", methods=['GET', 'POST'])
def signup():
    global user_config
    global config
    # TODO: add in logic for checking/hashing passwords, safe password
    # management, etc. For now just #yolo and log in people regardless.
    action = request.form.get("action")
    # Jiaxin: currently we are just using email as the username
    username = request.form.get("email")
    email = request.form.get("email")
    password = request.form.get("pass")
    print(action, username, password)

    if action == 'signup':
        single_user = {
            'username':username,
            'email':email,
            'password':password
        }
        result = user_config.add_single_user(single_user)
        print(single_user['username'], result)
        if result == 'Success':
            user_config.save_user_config()
            return render_template("home.html", title=config['annotation_task_name'], login_email = username, login_error = 'User registration success for ' + username + ', please login now')
        else:
            #TODO: return to the signup page and display error message
            return render_template("home.html", title=config['annotation_task_name'], login_error = result + ', please try again or log in')
    else:
        print('unknown action at home page')
        return render_template("home.html", title=config['annotation_task_name'], login_email = username, login_error = 'Invalid username or password')

@app.route("/newuser")
def new_user():
    return render_template("newuser.html")


def get_users():
    '''
    Returns an iterable over the usernames of all users who have annotated in
    the system so far
    '''
    global user_to_annotation_state
    return user_to_annotation_state.keys()


def lookup_user_state(username):
    '''
    Returns the UserAnnotationState for a user, or if that user has not yet
    annotated, creates a new state for them and registers them with the system.
    '''
    global user_to_annotation_state

    if username not in user_to_annotation_state:
        logger.debug(
            "Previously unknown user \"%s\"; creating new annotation state" % (username))
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
    output_annotation_dir = config['output_annotation_dir']

    # NB: Do some kind of sanitizing on the username to improve security
    user_dir = path.join(output_annotation_dir, username)

    user_state = lookup_user_state(username)

    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
        logger.debug("Created state directory for user \"%s\"" % (username))

    annotation_order_fname = path.join(user_dir, "annotation_order.txt")
    if not os.path.exists(annotation_order_fname) or save_order:
        with open(annotation_order_fname, 'wt') as outf:
            for inst in user_state.instance_id_ordering:
                # JIAXIN: output id has to be str
                outf.write(str(inst) + '\n')

    annotated_instances_fname = path.join(
        user_dir, "annotated_instances.jsonl")
    
    with open(annotated_instances_fname, 'wt') as outf:
        for inst_id, data in user_state.instance_id_to_labeling.items():
            bd_dict = user_state.instance_id_to_behavioral_data[inst_id] if inst_id in user_state.instance_id_to_behavioral_data else {}
            output = {'id': inst_id, 'annotation': data, 'behavioral_data': bd_dict}
            json.dump(output, outf)
            outf.write('\n')


def save_all_annotations():
    global user_to_annotation_state
    global config
    global instance_id_to_data

    # Figure out where this user's data would be stored on disk
    output_annotation_dir = config['output_annotation_dir']
    fmt = config['output_annotation_format']

    if not (fmt == 'csv' or fmt == 'tsv' or fmt == 'json' or 'jsonl'):
        raise Exception("Unsupported output format: " + fmt)

    if not os.path.exists(output_annotation_dir):
        os.makedirs(output_annotation_dir)
        logger.debug("Created state directory for annotations: %s" % (output_annotation_dir))
        
    annotated_instances_fname = path.join(output_annotation_dir, "annotated_instances." + fmt)
    
    # We write jsonl format regardless        
    if fmt == 'json' or fmt == 'jsonl':
        with open(annotated_instances_fname, 'wt') as outf:
            for user_id, user_state in user_to_annotation_state.items():
                for inst_id, data in user_state.instance_id_to_labeling.items():
                    
                    bd_dict = user_state.instance_id_to_behavioral_data[inst_id] if inst_id in user_state.instance_id_to_behavioral_data else {}
                    output = {'id': inst_id, 'annotation': data, 'behavioral_data': bd_dict}
                    json.dump(output, outf)
                    outf.write('\n')
    

    # Convert to Pandas and then dump
    elif fmt == 'csv' or fmt == 'tsv':
        df = defaultdict(list)

        # Loop 1, figure out which schemas/labels have values
        schema_to_labels = defaultdict(set)

        for user_id, user_state in user_to_annotation_state.items():
            for inst_id, annotation in user_state.instance_id_to_labeling.items():
                for schema, label_vals in annotation.items():
                    for label, val in label_vals.items():
                        schema_to_labels[schema].add(label)
                # TODO: figure out what's in the behavioral dict and how to format it

        # Loop 2, report everything that's been annotated
        for user_id, user_state in user_to_annotation_state.items():
            for inst_id, annotation in user_state.instance_id_to_labeling.items():

                df['user'].append(user_id)
                df['instance_id'].append(inst_id)

                for schema, labels in schema_to_labels.items():
                    if schema in annotation:
                        label_vals = annotation[schema]
                        for label in labels:
                            val = label_vals[label] if label in label_vals else None
                            # For some sanity, combine the schema and label it a single column
                            df[schema + ':::' + label].append(val)
                    # If the user did label this schema at all, fill it with None values
                    else:
                        for label in labels:
                            df[schema + ':::' + label].append(None)
                            
                # TODO: figure out what's in the behavioral dict and how to format it
                
        df = pd.DataFrame(df)
        sep = ',' if fmt == 'csv' else '\t'
        df.to_csv(annotated_instances_fname, index=False, sep=sep)

                    

def load_user_state(username):
    '''
    Loads the user's state from disk. The state includes which instances they
    have annotated and the order in which they are expected to see instances.
    '''
    global user_to_annotation_state
    global config
    global instance_id_to_data
    global logger

    # Figure out where this user's data would be stored on disk
    user_state_dir = config['output_annotation_dir']

    # NB: Do some kind of sanitizing on the username to improve securty
    user_dir = path.join(user_state_dir, username)

    # User has annotated before
    if os.path.exists(user_dir):
        logger.debug(
            "Found known user \"%s\"; loading annotation state" % (username))

        annotation_order_fname = path.join(user_dir, "annotation_order.txt")
        annotation_order = []
        with open(annotation_order_fname, 'rt') as f:
            for line in f:
                instance_id = line[:-1]
                if instance_id not in instance_id_to_data:
                    logger.warning('Annotation state for %s does not match instances in existing dataset at %s'
                                   % (user_dir, ','.join(config['data_files'])))
                    continue
                annotation_order.append(line[:-1])

        annotated_instances_fname = path.join(
            user_dir, "annotated_instances.jsonl")
        annotated_instances = []

        with open(annotated_instances_fname, 'rt') as f:
            for line in f:
                annotated_instance = json.loads(line)
                instance_id = annotated_instance['id']
                if instance_id not in instance_id_to_data:
                    logger.warning('Annotation state for %s does not match instances in existing dataset at %s'
                                   % (user_dir, ','.join(config['data_files'])))
                    continue
                annotated_instances.append(annotated_instance)

        # Ensure the current data is represented in the annotation order
        # NOTE: this is a hack to be fixed for when old user data is in the same directory
        #
        for iid in instance_id_to_data.keys():
            if iid not in annotation_order:
                annotation_order.append(iid)

        id_key = config['item_properties']['id_key']
        user_state = UserAnnotationState(instance_id_to_data)
        user_state.update(id_key, annotation_order, annotated_instances)

        # Make sure we keep track of the user throughout the program
        user_to_annotation_state[username] = user_state

        logger.info("Loaded %d annotations for known user \"%s\"" %
                    (user_state.get_annotation_count(), len(instance_id_to_data)))

    # New user, so initialize state
    else:

        logger.debug(
            "Previously unknown user \"%s\"; creating new annotation state" % (username))
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


@app.route("/annotate", methods=["GET", "POST"])
def annotate_page():
    '''
    Parses the input received from the user's annotation and takes some action
    based on what was clicked/typed. This method is the main switch for changing
    the state of the server for this user.
    '''
    
    global user_config

    
    username = request.form.get("email")

    # Check if the user is authorized. If not, go to the login page
    #if not user_config.is_valid_username(username):
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
    if 'instance_id' in request.form:
        #for key in request.form:
        #    print(key, request.form.get(key))
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
            if "active_learning_config" in config \
               and config["active_learning_config"]['enable_active_learning']:

                # Check to see if we've hit the threshold for the number of
                # annotations needed
                al_config = config["active_learning_config"]

                # How many total annotations do we need to have
                update_rate = al_config['update_rate']
                total_annotations = get_total_annotations()
                print(total_annotations, update_rate, total_annotations % update_rate)
                
                if total_annotations % update_rate == 0:
                    actively_learn()
            
            save_user_state(username)

            # Save everything in a separate thread to avoid I/O issues
            th = threading.Thread(target=save_all_annotations)
            th.start()

    ism = request.form.get("label")
    action = request.form.get("src")

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

    else:
        print('unrecognized action request: "%s"' % action)

    instance = get_cur_instance_for_user(username)

    text_key = config['item_properties']['text_key']
    id_key = config['item_properties']['id_key']
    if config['annotation_task_name'] == "Contextual Acceptability":
        context_key = config['item_properties']['context_key']
        context = instance[context_key]
    
    text = instance[text_key]
    instance_id = instance[id_key]
    
    
    if "keyword_highlights_file" in config:
        updated_text, schema_labels_to_highlight = post_process(config, text)
    else:
        updated_text, schema_labels_to_highlight = text, set()

    # Fill in the kwargs that the user wanted us to include when rendering the page
    kwargs = {}
    if 'kwargs' in config['item_properties']:
        for kw in config['item_properties']['kwargs']:
            kwargs[kw] = instance[kw]

    all_statistics = lookup_user_state(username).generate_user_statistics()

    #TODO: Display plots for agreement scores instead of only the overall score in the statistics sidebar
    all_statistics['Agreement'] = get_agreement_score('all', 'all', return_type='overall_average')
    #print(all_statistics)
        
    # Flask will fill in the things we need into the HTML template we've created,
    # replacing {{variable_name}} with the associated text for keyword arguments
    rendered_html = render_template(
        config['site_file'],
        username=username,
        # This is what instance the user is currently on
        instance=text,
        instance_obj=instance,
        instance_id=instance_id,
        finished=lookup_user_state(username).get_annotation_count(),
        total_count=len(instance_id_to_data),
        alert_time_each_instance=config['alert_time_each_instance'],
        statistics_nav = all_statistics,
        **kwargs
        # amount=len(all_data["annotated_data"]),
        # annotated_amount=user_dict[username]["current_display"]["annotated_amount"],
    )
   

    # UGHGHGHGH the tempalte does unusual escaping, which makes it a PAIN to do
    # the replacement later
    #m = re.search('<div name="instance_text">(.*?)</div>', rendered_html,
    #              flags=(re.DOTALL|re.MULTILINE))
    #text = m.group(1)

    # For whatever reason, doing this before the render_template causes the
    # embedded HTML to get escaped, so we just do a wholesale replacement here.
    #print(text, updated_text)
    #rendered_html = rendered_html.replace(text, updated_text)
    
    # Parse the page so we can programmatically reset the annotation state
    # to what it was before
    soup = BeautifulSoup(rendered_html, 'html.parser')

    # Highlight the schema's labels as necessary
    for schema, label in schema_labels_to_highlight:
        
        name = schema + ":::" + label              
        label_elem = soup.find("label", {"for": name})
        
        # Update style to match the current color
        c = get_color_for_schema_label(schema, label)

        # Jiaxin: sometimes label_elem is None
        if label_elem:
            label_elem['style'] = ("background-color: %s" % c)
            
    # If the user has annotated this before, wall the DOM and fill out what they
    # did
    annotations = get_annotations_for_user_on(username, instance_id)
    if annotations is not None:

        # Reset the state
        for schema, labels in annotations.items():
            for label, value in labels.items():
                name = schema + ":::" + label
                input_field = soup.find("input", {"name": name})
                if input_field is None:
                    print('No input for ', name)
                    continue
                input_field['checked'] = True
                input_field['value'] = value


    rendered_html = str(soup)  # soup.prettify()

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

    all_words = list(set(re.findall(r'\b[a-z]{4,}\b', text)))
    all_words = [w for w in all_words if not w.startswith('http')]
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

                pre = "<span style=\"background-color: %s\">" % c

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

    # Pick a few random words to highlight
    #
    # NOTE: we do this after the label assignment because if we somehow screw up
    # and wrongly flag a valid word, this coloring is embedded within the outer
    # (correct) <span> tag, so the word will get labeled correctly
    num_false_labels = random.randint(0, 1)
    # print('adding %d false labels' % num_false_labels)

    for i in range(min(num_false_labels, len(all_words))):

        # Pick a random word
        to_highlight = all_words[i]

        # Pick a random schema and label
        schema, label = random.choice(all_schemas)

        # print('assigning "%s" to false label "%s:%s"' % (to_highlight, schema, label))

        schema_labels_to_highlight.add((schema, label))

        # Figure out where this word occurs

        c = get_color_for_schema_label(schema, label)

        search_from = 0
        regex = r'\b' + to_highlight + r'\b'
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

            pre = "<span style=\"background-color: %s\">" % c

            replacement = pre + match.group() + '</span>'

            # print(pre + match.group() + '</span>')

            text = text[:start] + replacement + text[end:]

            # Be sure to count all the junk we just added when searching again
            search_from += end + (len(replacement) - len(match.group()))
            # print('\n%d -> %d\n%s' % (end, search_from, text[search_from:]))

    return text, schema_labels_to_highlight


def parse_story_pair_from_file(filepath):
    with open(filepath, "r") as f:
        lines = f.readlines()
    lines = [l.strip("\n").split("\t") for l in lines]
    # random.shuffle(lines)
    return lines


def arguments():
    '''
    Creates and returns the arg parser for Potato on the command line
    '''
    parser = ArgumentParser()
    parser.set_defaults(show_path=False, show_similarity=False)

    parser.add_argument("config_file")

    parser.add_argument("-p", "--port", action="store", type=int, dest="port",
                        help="The port to run on", default=8000)

    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Report verbose output", default=False)

    parser.add_argument("--debug", action="store_true",
                        help="Launch in debug mode with no login", default=False)
    
    parser.add_argument("--veryVerbose", action="store_true", dest="very_verbose",
                        help="Report very verbose output", default=False)
    # parser.add_argument("-p", "--show_path", action="store_true", dest="show_path")
    # parser.add_argument("-s", "--show_sim", action="store_true", dest="show_similarity")

    return parser.parse_args()


def generate_site(config):
    '''
    Generates the full HTML file in site/ for annotating this tasks data,
    combining the various templates with the annotation specification in
    the yaml file.
    '''
    global logger

    logger.info("Generating anntoation site at %s" % config['site_dir'])

    #
    # Stage 1: Construct the core HTML file devoid the annotation-specific content
    #    
    
    # Load the core template that has all the UI controls and non-task layout. 
    html_template_file = config['base_html_template']
    logger.debug("Reading html annotation template %s" % html_template_file)
    
    if not os.path.exists(html_template_file):

        real_path = os.path.realpath(config['__config_file__'])
        dir_path = os.path.dirname(real_path)
        abs_html_template_file = dir_path + '/' + html_template_file
        
        if not os.path.exists(abs_html_template_file):
            raise FileNotFoundError("html_template_file not found: %s" % html_template_file)
        else:
            html_template_file = abs_html_template_file
    
    with open(html_template_file, 'rt') as f:
        html_template = ''.join(f.readlines())

    # Load the header content we'll stuff in the template, which has scripts and assets we'll need
    header_file = config['header_file']
    logger.debug("Reading html header %s" % header_file)
    
    if not os.path.exists(header_file):

        # See if we can get it from the relative path
        real_path = os.path.realpath(config['__config_file__'])
        dir_path = os.path.dirname(real_path)
        abs_header_file = dir_path + '/' + header_file

        if not os.path.exists(abs_header_file):
            raise FileNotFoundError("header_file not found: %s" % header_file)
        else:
            header_file = abs_header_file
    
    with open(header_file, 'rt') as f:
        header = ''.join(f.readlines())

    html_template = html_template.replace("{{ HEADER }}", header)


    # Once we have the base template constructed, load the user's custom layout for their task
    html_layout_file = config['html_layout']
    logger.debug("Reading task layout html %s" % html_layout_file)

    if not os.path.exists(html_layout_file):

        # See if we can get it from the relative path
        real_path = os.path.realpath(config['__config_file__'])
        dir_path = os.path.dirname(real_path)
        abs_html_layout_file = dir_path + '/' + html_layout_file

        if not os.path.exists(abs_html_layout_file):        
            raise FileNotFoundError("html_layout not found: %s" % html_layout_file)
        else:
            html_layout_file = abs_html_layout_file
            
    with open(html_layout_file, 'rt') as f:
        task_html_layout = ''.join(f.readlines())
    

    #
    # Stage 2: Fill in the annotation-specific pieces in the layout
    #    
    
    # Grab the annotation schemes
    annotation_schemes = config['annotation_schemes']
    logger.debug("Saw %d annotation scheme(s)" % len(annotation_schemes))

    # Keep track of all the keybindings we have
    all_keybindings = [
        ('&#8594;', "Next Instance"),
        ('&#8592;', "Previous Instance"),
    ]
    
    # Potato admin can specify a custom HTML layout that allows variable-named
    # placement of task elements
    if 'custom_layout' in config and config['custom_layout']:
        
        for annotation_scheme in annotation_schemes:
            schema_layout, keybindings = generate_schematic(annotation_scheme)
            all_keybindings.extend(keybindings)
            schema_name = annotation_scheme['name']

            updated_layout = task_html_layout.replace(
            "{{" + schema_name + "}}", schema_layout)

            # Check that we actually updated the template
            if task_html_layout == updated_layout:
                raise Exception(
                    ('%s indicated a custom layout but a corresponding layout ' +
                     'was not found for {{%s}} in %s. Check to ensure the ' +
                     'config.yaml and layout.html files have matching names') %
                    (config['__config_file__'], schema_name, config['html_layout']))

            task_html_layout = updated_layout
    # If the admin doesn't specify a custom layout, use the default layout
    else:        
        # If we don't have a custom layout, accumulate all the tasks into a
        # single HTML element 
        schema_layouts = ""
        for annotation_scheme in annotation_schemes:
            schema_layout, keybindings = generate_schematic(annotation_scheme)
            schema_layouts += schema_layout + "\n"
            all_keybindings.extend(keybindings)
            
        task_html_layout = task_html_layout.replace(
            "{{annotation_schematic}}", schema_layouts)

    # Add in a codebook link if the admin specified one
    codebook_html = ''
    if 'annotation_codebook_url' in config and len(config['annotation_codebook_url']) > 0:
        annotation_codebook = config['annotation_codebook_url']
        codebook_html = '<a href="{{annotation_codebook_url}}" class="nav-item nav-link">Annotation Codebook</a>'        
        codebook_html = codebook_html.replace(
            "{{annotation_codebook_url}}", annotation_codebook)


    #
    # Step 3, drop in the annotation layout and insert the rest of the task-specific variables
    #


    # Swap in the task's layout
    html_template = html_template.replace("{{ TASK_LAYOUT }}", task_html_layout)            
    
    html_template = html_template.replace(
        "{{annotation_codebook}}", codebook_html)
        
    html_template = html_template.replace(
        "{{annotation_task_name}}", config['annotation_task_name'])


    keybindings_desc = generate_keybidings_sidebar(all_keybindings)
    html_template = html_template.replace(
        "{{keybindings}}", keybindings_desc)

    statistics_layout = generate_statistics_sidebar(STATS_KEYS)
    html_template = html_template.replace(
        "{{statistics_nav}}", statistics_layout)
    
    
    # Jiaxin: change the basename from the template name to the project name +
    # template name, to allow multiple annotation tasks using the same template
    site_name = '-'.join(config['annotation_task_name'].split(' ')
                         ) + '-' + basename(html_template_file)
    
    output_html_fname = os.path.join(config['site_dir'], site_name)

    # print(basename(html_template_file))
    # print(output_html_fname)

    # Cache this path as a shortcut to figure out which page to render
    config['site_file'] = site_name

    # Write the file
    with open(output_html_fname, 'wt') as outf:
        outf.write(html_template)

    logger.debug('writing annotation html to %s' % output_html_fname)


def generate_statistics_sidebar(statistics):
    '''
    Generate an HTML layout for the end-user of the statistics for the current
    task. The layout is intended to be displayed in a side bar
    '''

    layout = '<table><tr><th> </th><th> </th></tr>'
    for key in statistics:
        desc = "{{statistics_nav[\'%s\']}}" % statistics[key]
        layout += '<tr><td style="text-align: center;">%s</td><td>%s</td></tr>' % (key, desc)
    layout += '</table>'
    return layout


def generate_keybidings_sidebar(keybindings):
    '''
    Generate an HTML layout for the end-user of the keybindings for the current
    task. The layout is intended to be displayed in a side bar
    '''

    layout = '<table><tr><th>Key</th><th>Description</th></tr>'
    for key, desc in keybindings:
        layout += '<tr><td style="text-align: center;">%s</td><td>%s</td></tr>' % (key, desc)
    layout += '</table>'
    return layout
        

def generate_schematic(annotation_scheme):
    '''
    Based on the task's yaml configuration, generate the full HTML site needed
    to annotate the tasks's data.
    '''
    global logger

    # Figure out which kind of tasks we're doing and build the input frame
    annotation_type = annotation_scheme['annotation_type']

    if annotation_type == "multiselect":
        return generate_multiselect_layout(annotation_scheme)
    
    elif annotation_type == "radio":
        return generate_radio_layout(annotation_scheme)

    elif annotation_type == "likert":
        return generate_likert_layout(annotation_scheme)
        
    elif annotation_type == "text":
        return generate_textbox_layout(annotation_scheme)

    else:
        raise Exception("unsupported annotation type: %s" % annotation_type)


def generate_multiselect_layout(annotation_scheme):
    global logger
    
    schematic = \
        '<form action="/action_page.php">' + \
        '  <fieldset>' + \
        ('  <legend>%s</legend>' % annotation_scheme['description'])

    # TODO: display keyboard shortcuts on the annotation page
    key2label = {}
    label2key = {}

    key_bindings = []

    display_info = annotation_scheme['display_config'] if 'display_config' in annotation_scheme else {}
    
    n_columns = display_info['num_columns'] if 'num_columns' in display_info else 1

    schematic += '<table>'
    
    for i, label_data in enumerate(annotation_scheme['labels'], 1):

        
        if (i-1) % n_columns == 0:
            schematic += '<tr>'
        schematic += '<td>'
        
        label = label_data if isinstance(
            label_data, str) else label_data['name']

        name = annotation_scheme['name'] + ':::' + label
        class_name = annotation_scheme['name']
        key_value = name

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
                tooltip = 'data-toggle="tooltip" data-html="true" data-placement="top" title="%s"' \
                    % tooltip_text
                
            if 'key_value' in label_data:
                key_value = label_data['key_value']
                if key_value in key2label:
                    logger.warning(
                        "Keyboard input conflict: %s" % key_value)
                    quit()
                key2label[key_value] = label
                label2key[label] = key_value
                key_bindings.append((key_value, class_name +': ' + label))

        if "sequential_key_binding" in annotation_scheme \
           and  annotation_scheme["sequential_key_binding"] \
           and len(annotation_scheme['labels']) <= 10:
            key_value = str(i % 10)
            key2label[key_value] = label
            label2key[label] = key_value            

        label_content = label
        if annotation_scheme.get("video_as_label", None) == "True":
            assert "videopath" in label_data, "Video path should in each label_data when video_as_label is True."
            video_path = label_data["videopath"]
            label_content = f'''
            <video width="320" height="240" autoplay loop muted>
                <source src="{video_path}" type="video/mp4" />
            </video>'''
            
        #add shortkey to the label so that the annotators will know how to use it
        #when the shortkey is "None", this will not displayed as we do not allow short key for None category
        #if label in label2key and label2key[label] != 'None':
        #if label in label2key:
        #    label_content = label_content + \
        #        ' [' + label2key[label].upper() + ']'
        
        if ("single_select" in annotation_scheme) and (annotation_scheme["single_select"] == "True"):
            logger.warning("single_select is Depricated and will be removed soon. Use \"radio\" instead.")
            schematic += \
                (('  <input class="%s" type="checkbox" id="%s" name="%s" value="%s" onclick="onlyOne(this)">' +
                  '  <label for="%s" %s>%s</label><br/>')
                 % (class_name, label, name, key_value, name, tooltip, label_content))
        else:
            schematic += \
                (('<label for="%s" %s><input class="%s" type="checkbox" id="%s" name="%s" value="%s" onclick="whetherNone(this)">' +
                 '  %s</label><br/>')
                 % (name, tooltip, class_name, name, name, key_value, label_content))

        schematic += '</td>'
        if i % n_columns == 0:
            schematic += '</tr>'


    if 'has_free_response' in annotation_scheme and annotation_scheme['has_free_response']:

        label='free_response'
        name = annotation_scheme['name'] + ':::free_response' 
        class_name = annotation_scheme['name']
        tooltip = 'Entire a label not listed here'

        schematic += \
        (('Other? <input class="%s" type="text" id="%s" name="%s" >' +
         '  <label for="%s" %s></label><br/>')
         % (class_name, label, name, name, tooltip))


    schematic += '</table>'
    schematic += '  </fieldset>\n</form>\n'

    return schematic, key_bindings


def generate_radio_layout(annotation_scheme, horizontal=False):

    schematic = \
        '<form action="/action_page.php">' + \
        '  <fieldset>' + \
        ('  <legend>%s</legend>' % annotation_scheme['description'])

    # TODO: display keyboard shortcuts on the annotation page
    key2label = {}
    label2key = {}
    key_bindings = []
    
    for i, label_data in enumerate(annotation_scheme['labels'], 1):

        label = label_data if isinstance(
            label_data, str) else label_data['name']

        name = annotation_scheme['name'] + ':::' + label
        class_name = annotation_scheme['name']
        key_value = name

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
                tooltip = 'data-toggle="tooltip" data-html="true" data-placement="top" title="%s"' \
                    % tooltip_text

            # Bind the keys
            if 'key_value' in label_data:
                key_value = label_data['key_value']
                if key_value in key2label:
                    logger.warning(
                        "Keyboard input conflict: %s" % key_value)
                    quit()
                key2label[key_value] = label
                label2key[label] = key_value
                key_bindings.append((key_value, class_name +': ' + label))
            # print(key_value)
            
        if "sequential_key_binding" in annotation_scheme \
           and annotation_scheme["sequential_key_binding"] \
           and len(annotation_scheme['labels']) <= 10:
            key_value = str(i % 10)
            key2label[key_value] = label
            label2key[label] = key_value            
            

        label_content = label
        if annotation_scheme.get("video_as_label", None) == "True":
            assert "videopath" in label_data, "Video path should in each label_data when video_as_label is True."
            video_path = label_data["videopath"]
            label_content = f'''
            <video width="320" height="240" autoplay loop muted>
                <source src="{video_path}" type="video/mp4" />
            </video>'''

        # Add shortkey to the label so that the annotators will know how to use
        # it when the shortkey is "None", this will not displayed as we do not
        # allow short key for None category if label in label2key and
        # label2key[label] != 'None':
        #if label in label2key:
        #    label_content = label_content + \
        #        ' [' + label2key[label].upper() + ']'

        schematic += \
                (('  <input class="%s" type="radio" id="%s" name="%s" value="%s" onclick="onlyOne(this)">' +
                 '  <label for="%s" %s>%s</label><br/>')
                 % (class_name, label, name, key_value, name, tooltip, label_content))

    if 'has_free_response' in annotation_scheme and annotation_scheme['has_free_response']:

        label='free_response'
        name = annotation_scheme['name'] + ':::free_response' 
        class_name = annotation_scheme['name']
        tooltip = 'Entire a label not listed here'

        schematic += \
        (('Other? <input class="%s" type="text" id="%s" name="%s" >' +
         '  <label for="%s" %s></label><br/>')
         % (class_name, label, name, name, tooltip))        

    schematic += '  </fieldset>\n</form>\n'
    return schematic, key_bindings


def generate_likert_layout(annotation_scheme):

    # If the user specified the more complicated likert layout, default to the
    # radio layout
    if 'labels' in annotation_scheme:
        return generate_radio_layout(annotation_scheme, horizontal=False)

    if 'size' not in annotation_scheme:
        raise Exception('Likert scale for "%s" did not include size' \
                        % annotation_scheme['name'])
    if 'min_label' not in annotation_scheme:
        raise Exception('Likert scale for "%s" did not include min_label' \
                        % annotation_scheme['name'])
    if 'max_label' not in annotation_scheme:
        raise Exception('Likert scale for "%s" did not include max_label' \
                        % annotation_scheme['name'])

    schematic = \
        ('<div><form action="/action_page.php">' + \
        '  <fieldset> <legend>%s</legend> <ul class="likert"> <li> %s </li>') \
        % (annotation_scheme['description'], annotation_scheme['min_label'])
    
    key2label = {}
    label2key = {}    
    key_bindings = []
    
    for i in range(1, annotation_scheme['size']+1):

        label = 'scale_' + str(i)
        name = annotation_scheme['name'] + ':::' + label
        class_name = annotation_scheme['name']

        key_value = str(i % 10)
        
        # if the user wants us to add in easy key bindings
        if "sequential_key_binding" in annotation_scheme \
           and annotation_scheme["sequential_key_binding"] \
           and annotation_scheme['size'] <= 10: 
            key2label[key_value] = label
            label2key[label] = key_value
            key_bindings.append((key_value, class_name + ': ' + key_value))

            
        # In the collapsed version of the likert scale, no label is shown.
        label_content = ''
        tooltip = ''        

        #schematic += \
        #        ((' <li><input class="%s" type="radio" id="%s" name="%s" value="%s" onclick="onlyOne(this)">' +
        #         '  <label for="%s" %s>%s</label></li>')
        #         % (class_name, label, name, key_value, name, tooltip, label_content))

        schematic += \
            ((' <li><input class="{class_name}" type="radio" id="{id}" name="{name}" value="{value}" onclick="onlyOne(this)">' + \
              '  <label for="{label_for}" {label_args}>{label_text}</label></li>')).format(
                  class_name=class_name, id=label, name=name, value=key_value, label_for=name, 
                  label_args=tooltip, label_text=label_content)


    schematic += ('  <li>%s</li> </ul></fieldset>\n</form></div>\n' \
                  % (annotation_scheme['max_label']))
    
    return schematic, key_bindings



def generate_textbox_layout(annotation_scheme):
    
    #'<div style="border:1px solid black; border-radius: 25px;">' + \
    schematic = \
        '<form action="/action_page.php">' + \
        '  <fieldset>' + \
        ('  <legend>%s</legend>' % annotation_scheme['description'])

    # TODO: display keyboard shortcuts on the annotation page
    key2label = {}
    label2key = {}

    # TODO: decide whether text boxes need labels
    label = 'text_box'

    name = annotation_scheme['name'] + ':::' + label
    class_name = annotation_scheme['name']
    key_value = name

    # Technically, text boxes don't have these but we define it anyway
    key_bindings = []

    display_info = annotation_scheme['display_config'] if 'display_config' in annotation_scheme else {}

    # TODO: pull this out into a separate method that does some sanity checks
    custom_css = '""'
    if 'custom_css' in display_info:
        custom_css = '"'
        for k, v in display_info['custom_css'].items():
            custom_css += k + ":" + v + ";"
        custom_css += '"'
    
    tooltip = ''
    if False:
        if 'tooltip' in annotation_scheme:
            tooltip_text = annotation_scheme['tooltip']
            # print('direct: ', tooltip_text)
        elif 'tooltip_file' in annotation_scheme:
            with open(annotation_scheme['tooltip_file'], 'rt') as f:
                lines = f.readlines()
            tooltip_text = ''.join(lines)
            # print('file: ', tooltip_text)
        if len(tooltip_text) > 0:
            tooltip = 'data-toggle="tooltip" data-html="true" data-placement="top" title="%s"' \
                % tooltip_text
        if 'key_value' in label_data:
            key_value = label_data['key_value']
            if key_value in key2label:
                logger.warning(
                    "Keyboard input conflict: %s" % key_value)
                quit()
            key2label[key_value] = label
            label2key[label] = key_value


    label_content = label

    #add shortkey to the label so that the annotators will know how to use it
    #when the shortkey is "None", this will not displayed as we do not allow short key for None category
    #if label in label2key and label2key[label] != 'None':
    if label in label2key:
        label_content = label_content + \
            ' [' + label2key[label].upper() + ']'


    schematic += \
            (('  <input class="%s" style=%s type="text" id="%s" name="%s" >' +
             '  <label for="%s" %s></label><br/>')
             % (class_name, custom_css, label, name, name, tooltip))


    #schematic += '  </fieldset>\n</form></div>\n'
    schematic += '  </fieldset>\n</form>\n'

    
    return schematic, key_bindings
    

@app.route('/file/<path:filename>')
def get_file(filename):
    """Return css file in css folder."""
    try:
        return flask.send_from_directory("data/files/", filename)
    except FileNotFoundError:
        flask.abort(404)



def get_class( kls ):
    '''
    Returns an instantiated class object from a fully specified name.
    '''
    parts = kls.split('.')
    module = ".".join(parts[:-1])
    m = __import__( module )
    for comp in parts[1:]:
        m = getattr(m, comp)            
    return m


def actively_learn():
    global config
    global logger
    global user_to_annotation_state
    global instance_id_to_data

    if 'active_learning_config' not in config:
        logger.warning("the server is trying to do active learning " +
                       "but this hasn't been configured")
        return

    al_config = config['active_learning_config']

    # Skip if the user doesn't want us to do active learning
    if 'enable_active_learning' in al_config and not al_config['enable_active_learning']:
        return

    if 'classifier_name' not in al_config:
        raise Exception("active learning enabled but no classifier is set with \"classifier_name\"")

    if 'vectorizer_name' not in al_config:
        raise Exception("active learning enabled but no vectorizer is set with \"vectorizer_name\"")

    if 'resolution_strategy' not in al_config:
        raise Exception("active learning enabled but resolution_strategy is not set")

    # This specifies which schema we need to use in active learning (separate
    # classifiers for each). If the user doesn't specify these, we use all of
    # them.
    schema_used = []
    if "active_learning_schema" in al_config:
        schema_used = al_config["active_learning_schema"]
    
    cls_kwargs = al_config['classifier_kwargs'] if 'classifier_kwargs' in al_config else {}
    vectorizer_kwargs = al_config['vectorizer_kwargs'] if 'vectorizer_kwargs' in al_config else {}
    strategy = al_config['resolution_strategy']

    # Collect all the current labels
    instance_to_labels = defaultdict(list)
    for uid, uas in user_to_annotation_state.items():
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
    text_key = config['item_properties']['text_key']
    for iid, schema_to_label in instance_to_label.items():
        # get the text
        text = instance_id_to_data[iid][text_key]
        texts.append(text)
        for s in schema_seen:
            # In some cases where the user has not selected anything but somehow
            # this is considered annotated, we include some dummy label
            label = schema_to_label[s] if s in schema_to_label else 'DUMMY:NONE'

            # HACK: this needs to get fixed for multilabel data and possibly
            # number data
            label = list(label.keys())[0]
            scheme_to_labels[s].append(label)


    scheme_to_classifier = {}
            
    # Train a classifier for each scheme
    for scheme, labels in scheme_to_labels.items():

        # Sanity check we have more than 1 label
        print(labels)
        label_counts = Counter(labels)
        if len(label_counts) < 2:
            logger.warning(('In the current data, data labeled with %s has only a'
                            + 'single unique label, which is insufficient for '
                            + 'active learning; skipping...') % scheme)
            continue

        # Instantiate the classifier and the tokenizer
        cls = get_class(al_config['classifier_name'])(**cls_kwargs)
        vectorizer = get_class(al_config['vectorizer_name'])(**vectorizer_kwargs)

        # Train the classifier
        clf = Pipeline([('vectorizer', vectorizer), ('classifier', cls)])
        logger.info("training classifier for %s..." % scheme)
        clf.fit(texts, labels)
        logger.info("done training classifier for %s" % scheme)
        scheme_to_classifier[scheme] = clf


    # Get the remaining unlabeled instances and start predicting
    unlabeled_ids = [iid for iid in instance_id_to_data if iid not in instance_to_label]
    random.shuffle(unlabeled_ids)

    perc_random = al_config['random_sample_percent'] / 100

    # Split to keep some of the data random
    random_ids = unlabeled_ids[int(len(unlabeled_ids) * perc_random):]
    unlabeled_ids = unlabeled_ids[:int(len(unlabeled_ids) * perc_random)]
    remaining_ids = []
    
    # Cap how much inference we need to do (important for big datasets)    
    if 'max_inferred_predictions' in al_config:
        max_insts = al_config['max_inferred_predictions']
        remaining_ids = unlabeled_ids[max_insts:]
        unlabeled_ids = unlabeled_ids[:max_insts]

    # For each scheme, use its classifier to label the data
    scheme_to_predictions = {}
    unlabeled_texts = [instance_id_to_data[iid][text_key] for iid in unlabeled_ids]
    for scheme, clf in scheme_to_classifier.items():
        logger.info("Inferring labels for %s" % scheme)
        preds = clf.predict_proba(unlabeled_texts)
        scheme_to_predictions[scheme] = preds
        # id_to_scheme_to_predictions[iid][scheme] = preds
            
    # Figure out which of the instances to prioritize, keeping the specified
    # ratio of random-vs-AL-selected instances.
    ids_and_confidence = []
    logger.info("Scoring items by model confidence")
    for i, iid in enumerate(tqdm(unlabeled_ids)):
        most_confident_pred = 0
        mp_scheme = None
        for scheme, all_preds in scheme_to_predictions.items():

            preds = all_preds[i,:]
            mp = max(preds)
            # print(mp, preds)
            if mp > most_confident_pred:
                most_confident_pred = mp
                mp_scheme = scheme
        ids_and_confidence.append((iid, most_confident_pred, mp_scheme))

    # Sort by confidence
    ids_and_confidence = sorted(ids_and_confidence, key=lambda x: x[1])

    print(ids_and_confidence[:5])
        
    # Re-order all of the unlabeled instances
    new_id_order = []
    id_to_selection_type = {}
    for (al, rand_id) in zip_longest(ids_and_confidence, random_ids, fillvalue=None):
        if al:
            new_id_order.append(al[0])
            id_to_selection_type[al[0]] = '%s Classifier' % al[2]
        if rand_id:
            new_id_order.append(rand_id)
            id_to_selection_type[rand_id] = 'Random'
            
    # These are the IDs that weren't in the random sample or that we didn't
    # reorder with active learning
    new_id_order.extend(remaining_ids)

    # Update each user's ordering, preserving the order for any item that has
    # any annotation so that it stays in the front of the users' queues even if
    # they haven't gotten to it yet (but others have)
    already_annotated = list(instance_to_labels.keys())
    for user, annotation_state in user_to_annotation_state.items():
        annotation_state.reorder_remaining_instances(new_id_order,
                                                     already_annotated)

    logger.info('Finished reording instances')
        
def resolve(annotations, strategy):
    if strategy == 'random':
        return random.choice(annotations)
    else:
        raise Exception("Unknonwn annotation resolution strategy: \"%s\"" % (strategy))
    

        
def main():
    global config
    global logger
    global user_config
    global user_to_annotation_state

    args = arguments()

    with open(args.config_file, 'rt') as f:
        config = yaml.safe_load(f)

    user_config = UserConfig(USER_CONFIG_PATH)

    #Jiaxin: commenting the following lines since we will have a seperate
    #        user_config file to save user info.  This is necessary since we
    #        cannot directly write to the global config file for user
    #        registration
    '''
    user_config_data = config['user_config']
    if 'allow_all_users' in user_config_data:
        user_config.allow_all_users = user_config_data['allow_all_users']

        if 'users' in user_config_data:       
            for user in user_config_data["users"]:
                username = user['firstname'] + '_' + user['lastname']
                user_config.add_user(username)
    '''

    logger_name = 'potato'
    if 'logger_name' in config:
        logger_name = config['logger_name']
                
    logger = logging.getLogger(logger_name)

    logger.setLevel(logging.INFO)
    logging.basicConfig()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    if args.very_verbose:
        logger.setLevel(logging.NOTSET)

    # For helping in debugging, stuff in the config file name
    config['__config_file__'] = args.config_file

    if args.debug:
        config['__debug__'] = True
    
    # Creates the templates we'll use in flask by mashing annotation
    # specification on top of the proto-templates
    generate_site(config)

    # Loads the training data
    load_all_data(config)

    # Generate the output directory if it doesn't exist yet
    if not os.path.exists(config['output_annotation_dir']):
        os.makedirs(config['output_annotation_dir'])
        
    # load users with annotations to user_to_annotation_state
    users_with_annotations = [f for f in os.listdir(config['output_annotation_dir']) if os.path.isdir(config['output_annotation_dir'] + f)]
    for user in users_with_annotations:
        load_user_state(user)

    # TODO: load previous annotation state
    # load_annotation_state(config)

    flask_logger = logging.getLogger('werkzeug')
    flask_logger.setLevel(logging.ERROR)

    print('running at:\nlocalhost:'+str(args.port))
    app.run(debug=args.very_verbose, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
