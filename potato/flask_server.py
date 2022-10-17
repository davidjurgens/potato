import os
import numpy as np
import flask
from flask import Flask, render_template, request
import sys
import pandas as pd

import yaml
import re
from os.path import basename

from os import path

from bs4 import BeautifulSoup

from tqdm import tqdm

import threading


import logging

# import requests
import random
random.seed(0)
import json
from collections import deque, defaultdict, Counter, OrderedDict
from collections.abc import Mapping
from argparse import ArgumentParser

from sklearn.pipeline import Pipeline

from itertools import zip_longest
import krippendorff
import string

import webbrowser

from create_task_cli import create_task_cli

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

#A global mapping from username to the annotator's
user_to_annotation_state = {}

# A global mapping from an instance's id to its data. This is filled by
# load_all_data()
instance_id_to_data = {}

#A global dict to keep tracking of the task assignment status
task_assignment = {}

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

SPAN_COLOR_PALETTE = ['(230, 25, 75)', '(60, 180, 75)', '(255, 225, 25)', '(0, 130, 200)', '(245, 130, 48)', '(145, 30, 180)', '(70, 240, 240)', '(240, 50, 230)', '(210, 245, 60)', '(250, 190, 212)', '(0, 128, 128)', '(220, 190, 255)', '(170, 110, 40)', '(255, 250, 200)', '(128, 0, 0)', '(170, 255, 195)', '(128, 128, 0)', '(255, 215, 180)', '(0, 0, 128)', '(128, 128, 128)', '(255, 255, 255)', '(0, 0, 0)']

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
    
    def __init__(self, assigned_user_data):

        # This data structure keeps the label-based annotations the user has
        # completed so far
        self.instance_id_to_labeling = {}

        # This data structure keeps the span-based annotations the user has
        # completed so far
        self.instance_id_to_span_annotations = {}
        
        # This is a reference to the data
        #
        # NB: do we need this as a field?
        self.instance_id_to_data = assigned_user_data

        # TODO: Put behavioral information of each instance with the labels
        # together however, that requires too many changes of the data structure
        # therefore, we contruct a separate dictionary to save all the
        # behavioral information (e.g. time, click, ..)
        self.instance_id_to_behavioral_data = {}

        # NOTE: this might be dumb but at the moment, we cache the order in
        # which this user will walk the instances. This might not work if we're
        # annotating a ton of things with a lot of people, but hopefully it's
        # not too bad. The underlying motivation is to programmatically change
        # this ordering later
        self.instance_id_ordering = list(assigned_user_data.keys())

        #initialize the mapping from instance id to order
        self.instance_id_to_order = self.generate_id_order_mapping(self.instance_id_ordering)

        self.instance_cursor = 0

        # Indicator of whether the user has passed the prestudy, None means no
        # prestudy or prestudy not complete, True means passed and False means
        # failed
        self.prestudy_passed = None
        
        # Indicator of whether the user has agreed to participate this study,
        # None means consent not complete, True means yes and False measn no
        self.consent_agreed = None

        # Total annotation instances assigned to a user
        self.real_instance_assigned_count = 0

    def generate_id_order_mapping(self,instance_id_ordering):
        id_order_mapping = {}
        for i in range(len(instance_id_ordering)):
            id_order_mapping[instance_id_ordering[i]] = i
        return id_order_mapping

    # add new assigned data to the user state
    def add_new_assigned_data(self, new_assigned_data):
        for key in new_assigned_data:
            self.instance_id_to_data[key] = new_assigned_data[key]
            self.instance_id_ordering.append(key)
        self.instance_id_to_order = self.generate_id_order_mapping(self.instance_id_ordering)

    def get_assigned_data(self):
        return self.instance_id_to_data

    def current_instance(self):
        #print("current_instance(): cursor is now ", self.instance_cursor)
        inst_id = self.instance_id_ordering[self.instance_cursor]
        instance = self.instance_id_to_data[inst_id]
        return instance

    def get_instance_cursor(self):
        return self.instance_cursor

    def cursor_to_real_instance_id(self, cursor):
        return self.instance_id_ordering[cursor]

    def is_prestudy_question(self, cursor):
        return self.instance_id_ordering[cursor][:8] == 'prestudy'

    def go_back(self):
        if self.instance_cursor > 0:
            if self.prestudy_passed != None and self.is_prestudy_question(self.instance_cursor - 1):
                return
            self.instance_cursor -= 1

    def go_forward(self):
        old_cur = self.instance_cursor
        if self.instance_cursor < len(self.instance_id_to_data) - 1:
            self.instance_cursor += 1

    def go_to_id(self, id):
        old_cur = self.instance_cursor
        if id < len(self.instance_id_to_data) and id >= 0:
            self.instance_cursor = id

    def get_all_annotations(self):
        '''
        Returns all annotations (label and span) for all annotated instances
        '''
        labeled = set(self.instance_id_to_labeling.keys()) | \
            set(self.instance_id_to_span_annotations.keys())

        anns = {}
        for iid in labeled:
            labels = {}
            if iid in self.instance_id_to_labeling:
                labels = self.instance_id_to_labeling[iid]
            spans = {}
            if iid in self.instance_id_to_span_annotations:
                spans = self.instance_id_to_span_annotations[iid]

            anns[iid] = { 'labels': labels, 'spans': spans }

        return anns
            
    def get_label_annotations(self, instance_id):
        '''
        Returns the label-based annotations for the instance.
        '''
        if instance_id not in self.instance_id_to_labeling:
            return None
        else:
            # NB: Should this be a view/copy?
            return self.instance_id_to_labeling[instance_id]

    def get_span_annotations(self, instance_id):
        '''
        Returns the span annotations for this instance.
        '''
        if instance_id not in self.instance_id_to_span_annotations:
            return None
        else:
            # NB: Should this be a view/copy?
            return self.instance_id_to_span_annotations[instance_id]
        
    def get_annotation_count(self):
        return len(self.instance_id_to_labeling) + \
            len(self.instance_id_to_span_annotations)

    def get_assigned_instance_count(self):
        return len(self.instance_id_ordering)

    def set_prestudy_status(self, whether_passed):
        if self.prestudy_passed != None:
            return False
        self.prestudy_passed = whether_passed
        return True

    # check if the user has passed the prestudy test
    def get_prestudy_status(self):
        return  self.prestudy_passed

    # check if the user has agreed to participate this study
    def get_consent_status(self):
        return  self.consent_agreed

    # check the number of assigned instances for a user (only the core annotation parts)
    def get_real_assigned_instance_count(self):
        return  self.real_instance_assigned_count

    def set_annotation(self, instance_id, schema_to_label_to_value,
                       span_annotations, behavioral_data_dict):
        '''
        Based on a user's actions, updates the annotation for this particular instance.

        :span_annotations: a list of span annotations, which are each
          represented as dictionary objects/
        :return: True if setting these annotation values changes the previous
          annotation of this instance.
        '''

        # Get whatever annotations were present for this instance, or, if the
        # item has not been annotated represent that with empty data structures
        # so we can keep track of whether the state changes
        if instance_id in self.instance_id_to_labeling:
            old_annotation = self.instance_id_to_labeling[instance_id]
        else:
            old_annotation = defaultdict(dict)
            
        if instance_id in self.instance_id_to_span_annotations:
            old_span_annotations = self.instance_id_to_span_annotations[instance_id]
        else:
            old_span_annotations = []
            
        # Avoid updating with no entries
        if len(schema_to_label_to_value) > 0:
            self.instance_id_to_labeling[instance_id] = schema_to_label_to_value
        # If the user didn't label anything (e.g. they unselected items), then
        # we delete the old annotation state
        elif instance_id in self.instance_id_to_labeling:
            del self.instance_id_to_labeling[instance_id]

        # Avoid updating with no entries
        if len(span_annotations) > 0:
            self.instance_id_to_span_annotations[instance_id] = span_annotations
        # If the user didn't label anything (e.g. they unselected items), then
        # we delete the old annotation state
        elif instance_id in self.instance_id_to_span_annotations:
            del self.instance_id_to_span_annotations[instance_id]

        # TODO: keep track of all the annotation behaviors instead of only
        # keeping the latest one each time when new annotation is updated,
        # we also update the behavioral_data_dict (currently done in the
        # update_annotation_state function)
        #
        #self.instance_id_to_behavioral_data[instance_id] = behavioral_data_dict           
        
        return old_annotation != schema_to_label_to_value or \
            old_span_annotations != span_annotations

    # This is only used to update the entire list of annotations,
    # normally when loading all the saved data
    def update(self, annotation_order, annotated_instances):
        '''
        Updates the entire state of annotations for this user by inserting
        all the data in annotated_instances into this user's state. Typically
        this data is loaded from a file

        :annotation_order: a list of string instance IDs in the order that this
        user should see those instances.
        :annotated_instances: a list of dictionary objects detailing the
        annotations on each item.
        '''
        
        self.instance_id_to_labeling = {}
        for inst in annotated_instances:

            inst_id = inst['id']
            label_annotations = inst['label_annotations']
            span_annotations = inst['span_annotations']

            self.instance_id_to_labeling[inst_id] = label_annotations
            self.instance_id_to_span_annotations[inst_id] = span_annotations

            behavior_dict = {}
            if 'behavioral_data' in inst:
                behavior_dict = inst['behavioral_data']
            self.instance_id_to_behavioral_data[inst_id] = behavior_dict
            
            # TODO: move this code somewhere else so consent is organized
            # separately
            if re.search('consent', inst_id):
                consent_key = 'I want to participate in this research and continue with the study.'
                if 'Yes' in annotation[consent_key] and annotation[consent_key]['Yes'] == 'true':
                    self.consent_agreed = True
                else:
                    self.consent_agreed = False
            

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
    global unassigned_ids
    global task_assignment

    # Hacky nonsense
    global re_to_highlights

    # Where to look in the JSON item object for the text to annotate
    text_key = config['item_properties']['text_key']
    id_key = config['item_properties']['id_key']

    # todo: depreciate this variable since it's not actively used
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


    #todo setup automatic test questions for each annotation schema, currently we are doing it similar to survey flow to allow multilingual test questions
    if "surveyflow" in config and config["surveyflow"]['on']:
        if "testing" in config["surveyflow"] and len(config["surveyflow"]["testing"]) > 0:
            for test_file in config["surveyflow"]["testing"]:
                with open(test_file, 'r') as r:
                    for line in r:
                        line = json.loads(line.strip())
                        for l in line['choices']:
                            item = {"id": line['id'] + '_testing_' + l, "text": line['text'].replace('[test_question_choice]', l)}
                            # currently we simply move all these test questions to the end of the instance list
                            instance_id_to_data.update({item['id']: item})
                            instance_id_to_data.move_to_end(item['id'], last=True)
                            items_to_annotate.append(item)


    # insert survey questions into instance_id_to_data
    #if "surveyflow" in config and config["survey"]['on']:
    if "pre_annotation_pages" in config:
        for page in config["pre_annotation_pages"]:
            #todo currently we simply remove the language type before -, but we need a more elegant way for this in the future
            item = {"id":page,"text":page.split('-')[-1][:-5]}
            instance_id_to_data.update({page:item})
            instance_id_to_data.move_to_end(page, last=False)
            items_to_annotate.insert(0, item)

    for it in ['prestudy_failed_pages', 'prestudy_passed_pages']:
        if it in config:
            for page in config[it]:
                #todo currently we simply remove the language type before -, but we need a more elegant way for this in the future
                item = {"id":page,"text":page.split('-')[-1][:-5]}
                instance_id_to_data.update({page:item})
                instance_id_to_data.move_to_end(page, last=False)
                items_to_annotate.insert(0, item)

    if "post_annotation_pages" in config:
        for page in config["post_annotation_pages"]:
            item = {"id":page,"text":page.split('-')[-1][:-5]}
            instance_id_to_data.update({page:item})
            instance_id_to_data.move_to_end(page, last=True)
            items_to_annotate.append(item)




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



    # Load the annotation assignment info if automatic task assignment is on.
    # Jiaxin: we are simply saving this as a json file at this moment
    if "automatic_assignment" in config and config["automatic_assignment"]['on']:

        # path to save task assignment information
        task_assignment_path = config['output_annotation_dir'] + config["automatic_assignment"]["output_filename"]

        if os.path.exists(task_assignment_path):
            # load the task assignment if it has been generated and saved
            with open(task_assignment_path, 'r') as r:
                task_assignment = json.load(r)
        else:
            # Otherwise generate a new task assignment dict
            task_assignment = {'assigned':{}, 'unassigned':{}, 'testing': {'test_question_per_annotator': 0, 'ids': []}, 'prestudy_ids': [], 'prestudy_passed_users':[], 'prestudy_failed_users':[]}
            # setting test_question_per_annotator if it is defined in automatic_assignment, otherwise it is default to 0 and no test question will be used
            if "test_question_per_annotator" in config["automatic_assignment"]:
                task_assignment['testing']['test_question_per_annotator'] = config["automatic_assignment"]["test_question_per_annotator"]

            for it in ['pre_annotation', 'prestudy_passed', 'prestudy_failed', 'post_annotation']:
                if it + '_pages' in config:
                    task_assignment[it + '_pages'] = config[it + '_pages']
                    for p in config[it + '_pages']:
                        task_assignment['assigned'][p] = 0

            for id in instance_id_to_data:
                if id in task_assignment['assigned']:
                    continue
                # add test questions to the assignment dict
                if re.search('testing', id):
                    task_assignment['testing']['ids'].append(id)
                    continue
                elif re.search('prestudy', id):
                    task_assignment['prestudy_ids'].append(id)
                    continue
                # set the total labels per instance, if not specified, default to 3
                task_assignment['unassigned'][id] = config["automatic_assignment"]["labels_per_instance"] if "labels_per_instance" in config["automatic_assignment"] else 3
                #task_assignment['assigned'][id] = []



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
            elif isinstance(alpha, (np.floating, float)):
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

    # Jiaxin: the instance_id are changed to the user's local instance cursor
    instance_id = user_state.cursor_to_real_instance_id(int(request.form['instance_id']))

    schema_to_label_to_value = defaultdict(dict)

    behavioral_data_dict = {}
    
    did_change = False
    for key in form:


        # look for behavioral information regarding time, click, ...
        if key[:9] == 'behavior_':
            behavioral_data_dict[key[9:]] = form[key]
            continue
       
        # Look for the marker that indicates an annotation label.
        #
        # NOTE: The span annotation uses radio buttons as well to figure out
        # which label. These inputs are labeled with "span_label" so we can skip
        # them as being actual annotatins (the spans are saved below though).
        if ':::' in key and 'span_label' not in key:

            cols = key.split(':::')
            annotation_schema = cols[0]
            annotation_label = cols[1]
            annotation_value = form[key]

            #skip the input when it is an empty string (from a text-box)
            if annotation_value == '':
                continue

            schema_to_label_to_value[annotation_schema][annotation_label] = annotation_value

    # Span annotations are a bit funkier since we're getting raw HTML that
    # we need to post-process on the server side.
    span_annotations = []
    if 'span-annotation' in form:
        span_annotation_html = form['span-annotation']
        span_text, span_annotations = parse_html_span_annotation(span_annotation_html)
        # print('span_annotations:' , span_annotations)            
            
    # print("Received annotations from %s" % username, schema_to_label_to_value)

    # print("-- for user %s, instance %s -> %s" % (username, instance_id, str(schema_to_labels)))


    did_change = user_state.set_annotation(instance_id, schema_to_label_to_value,
                                           span_annotations, behavioral_data_dict)


    # update the behavioral information regarding time only when the annotations are changed
    if did_change:
        user_state.instance_id_to_behavioral_data[instance_id] = behavioral_data_dict
        # print('misc information updated')

        # todo: we probably need a more elegant way to check the status of user consent
        # when the user agreed to participate, try to assign
        if re.search('consent', instance_id):
            consent_key = 'I want to participate in this research and continue with the study.'
            if 'Yes' in schema_to_label_to_value[consent_key] and schema_to_label_to_value[consent_key]['Yes'] == 'true':
                user_state.consent_agreed = True
            else:
                user_state.consent_agreed = False
            assign_instances_to_user(username)

        #when the user is working on prestudy, check the status
        if re.search('prestudy', instance_id):
            print(check_prestudy_status(username))

    return did_change


