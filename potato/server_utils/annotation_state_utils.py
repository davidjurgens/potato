"""
Utility functions around managing annotation states.
"""

import os
import re
import json
import logging
from collections import defaultdict
import pandas as pd
from potato.server_utils.config_module import config
from potato.server_utils.prestudy import check_prestudy_status
from potato.server_utils.user_state_utils import (
    lookup_user_state, assign_instances_to_user
)
import potato.state as state
logger = logging.getLogger(__name__)


def _parse_html_span_annotation(html_span_annotation):
    """
    Parses the span annotations produced in raw HTML by Potato's front end
    and extracts out the precise spans and labels annotated by users.

    :returns: a tuple of (1) the annotated string without annotation HTML
              and a list of annotations
    """
    span_annotation = html_span_annotation.strip()
    init_tag_regex = re.compile(r"(<span.+?>)")
    end_tag_regex = re.compile(r"(</span>)")
    anno_regex = re.compile(r'<div class="span_label".+?>(.+)</div>')
    no_html_s = ""
    start = 0

    annotations = []

    while True:
        _m = init_tag_regex.search(span_annotation, start)
        if not _m:
            break

        # find the end tag
        _m2 = end_tag_regex.search(span_annotation, _m.end())

        middle = span_annotation[_m.end() : _m2.start()]

        # Get the annotation label from the middle text
        _m3 = anno_regex.search(middle)

        middle_text = middle[: _m3.start()]
        annotation = _m3.group(1)

        no_html_s += span_annotation[start : _m.start()]

        ann = {
            "start": len(no_html_s),
            "end": len(no_html_s) + len(middle_text),
            "span": middle_text,
            "annotation": annotation,
        }
        annotations.append(ann)

        no_html_s += middle_text
        start = _m2.end(0)

    # Add whatever trailing text exists
    no_html_s += span_annotation[start:]

    return no_html_s, annotations


def _get_users():
    """
    Returns an iterable over the usernames of all users who have annotated in
    the system so far
    """
    return list(state.user_to_annotation_state.keys())


def get_total_annotations():
    """
    Returns the total number of unique annotations done across all users.
    """
    total = 0
    for username in _get_users():
        user_state = lookup_user_state(username)
        total += user_state.get_annotation_count()

    return total


def get_annotations_for_user_on(username, instance_id):
    """
    Returns the label-based annotations made by this user on the instance.
    """
    user_state = lookup_user_state(username)
    annotations = user_state.get_label_annotations(instance_id)
    return annotations


def get_span_annotations_for_user_on(username, instance_id):
    """
    Returns the span annotations made by this user on the instance.
    """
    user_state = lookup_user_state(username)
    span_annotations = user_state.get_span_annotations(instance_id)
    return span_annotations


def update_annotation_state(username, form):
    """
    Parses the state of the HTML form (what the user did to the instance) and
    updates the state of the instance's annotations accordingly.
    """
    # Get what the user has already annotated, which might include
    # this instance too
    user_state = lookup_user_state(username)

    # Jiaxin: the instance_id are changed to the user's local instance cursor
    instance_id = user_state.cursor_to_real_instance_id(int(form["instance_id"]))

    schema_to_label_to_value = defaultdict(dict)

    behavioral_data_dict = {}

    did_change = False
    for key in form:

        # look for behavioral information regarding time, click, ...
        if key[:9] == "behavior_":
            behavioral_data_dict[key[9:]] = form[key]
            continue

        # Look for the marker that indicates an annotation label.
        #
        # NOTE: The span annotation uses radio buttons as well to figure out
        # which label. These inputs are labeled with "span_label" so we can
        # skip them as being actual annotatins (spans are saved below though).
        if ":::" in key and "span_label" not in key:

            cols = key.split(":::")
            annotation_schema = cols[0]
            annotation_label = cols[1]
            annotation_value = form[key]

            # skip the input when it is an empty string (from a text-box)
            if annotation_value == "":
                continue

            schema_to_label_to_value[annotation_schema][annotation_label] = annotation_value

    # Span annotations are a bit funkier since we're getting raw HTML that
    # we need to post-process on the server side.
    span_annotations = []
    if "span-annotation" in form:
        span_annotation_html = form["span-annotation"]
        span_text, span_annotations = _parse_html_span_annotation(span_annotation_html)

    did_change = user_state.set_annotation(
        instance_id, schema_to_label_to_value, span_annotations, behavioral_data_dict
    )

    # update the behavioral information regarding time only when
    # the annotations are changed
    if did_change:
        user_state.instance_id_to_behavioral_data[instance_id] = behavioral_data_dict

        # TODO: we probably need a more elegant way to check
        # the status of user consent
        # when the user agreed to participate, try to assign
        if re.search("consent", instance_id):
            consent_key = "I want to participate in this research and continue with the study."
            user_state.consent_agreed = False
            if schema_to_label_to_value[consent_key].get("Yes") == "true":
                user_state.consent_agreed = True
            assign_instances_to_user(username)

        # when the user is working on prestudy, check the status
        if re.search("prestudy", instance_id):
            print(check_prestudy_status(username))

    return did_change


