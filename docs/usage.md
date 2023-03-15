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
    learning](https://potato-annotation-tutorial.readthedocs.io/en/latest/productivity.html#active-learning)

## Launch potato locally 

And that\'s it! You can go ahead and get started labeling data in one of
two ways:

**Option 1:** Follow the prompts given above to define a YAML file that
specifies the data sources, server configuration, annotation schemes,
and any custom visualizations
([examples](https://github.com/davidjurgens/potato/tree/master/config/examples))
and then launch potato.

`python3 potato/flask_server.py config/examples/simple-check-box.yaml -p 8000`

**Option 2:** Launch potato without a YAML. In this case, the server
will have you follow a series of prompts about the task and
automatically generate a YAML file for you. A YAML file is then passed
to the server on the command line to launch the server for annotation.

`python3 potato/flask_server.py -p 8000`

This will launch the webserver on port 8000 which can be accessed at
<http://localhost:8000>. You can [create an
account](https://potato-annotation-tutorial.readthedocs.io/en/latest/user_and_collaboration.html)
and start labeling data. Clicking \"Submit\" will autoadvance to the
next instance and you can navigate between items using the arrow keys.
Potato currently supports one annotation task per server instance,
though multiple servers may be run on different posts to concurrently
annotate different data.