def get_annotations_for_user_on(username, instance_id):
    '''
    Returns the label-based annotations made by this user on the instance.
    '''
    user_state = lookup_user_state(username)
    annotations = user_state.get_label_annotations(instance_id)
    return annotations


def get_span_annotations_for_user_on(username, instance_id):
    '''
    Returns the span annotations made by this user on the instance.
    '''
    user_state = lookup_user_state(username)
    span_annotations = user_state.get_span_annotations(instance_id)
    return span_annotations

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
    global user_config
    
    if config['__debug__']:
        return annotate_page('debug_user', action='home')
    elif 'require_no_password' in config and config['require_no_password']:
        username = request.args.get('PROLIFIC_PID')
        password = 'require_no_password'
        return annotate_page(username, action='home')#render_template("id_login_home.html", title=config['annotation_task_name'])
    else:
        return render_template("home.html", title=config['annotation_task_name'])


@app.route("/login", methods=['GET', 'POST'])
def login():
    global user_config
    global config


    if config['__debug__'] == True:
        action = 'login'
        username = 'debug_user'
        password = 'debug'
    elif 'require_no_password' in config and config['require_no_password'] == True:
        action = request.form.get("action")
        username = request.form.get("email")
        password = 'require_no_password'
    else:
        # Jiaxin: currently we are just using email as the username
        action = request.form.get("action")
        username = request.form.get("email")
        password = request.form.get("pass")


    if action == 'login':
        if config['__debug__'] or ('require_no_password' in config and config['require_no_password']) or user_config.is_valid_password(username, password):
            #if surveyflow is setup, jump to the page before annotation
            print('%s login successful'%username)
            return annotate_page(username)
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
            return render_template("home.html", title=config['annotation_task_name'],
                                   login_email = username,
                                   login_error = 'User registration success for ' + username + ', please login now')
        else:
            #TODO: return to the signup page and display error message
            return render_template("home.html", title=config['annotation_task_name'],
                                   login_error = result + ', please try again or log in')
    else:
        print('unknown action at home page')
        return render_template("home.html", title=config['annotation_task_name'],
                               login_email = username, login_error = 'Invalid username or password')

@app.route("/newuser")
def new_user():
    return render_template("newuser.html")

