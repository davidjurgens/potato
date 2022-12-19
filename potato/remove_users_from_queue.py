'''
This script is used to remove user from the assigned data. This operation is usually used when there are bad users who participate in the task but didn't finish all the instances.
'''

import json
import os
#from server_utils.config_module import init_config, config
from argparse import ArgumentParser
import pandas as pd
import shutil

task_assignment_path = None#os.path.join(config["output_annotation_dir"], config["automatic_assignment"]["output_filename"])

annotation_data_dir = None#config["output_annotation_dir"]
annotation_data_path = None#os.path.join(config["output_annotation_dir"], "annotated_instances.tsv")

parser = ArgumentParser()
parser.set_defaults(show_path=False, show_similarity=False)
parser.add_argument("--task_assignment_path", default=task_assignment_path)
parser.add_argument("--annotation_data_dir", default=annotation_data_dir)
parser.add_argument("--user_file")

args = parser.parse_args()
args.annotation_data_path = os.path.join(args.annotation_data_dir, "annotated_instances.tsv")

print(args)
with open(args.user_file,'r') as r:
    users = [it.strip() for it in r.readlines()]
    user_set = set(users)

print("users to be removed from the assigned data and annotation instances: ", users)

# remove user annotations from the global annotation file
annotated_df = pd.read_csv(args.annotation_data_path, sep="\t")
new_annotated_df = annotated_df[~annotated_df['user'].isin(users)]
print("%d lines removed from bad users"%(len(annotated_df)-len(new_annotated_df)))
new_annotated_df.to_csv(args.annotation_data_path + '_new', sep="\t", index=False)

# move the bad users into a separate dir under annotation output
bad_user_dir = args.annotation_data_dir + "archived_users"
if not os.path.exists(bad_user_dir):
    os.mkdir(bad_user_dir)
for u in users:
    shutil.move(os.path.join(args.annotation_data_dir, u), os.path.join(bad_user_dir, u))
print('bad users moved to %s'%bad_user_dir)

# remove users from the task assignment
if os.path.exists(args.task_assignment_path):
    # load the task assignment if it has been generated and saved
    with open(args.task_assignment_path, "r") as r:
        task_assignment = json.load(r)

for inst_id in task_assignment['assigned']:
    new_li = []
    if type(task_assignment['assigned'][inst_id]) != list:
        continue
    for u in task_assignment['assigned'][inst_id]:
        if u in user_set:
            if inst_id not in task_assignment['unassigned']:
                task_assignment['unassigned'][inst_id] = 0
            task_assignment['unassigned'][inst_id] += 1
        else:
            new_li.append(u)
    #if len(new_li) != len(task_assignment['assigned'][inst_id]):
    #    print(task_assignment['assigned'][inst_id], new_li)
    task_assignment['assigned'][inst_id] = new_li

if os.path.exists(args.task_assignment_path):
    # load the task assignment if it has been generated and saved
    with open(args.task_assignment_path + '_new', "w") as w:
        json.dump(task_assignment, w)

print('unassigned instances after user removal',task_assignment['unassigned'])