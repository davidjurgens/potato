# Crowdsourcing setting

Potato can be seamlessly deployed online to collect annotations from common crowdsourcing platforms like Prolifc.com

Setup potato on a server with open ports \-\-\-\-\-\-\-\-\-\-\--To run
potato in a crowdsourcing setup, you need to setup potato on a server
with open ports (ports that can be accessed via open internet). When you
start the potato server, simply changc to default port to the openly
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