'''
pre_annotation_page_cursor = 0
@app.route("/surveyflow", methods=['GET', 'POST'])
def pre_annotation_pages(username):
    global config
    page_order = config['pre_annotation_pages']
    username = request.form.get("email")
    print(config['site_file'],page_order)


    rendered_html = render_template(
        config['site_file'],
        username=username,
        # This is what instance the user is currently on
        instance=text,
        instance_obj=instance,
        instance_id=lookup_user_state(username).get_instance_cursor(),
        finished=lookup_user_state(username).get_annotation_count(),
        total_count=lookup_user_state(username).get_assigned_instance_count(),
        alert_time_each_instance=config['alert_time_each_instance'],
        statistics_nav = all_statistics,
        **kwargs
        # amount=len(all_data["annotated_data"]),
        # annotated_amount=user_dict[username]["current_display"]["annotated_amount"],
    )



    return render_template(page_order[pre_annotation_page_cursor], title=config['annotation_task_name'], login_email=username)

    #while pre_annotation_page_cursor < len(page_order):
    #    render_template(page_order[pre_annotation_page_cursor], title=config['annotation_task_name'], login_email = username)

    return annotate_page()
'''





def get_users():
    '''
    Returns an iterable over the usernames of all users who have annotated in
    the system so far
    '''
    global user_to_annotation_state
    return user_to_annotation_state.keys()


def get_prestudy_label(label):
    global config

    for schema in config["annotation_schemes"]:
        if schema['name'] == config['prestudy']['question_key']:
            cur_schema = schema['annotation_type']
    label = convert_labels(label[config['prestudy']['question_key']], cur_schema)
    return config['prestudy']['answer_mapping'][label]


def print_prestudy_result():
    global task_assignment
    print('----- prestudy test restult -----')
    print('passed annotators: ', task_assignment['prestudy_passed_users'])
    print('failed annotators: ', task_assignment['prestudy_failed_users'])
    print('pass rate: ', len(task_assignment['prestudy_passed_users']) / len(task_assignment['prestudy_passed_users'] + task_assignment['prestudy_failed_users']))


def check_prestudy_status(username):
    '''
    Check whether a user has passed the prestudy test (this function will only be used )
    :return:
    '''
    global task_assignment
    global config
    global instance_id_to_data

    if 'prestudy' not in config or config['prestudy']['on'] == False:
        return 'no prestudy test'
    user_state = lookup_user_state(username)

    #directly return the status if the user has passed/failed the prestudy before
    if user_state.get_prestudy_status() == False:
        return 'prestudy failed'
    elif user_state.get_prestudy_status() == True:
        return 'prestudy passed'

    res = []
    for id in task_assignment['prestudy_ids']:
        label = user_state.get_label_annotations(id)
        if label == None:
            return 'prestudy not complete'
        groundtruth = instance_id_to_data[id][config['prestudy']['groundtruth_key']]
        label = get_prestudy_label(label)
        print(label, groundtruth)
        res.append(label == groundtruth)

    print(res, sum(res) / len(res))
    #check if the score is higher than the minimum defined in config
    if (sum(res) / len(res)) < config['prestudy']['minimum_score']:
        user_state.set_prestudy_status(False)
        task_assignment['prestudy_failed_users'].append(username)
        prestudy_result = 'prestudy just failed'
    else:
        user_state.set_prestudy_status(True)
        task_assignment['prestudy_passed_users'].append(username)
        prestudy_result = 'prestudy just passed'

    print_prestudy_result()

    # update the annotation list according the prestudy test result
    assign_instances_to_user(username)

    return prestudy_result






def check_annotation_progress():
    '''
    check the current progress of annotation.
    :return:
    '''




def generate_initial_user_dataflow(username):
    '''
       Generate initial dataflow for a new annotator including surveyflows and prestudy
       :return: UserAnnotationState
       '''

    global user_to_annotation_state
    global config
    global instance_id_to_data

    sampled_keys = []
    for it in ['pre_annotation_pages', 'prestudy_ids']:
        if it in task_assignment:
            sampled_keys += task_assignment[it]
            print(it, task_assignment[it])

    print(sampled_keys)

    assigned_user_data = {key: instance_id_to_data[key] for key in sampled_keys}

    # save the assigned user data dict
    user_dir = path.join(config['output_annotation_dir'], username)
    assigned_user_data_path = user_dir + '/assigned_user_data.json'

    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
        logger.debug("Created state directory for user \"%s\"" % (username))

    with open(assigned_user_data_path, 'w') as w:
        json.dump(assigned_user_data, w)

    # return the assigned user data dict
    return assigned_user_data



def sample_instances(username):
    global user_to_annotation_state
    global config
    global instance_id_to_data

    if "sampling_strategy:" not in config["automatic_assignment"]:
        logger.debug(
            "Undefined sampling strategy, default to random assignment")
        config["automatic_assignment"]["sampling_strategy"] = 'random'

    # Force the sampling strategy to be random at this moment, will change this when more sampling strategies are created
    config["automatic_assignment"]["sampling_strategy"] = 'random'

    if config["automatic_assignment"]["sampling_strategy"] == 'random':
        #previously we were doing random sample directly, however, when there are a large amount of instances and users, it is possible that some instances are rarely sampled and some are oversampled at the end of the sampling process
        #sampled_keys = random.sample(list(task_assignment['unassigned'].keys()),
        #                             config["automatic_assignment"]["instance_per_annotator"])

        #Currently we will shuffle the unassinged keys first, and then rank the dict based on the availability of each instance, and they directly get the first N instances
        unassigned_dict = task_assignment['unassigned']
        #print('before', unassigned_dict)
        unassigned_dict = {k:unassigned_dict[k] for k in random.sample(list(unassigned_dict.keys()), len(unassigned_dict))}
        sorted_keys = [it[0] for it in sorted(unassigned_dict.items(), key=lambda item: item[1], reverse=True)]
        #print('sorted', sorted(unassigned_dict.items(), key=lambda item: item[1], reverse=True))
        sampled_keys = sorted_keys[:min(config["automatic_assignment"]["instance_per_annotator"], len(sorted_keys))]
        #print(sorted_keys)


        # update task_assignment to keep track of task assignment status globally
        for key in sampled_keys:
            if key not in task_assignment['assigned']:
                task_assignment['assigned'][key] = []
            task_assignment['assigned'][key].append(username)
            task_assignment['unassigned'][key] -= 1
            if task_assignment['unassigned'][key] == 0:
                del task_assignment['unassigned'][key]

        # sample and insert test questions
        if task_assignment['testing']['test_question_per_annotator'] > 0:
            sampled_testing_ids = random.sample(task_assignment['testing']['ids'],
                                                k=task_assignment['testing']['test_question_per_annotator'])
            # adding test question sampling status to the task assignment
            for key in sampled_testing_ids:
                if key not in task_assignment['assigned']:
                    task_assignment['assigned'][key] = []
                task_assignment['assigned'][key].append(username)
                sampled_keys.insert(random.randint(0, len(sampled_keys) - 1), key)

    return sampled_keys




def assign_instances_to_user(username):
    '''
    Assign instances to a user
    :return: UserAnnotationState
    '''

    global user_to_annotation_state
    global config
    global instance_id_to_data

    #"sampling_strategy:": 'random',

   # "instance_per_annotator": 50,


    user_state = lookup_user_state(username)

    #check if the user has already been assigned with instances to annotate
    #Currently we are just assigning once, but we might chance this later
    if user_state.get_real_assigned_instance_count() > 0:
        logging.warning(
            "Instance already assigned to user %s, assigning process stoppped"%username)
        return False

    prestudy_status = user_state.get_prestudy_status()
    consent_status = user_state.get_consent_status()

    if prestudy_status == None:
        if 'prestudy' in config and config['prestudy']['on']:
            logging.warning("Trying to assign instances to user when the prestudy test is not completed, assigning process stoppped")
            return False
        else:
            if consent_status:
                sampled_keys = sample_instances(username)
                user_state.real_instance_assigned_count += len(sampled_keys)
                if 'post_annotation_pages' in task_assignment:
                    sampled_keys = sampled_keys + task_assignment['post_annotation_pages']
            else:
                logging.warning(
                    "Trying to assign instances to user when the user has yet agreed to participate. assigning process stoppped")
                return False
    elif prestudy_status == False:
        sampled_keys = task_assignment['prestudy_failed_pages']
    else:
        sampled_keys = sample_instances(username)
        user_state.real_instance_assigned_count += len(sampled_keys)
        sampled_keys = task_assignment['prestudy_passed_pages'] + sampled_keys
        if 'post_annotation_pages' in task_assignment:
            sampled_keys = sampled_keys + task_assignment['post_annotation_pages']

    print(sampled_keys)
    assigned_user_data = {key:instance_id_to_data[key] for key in sampled_keys}
    user_state.add_new_assigned_data(assigned_user_data)

    print('assinged %d instances to %s, total pages: %s'%(user_state.get_real_assigned_instance_count(), username, user_state.get_assigned_instance_count()))

    # save the assigned user data dict
    user_dir = path.join(config['output_annotation_dir'], username)
    assigned_user_data_path =  user_dir + '/assigned_user_data.json'

    if not os.path.exists(user_dir):
        os.makedirs(user_dir)
        logger.debug("Created state directory for user \"%s\"" % (username))

    with open(assigned_user_data_path, 'w') as w:
        json.dump(user_state.get_assigned_data(), w)

    # save task assignment status
    task_assignment_path = config['output_annotation_dir'] + config["automatic_assignment"]["output_filename"]
    with open(task_assignment_path, 'w') as w:
        json.dump(task_assignment, w)

    user_state.instance_assigned = True

    # return the assigned user data dict
    return assigned_user_data



