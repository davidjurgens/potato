"""
Handle all front-end related functionalities.
"""

import os
import logging
import json
import re
import hashlib
from collections import OrderedDict

#add local module
from pathlib import Path
import sys
path_root = Path(__file__).parents[2]
sys.path.append(str(path_root))

from potato.server_utils.config_module import config
from potato.server_utils.schemas import (
    generate_multiselect_layout,
    generate_multirate_layout,
    generate_radio_layout,
    generate_span_layout,
    generate_likert_layout,
    generate_textbox_layout,
    generate_number_layout,
    generate_pure_display_layout,
    generate_select_layout,
    generate_slider_layout,
)

logger = logging.getLogger(__name__)


# TODO: Move this to config.yaml files
# Items which will be displayed in the popup statistics sidebar
STATS_KEYS = {
    "Annotated instances": "Annotated instances",
    "Total working time": "Total working time",
    "Average time on each instance": "Average time on each instance",
    "Agreement": "Agreement",
}

# Default name for the generated annotation layout file
DEFAULT_ANNOTATION_LAYOUT_SUBDIR = "layouts"
DEFAULT_ANNOTATION_LAYOUT_FILENAME = "task_layout.html"


def compute_config_md5(config):
    """
    Compute MD5 hash of the config dict for template invalidation.
    """
    # Remove unserializable fields if needed
    config_copy = {k: v for k, v in config.items() if k not in ['__config_file__', 'site_file']}
    config_str = json.dumps(config_copy, sort_keys=True, default=str)
    return hashlib.md5(config_str.encode('utf-8')).hexdigest()


def generate_annotation_layout_file(config: dict, annotation_schemes: list[dict]) -> str:
    """
    Generate a dedicated annotation layout file in the task directory under layouts/task_layout.html.
    """
    task_dir = config.get("task_dir")
    if not task_dir:
        raise ValueError("task_dir is required in config to generate annotation layout file")

    # Ensure task directory and layouts subdirectory exist
    layout_dir = os.path.join(task_dir, DEFAULT_ANNOTATION_LAYOUT_SUBDIR)
    if not os.path.exists(layout_dir):
        os.makedirs(layout_dir)

    # Generate the layout file path
    layout_file_path = os.path.join(layout_dir, DEFAULT_ANNOTATION_LAYOUT_FILENAME)

    # Generate the HTML layout content
    schema_layouts = ""
    all_keybindings = []

    for annotation_scheme in annotation_schemes:
        schema_layout, keybindings = generate_schematic(annotation_scheme)
        schema_layouts += schema_layout + "\n"
        all_keybindings.extend(keybindings)

    # Compute config hash
    config_hash = compute_config_md5(config)

    # Create the layout HTML content with config hash at the top
    layout_content = f"""<!-- CONFIG_HASH: {config_hash} -->
<!-- Generated annotation layout file -->
<!-- This file was automatically generated based on the annotation schemes in your config -->
<!-- You can customize this file to modify the layout of your annotation interface -->
<!-- Changes to this file will be preserved across server restarts -->

<div class=\"annotation_schema\">
{schema_layouts}
</div>
"""

    # Write the layout file
    with open(layout_file_path, "wt") as outf:
        outf.write(layout_content)

    logger.info(f"Generated annotation layout file: {layout_file_path}")
    return layout_file_path


def get_or_generate_annotation_layout(config: dict, annotation_schemes: list[dict]) -> str:
    """
    Get the annotation layout file path, generating it if it doesn't exist or if the config hash has changed.
    """
    task_dir = config.get("task_dir")
    if not task_dir:
        raise ValueError("task_dir is required in config")
    layout_dir = os.path.join(task_dir, DEFAULT_ANNOTATION_LAYOUT_SUBDIR)
    layout_file_path = os.path.join(layout_dir, DEFAULT_ANNOTATION_LAYOUT_FILENAME)

    current_hash = compute_config_md5(config)

    # Check if the layout file already exists and if the hash matches
    if os.path.exists(layout_file_path):
        with open(layout_file_path, "rt") as f:
            for _ in range(2):  # Only need to check the first two lines
                line = f.readline()
                if line.startswith("<!-- CONFIG_HASH:"):
                    file_hash = line.strip().split(":", 1)[1].replace('-->', '').strip()
                    if file_hash == current_hash:
                        logger.info(f"Using existing annotation layout file: {layout_file_path} (hash match)")
                        return layout_file_path
                    else:
                        logger.info(f"Config hash mismatch, regenerating annotation layout file: {layout_file_path}")
                    break

    # Generate the layout file if it doesn't exist or hash mismatches
    logger.info(f"Annotation layout file not found or hash mismatch, generating: {layout_file_path}")
    return generate_annotation_layout_file(config, annotation_schemes)


