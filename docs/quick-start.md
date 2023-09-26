# Quick start

## start with pypi
install potato [pypi package](https://pypi.org/project/potato-annotation/)

    pip install potato-annotation

Check all the available project templates

    potato list all

potato currently supports (check out example-projects page for all the projects)

    simple_schema_examples
    dialogue_analysis
    empathy
    gif_reply
    immigration_framing
    match_finding
    match_finding_with_prestudy
    sentiment_analysis
    summarization_evaluation
    textual_uncertainty
    question_answering

Get one from the project hub

    potato get sentiment_analysis

Start the project

    potato start sentiment_analysis



## start from the github repo
Clone the github repo to your computer

``` console
git clone https://github.com/davidjurgens/potato.git
```

Install all the required dependencies

``` console
pip install -r requirements.txt
```

To run a simple check-box style annotation on text data, run

``` console
python potato/flask_server.py start project-hub/simple_examples/configs/simple-check-box.yaml -p 8000
```

This will launch the webserver on port 8000 which can be accessed at
<http://localhost:8000>.