def generate_full_user_dataflow(username):
    '''
    Directly assign all the instances to a user at the beginning of the study
    :return: UserAnnotationState
    '''

    global user_to_annotation_state
    global config
    global instance_id_to_data

    #"sampling_strategy:": 'random',

   # "instance_per_annotator": 50,

    if "sampling_strategy:" not in config["automatic_assignment"]:
        logger.debug(
            "Undefined sampling strategy, default to random assignment")
        config["automatic_assignment"]["sampling_strategy"] = 'random'

    # Force the sampling strategy to be random at this moment, will change this when more sampling strategies are created
    config["automatic_assignment"]["sampling_strategy"] = 'random'

    if config["automatic_assignment"]["sampling_strategy"] == 'random':
        sampled_keys = random.sample(list(task_assignment['unassigned'].keys()), config["automatic_assignment"]["instance_per_annotator"])
        # update task_assignment to keep track of task assignment status globally
        for key in sampled_keys:
            if key not in task_assignment['assigned']:
                task_assignment['assigned'][key] = []
            task_assignment['assigned'][key].append(username)
            task_assignment['unassigned'][key] -= 1
            if task_assignment['unassigned'][key] == 0:
                del task_assignment['unassigned'][key]

        # sample and insert test questions
        if task_assignment['testing']['test_question_per_annotator'] > 0:
            sampled_testing_ids = random.sample(task_assignment['testing']['ids'], k = task_assignment['testing']['test_question_per_annotator'])
            # adding test question sampling status to the task assignment
            for key in sampled_testing_ids:
                if key not in task_assignment['assigned']:
                    task_assignment['assigned'][key] = []
                task_assignment['assigned'][key].append(username)
                sampled_keys.insert(random.randint(0,len(sampled_keys)-1), key)


        # save task assignment status
        task_assignment_path = config['output_annotation_dir'] + config["automatic_assignment"]["output_filename"]
        with open(task_assignment_path, 'w') as w:
            json.dump(task_assignment, w)

        #add the amount of sampled instances
        real_assigned_instance_count = len(sampled_keys)

        if 'pre_annotation_pages' in task_assignment:
            sampled_keys = task_assignment['pre_annotation_pages'] + sampled_keys

        if 'post_annotation_pages' in task_assignment:
            sampled_keys =  sampled_keys + task_assignment['post_annotation_pages']

        print(sampled_keys)

        assigned_user_data = {key:instance_id_to_data[key] for key in sampled_keys}

        # save the assigned user data dict
        user_dir = path.join(config['output_annotation_dir'], username)
        assigned_user_data_path =  user_dir + '/assigned_user_data.json'

        if not os.path.exists(user_dir):
            os.makedirs(user_dir)
            logger.debug("Created state directory for user \"%s\"" % (username))

        with open(assigned_user_data_path, 'w') as w:
            json.dump(assigned_user_data, w)

        # return the assigned user data dict
        return assigned_user_data, real_assigned_instance_count


def instances_all_assigned():
    global task_assignment

    if 'unassigned' in task_assignment and len(task_assignment['unassigned']) <= int(config["automatic_assignment"]["instance_per_annotator"] * 0.7):
        return True
    return False



def lookup_user_state(username):
    global config
    '''
    Returns the UserAnnotationState for a user, or if that user has not yet
    annotated, creates a new state for them and registers them with the system.
    '''
    global user_to_annotation_state


    if username not in user_to_annotation_state:
        logger.debug(
            "Previously unknown user \"%s\"; creating new annotation state" % (username))

        if "automatic_assignment" in config and config["automatic_assignment"]['on']:
            #print(type(config["automatic_assignment"]['on']))
            #assign instances to new user when automatic assignment is turned on

            if 'prestudy' in config and config["prestudy"]['on']:
                user_state = UserAnnotationState(generate_initial_user_dataflow(username))
            else:
                #assinged_data, real_assigned_instance_count = generate_full_user_dataflow(username)
                #user_state = UserAnnotationState(assinged_data)
                #user_state.real_instance_assigned_count = real_assigned_instance_count
                user_state = UserAnnotationState(generate_initial_user_dataflow(username))
            user_to_annotation_state[username] = user_state
        else:
            #assign all the instance to each user when automatic assignment is turned off
            user_state = UserAnnotationState(instance_id_to_data)
            user_to_annotation_state[username] = user_state
    else:
        user_state = user_to_annotation_state[username]

    return user_state


