# Usage

Getting started with Potato is easy! Here\'s what you need to do:

## Install Potato to your machine

Potato has a Python-based server architecture that can be run locally or
hosted on any device. In order to install Potato:

-   Make sure you have Python version 3 installed
-   Follow the quickstart instructions
    [here](https://potato-annotation-tutorial.readthedocs.io/en/latest/quick-start.html).

## Set up the project data

In order to input document and specify:

-   [Prepare](https://potato-annotation-tutorial.readthedocs.io/en/latest/data_format.html#prepare-your-input-data)
    your input data (csv, tsv, or json) and upload it in the `data`
    folder
-   Specify where and in what format you want the
    [output](https://potato-annotation-tutorial.readthedocs.io/en/latest/data_format.html#update-output-data-preferences-on-the-yaml-config-file)
    data
-   Optional: Update the config YAML file with
    [input](https://potato-annotation-tutorial.readthedocs.io/en/latest/data_format.html#update-input-data-formats-on-the-yaml-config-file)
    and
    [output](https://potato-annotation-tutorial.readthedocs.io/en/latest/data_format.html#update-output-data-preferences-on-the-yaml-config-file)
    data preferences

## Create your codebook and schema

Next, you\'ll need to specify what annotators annotate:

-   Create your annotation codebook and [link
    it](https://potato-annotation-tutorial.readthedocs.io/en/latest/schemas_and_templates.html#add-the-codebook-to-the-page)
    to the annotation interface
-   Specify the
    [schema](https://potato-annotation-tutorial.readthedocs.io/en/latest/schemas_and_templates.html),
    including:
    -   Annotation Type: `multiselect` (checkboxes), `radio` (single
        selection), `likert` (scale with endpoints labeled), or `text`
        (free-form)
    -   Questions for annotators
    -   Answer Choices for multiselect and radio types
    -   End Labels and Length for likert type questions
    -   Optional Question Features: `required`, `horizontal` (placement
        of answers is horizontal not vertical), `has_free_response`
        (whether to include an open text box at the end of multiselect
        or radio question, like having an \"other\" option)
    -   Optional Answer Features:
        [tooltips](https://potato-annotation-tutorial.readthedocs.io/en/latest/productivity.html#tooltips),
        [keyboard
        shortcuts](https://potato-annotation-tutorial.readthedocs.io/en/latest/productivity.html#keyboard-shortcuts),
        [keywords to
        highlight](https://potato-annotation-tutorial.readthedocs.io/en/latest/productivity.html#dynamic-highlighting)
-   Optional: Format the schema for the YAML config file ([basic
    examples](https://potato-annotation-tutorial.readthedocs.io/en/latest/schemas_and_templates.html),
    [advanced
    examples](https://potato-annotation-tutorial.readthedocs.io/en/latest/productivity.html))

## Define annotation settings

There are a few other settings you can play with:

-   Choose an existing [html
    template](https://potato-annotation-tutorial.readthedocs.io/en/latest/schemas_and_templates.html#choose-or-create-your-html-template)
    for the annotation task or create a new one
-   Optional: Specify privacy and access
    [settings](https://potato-annotation-tutorial.readthedocs.io/en/latest/user_and_collaboration.html)
    for the task
-   Optional: Update the YAML file with the [look and
    feel](https://potato-annotation-tutorial.readthedocs.io/en/latest/schemas_and_templates.html#update-yaml-file-with-look-and-feel).
-   Optional: Set up [active
    learning](active_learning_guide.md)

## Launch potato locally

And that's it! You can go ahead and get started labeling data in one of
two ways:

### Option 1: Direct Config File (Recommended)

**Important**: Your YAML configuration file must be located within the `task_dir` specified in the configuration. This is a security requirement.

```bash
# Start with a specific config file
python potato/flask_server.py start my_annotation_task/config.yaml -p 8000
```

Your project structure should look like this:
```
my_annotation_task/
├── config.yaml              # ✅ Config file in task_dir
├── data/
│   └── my_data.json
├── output/
│   └── annotations/
└── templates/
    └── custom_layout.html
```

### Option 2: Project Directory with Configs Subfolder

If you have multiple configuration files, you can organize them in a `configs/` subdirectory:

```bash
# Start with project directory (will prompt to choose config if multiple exist)
python potato/flask_server.py start my_annotation_task/ -p 8000
```

Your project structure would look like this:
```
my_annotation_task/
├── configs/
│   ├── experiment1.yaml     # ✅ Config files in configs/
│   └── experiment2.yaml
├── data/
│   └── my_data.json
└── output/
    └── annotations/
```

### Option 3: Interactive Setup (Legacy)

Launch potato without a YAML. In this case, the server
will have you follow a series of prompts about the task and
automatically generate a YAML file for you.

```bash
python3 potato/flask_server.py -p 8000
```

This will launch the webserver on port 8000 which can be accessed at
<http://localhost:8000>. You can [create an
account](https://potato-annotation-tutorial.readthedocs.io/en/latest/user_and_collaboration.html)
and start labeling data. Clicking \"Submit\" will autoadvance to the
next instance and you can navigate between items using the arrow keys.
Potato currently supports one annotation task per server instance,
though multiple servers may be run on different posts to concurrently
annotate different data.


## Find the right IP address for local usage
In many cases you might need to use potato within your local network. For example, you have some
private data that are not allowed to be uploaded to a public server, and you want your annotators to
access the interface using their own devices, here are the following steps:
-   Deploy potato on the server/computer where the data is hosted
-   Find the local address of your server (this is different from the public id address, it is the address that
is only accessible within your local network)

-   For linux/mac go to the terminal, type `ifconfig en0` and press enter.
    -   You will see a list of addresses, and please find the one after `inet`, for example, you should find
    one line looks like this: `inet 192.168.1.218 netmask 0xffffff00 broadcast 192.168.1.255`
    -  Use the address after inet, which is `192.168.1.218` in this case

-   On the annotator end, use `ip:port` in the browser. For example, if you have potato running on
port 8000, and in the above case, the final address to access the interface will be `192.168.1.218:8000`

-   Please make sure your annotators are either within the local network (e.g. company or school's net), or are
connected to the vpn if they are outside the local network.

-   You can also try the above link on your ipad or smartphones as long as they are connected to the
same wifi as the server (could be your own laptop)