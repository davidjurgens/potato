# Usage

Getting started with Potato is easy! Here's what you need to do:

## Install Potato to your machine

Potato has a Python-based server architecture that can be run locally or
hosted on any device. In order to install Potato:

- Make sure you have Python version 3.8+ installed
- Follow the quickstart instructions in our [Quick Start Guide](quick-start.md)

## Set up the project data

In order to input documents and specify annotation preferences:

- [Prepare your input data](data_format.md#input-data-formats) (CSV, TSV, or JSON) and upload it to your project's `data` folder
- Specify where and in what format you want the [output data](data_format.md#output-data-formats)
- Optional: Update the config YAML file with input and output data preferences

## Create your codebook and schema

Next, you'll need to specify what annotators annotate:

- Create your annotation codebook and link it to the annotation interface using the `annotation_codebook_url` config option
- Specify the [annotation schema](schemas_and_templates.md), including:
  - Annotation Type: `multiselect` (checkboxes), `radio` (single selection), `likert` (scale with endpoints labeled), `span` (text highlighting), `text` (free-form), `slider`, `number`, or `multirate`
  - Questions for annotators
  - Answer Choices for multiselect and radio types
  - End Labels and Length for likert type questions
  - Optional Question Features: `required`, `horizontal` (placement of answers is horizontal not vertical), `has_free_response` (whether to include an open text box at the end of multiselect or radio question, like having an "other" option)
  - Optional Answer Features: [tooltips](productivity.md#tooltips), [keyboard shortcuts](productivity.md#keyboard-shortcuts), [keywords to highlight](productivity.md#dynamic-highlighting)
- Optional: See [schemas and templates](schemas_and_templates.md) for basic and advanced examples

## Define annotation settings

There are a few other settings you can configure:

- Choose an existing [HTML template](schemas_and_templates.md#available-layout-templates) for the annotation task or create a new one
- Optional: Specify privacy and access [settings](user_and_collaboration.md) for the task
- Optional: Update the YAML file with the [UI and layout configuration](configuration.md#ui-and-layout-configuration)
- Optional: Set up [active learning](active_learning_guide.md)

## Launch Potato locally

And that's it! You can go ahead and get started labeling data in one of two ways:

### Option 1: Direct Config File (Recommended)

**Important**: Your YAML configuration file must be located within the `task_dir` specified in the configuration. This is a security requirement.

```bash
# Start with a specific config file
python potato/flask_server.py start my_annotation_task/config.yaml -p 8000
```

Your project structure should look like this:
```
my_annotation_task/
├── config.yaml              # Config file in task_dir
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
│   ├── experiment1.yaml     # Config files in configs/
│   └── experiment2.yaml
├── data/
│   └── my_data.json
└── output/
    └── annotations/
```

### Option 3: Interactive Setup (Legacy)

Launch Potato without a YAML. In this case, the server will have you follow a series of prompts about the task and automatically generate a YAML file for you.

```bash
python3 potato/flask_server.py -p 8000
```

This will launch the webserver on port 8000 which can be accessed at <http://localhost:8000>. You can [create an account](user_and_collaboration.md) and start labeling data. Clicking "Submit" will auto-advance to the next instance and you can navigate between items using the arrow keys. Potato currently supports one annotation task per server instance, though multiple servers may be run on different ports to concurrently annotate different data.

## Find the right IP address for local usage

In many cases you might need to use Potato within your local network. For example, you have some private data that are not allowed to be uploaded to a public server, and you want your annotators to access the interface using their own devices. Here are the following steps:

1. Deploy Potato on the server/computer where the data is hosted

2. Find the local address of your server (this is different from the public IP address; it is the address that is only accessible within your local network)

3. For Linux/Mac, go to the terminal, type `ifconfig en0` and press enter:
   - You will see a list of addresses, and please find the one after `inet`, for example, you should find one line looks like this: `inet 192.168.1.218 netmask 0xffffff00 broadcast 192.168.1.255`
   - Use the address after inet, which is `192.168.1.218` in this case

4. On the annotator end, use `ip:port` in the browser. For example, if you have Potato running on port 8000, and in the above case, the final address to access the interface will be `192.168.1.218:8000`

5. Please make sure your annotators are either within the local network (e.g. company or school's network), or are connected to the VPN if they are outside the local network

6. You can also try the above link on your iPad or smartphones as long as they are connected to the same WiFi as the server (could be your own laptop)

## Next Steps

- [Configuration Guide](configuration.md) - Complete configuration reference
- [Schemas and Templates](schemas_and_templates.md) - All annotation types
- [Quality Control](quality_control.md) - Attention checks and gold standards
- [Crowdsourcing](crowdsourcing.md) - MTurk and Prolific integration
- [Admin Dashboard](admin_dashboard.md) - Monitoring and management