def save_user_state(username, save_order=False):
    global user_to_annotation_state
    global config
    global instance_id_to_data

    # print("username: ", username)
    
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
        for inst_id, data in user_state.get_all_annotations().items():
            bd_dict = {}
            if inst_id in user_state.instance_id_to_behavioral_data:
                bd_dict = user_state.instance_id_to_behavioral_data[inst_id]
                
            output = {
                'id': inst_id,
                'displayed_text': instance_id_to_data[inst_id]['displayed_text'],
                'label_annotations': data['labels'],
                'span_annotations': data['spans'],
                'behavioral_data': bd_dict
            }
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
                for inst_id, data in user_state.get_all_annotations().items():
                    
                    bd_dict = {}
                    if inst_id in user_state.instance_id_to_behavioral_data:
                        bd_dict = user_state.instance_id_to_behavioral_data[inst_id]

                    output = {
                        'id': inst_id,
                        'displayed_text': instance_id_to_data[inst_id]['displayed_text'],
                        'label_annotations': data['labels'],
                        'span_annotations': data['spans'],
                        'behavioral_data': bd_dict,
                    }
                    json.dump(output, outf)
                    outf.write('\n')
    

    # Convert to Pandas and then dump
    elif fmt == 'csv' or fmt == 'tsv':
        df = defaultdict(list)

        # Loop 1, figure out which schemas/labels have values so we know which
        # things will need to be columns in each row
        schema_to_labels = defaultdict(set)
        span_labels = set()

        for user_id, user_state in user_to_annotation_state.items():
            for inst_id, annotations in user_state.get_all_annotations().items():
                # Columns for each label-based annotation
                for schema, label_vals in annotations['labels'].items():
                    for label, val in label_vals.items():
                        schema_to_labels[schema].add(label)

                # Columns for each span type too 
                for span in annotations['spans']:
                    span_labels.add(span['annotation'])
                    
                # TODO: figure out what's in the behavioral dict and how to format it

        # Loop 2, report everything that's been annotated
        for user_id, user_state in user_to_annotation_state.items():
            for inst_id, annotations in user_state.get_all_annotations().items():

                df['user'].append(user_id)
                df['instance_id'].append(inst_id)
                df['displayed_text'].append(instance_id_to_data[inst_id]['displayed_text'])

                label_annotations = annotations['labels']
                span_annotations = annotations['spans']
                
                for schema, labels in schema_to_labels.items():
                    if schema in label_annotations:
                        label_vals = label_annotations[schema]
                        for label in labels:
                            val = label_vals[label] if label in label_vals else None
                            # For some sanity, combine the schema and label it a single column
                            df[schema + ':::' + label].append(val)
                    # If the user did label this schema at all, fill it with None values
                    else:
                        for label in labels:
                            df[schema + ':::' + label].append(None)

                # We bunch spans by their label to make it slightly easier to
                # process, but it's still kind of messy compared with the JSON
                # format.
                for span_label in span_labels:
                    anns = [sa for sa in span_annotations if sa['annotation'] == span_label]
                    df['span_annotation:::' + span_label].append(anns)
                
                # TODO: figure out what's in the behavioral dict and how to format it
                
        df = pd.DataFrame(df)
        sep = ',' if fmt == 'csv' else '\t'
        df.to_csv(annotated_instances_fname, index=False, sep=sep)

    # Save the annotation assignment info if automatic task assignment is on.
    # Jiaxin: we are simply saving this as a json file at this moment
    if "automatic_assignment" in config and config["automatic_assignment"]['on']:
        # TODO: write the code here
        print('saved')

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


    # User has annotated before or has assigned_data
    if os.path.exists(user_dir):
        logger.debug(
            "Found known user \"%s\"; loading annotation state" % (username))

        # if automatic assignment is on, load assigned user data
        if "automatic_assignment" in config and config["automatic_assignment"]['on']:
            assigned_user_data_path = user_dir + '/assigned_user_data.json'

            with open(assigned_user_data_path, 'r') as r:
                assigned_user_data = json.load(r)
        # otherwise, set the assigned user data as all the instances
        else:
            assigned_user_data = instance_id_to_data

        annotation_order = []
        annotation_order_fname = path.join(user_dir, "annotation_order.txt")
        if os.path.exists(annotation_order_fname):
            with open(annotation_order_fname, 'rt') as f:
                for line in f:
                    instance_id = line[:-1]
                    if instance_id not in assigned_user_data:
                        logger.warning(('Annotation state for %s does not match ' +
                                        'instances in existing dataset at %s')
                                       % (user_dir, ','.join(config['data_files'])))
                        continue
                    annotation_order.append(line[:-1])

        annotated_instances = []
        annotated_instances_fname = path.join(user_dir, "annotated_instances.jsonl")
        if os.path.exists(annotated_instances_fname):

            with open(annotated_instances_fname, 'rt') as f:
                for line in f:
                    annotated_instance = json.loads(line)
                    instance_id = annotated_instance['id']
                    if instance_id not in assigned_user_data:
                        logger.warning(('Annotation state for %s does not match ' +
                                        'instances in existing dataset at %s')
                                       % (user_dir, ','.join(config['data_files'])))
                        continue
                    annotated_instances.append(annotated_instance)

        # Ensure the current data is represented in the annotation order
        # NOTE: this is a hack to be fixed for when old user data is in the same directory
        #
        for iid in assigned_user_data.keys():
            if iid not in annotation_order:
                annotation_order.append(iid)

        # NOTE: I'm unsure what id_key is even doing here, so I'm commenting it out for now
        #id_key = config['item_properties']['id_key']
        user_state = UserAnnotationState(assigned_user_data)
        user_state.update(annotation_order, annotated_instances)

        # Make sure we keep track of the user throughout the program
        user_to_annotation_state[username] = user_state

        logger.info("Loaded %d annotations for known user \"%s\"" %
                    (user_state.get_annotation_count(), username))

        return 'old user loaded'
    # New user, so initialize state
    else:

        logger.debug(
            "Previously unknown user \"%s\"; creating new annotation state" % (username))
        #user_state = UserAnnotationState(instance_id_to_data)
        #user_to_annotation_state[username] = user_state

        #create new user state with the look up function
        if instances_all_assigned():
            return 'all instances have been assigned'

        lookup_user_state(username)
        return 'new user initialized'


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
def annotate_page(username = None, action=None):
    '''
    Parses the input received from the user's annotation and takes some action
    based on what was clicked/typed. This method is the main switch for changing
    the state of the server for this user.
    '''
    
    global user_config
    global config

    #use the provided username when the username is given
    if not username:
        if config['__debug__']:
            username = 'debug_user'
        else:
            username_from_last_page = request.form.get("email")
            #print(username_on_page)
            if username_from_last_page == None:
                #return render_template("error.html", error_message='You must use the link provided by prolific to work on this study')
                return render_template("error.html", error_message='Please login to annotate or you are using the wrong link')
            else:
                username = username_from_last_page

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
    action = request.form.get("src") if action == None else action


    if action == "home":
        result_code = load_user_state(username)
        print(result_code)
        if result_code == 'all instances have been assigned':
            return render_template('error.html', error_message='Sorry that you come a bit late. We have collected enough responses for our study. However, prolific sometimes will recruit more participants than we expected. We are sorry for the inconvenience!')
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

    # automatically unfold the text list when input text is a list (e.g. best-worst-scaling).
    if 'list_as_text' in config and config['list_as_text']:
        if type(text) == str:
            try:
                text = eval(text)
            except:
                text = str(text)
        if type(text) == list:
            if config['list_as_text']['text_list_prefix_type'] == 'alphabet':
                prefix_list = list(string.ascii_uppercase)
                text = [prefix_list[i] + '. ' + text[i] for i in range(len(text))]
            elif config['list_as_text']['text_list_prefix_type'] == 'number':
                text = [str(i) + '. ' + text[i] for i in range(len(text))]
            text = '<br>'.join(text)

        #unfolding dict into different sections
        elif type(text) == dict:
            block = []
            if "horizontal" in config['list_as_text'] and config['list_as_text']["horizontal"]:
                for key in text:
                    block.append('<div name="instance_text" style="float:left;width:%s;padding:5px;" class="column"> <legend> %s </legend> %s </div>' % ("%d"%int(100/len(text))+"%", key, text[key]))
                text = '<div class="row" style="display: table"> %s </div>' % (''.join(block))
            else:
                for key in text:
                    block.append('<div name="instance_text"> <legend> %s </legend> %s <br/> </div>'%(key, text[key]))
                text = ''.join(block)
        else:
            text = text
            #raise Exception('list_as_text is used when input column %s is not a list' % config['item_properties']['text_key'])
    instance_id = instance[id_key]
    # also save the displayed text in the metadata dict
    instance_id_to_data[instance_id]['displayed_text'] = text

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

    # TODO: Display plots for agreement scores instead of only the overall score
    # in the statistics sidebar   
    #all_statistics['Agreement'] = get_agreement_score('all', 'all', return_type='overall_average')
    #print(all_statistics)

    # Set the html file as surveyflow pages when the instance is a not an
    # annotation page (survey pages, prestudy pass or fail page)
    if 'non_annotation_pages' in config and (instance_id in config['non_annotation_pages']):
        html_file = instance_id
    #otherwise set the page as the normal annotation page
    else:
        html_file = config['site_file']
        
    # Flask will fill in the things we need into the HTML template we've created,
    # replacing {{variable_name}} with the associated text for keyword arguments
    rendered_html = render_template(
        html_file,
        username=username,
        # This is what instance the user is currently on
        instance=text,
        instance_obj=instance,
        instance_id=lookup_user_state(username).get_instance_cursor(),
        #finished=lookup_user_state(username).get_annotation_count(),
        finished=lookup_user_state(username).get_instance_cursor(),
        total_count=lookup_user_state(username).get_assigned_instance_count(),
        alert_time_each_instance=config['alert_time_each_instance'],
        statistics_nav = all_statistics,
        **kwargs
        # amount=len(all_data["annotated_data"]),
        # annotated_amount=user_dict[username]["current_display"]["annotated_amount"],
    )

    with open('debug-pre.html', 'wt') as outf:
        outf.write(rendered_html)
    
    # UGHGHGHGH the tempalte does unusual escaping, which makes it a PAIN to do
    # the replacement later
    #m = re.search('<div name="instance_text">(.*?)</div>', rendered_html,
    #              flags=(re.DOTALL|re.MULTILINE))
    #text = m.group(1)

    # For whatever reason, doing this before the render_template causes the
    # embedded HTML to get escaped, so we just do a wholesale replacement here.
    #print(text, updated_text)
    rendered_html = rendered_html.replace(text, updated_text)

    with open('debug-pre.html', 'wt') as outf:
        outf.write(rendered_html)
        
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
            
    # If the user has annotated this before, walk the DOM and fill out what they
    # did
    annotations = get_annotations_for_user_on(username, instance_id)
    if annotations is not None:
        # Reset the state
        for schema, labels in annotations.items():
            for label, value in labels.items():
                name = schema + ":::" + label
                input_field = soup.find_all(["input", "select"], {"name": name})[0] #select both input and select tags
                if input_field is None:
                    print('No input for ', name)
                    continue
                input_field['checked'] = True
                input_field['value'] = value
                #find the right option and set it as selected if the current annotation schema is a select box
                if label == 'select-one':
                    option = input_field.findChildren('option', {"value": value})[0]
                    option['selected'] = "selected"

                    
    rendered_html = str(soup)  # soup.prettify()

    with open('debug.html', 'wt') as outf:
        outf.write(rendered_html)

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

def render_span_annotations(text, span_annotations):
    '''    
    Retuns a modified version of the text with span annotation overlays inserted
    into the text.

    :text: some instance to be annotated
    :span_annotations: annotations already made by the user that need to be
       re-inserted into the text
    '''
    global config
    
    # This code is synchronized with the javascript function
    # surroundSelection(selectionLabel) function in base_template.html which
    # wraps any labeled text with a <div> element indicating its label. We
    # replicate this code here (in python).
    #
    # This synchrony also means that any changes to the UI code for rendering
    # need to be updated here too.


    # We need to go in reverse order to make the string update in the right
    # places, so make sure things are ordered in reverse of start

    rev_order_sa = sorted(span_annotations, key=lambda d: d['start'], reverse=True) 

    ann_wrapper = ('<span class="span_container" selection_label="{annotation}" ' +
                      'style="background-color:rgb{bg_color};">' +
                   '{span}' +
                   '<div class="span_label" ' +
                       'style="background-color:white;border:2px solid rgb{color};">' +
                   '{annotation}</div></span>')
    for a in rev_order_sa:

        # Spans are colored according to their order in the list and we need to
        # retrofit the color
        color = get_span_color(a['annotation'])
        # The color is an RGB triple like (1,2,3) and we want the background for
        # the text to be somewhat transparent so we switch to RGBA for bg
        bg_color = color.replace(')', ',0.25)')
        
        ann = ann_wrapper.format(annotation=a['annotation'], span=a['span'],
                                 color=color, bg_color=bg_color)    
        text = text[:a['start']] + ann + text[a['end']:]

    return text

def get_span_color(span_label):
    '''
    Returns the color of a span with this label as a string with an RGB triple
    in parentheses, or None if the span is unmapped.
    '''
    global config

    if 'ui' not in config or 'spans' not in config['ui']:
        return None
    span_ui = config['ui']['spans']

    if 'span_colors' not in span_ui:
        return None

    if span_label in span_ui['span_colors']:
        return span_ui['span_colors'][span_label]
    else:
        return None


def set_span_color(span_label, color):
    '''
    Sets the color of a span with this label as a string with an RGB triple in parentheses.

    :color: a string containing an RGB triple in parentheses
    '''
    global config

    if 'ui' not in config:
        ui = {}
        config['ui'] = ui
    else:
        ui = config['ui']

    if 'spans' not in ui:
        span_ui = {}
        ui['spans'] = span_ui
    else:
        span_ui = ui['spans']

    if 'span_colors' not in span_ui:
        span_colors = {}
        span_ui['span_colors'] = span_colors
    else:
        span_colors = span_ui['span_colors']

    span_colors[span_label] = color
    

