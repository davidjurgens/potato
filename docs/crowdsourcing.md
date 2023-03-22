# Crowdsourcing setting

Potato can be seamlessly deployed online to collect annotations from common crowdsourcing platforms like Prolifc.com

## Setup potato on a server with open ports 
To run potato in a crowdsourcing setup, you need to setup potato on a server
with open ports (ports that can be accessed via open internet). When you
start the potato server, simply change to default port to the openly
accessible ports and you should be able to access the annotation page
via you_ip_address:the_port

## Prolific

Prolific is a platform where you can easily recruit task participants
and Potato can be used seamlessly with prolific.co. To used potato with
prolific.co, you need to define the login type as
[url_direct]{.title-ref} and set up the \"url_argument\" as
\'PROLIFIC_PID\'.

``` YAML
#defining the ways annotators entering the annotation system
"login": {
   "type": 'url_direct',    #can be 'password' or 'url_direct'
   "url_argument": 'PROLIFIC_PID' # when the login type is set to 'url_direct', 'url_argument' must be setup for a direct url argument login
},
```

It is also recommended to set the \"jumping_to_id_disabled\" and
\"hide_navbar\" as True

``` YAML
#the jumping-to-id function will be disabled if "jumping_to_id_disabled" is True
 "jumping_to_id_disabled": False,

#the navigation bar will be hidden to the annotators if "hide_navbar" is True
 "hide_navbar": True,
```

As prolific uses finishing code to indicate whether an annotator has finished all the tasks, you would also need to set up an end page 
and display it at the end of the study. To insert an end page, you would need to use the surveyflow feature of potato and here are the following steps

### create an end page in surveyflow
create a dir named surveyflow under your project dir and create a end.jsonl file with the following content:
``` YAML
{"id":"1","text":"Thanks for your time, please copy the following end code to prolific to complete the study","schema": "pure_display", "choices": ["YOUR-PROLIFIC-CODE"]}
```
Please make sure you put your own prolific end code in "choices".

### add this page in the configuration file
Please add the relative path to your end page in the surveyflow field of your .yaml file

``` YAML
"surveyflow": {
        "on": true,
        "order": [
            "pre_annotation",
            "post_annotation"
        ],
        "pre_annotation": [
            "surveyflow/consent.jsonl",
        ],
        "post_annotation": [
            "surveyflow/end.jsonl",
        ],
        "testing": [
        ]
},
```

Then the end page will be automatically displayed at the end of the study and your annotators will use the code to indicate they have finished their annotations.

You may check the [match_finding](https://github.com/davidjurgens/potato/tree/master/project-hub/match_finding) project in project hub to see how the end page is configurated.