def generate_schematic(annotation_scheme):
    """
    Based on the task's yaml configuration, generate the full HTML site needed
    to annotate the tasks's data.
    """
    # Figure out which kind of tasks we're doing and build the input frame
    annotation_type = annotation_scheme["annotation_type"]
    annotation_func = {
        "multiselect": generate_multiselect_layout,
        "multirate": generate_multirate_layout,
        "radio": generate_radio_layout,
        "highlight": generate_span_layout,
        "span": generate_span_layout,
        "likert": generate_likert_layout,
        "text": generate_textbox_layout,
        "number": generate_number_layout,
        "pure_display": generate_pure_display_layout,
        "select": generate_select_layout,
        "slider": generate_slider_layout,
    }.get(annotation_type)

    if not annotation_func:
        raise Exception("unsupported annotation type: %s" % annotation_type)

    print("annotation_func(annotation_scheme)")
    print(annotation_func(annotation_scheme))
    return annotation_func(annotation_scheme)


def generate_keybindings_sidebar(config, keybindings, horizontal=False):
    """
    Generate an HTML layout for the end-user of the keybindings for the current
    task. The layout is intended to be displayed in a side bar or on the annotation page if fixed_keybinding_layout.html is used as the layout
    """
    if config.get("horizontal_key_bindings"):
        horizontal = True

    if not keybindings:
        return ""

    if horizontal:
        keybindings = [[it[0], it[1].split(":")[-1]] for it in keybindings]
        lines = list(zip(*keybindings))
        layout = '<table style="border:1px solid black;margin-left:auto;margin-right:auto;text-align: center;">'
        for line in lines:
            layout += (
                "<tr>"
                + "".join(["<td>&nbsp;&nbsp;%s&nbsp;&nbsp;</td>" % it for it in line])
                + "</tr>"
            )
        layout += "</table>"

    else:
        layout = "<table><tr><th>Key</th><th>Description</th></tr>"
        for key, desc in keybindings:
            layout += '<tr><td style="text-align: center;">%s</td><td>%s</td></tr>' % (key, desc)
        layout += "</table>"

    return layout


def generate_statistics_sidebar(statistics):
    """
    Generate an HTML layout for the end-user of the statistics for the current
    task. The layout is intended to be displayed in a side bar
    """
    layout = "<table><tr><th> </th><th> </th></tr>"
    for key in statistics:
        desc = "{{statistics_nav['%s']}}" % statistics[key]
        layout += '<tr><td style="text-align: center;">%s</td><td>%s</td></tr>' % (key, desc)
    layout += "</table>"
    return layout