def parse_html_span_annotation(html_span_annotation):
    '''
    Parses the span annotations produced in raw HTML by Potato's front end
    and extracts out the precise spans and labels annotated by users.

    :returns: a tuple of (1) the annotated string without annotation HTML
              and a list of annotations    
    '''
    
    s = html_span_annotation.strip()
    init_tag_regex = re.compile(r'(<span.+?>)')
    end_tag_regex = re.compile(r'(</span>)')
    anno_regex = re.compile(r'<div class="span_label".+?>(.+)</div>')
    no_html_s = ''
    start = 0

    annotations = []

    while True:
        m = init_tag_regex.search(s, start)
        if not m:
            break

        # find the end tag
        m2 = end_tag_regex.search(s, m.end())

        middle = s[m.end():m2.start()]

        # Get the annotation label from the middle text
        m3 = anno_regex.search(middle)

        middle_text = middle[:m3.start()]
        annotation = m3.group(1)

        no_html_s += s[start:m.start()] 

        ann = {
            'start': len(no_html_s),
            'end': len(no_html_s) + len(middle_text),
            'span': middle_text,
            'annotation': annotation
        }
        annotations.append(ann)

        no_html_s += middle_text
        start = m2.end(0) 

    # Add whatever trailing text exists
    no_html_s += s[start:]
    
    return no_html_s, annotations    

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
                        help="The port to run on", default=None)

    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Report verbose output", default=False)

    parser.add_argument("--debug", action="store_true",
                        help="Launch in debug mode with no login", default=False)
    
    parser.add_argument("--veryVerbose", action="store_true", dest="very_verbose",
                        help="Report very verbose output", default=False)

    return parser.parse_args()


def generate_site(config):
    '''
    Generates the full HTML file in site/ for annotating this tasks data,
    combining the various templates with the annotation specification in
    the yaml file.
    '''
    global logger

    logger.info("Generating anntotation site at %s" % config['site_dir'])

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

    if "jumping_to_id_disabled" in config and config["jumping_to_id_disabled"]:
        html_template = html_template.replace("<input type=\"submit\" value=\"go\">", "<input type=\"submit\" value=\"go\" hidden>")
        html_template = html_template.replace("<input type=\"number\" name=\"go_to\" id=\"go_to\" value=\"\" onfocusin=\"user_input()\" onfocusout=\"user_input_leave()\" max={{total_count}} min=0 required>",
                              "<input type=\"number\" name=\"go_to\" id=\"go_to\" value=\"\" onfocusin=\"user_input()\" onfocusout=\"user_input_leave()\" max={{total_count}} min=0 required hidden>")

    if "hide_navbar" in config and config["hide_navbar"]:
        html_template = html_template.replace('<div class="navbar-nav">',
                                              '<div class="navbar-nav" hidden>')


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
        ('&#8592;', "Move backward"),
        ('&#8594;', "Move forward"),
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