def save_all_annotations():
    # Figure out where this user's data would be stored on disk
    output_annotation_dir = config["output_annotation_dir"]
    fmt = config["output_annotation_format"]

    if fmt not in ["csv", "tsv", "json", "jsonl"]:
        raise Exception("Unsupported output format: " + fmt)

    if not os.path.exists(output_annotation_dir):
        os.makedirs(output_annotation_dir)
        logger.debug("Created state directory for annotations: %s" % (output_annotation_dir))

    annotated_instances_fname = os.path.join(output_annotation_dir, "annotated_instances." + fmt)

    # We write jsonl format regardless
    if fmt in ["json", "jsonl"]:
        with open(annotated_instances_fname, "wt") as outf:
            for user_state in state.user_to_annotation_state.values():
                for inst_id, data in user_state.get_all_annotations().items():

                    bd_dict = user_state.instance_id_to_behavioral_data.get(inst_id, {})

                    output = {
                        "id": inst_id,
                        "displayed_text": state.instance_id_to_data[inst_id]["displayed_text"],
                        "label_annotations": data["labels"],
                        "span_annotations": data["spans"],
                        "behavioral_data": bd_dict,
                    }
                    json.dump(output, outf)
                    outf.write("\n")

    # Convert to Pandas and then dump
    elif fmt in ["csv", "tsv"]:
        df = defaultdict(list)

        # Loop 1, figure out which schemas/labels have values so we know which
        # things will need to be columns in each row
        schema_to_labels = defaultdict(set)
        span_labels = set()

        for user_state in state.user_to_annotation_state.values():
            for annotations in user_state.get_all_annotations().values():
                # Columns for each label-based annotation
                for schema, label_vals in annotations["labels"].items():
                    for label in label_vals.keys():
                        schema_to_labels[schema].add(label)

                # Columns for each span type too
                for span in annotations["spans"]:
                    span_labels.add(span["annotation"])

                # TODO: figure out what's in the behavioral dict and how to format it

        # Loop 2, report everything that's been annotated
        for user_id, user_state in state.user_to_annotation_state.items():
            for (inst_id, annotations) in user_state.get_all_annotations().items():

                df["user"].append(user_id)
                df["instance_id"].append(inst_id)
                df["displayed_text"].append(state.instance_id_to_data[inst_id]["displayed_text"])

                label_annotations = annotations["labels"]
                span_annotations = annotations["spans"]

                for schema, labels in schema_to_labels.items():
                    if schema in label_annotations:
                        label_vals = label_annotations[schema]
                        for label in labels:
                            val = label_vals.get(label)
                            # For some sanity, combine the schema and label it a single column
                            df[schema + ":::" + label].append(val)
                    # If the user did label this schema at all, fill it with None values
                    else:
                        for label in labels:
                            df[schema + ":::" + label].append(None)

                # We bunch spans by their label to make it slightly easier to
                # process, but it's still kind of messy compared with the JSON
                # format.
                for span_label in span_labels:
                    anns = [sa for sa in span_annotations if sa["annotation"] == span_label]
                    df["span_annotation:::" + span_label].append(anns)

                # TODO: figure out what's in the behavioral dict and how to format it

        df = pd.DataFrame(df)
        sep = "," if fmt == "csv" else "\t"
        df.to_csv(annotated_instances_fname, index=False, sep=sep)

    # Save the annotation assignment info if automatic task assignment is on.
    # Jiaxin: we are simply saving this as a json file at this moment
    if "automatic_assignment" in config and config["automatic_assignment"]["on"]:
        # TODO: write the code here
        print("saved")
