Example projects (project hub) ===== Potato aims to improve the
replicability of data annotation and reduce the cost for researchers to
set up new annotation tasks. Therefore, Potato comes with a list of
predefined example projects, and welcome public contribution to the
project hub. If you have used potato for your own annotation, you are
encouraged to create a pull request and release your annotation setup.

### Dialogue analysis (span + categorization) 

[yaml
config](https://github.com/davidjurgens/potato/tree/master/example-projects/dialogue_analysis)

``` 
[launch] python3 potato/flask_server.py example-projects/dialogue_analysis/configs/dialogue-analysis.yaml -p 8000
[Annotate] http://localhost:8000
```

![Alt text](img/dialogue_analysis.gif)

### Sentiment analysis (categorization) 

[yaml
config](https://github.com/davidjurgens/potato/tree/master/example-projects/sentiment_analysis)

``` 
[launch] python3 potato/flask_server.py example-projects/sentiment_analysis/configs/sentiment-analysis.yaml -p 8000
[Annotate] http://localhost:8000
```

![Alt text](img/sentiment_analysis.png)

### Summarization evaluation (likert + categorization)

``` 
[launch] python3 potato/flask_server.py example-projects/summarization_evaluation/configs/summ-eval.yaml -p 8000
[Annotate] http://localhost:8000/?PROLIFIC_PID=user
```

![Alt text](img/summ_eval.png)

### Match findings in papers and news (likert + prescreening questions +
multi-task) 

[yaml
config](https://github.com/davidjurgens/potato/tree/master/example-projects/match_finding)
\| [Paper](http://www.copenlu.com/publication/2022_emnlp_wright/) \|
[Dataset](https://huggingface.co/datasets/copenlu/spiced)

``` 
[Setup configuration files for multiple similar tasks] python3 potato/setup_multitask_config.py example-projects/match_finding/multitask_config.yaml
[launch] python3 potato/flask_server.py example-projects/match_finding/configs/Computer_Science.yaml -p 8000
[Annotate] http://localhost:8000/?PROLIFIC_PID=user
```

![Alt text](img/match_finding.gif)

### Match findings in papers and news (prestudy test)

[yaml
config](https://github.com/davidjurgens/potato/tree/master/example-projects/match_finding_with_prestudy)

``` 
[launch] python3 potato/flask_server.py example-projects/match_finding_with_prestudy/configs/match_finding.yaml -p 8000
[Annotate] http://localhost:8000/?PROLIFIC_PID=user
```

![Alt text](img/match_finding.gif)

### Textual uncertainty (likert + categorization) 

[yaml
config](https://github.com/davidjurgens/potato/tree/master/example-projects/textual_uncertainty)
\|
[Paper](https://jiaxin-pei.github.io/project_websites/certainty/Certainty-in-Science-Communication.html)
\|
[Dataset](https://github.com/Jiaxin-Pei/Certainty-in-Science-Communication/tree/main/data/annotated_data)

``` 
[launch sentence-level] python3 potato/flask_server.py example-projects/textual_uncertainty/configs/sentence_level.yaml -p 8000
[launch aspect-level] python3 potato/flask_server.py example-projects/textual_uncertainty/configs/aspect_level.yaml -p 8000
[Annotate] http://localhost:8000
```

![Alt text](img/textual_uncertainty.gif)

### Immigration framing in tweets (Multi-schema categorization)

[yaml
config](https://github.com/davidjurgens/potato/tree/master/example-projects/immigration_framing)
\| [Paper](https://aclanthology.org/2021.naacl-main.179/) \|
[Dataset](https://github.com/juliamendelsohn/framing)

``` 
[launch] python3 potato/flask_server.py example-projects/immigration_framing/configs/config.yaml -p 8000
[Annotate] http://localhost:8000/
```

![Alt text](img/screenshots/immigration-framing.gif)

### GIF Reply Appropriateness (video as label)

[yaml
config](https://github.com/davidjurgens/potato/tree/master/example-projects/gif_reply)
\| [Paper](https://aclanthology.org/2021.findings-emnlp.276/) \|
[Dataset](https://github.com/xingyaoww/gif-reply)

``` 
[launch] python3 potato/flask_server.py example-projects/gif_reply/configs/gif-reply.yaml -p 8000
[Annotate] http://localhost:8000/
```

![Alt text](img/gif_reply.gif)