def generate_surveyflow_pages(config):
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

    if "jumping_to_id_disabled" in config and config["jumping_to_id_disabled"]:
        html_template = html_template.replace("<input type=\"submit\" value=\"go\">", "<input type=\"submit\" value=\"go\" hidden>")
        html_template = html_template.replace("<input type=\"number\" name=\"go_to\" id=\"go_to\" value=\"\" onfocusin=\"user_input()\" onfocusout=\"user_input_leave()\" max={{total_count}} min=0 required>",
                              "<input type=\"number\" name=\"go_to\" id=\"go_to\" value=\"\" onfocusin=\"user_input()\" onfocusout=\"user_input_leave()\" max={{total_count}} min=0 required hidden>")

    if "hide_navbar" in config and config["hide_navbar"]:
        html_template = html_template.replace('<div class="navbar-nav">',
                                              '<div class="navbar-nav" hidden>')

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

    # put forms in rows for survey questions
    task_html_layout = task_html_layout.replace("<div class=\"annotation_schema\">", "<div class=\"annotation_schema\" style=\"flex-direction:column;\">")

    #
    # Stage 2: drop in the annotation layout and insertthe task-specific variables
    #

    # Add in a codebook link if the admin specified one
    codebook_html = ''
    if 'annotation_codebook_url' in config and len(config['annotation_codebook_url']) > 0:
        annotation_codebook = config['annotation_codebook_url']
        codebook_html = '<a href="{{annotation_codebook_url}}" class="nav-item nav-link">Annotation Codebook</a>'
        codebook_html = codebook_html.replace(
            "{{annotation_codebook_url}}", annotation_codebook)

    html_template = html_template.replace(
        "{{annotation_codebook}}", codebook_html)

    html_template = html_template.replace(
        "{{annotation_task_name}}", config['annotation_task_name'])

    statistics_layout = generate_statistics_sidebar(STATS_KEYS)
    html_template = html_template.replace(
        "{{statistics_nav}}", ' ')



    #
    # Step 3, Fill in the annotation-specific pieces in the layout and save the page
    #

    #grab survey flow files
    surveyflow_pages = defaultdict(list)
    surveyflow = config['surveyflow']
    surveyflow_list = []
    for key in surveyflow['order']:
        surveyflow_list += surveyflow[key]
    for file in surveyflow_list:
        if file.split('.')[-1] == 'jsonl':
            with open(file, 'r') as r:
                for line in r:
                    line = json.loads(line.strip())
                    line['filename'] = file
                    line['pagename'] = file.split('.')[0].split('/')[-1]
                    surveyflow_pages[line['pagename']].append(line)

    # Grab the annotation schemes
    annotation_schemes = config['annotation_schemes']
    logger.debug("Saw %d annotation scheme(s)" % len(annotation_schemes))

    # Keep track of all the keybindings we have
    all_keybindings = [
        ('&#8592;', "Move backward"),
        ('&#8594;', "Move forward"),
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
        for i, page in enumerate(surveyflow_pages):
            schema_layouts = ""
            #for annotation_scheme in annotation_schemes:
            for line in surveyflow_pages[page]:
                annotation_scheme = {
                    "annotation_type": line['schema'],
                    #todo: pack select type in to a dict with the key 'schema'
                    #whether use predefined labels for select type, if so, define it, currently we support country, religion, ethnicity
                    "use_predefined_labels": line["use_predefined_labels"] if "use_predefined_labels" in line else None,
                    "id": line['id'],
                    "name": line['text'],
                    "description": line['text'],
                    # If true, display the labels horizontally
                    "horizontal": False,
                    "labels": line['choices'] if 'choices' in line else None,
                    "label_requirement": line['label_requirement'] if 'label_requirement' in line else None,
                    "sequential_key_binding": False,
                }
                schema_layout, keybindings = generate_schematic(annotation_scheme)
                schema_layouts += schema_layout + "<br>" + "\n"
                #all_keybindings.extend(keybindings)

            cur_task_html_layout = task_html_layout.replace(
                "{{annotation_schematic}}", schema_layouts)


            # Swap in the task's layout
            cur_html_template = html_template.replace("{{ TASK_LAYOUT }}", cur_task_html_layout)

            # TODO: Maybe remove input instances for survey questions?
            #cur_html_template  = cur_html_template .replace("<div class=\"annotation_schema\">",
            #                                            "<div class=\"annotation_schema\" style=\"flex-direction:column;\">")

            # Do not display keybindings for the first and last page
            if i == 0:
                keybindings_desc = generate_keybidings_sidebar(all_keybindings[1:])
                cur_html_template = cur_html_template.replace(
                    '<a class="btn btn-secondary" href="#" role="button" onclick="click_to_prev()">Move backward</a>',
                    '<a class="btn btn-secondary" href="#" role="button" onclick="click_to_prev()" hidden>Move backward</a>')
            elif i == len(surveyflow_pages) - 1 or re.search('prestudy_fail', page):
                keybindings_desc = generate_keybidings_sidebar(all_keybindings[:-1])
                cur_html_template = cur_html_template.replace(
                    '<a class="btn btn-secondary" href="#" role="button" onclick="click_to_next()">Move forward</a>',
                    '<a class="btn btn-secondary" href="#" role="button" onclick="click_to_next()" hidden>Move forward</a>')
            else:
                keybindings_desc = generate_keybidings_sidebar(all_keybindings)

            cur_html_template = cur_html_template.replace(
                "{{keybindings}}", keybindings_desc)
            # Jiaxin: change the basename from the template name to the project name +
            # template name, to allow multiple annotation tasks using the same template
            site_name = '%s.html'%page

            output_html_fname = os.path.join(config['site_dir'], site_name)

            # print(basename(html_template_file))
            # print(output_html_fname)

            # Cache this path as a shortcut to figure out which page to render
            if 'surveyflow_site_file' not in config:
                config['surveyflow_site_file'] = {}
            config['surveyflow_site_file'][page] = site_name


            # Write the file
            with open(output_html_fname, 'wt') as outf:
                outf.write(cur_html_template)

            logger.debug('writing annotation html to %s%s.html' % (output_html_fname,page))

    config['non_annotation_pages'] = []
    for key in surveyflow['order']:
        config['%s_pages'%key] = [config['surveyflow_site_file'][it.split('.')[0].split('/')[-1]] for it in config['surveyflow'][key]]
        config['non_annotation_pages'] += config['%s_pages'%key]
        #config['post_annotation_pages'] = [config['surveyflow_site_file'][it.split('.')[0].split('/')[-1]] for it in config['surveyflow']['post_annotation']]




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


def generate_keybidings_sidebar(keybindings, horizontal = False):
    '''
    Generate an HTML layout for the end-user of the keybindings for the current
    task. The layout is intended to be displayed in a side bar
    '''
    global config
    if "horizontal_key_bindings" in config and config["horizontal_key_bindings"]:
        horizontal = True

    if not keybindings:
        return ''
    #keybindings.insert(0, ('key', 'description'))
    if horizontal:
        keybindings = [[it[0], it[1].split(':')[-1]] for it in keybindings]
        lines = list(zip(*keybindings))
        print(lines)
        layout = '<table style="border:1px solid black;margin-left:auto;margin-right:auto;text-align: center;">'
        for line in lines:
            layout += "<tr>" + ''.join(['<td>&nbsp;&nbsp;%s&nbsp;&nbsp;</td>'%it for it in line]) + "</tr>"
        layout += '</table>'

    else:
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

    elif annotation_type == "highlight":
        return generate_span_layout(annotation_scheme)
    
    elif annotation_type == "likert":
        return generate_likert_layout(annotation_scheme)
        
    elif annotation_type == "text":
        return generate_textbox_layout(annotation_scheme)

    elif annotation_type == "number":
        return generate_number_layout(annotation_scheme)

    elif annotation_type == "pure_display":
        return generate_pure_display_layout(annotation_scheme)

    elif annotation_type == "select":
        return generate_select_layout(annotation_scheme)

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

    # setting up label validation for each label, if "required" is True, the annotators will be asked to finish the current instance to proceed
    validation = ''
    label_requirement = annotation_scheme['label_requirement'] if 'label_requirement' in annotation_scheme else None
    if label_requirement and label_requirement['required']:
        validation = 'required'

    # if right_label is provided, the associated label has to be clicked to proceed. This is normally used for consent questions at the beginning of a survey.
    right_label = set()
    if label_requirement and "right_label" in label_requirement:
        if type(label_requirement["right_label"]) == str:
            right_label.add(label_requirement["right_label"])
        elif type(label_requirement["right_label"]) == list:
            right_label = set(label_requirement["right_label"])
        else:
            logger.warning(
                "Incorrect format of right_label %s" % label_requirement["right_label"])
            #quit()


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
        if isinstance(label_data, Mapping):
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

        final_validation = 'right_label' if label in right_label else validation

        
        if ("single_select" in annotation_scheme) and (annotation_scheme["single_select"] == "True"):
            logger.warning("single_select is Depricated and will be removed soon. Use \"radio\" instead.")
            schematic += \
                (('  <input class="%s" type="checkbox" id="%s" name="%s" value="%s" onclick="onlyOne(this)" validation="%s">' +
                  '  <label for="%s" %s>%s</label><br/>')
                 % (class_name, name, name, key_value, final_validation,
                    name, tooltip, label_content))
        else:
            schematic += \
                (('<label for="%s" %s><input class="%s" type="checkbox" id="%s" name="%s" value="%s" onclick="whetherNone(this)" validation="%s">' +
                 '  %s</label><br/>')
                 % (name, tooltip, class_name, name, name, key_value, final_validation,
                    label_content))

        schematic += '</td>'
        if i % n_columns == 0:
            schematic += '</tr>'


    if 'has_free_response' in annotation_scheme and annotation_scheme['has_free_response']:

        label='free_response'
        name = annotation_scheme['name'] + ':::free_response' 
        class_name = annotation_scheme['name']
        tooltip = 'Entire a label not listed here'
        instruction = "Other" if "instruction" not in annotation_scheme['has_free_response'] else annotation_scheme['has_free_response']["instruction"]

        schematic += \
        (('<tr><td colspan="%s"><div style="float:left; display:flex; flex-direction:row;">%s <input class="%s" type="text" id="%s" name="%s">' +
         '  <label for="%s" %s></label></div></td</tr>')
         % (str(n_columns), instruction, class_name, name, name, name, tooltip))


    schematic += '</table>'
    schematic += '  </fieldset>\n</form>\n'

    return schematic, key_bindings


def generate_radio_layout(annotation_scheme, horizontal=False):

    #when horizontal is specified in the annotation_scheme, set horizontal = True
    if "horizontal" in annotation_scheme and annotation_scheme['horizontal']:
        horizontal = True

    schematic = \
        '<form action="/action_page.php">' + \
        '  <fieldset>' + \
        ('  <legend>%s</legend>' % annotation_scheme['description'])

    # TODO: display keyboard shortcuts on the annotation page
    key2label = {}
    label2key = {}
    key_bindings = []

    # Setting up label validation for each label, if "required" is True, the
    # annotators will be asked to finish the current instance to proceed
    validation = ''
    label_requirement = annotation_scheme['label_requirement'] if 'label_requirement' in annotation_scheme else None
    if label_requirement and ('required' in label_requirement) and label_requirement['required']:
        validation = 'required'

    #print(annotation_scheme)

    # If right_label is provided, the associated label has to be clicked to
    # proceed. This is normally used for consent questions at the beginning of a
    # survey.
    right_label = set()
    if label_requirement and "right_label" in label_requirement:
        if type(label_requirement["right_label"]) == str:
            right_label.add(label_requirement["right_label"])
        elif type(label_requirement["right_label"]) == list:
            right_label = set(label_requirement["right_label"])
        else:
            logger.warning(
                "Incorrect format of right_label %s" % label_requirement["right_label"])
            #quit()
    
    for i, label_data in enumerate(annotation_scheme['labels'], 1):

        label = label_data if isinstance(
            label_data, str) else label_data['name']

        name = annotation_scheme['name'] + ':::' + label
        class_name = annotation_scheme['name']
        key_value = name

        tooltip = ''
        if isinstance(label_data, Mapping):
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
            key_bindings.append((key_value, class_name + ': ' + label))

        label_content = label_data['key_value'] + '.' + label if ('displaying_score' in annotation_scheme and annotation_scheme['displaying_score']) else label
        #label_content = label
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


        final_validation = 'right_label' if label in right_label else validation


        #add support for horizontal layout
        br_label = "<br/>"
        if horizontal:
            br_label = ''
        schematic += \
                (('      <input class="%s" type="radio" id="%s" name="%s" value="%s" onclick="onlyOne(this)" validation="%s">' +
                 '  <label for="%s" %s>%s</label>%s')
                 % (class_name, name, name, key_value, 'right_label' if label in right_label else final_validation,
                    name, tooltip, label_content, br_label))

    if 'has_free_response' in annotation_scheme and annotation_scheme['has_free_response']:

        label='free_response'
        name = annotation_scheme['name'] + ':::free_response' 
        class_name = annotation_scheme['name']
        tooltip = 'Entire a label not listed here'
        instruction = "Other" if "instruction" not in annotation_scheme['has_free_response'] else annotation_scheme['has_free_response']["instruction"]

        schematic += \
        (('%s <input class="%s" type="text" id="%s" name="%s" >' +
         '  <label for="%s" %s></label><br/>')
         % (instruction, class_name, name, name, name, tooltip))

    schematic += '  </fieldset>\n</form>\n'
    return schematic, key_bindings


def generate_span_layout(annotation_scheme, horizontal=False):
    '''
    Renders a span annotation option selection in the annotation panel and
    returns the HTML code
    '''
    
    #when horizontal is specified in the annotation_scheme, set horizontal = True
    if "horizontal" in annotation_scheme and annotation_scheme['horizontal']:
        horizontal = True

    schematic = \
        '<form action="/action_page.php">' + \
        '  <fieldset>' + \
        ('  <legend>%s</legend>' % annotation_scheme['description'])

    # TODO: display keyboard shortcuts on the annotation page
    key2label = {}
    label2key = {}
    key_bindings = []

    # setting up label validation for each label, if "required" is True, the annotators will be asked to finish the current instance to proceed
    validation = ''
    label_requirement = annotation_scheme['label_requirement'] if 'label_requirement' in annotation_scheme else None
    if label_requirement and ('required' in label_requirement) and label_requirement['required']:
        validation = 'required'
    
    for i, label_data in enumerate(annotation_scheme['labels'], 1):

        label = label_data if isinstance(
            label_data, str) else label_data['name']
        
        name = annotation_scheme['name'] + ':::' + label
        class_name = annotation_scheme['name']
        key_value = name
        
        span_color = get_span_color(label)
        if span_color is None:
            span_color = SPAN_COLOR_PALETTE[(i-1) % len(SPAN_COLOR_PALETTE)]
            set_span_color(label, span_color)

        # For better or worse, we need to cache these label-color pairings
        # somewhere so that we can render them in the colored instances later in
        # render_span_annotations(). The config object seems like a reasonable
        # place to do since it's global and the colors are persistent 
        config['ui']

        
        tooltip = ''
        if isinstance(label_data, Mapping):
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
            key_bindings.append((key_value, class_name + ': ' + label))

        if ('displaying_score' in annotation_scheme and annotation_scheme['displaying_score']):
            label_content = label_data['key_value'] + '.' + label
        else:          
            label_content = label

        # Check the first radio
        if i == 1:
            is_checked = 'xchecked="checked"'
        else:
            is_checked = ''
        
        # TODO: add support for horizontal layout
        br_label = "<br/>"
        if horizontal:
            br_label = ''

        # We want to mark that this input isn't actually an annotation (unlike,
        # say, checkboxes) so we prefix the name with span_label so that the
        # answer ingestion code in update_annotation_state() can skip over which
        # radio was checked as being annotations that need saving (while the
        # spans themselves are saved)
        name_with_span = 'span_label:::' + name
            
        schematic += \
            ('      <input class="{class_name}" type="radio" id="{name}" name="{name_with_span}" ' +
             ' value="{key_value}" {is_checked} ' +
             'onclick="onlyOne(this); changeSpanLabel(\'{label_content}\', \'{span_color}\');">' +
             '  <label for="{name}" {tooltip}>' +
             '<span style="background-color:rgb{bg_color};">{label_content}</span></label>{br_label}').format(
                 class_name=class_name, name=name, key_value=key_value,
                 label_content=label_content, tooltip=tooltip, br_label=br_label,
                 is_checked=is_checked, name_with_span=name_with_span,
                 bg_color=span_color.replace(")", ",0.25)"),
                 span_color=span_color)
             
            

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
        '  <fieldset> <legend>%s</legend> <ul class="likert" style="text-align: center;"> <li> %s </li>') \
        % (annotation_scheme['description'], annotation_scheme['min_label'])
    
    key2label = {}
    label2key = {}    
    key_bindings = []

    # setting up label validation for each label, if "required" is True, the annotators will be asked to finish the current instance to proceed
    validation = ''
    label_requirement = annotation_scheme['label_requirement'] if 'label_requirement' in annotation_scheme else None
    if label_requirement and ('required' in label_requirement) and label_requirement['required']:
        validation = 'required'
    
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
        label_content = str(i) if ('displaying_score' in annotation_scheme and annotation_scheme['displaying_score']) else ''
        tooltip = ''        

        # displaying the label content in a different line if it is not empty
        if label_content != '':
            line_break = '<br>'
        else:
            line_break = ''
        #schematic += \
        #        ((' <li><input class="%s" type="radio" id="%s" name="%s" value="%s" onclick="onlyOne(this)">' +
        #         '  <label for="%s" %s>%s</label></li>')
        #         % (class_name, label, name, key_value, name, tooltip, label_content))

        schematic += \
            ((' <li><input class="{class_name}" type="radio" id="{id}" name="{name}" value="{value}" onclick="onlyOne(this)" validation="{validation}">' + \
              ' {line_break} <label for="{label_for}" {label_args}>{label_text}</label></li>')).format(
                  class_name=class_name, id=name, name=name, value=key_value, validation=validation,
                line_break=line_break, label_for=name, label_args=tooltip, label_text=" " + label_content)

    # allow annotators to choose bad_text label
    bad_text_schematic = ''
    if 'bad_text_label' in annotation_scheme and 'label_content' in annotation_scheme['bad_text_label']:
        name = annotation_scheme['name'] + ':::' + 'bad_text'
        bad_text_schematic = \
            ((' <li><input class="{class_name}" type="radio" id="{id}" name="{name}" value="{value}" onclick="onlyOne(this)" validation="{validation}">' + \
                        ' {line_break} <label for="{label_for}" {label_args}>{label_text}</label></li>')).format(
                class_name=annotation_scheme['name'], id=name, name=name, value=0, validation=validation,
                line_break='<br>', label_for=name, label_args='', label_text=annotation_scheme['bad_text_label']['label_content'])
        key_bindings.append((0, class_name + ': ' + annotation_scheme['bad_text_label']['label_content']))

    schematic += ('  <li>%s</li> %s </ul></fieldset>\n</form></div>\n' \
                  % (annotation_scheme['max_label'], bad_text_schematic))
    
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

    # setting up label validation for each label, if "required" is True, the annotators will be asked to finish the current instance to proceed
    validation = ''
    label_requirement = annotation_scheme['label_requirement'] if 'label_requirement' in annotation_scheme else None
    if label_requirement and 'required' in label_requirement and label_requirement['required']:
        validation = 'required'

    schematic += \
            (('  <input class="%s" style=%s type="text" id="%s" name="%s" validation="%s">' +
             '  <label for="%s" %s></label><br/>')
             % (class_name, custom_css, name, name, validation,
                name, tooltip))

    #schematic += '  </fieldset>\n</form></div>\n'
    schematic += '  </fieldset>\n</form>\n'

    
    return schematic, key_bindings