def generate_annotation_html_template(config: dict) -> str:
    """
    Generates the full HTML file in site/ for annotating this tasks data,
    combining the various templates with the annotation specification in
    the yaml file and returns the path to the HTML template for this
    annotation task.
    """
    logger.info("Generating anntotation site at %s" % config["site_dir"])

    #
    # Stage 1: Construct the core HTML file devoid the annotation-specific content
    #

    # Use hardcoded template paths - no longer configurable
    cur_program_dir = os.path.dirname(os.path.abspath(__file__))
    html_template_file = os.path.join(cur_program_dir, '..', 'templates', 'base_template_v2.html')
    header_file = os.path.join(cur_program_dir, '..', 'templates', 'header.html')

    logger.debug("Reading html annotation template %s" % html_template_file)
    print('html_template_file: ', html_template_file)

    if not os.path.exists(html_template_file):
        raise FileNotFoundError("html_template_file not found: %s" % html_template_file)

    with open(html_template_file, "rt") as file_p:
        html_template = "".join(file_p.readlines())

    # Load the header content we'll stuff in the template, which has scripts
    # and assets we'll need
    logger.debug("Reading html header %s" % header_file)

    if not os.path.exists(header_file):
        raise FileNotFoundError("header_file not found: %s" % header_file)

    with open(header_file, "rt") as file_p:
        header = "".join(file_p.readlines())

    html_template = html_template.replace("{{ HEADER }}", header)

    if config.get("jumping_to_id_disabled"):
        html_template = html_template.replace(
            '<input type="submit" value="go">', '<input type="submit" value="go" hidden>'
        )
        html_template = html_template.replace(
            '<input type="number" name="go_to" id="go_to" value="" onfocusin="user_input()" onfocusout="user_input_leave()" max={{total_count}} min=0 required>',
            '<input type="number" name="go_to" id="go_to" value="" onfocusin="user_input()" onfocusout="user_input_leave()" max={{total_count}} min=0 required hidden>',
        )

    if config.get("hide_navbar"):
        html_template = html_template.replace(
            '<div class="navbar-nav">', '<div class="navbar-nav" hidden>'
        )

    # Grab the annotation schemes
    annotation_schemes = config["annotation_schemes"]
    logger.debug("Saw %d annotation scheme(s)" % len(annotation_schemes))

    # insert annotation id to each of the schemes
    for idx, annotation_scheme in enumerate(annotation_schemes):
        annotation_scheme["annotation_id"] = idx

    # Keep track of all the keybindings we have
    all_keybindings = [("&#8592;", "Move backward"), ("&#8594;", "Move forward")]

    # Check if we're using the new API-based template that generates forms dynamically
    is_api_template = "base_template_v2.html" in html_template_file

    # Handle annotation layout generation
    # Check if user provided a custom task_layout file
    task_layout_file = config.get("task_layout")

    if task_layout_file:
        # User provided a custom task layout file
        logger.info(f"Using custom task layout file: {task_layout_file}")

        # Resolve the path relative to the config file
        if not os.path.exists(task_layout_file):
            real_path = os.path.realpath(config["__config_file__"])
            dir_path = os.path.dirname(real_path)
            abs_task_layout_file = os.path.join(dir_path, task_layout_file)

            if not os.path.exists(abs_task_layout_file):
                raise FileNotFoundError(f"task_layout file not found: {task_layout_file}")
            task_layout_file = abs_task_layout_file

        # Read the custom task layout
        with open(task_layout_file, "rt") as f:
            task_html_layout = "".join(f.readlines())

        # Extract keybindings from the annotation schemes for the sidebar
        for annotation_scheme in annotation_schemes:
            _, keybindings = generate_schematic(annotation_scheme)
            all_keybindings.extend(keybindings)

    else:
        # Use the dedicated annotation layout file system (auto-generated)
        try:
            print("12312321432")
            layout_file_path = get_or_generate_annotation_layout(config, annotation_schemes)
            # Read the generated layout file
            with open(layout_file_path, "rt") as f:
                task_html_layout = "".join(f.readlines())

            # Extract keybindings from the annotation schemes for the sidebar
            for annotation_scheme in annotation_schemes:
                _, keybindings = generate_schematic(annotation_scheme)
                all_keybindings.extend(keybindings)
            
        except Exception as e:
            logger.warning(f"Failed to use dedicated layout file: {e}. Falling back to inline generation.")

            # Fallback to inline generation
            if is_api_template:
                # For the new API-based template, generate server-side forms but use API endpoints
                # The frontend JavaScript will handle form interactions via API calls
                logger.info("Using API-based template - generating server-side forms with API integration")

                # Generate the forms using the existing schematic generation
                schema_layouts = ""
                for annotation_scheme in annotation_schemes:
                    schema_layout, keybindings = generate_schematic(annotation_scheme)
                    schema_layouts += schema_layout + "\n"
                    all_keybindings.extend(keybindings)

                task_html_layout = schema_layouts
            else:
                # Generate inline layout
                schema_layouts = ""
                for annotation_scheme in annotation_schemes:
                    schema_layout, keybindings = generate_schematic(annotation_scheme)
                    schema_layouts += schema_layout + "\n"
                    all_keybindings.extend(keybindings)

                task_html_layout = f'<div class="annotation_schema">{schema_layouts}</div>'

    # Add in a codebook link if the admin specified one
    codebook_html = ""
    if len(config.get("annotation_codebook_url", "")) > 0:
        annotation_codebook = config["annotation_codebook_url"]
        codebook_html = '<a href="{{annotation_codebook_url}}" class="nav-item nav-link">Annotation Codebook</a>'
        codebook_html = codebook_html.replace("{{annotation_codebook_url}}", annotation_codebook)

    #
    # Step 3, drop in the annotation layout and insert the rest of the task-specific variables
    #

    # Swap in the task's layout
    html_template = html_template.replace("{{ TASK_LAYOUT }}", task_html_layout)
    html_template = html_template.replace("{{annotation_codebook}}", codebook_html)
    html_template = html_template.replace(
        "{{annotation_task_name}}", config["annotation_task_name"]
    )

    # For API-based templates, replace debug placeholder
    if is_api_template:
        html_template = html_template.replace("{{ debug | tojson | safe }}", str(config.get("debug", False)).lower())

    keybindings_desc = generate_keybindings_sidebar(config, all_keybindings)
    html_template = html_template.replace("{{keybindings}}", keybindings_desc)

    statistics_layout = generate_statistics_sidebar(STATS_KEYS)
    html_template = html_template.replace("{{statistics_nav}}", statistics_layout)

    # Jiaxin: change the basename from the template name to the project name +
    # template name, to allow multiple annotation tasks using the same template
    site_name = (
        "-".join(config["annotation_task_name"].split(" "))
        + "-"
        + os.path.basename(html_template_file)
    )

    # Create generated subdirectory within the templates directory
    generated_dir = os.path.join(config["site_dir"], "generated")
    if not os.path.exists(generated_dir):
        os.makedirs(generated_dir)
        logger.info(f"Created generated templates directory: {generated_dir}")

    output_html_fname = os.path.join(generated_dir, site_name)
    print('output_html_fname: ', output_html_fname)

    # Cache this path as a shortcut to figure out which page to render
    config["site_file"] = site_name

    # Compute config hash and add it to the template
    config_hash = compute_config_md5(config)
    html_template_with_hash = f"<!-- CONFIG_HASH: {config_hash} -->\n{html_template}"

    # Write the file
    with open(output_html_fname, "wt") as outf:
        outf.write(html_template_with_hash)

    logger.debug("writing annotation html to %s" % output_html_fname)

    return site_name

