# Data Formats 

## Prepare your input data 

Upload one or more files containing documents to be annotated in the
`data` folder.

We support multiple formats of raw data files, including: csv, tsv,
json, or jsonl.

Each document needs, at minimum, a unique identifier and the body of the
document.

You can find example data files
[here](https://github.com/davidjurgens/potato/blob/master/project-hub/simple_examples/data/). We
currently support four different document formats:

-   Text: body is the document plaintext
    ([example](https://github.com/davidjurgens/potato/blob/master/project-hub/simple_examples/data/toy-example.json))
-   Image, Video, or GIF: body is the filepath
    ([example](https://github.com/davidjurgens/potato/blob/master/project-hub/simple_examples/data/video-as-input.json))
-   Dialogue or a list of text: body is a list of comma-seperated
    documents and potato will automatically display the list of text
    horizontally.
    ([example](https://github.com/davidjurgens/potato/blob/master/project-hub/dialogue_analysis/data_files/dialogue-example.json))
-   Pairs of text displayed in separate boxes: body is a dictionary of
    documents
    ([example](https://github.com/davidjurgens/potato/blob/master/project-hub/match_finding/data_files/pilot_data_Biology.csv))
-   Html files
    - Put the .html files in a folder ([example](https://github.com/davidjurgens/potato/blob/master/project-hub/simple_examples/data/html_data)),
    - Then put the relatiev paths to these htmls as normal text input ([example](https://github.com/davidjurgens/potato/blob/master/project-hub/simple_examples/data/html-as-input.json))
-   Best-Worst Scaling: body is a comma-separated list of documents to
    order
    ([example](https://github.com/davidjurgens/potato/blob/master/project-hub/simple_examples/data/bws-example.json))
-   Custom Arguments: body is one of the above + extra fields for
    whatever custom arguments you want to enter
    ([example](https://github.com/davidjurgens/potato/blob/master/project-hub/simple_examples/data/bws-example.json)
    \-- in this `kwargs` and `other_kwargs` are the custom endpoints for
    a Likert scale)
-   Annotating Document A in context of Document B: body is document A +
    extra `context` field with the body of document B
    ([example](https://github.com/davidjurgens/potato/blob/master/project-hub/simple_examples/data/))

You can also use html tags to design the way your text to be displayed.
In the [match finding example
project](https://github.com/davidjurgens/potato/tree/master/project-hub/match_finding),
html tags are used to create two seperate boxes for the finding pairs.


## Displaying a list or a dictionary of instances
Potato allows you to easily display a list or a dictionary of instance and you could easily set
`list_as_text` as `True`.

If you are using a list of instances, you could also define whether adding a prefix to the text
``` yaml
"list_as_text": {
  "text_list_prefix_type": 'alphabet'
  # whether adding a prefix to each instance in the list
  # when creating displayed_text, 
  # options: 
  #     alphabet: add alphabets before each instance (e.g. A.this is good, B.nice)
  #     number: add alphabets before each instance (e.g. 1.this is good, 2.nice)
},
```

the content will displayed vertically by default, 
if you want to display the list or dict horizontally, you can set `horizontal` as `True`
``` yaml
"list_as_text": {
  "horizontal": True
},
```

if you want to randomize the diplayed content for a dictionary, you can use `randomization`,
In this case, the order of the displayed content will be shuffled, so that you can avoid potential
biased caused by the ordering effect. You can access the displayed content in the annotated outputs.

``` yaml
"list_as_text": {
  "randomization":"value" # whether randomizing the list or dictionary when creating displayed_text, 
                          # options: 
                          #     "value": only shuffle the values but keep the order of the keys
                          #     "key": shuffle the order of keys
},
```


## Update input data formats on the YAML config file

You would pass the input data paths and field names into the YAML config
file as follows (please make sure you have "id" and "text" key in your data):

``` yaml
# Pass in a comma-separated list of data files containing documents to be annotated in this task
"data_files": [
   "data/toy-example1.json",
   "data/toy-example2.json"
],

# Specify the field names containing the document unique identifier (id) and document body (text)
"item_properties": {
    "id_key": "id",
    "text_key": "text"
},
```

## Update output data preferences on the YAML config file

The output file will include each labeled document\'s id and
annotations; the header will consist of the question and answer labels
specified in the
[schema](https://potato-annotation.readthedocs.io/en/latest/schemas_and_templates).
You need to specify a subdirectory of the `annotation_output` directory
where files for each annotator should be placed. We support multiple
output formats, including: csv, tsv, json, or jsonl.

``` yaml
# Potato will write the annotation file for all annotations to this
# directory, as well as per-annotator output files and state information
# necessary to restart annotation.
"output_annotation_dir": "annotation_output/folder_name/",

# The output format for the all-annotator data. Allowed formats are:
# * jsonl
# * json (same output as jsonl)
# * csv
# * tsv
#
"output_annotation_format": "json", 
```