def generate_number_layout(annotation_scheme):
    # '<div style="border:1px solid black; border-radius: 25px;">' + \
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

    # add shortkey to the label so that the annotators will know how to use it
    # when the shortkey is "None", this will not displayed as we do not allow short key for None category
    # if label in label2key and label2key[label] != 'None':
    if label in label2key:
        label_content = label_content + \
                        ' [' + label2key[label].upper() + ']'

    # setting up label validation for each label, if "required" is True, the annotators will be asked to finish the current instance to proceed
    validation = ''
    label_requirement = annotation_scheme['label_requirement'] if 'label_requirement' in annotation_scheme else None
    if label_requirement and 'required' in label_requirement and label_requirement['required']:
        validation = 'required'

    schematic += \
        (('  <input class="%s" style=%s type="number" id="%s" name="%s" validation="%s">' +
          '  <label for="%s" %s></label><br/>')
         % (class_name, custom_css, name, name, validation,
            name, tooltip))

    # schematic += '  </fieldset>\n</form></div>\n'
    schematic += '  </fieldset>\n</form>\n'

    return schematic, key_bindings


def generate_pure_display_layout(annotation_scheme):
    schematic = '<Strong>%s</Strong> %s' % (annotation_scheme['description'], '<br>'.join(annotation_scheme['labels']))

    return schematic, None


def generate_select_layout(annotation_scheme):

    # setting up label validation for each label, if "required" is True, the annotators will be asked to finish the current instance to proceed
    validation = ''
    label_requirement = annotation_scheme['label_requirement'] if 'label_requirement' in annotation_scheme else None
    if label_requirement and ('required' in label_requirement) and label_requirement['required']:
        validation = 'required'

    schematic = \
        '<form action="/action_page.php">' + \
        '  <fieldset>' + \
        ('  <legend>%s</legend>' % annotation_scheme['description']) + \
        ('  <select type="select-one" class="%s" id="%s" name="%s" validation="%s">' % (annotation_scheme['description'], annotation_scheme['id'], annotation_scheme['name'] + ':::select-one', validation))

    #todo move this to the config file
    predefined_labels_dict = {
        'country': 'potato/static/survey_assets/country_dropdown_list.html',
        'ethnicity': 'potato/static/survey_assets/ethnicity_dropdown_list.html',
        'religion': 'potato/static/survey_assets/religion_dropdown_list.html'
    }

    # directly use the predefined labels if annotation_scheme["use_predefined_labels"] is defined
    if "use_predefined_labels" in annotation_scheme and annotation_scheme["use_predefined_labels"] in predefined_labels_dict:
        with open(predefined_labels_dict[annotation_scheme["use_predefined_labels"]]) as r:
            schematic += r.read()

    else:
        # if annotation_scheme['labels'] is defined as a path
        if type(annotation_scheme['labels']) == str and os.path.exists(annotation_scheme['labels']):
            with open(annotation_scheme['labels'], 'r') as r:
                labels = [it.strip() for it in r.readlines()]
        else:
            labels = annotation_scheme['labels']

        for i, label_data in enumerate(labels, 1):

            label = label_data if isinstance(
                label_data, str) else label_data['name']

            name = annotation_scheme['name'] + ':::' + label
            class_name = annotation_scheme['name']
            key_value = name
            label_content = label

            schematic += \
                ((
                     '<option class="%s" id="%s" name="%s" value="%s">%s</option>')
                 % (class_name, name, name, label_content, label_content))


    schematic += '  </select>\n</fieldset>\n</form>\n'
    return schematic, []


@app.route('/files/<path:filename>')
def get_file(filename):
    """Make files available for annotation access from a folder."""
    try:
        return flask.send_from_directory("../data/files/", filename)
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


def yes_or_no(question):
    while "the answer is invalid":
        reply = str(input(question+' (y/n): ')).lower().strip()
        if reply[:1] == 'y':
            return True
        if reply[:1] == 'n':
            return False    

        
def main():
    global config
    global logger
    global user_config
    global user_to_annotation_state


    # Check if the user launched with no arguments and if so, launch the task
    # configuration script for them
    if len(sys.argv) == 1:
        if yes_or_no("Launch task creation process?"):
            if yes_or_no("Launch on command line?"):
                config_file = create_task_cli()
            else:
                # Probably need to launch the Flask server to accept form inputs
                webbrowser.open('file://' + TODO + 'potato/static/create-task.html', new=1)

                # TODO: figure out how to capture the config file
                config_file = 'unknown'
            
            return
    
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

    config['__debug__'] = False
    if args.debug:
        config['__debug__'] = True
    
    # Creates the templates we'll use in flask by mashing annotation
    # specification on top of the proto-templates
    generate_site(config)
    if "surveyflow" in config and config["surveyflow"]["on"]:
        generate_surveyflow_pages(config)


    #quit()

    # Generate the output directory if it doesn't exist yet
    if not os.path.exists(config['output_annotation_dir']):
        os.makedirs(config['output_annotation_dir'])

    # Loads the training data
    load_all_data(config)

        
    # load users with annotations to user_to_annotation_state
    users_with_annotations = [f for f in os.listdir(config['output_annotation_dir']) if os.path.isdir(config['output_annotation_dir'] + f)]
    for user in users_with_annotations:
        load_user_state(user)

    #test the sampling strategy for all users
    #for user in range(50):
    #    print(user, len(sample_instances(str(user))), len(task_assignment['unassigned']), instances_all_assigned())

    # TODO: load previous annotation state
    # load_annotation_state(config)

    flask_logger = logging.getLogger('werkzeug')
    flask_logger.setLevel(logging.ERROR)

    port = args.port or config.get('port', default_port)
    print('running at:\nlocalhost:'+str(port))
    app.run(debug=args.very_verbose, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
