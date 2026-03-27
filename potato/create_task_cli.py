"""
Interactive Task Creation CLI Module

Provides an interactive command-line interface for creating new annotation tasks.
Guides users through configuration and generates a YAML config file.
"""

import os

import click
import yaml


# Common annotation types shown in the interactive prompt.
# The full set of supported types is in the schema registry.
COMMON_ANNOTATION_TYPES = [
    "radio",
    "multiselect",
    "text",
    "likert",
    "slider",
    "span",
    "bws",
    "pairwise",
    "ranking",
]


def create_task_cli():
    """
    Interactive task creation wizard.

    Walks the user through server setup, data files, annotation schemes,
    and output settings, then writes a YAML config file.
    """
    click.echo("Welcome to the Potato annotation task creation wizard!")
    click.echo("This will generate a .yaml config file for your annotation task.")
    click.echo("You can edit the file afterwards to add advanced features.\n")

    click.echo("— Server setup —\n")

    task_name = click.prompt("Task name (shown to annotators)", default="My Annotation Task")
    port = click.prompt("Server port", default=8000, type=click.IntRange(1, 65535))

    click.echo("\n— Data files —\n")

    data_files = []
    fname = click.prompt("Path to your data file (JSONL)")
    data_files.append(fname)
    while click.confirm("Add another data file?", default=False):
        fname = click.prompt("Path to data file")
        data_files.append(fname)

    id_key = click.prompt("Which field in the data is the item ID?", default="id")
    text_key = click.prompt("Which field is the item text?", default="text")

    click.echo("\n— Annotation schemes —\n")

    annotation_schemes = []
    while True:
        atype = click.prompt(
            "Annotation type",
            type=click.Choice(COMMON_ANNOTATION_TYPES, case_sensitive=False),
        )
        name = click.prompt("Internal name for this scheme (used in output)")
        desc = click.prompt("Description/question shown to annotators")

        scheme = {
            "annotation_type": atype,
            "name": name,
            "description": desc,
        }

        if atype in ("radio", "multiselect"):
            labels = []
            click.echo("Enter labels one at a time (empty line to finish):")
            while True:
                label = click.prompt("  Label", default="", show_default=False)
                if not label:
                    break
                labels.append(label)
            scheme["labels"] = labels

        elif atype == "likert":
            size = click.prompt("Scale size", default=5, type=int)
            min_label = click.prompt("Label for minimum", default="Strongly Disagree")
            max_label = click.prompt("Label for maximum", default="Strongly Agree")
            scheme["size"] = size
            scheme["min_label"] = min_label
            scheme["max_label"] = max_label

        elif atype == "slider":
            scheme["min_value"] = click.prompt("Minimum value", default=0, type=int)
            scheme["max_value"] = click.prompt("Maximum value", default=100, type=int)

        elif atype == "bws":
            size = click.prompt("Tuple size (items shown at once)", default=4, type=int)
            scheme["size"] = size

        elif atype == "ranking":
            labels = []
            click.echo("Enter options to rank (empty line to finish):")
            while True:
                label = click.prompt("  Option", default="", show_default=False)
                if not label:
                    break
                labels.append(label)
            scheme["labels"] = labels

        annotation_schemes.append(scheme)

        if not click.confirm("\nAdd another annotation scheme?", default=False):
            break

    click.echo("\n— Output settings —\n")

    output_dir = click.prompt("Output directory for annotations", default="annotation_output")
    codebook_url = click.prompt("Annotation codebook URL (optional)", default="")

    auto_export = click.confirm("Auto-export annotations in CSV/JSONL?", default=False)
    export_format = None
    if auto_export:
        export_format = click.prompt(
            "Export format",
            type=click.Choice(["csv", "tsv", "jsonl"], case_sensitive=False),
            default="csv",
        )

    # Build config
    config = {
        "annotation_task_name": task_name,
        "port": port,
        "data_files": data_files,
        "item_properties": {
            "id_key": id_key,
            "text_key": text_key,
        },
        "annotation_schemes": annotation_schemes,
        "output_annotation_dir": output_dir,
        "annotation_codebook_url": codebook_url,
        "user_config": {
            "allow_all_users": True,
            "users": [],
        },
    }

    if export_format:
        config["export_annotation_format"] = export_format

    click.echo("\n— Save config —\n")

    config_file = click.prompt("Path for the config file", default="config.yaml")

    if os.path.exists(config_file):
        if not click.confirm(f"{config_file} already exists. Overwrite?", default=False):
            click.echo("Aborted.")
            return

    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    click.echo(f"\nConfig written to {config_file}")
    click.echo(f"Start annotating with: potato start {config_file}")