def get_html(fname: str, config: dict):
    """
    Returns the content of an HTML file, looking for alternative locations relative
    to the config file if the path is relative.
    """
    if not os.path.exists(fname):

        real_path = os.path.realpath(config["__config_file__"])
        dir_path = os.path.dirname(real_path)
        abs_html_template_file = dir_path + "/" + fname

        if not os.path.exists(abs_html_template_file):
            raise FileNotFoundError("html file not found: %s" % fname)
        else:
            fname = abs_html_template_file

    with open(fname, "rt") as f:
        html = "".join(f.readlines())
    return html

def generate_core_task_html(config: dict,
                            annotation_schemas: list[dict]) -> str:
    """
    Generates the HTML layout for the core annotation task for
    all the annotation-specific content and returns the HTML layout.
    """
    schema_layouts = ""
    task_html_layout = ""
    for annotation_scheme in annotation_schemas:

        schema_layout, keybindings = generate_schematic(annotation_scheme)
        schema_layouts += schema_layout + "<br>" + "\n"

        print("generate_schematic")
        print(generate_schematic)

        cur_task_html_layout = task_html_layout.replace(
            "{{annotation_schematic}}", schema_layouts
        )

    # Swap in the task's layout
    return cur_task_html_layout


def generate_html_from_schematic(annotation_schemas: list[dict],
                                 allow_jumping_to_id: bool,
                                 hide_navbar: bool,
                                 phase_name: str,
                                 config: dict,
                                 task_layout_file: str = None):
    """
    Generates the full HTML file in site/ for annotating this tasks data,
    combining the various templates with the annotation specification in
    the yaml file.
    """
    #
    # Stage 1: Construct the core HTML file devoid the annotation-specific content
    #

    # Use hardcoded template paths - no longer configurable
    cur_program_dir = os.path.dirname(os.path.abspath(__file__))
    html_template_filename = os.path.join(cur_program_dir, '..', 'templates', 'base_template_v2.html')
    html_header_filename = os.path.join(cur_program_dir, '..', 'templates', 'header.html')

    # Load the core template that has all the UI controls and non-task layout.
    logger.debug("Reading html annotation template %s" % html_template_filename)
    html_template = get_html(html_template_filename, config)

    # Load the header content we'll stuff in the template, which has scripts and assets we'll need
    logger.debug("Reading html header %s" % html_header_filename)
    header = get_html(html_header_filename, config)

    # Once we have the base template constructed, load the user's custom layout for their task
    html_template = html_template.replace("{{ HEADER }}", header)

    if allow_jumping_to_id:
        html_template = html_template.replace(
            '<input type="submit" value="go">', '<input type="submit" value="go" hidden>'
        )
        html_template = html_template.replace(
            '<input type="number" name="go_to" id="go_to" value="" onfocusin="user_input()" onfocusout="user_input_leave()" max={{total_count}} min=0 required>',
            '<input type="number" name="go_to" id="go_to" value="" onfocusin="user_input()" onfocusout="user_input_leave()" max={{total_count}} min=0 required hidden>',
        )

    if hide_navbar:
        html_template = html_template.replace(
            '<div class="navbar-nav">', '<div class="navbar-nav" hidden>'
        )

    # Handle annotation layout generation for surveyflow phases
    # Check if user provided a custom task_layout file (either from config or phase)
    if not task_layout_file:
        task_layout_file = config.get("task_layout")

    if task_layout_file:
        # User provided a custom task layout file
        logger.info(f"Using custom task layout file: {task_layout_file}")

        # Resolve the path relative to the config file
        if not os.path.exists(task_layout_file):
            real_path = os.path.realpath(config["__config_file__"])
            dir_path = os.path.dirname(real_path)
            abs_task_layout_file = os.path.join(dir_path, task_layout_file)

            if not os.path.exists(abs_task_layout_file):
                raise FileNotFoundError(f"task_layout file not found: {task_layout_file}")
            task_layout_file = abs_task_layout_file

        # Read the custom task layout
        with open(task_layout_file, "rt") as f:
            task_html_layout = "".join(f.readlines())

    else:
        # Use the dedicated annotation layout file system (auto-generated)
        try:
            print("fewifjwoiejf")
            layout_file_path = get_or_generate_annotation_layout(config, annotation_schemas)
            
            # Read the generated layout file
            with open(layout_file_path, "rt") as f:
                task_html_layout = "".join(f.readlines())
            
        except Exception as e:
            logger.warning(f"Failed to use dedicated layout file: {e}. Falling back to inline generation.")

            # Fallback to inline generation
            # Generate inline layout
            schema_layouts = ""
            for annotation_scheme in annotation_schemas:
                schema_layout, keybindings = generate_schematic(annotation_scheme)
                schema_layouts += schema_layout + "\n"

            task_html_layout = f'<div class="annotation_schema">{schema_layouts}</div>'

    cur_html_template = html_template.replace("{{ TASK_LAYOUT }}", task_html_layout)

    # Add in a codebook link if the admin specified one
    codebook_html = ""
    if len(config.get("annotation_codebook_url", "")) > 0:
        annotation_codebook = config["annotation_codebook_url"]
        codebook_html = '<a href="{{annotation_codebook_url}}" class="nav-item nav-link">Annotation Codebook</a>'
        codebook_html = codebook_html.replace("{{annotation_codebook_url}}", annotation_codebook)

    html_template = html_template.replace("{{annotation_codebook}}", codebook_html)

    html_template = html_template.replace(
        "{{annotation_task_name}}", config["annotation_task_name"]
    )

    _ = generate_statistics_sidebar(STATS_KEYS)
    html_template = html_template.replace("{{statistics_nav}}", " ")

    #
    # Step 3, Fill in the annotation-specific pieces in the layout and save the page
    #

    logger.debug("Saw %d annotation scheme(s)" % len(annotation_schemas))

    # Keep track of all the keybindings we have
    all_keybindings = [("&#8592;", "Move backward"), ("&#8594;", "Move forward")]

    # Do not display keybindings for the first and last page
    if False:
        if i == 0:
            keybindings_desc = generate_keybindings_sidebar(config, all_keybindings[1:])
            cur_html_template = cur_html_template.replace(
                '<a class="btn btn-secondary" href="#" role="button" onclick="click_to_prev()">Move backward</a>',
                '<a class="btn btn-secondary" href="#" role="button" onclick="click_to_prev()" hidden>Move backward</a>',
            )
        elif i == len(annotation_schemas) - 1 or re.search("prestudy_fail", page):
            keybindings_desc = generate_keybindings_sidebar(config, all_keybindings[:-1])
            cur_html_template = cur_html_template.replace(
                '<a class="btn btn-secondary" href="#" role="button" onclick="click_to_next()">Move forward</a>',
                '<a class="btn btn-secondary" href="#" role="button" onclick="click_to_next()" hidden>Move forward</a>',
            )
        else:
            keybindings_desc = generate_keybindings_sidebar(config, all_keybindings)

        cur_html_template = cur_html_template.replace("{{keybindings}}", keybindings_desc)

    # Cache the html as a template for use in flask server
    site_name = (
            "_".join(config["annotation_task_name"].split(" "))
            + "-"
            + "%s.html" % phase_name
        )

    # Create generated subdirectory within the templates directory
    generated_dir = os.path.join(config["site_dir"], "generated")
    if not os.path.exists(generated_dir):
        os.makedirs(generated_dir)
        logger.info(f"Created generated templates directory: {generated_dir}")

    output_html_fname = os.path.join(generated_dir, site_name)

    # Write the file
    logger.debug("writing %s html to %s.html" % (phase_name, output_html_fname))
    with open(output_html_fname, "wt") as outf:
        outf.write(cur_html_template)

    return site_name #output_html_fname