# 🥔Potato: the POrtable Text Annotation TOol
 
[📖Documentation](https://potato-annotation.readthedocs.io/) | [🍎Feature hightlights](#Feature-hightlights)  |  [🛫️Quick Start](#Quick-Start) | [🌰Example projects (project hub)](#Example-projects-project-hub) | [🔥Design Team and Support](#Design-Team-and-Support) | [💰License](#License) | [🍞Cite us](#Cite-us)

<p align="center">
<img src="https://github.com/davidjurgens/potato/raw/master/docs/img/potato-goal.png" width="600" height="280">
</p>



Potato is an easy-to-use  web-based annotation tool accepted by EMNLP 2022 DEMO track. Potato allows you to quickly mock-up and deploy a variety of text annotation tasks. Potato works in the back-end as a web server that you can launch locally and then annotators use the web-based front-end to work through data. Our goal is to allow folks to quickly and easily annotate text data by themselves or in small teams&mdash;going from zero to annotating in a matter of a few lines of configuration.

Potato is driven by a single configuration file that specifies the type of task and data you want to use. Potato does not require any coding to get up and running. For most tasks, no additional web design is needed, though Potato is easily customizable so you can tweak the interface and elements your annotators see.

Please check out our [official documentation](https://potato-annotation.readthedocs.io/) for detailed instructions.

>Jiaxin Pei, Aparna Ananthasubramaniam, Xingyao Wang, Naitian Zhou, Jackson Sargent, Apostolos Dedeloudis and David Jurgens. 🥔Potato: the POrtable Text Annotation TOol. In Proceedings of the 2022 Conference on Empirical Methods on Natural Language Processing (EMNLP'22 demo)

## Feature hightlights 
Potato supports a wide range of features that can make your data annotation easier:

### Easy setup and flexible for diverse needs
Potato can be easily set up with simply editing a configuration file. You don't need to write any codes to set up your annotation webpage. Potato also comes with a series of features for diverse needs.
- [Built-in schemas and templates](https://potato-annotation.readthedocs.io/en/latest/schemas_and_templates): Potato supports a wide range of annotation schemas including radio, likert, checkbox, textbox, span, pairwise comparison, best-worst-scaling, image/video-as-label, etc. All these schemas can be 
- [Flexible data types](https://potato-annotation.readthedocs.io/en/latest/data_format): Potato supports displaying short documents, long documents, dialogue, comparisons, etc.. 
- [Multi-task setup](https://potato-annotation.readthedocs.io/en/latest/schemas_and_templates): NLP researchers may need to set up a series of similar but different tasks (e.g. multilingual annotation). Potato allows you to easily generate configuration files for all the tasks with minimum configurations and has supported the [SemEval 2023 Task 9: Multilingual Tweet Intimacy Analysis](https://sites.google.com/umich.edu/semeval-2023-tweet-intimacy/home)

### Improving Annotator Productivity
Potato is carefully desinged with a series of features that can make your annotators experience better and help you get your annotations faster. You can easily set up 
- [Keyboard Shortcuts](https://potato-annotation.readthedocs.io/en/latest/productivity/#keyboard-shortcuts): Annotators can direcly type in their answers with keyboards
- [Dynamic Highlighting](https://potato-annotation.readthedocs.io/en/latest/productivity/#dynamic-highlighting): For tasks that have a lot of labels or super long documents, you can setup dynamic highlighting which will smartly highlight the potential association between labels and keywords in the document (as defined by you). 
- [Label Tooltips](https://potato-annotation.readthedocs.io/en/latest/productivity/#tooltips): When you have a lot of labels (e.g. 30 labels in 4 categories), it'd be extremely hard for annotators to remember all the detailed descriptions of each of them. Potato allows you to set up label tooltips and annotators can hover the mouse over labels to view the description.

### Knowing better about your annotators
Potato allows a series of features that can help you to better understand the background of annotators and identify potential data biases in your data.
- [Pre and Post screening questions](https://potato-annotation.readthedocs.io/en/latest/surveyflow/#pre-study-survey): Potato allows you to easily set up prescreening and postscreening questions and can help you to better understand the backgrounds of your annotators. Potato comes with a seires of question templates that allows you to easily setup common prescreening questions like [demographics](https://potato-annotation.readthedocs.io/en/latest/surveyflow/#built-in-demographic-questions).

### Better quality control
Potato comes with features that allows you to collect more reliable annotations and identify potential spammers.
- [Attention Test](https://potato-annotation.readthedocs.io/en/latest/surveyflow/#attention-test): Potato allows you to easily set up attention test questions and will randomly insert them into the annotation queue, allowing you to better identify potential spammers.
- [Qualification Test](https://potato-annotation.readthedocs.io/en/latest/surveyflow/#pre-study-test): Potato allows you to easily set up qualification test before the full data labeling and allows you to easily identify disqualified annotators.
- [Built-in time check](https://potato-annotation.readthedocs.io/en/latest/annotator_stats/#annotation-time): Potato automatically keeps track of the time annotators spend on each instance and allows you to better analyze annotator behaviors.


## Quick start
install potato [pypi package](https://pypi.org/project/potato-annotation/)

    pip install potato-annotation

Check all the available project templates

    potato list all

Get one from the project hub

    potato get sentiment_analysis

Start the project

    potato start sentiment_analysis


## Start directly from the github repo
Clone the github repo to your computer

    git clone https://github.com/davidjurgens/potato.git

Install all the required dependencies

    pip install -r requirements.txt

To run a simple check-box style annotation on text data, run

    python potato/flask_server.py start project-hub/simple_examples/configs/simple-check-box.yaml -p 8000
        
This will launch the webserver on port 8000 which can be accessed at [http://localhost:8000](http://localhost:8000). 

Clicking "Submit" will autoadvance to the next instance and you can navigate between items using the arrow keys.

The `project-hub/simple_examples/configs` folder contains example `.yaml` configuration files that match many common simple use-cases. See the full [documentation](https://potato-annotation.readthedocs.io/en/latest/usage/) for all configuration options.



## Baked potatoes
Potato aims to improve the replicability of data annotation and reduce the cost for researchers to set up new annotation tasks. Therefore, Potato comes with a list of predefined example projects, and welcome public contribution to the project hub. If you have used potato for your own annotation, you are encouraged to create a pull request and release your annotation setup. 

Potato currently include the following example projects:

- [simple_schema_examples](https://potato-annotation.readthedocs.io/en/latest/example-projects/#simple-schema-examples)
- [dialogue_analysis](https://potato-annotation.readthedocs.io/en/latest/example-projects/#dialogue-analysis-span-categorization)
- [empathy](https://potato-annotation.readthedocs.io/en/latest/example-projects/#empathy)
- [gif_reply](https://potato-annotation.readthedocs.io/en/latest/example-projects/#gif-reply)
- [immigration_framing](https://potato-annotation.readthedocs.io/en/latest/example-projects/#immigration-framing)
- [match_finding](https://potato-annotation.readthedocs.io/en/latest/example-projects/#match-finding)
- [match_finding_with_prestudy](https://potato-annotation.readthedocs.io/en/latest/example-projects/#match-findings-in-papers-and-news-prestudy-test)
- [sentiment_analysis](https://potato-annotation.readthedocs.io/en/latest/example-projects/#sentiment-analysis)
- [summarization_evaluation](https://potato-annotation.readthedocs.io/en/latest/example-projects/#summarization-evaluation)
- [textual_uncertainty](https://potato-annotation.readthedocs.io/en/latest/example-projects/#textual-uncertainty)
- [question_answering](https://potato-annotation.readthedocs.io/en/latest/example-projects/#question-answering)

Please check full list of [baked potatoes](https://potato-annotation.readthedocs.io/en/latest/example-projects/) for more details!


## Design Team and Support

Potato is run by a small and engergetic team of academics doing the best they can. For support, please leave a issue on this git repo. Feature requests and issues are both welcomed!
If you have any questions or want to collaborate on this project, please email pedropei@umich.edu or jurgens@umich.edu


## License
Potato is dual-licensed. All use cases are covered by Polyform Shield but a commercial license is available for those use cases not allowed by Polyform Shield. Please contact us for details on commercial licensing.

FAQ:
1. If I am an open-source developer, can I fork potato and work on it separately?
    
    Yes, this is allowed with the license
2. If I am an open-source developer, can I fork potato and publicly release a new version with my own features?
    
    No, this is not allowed with the license; such a product would be considered as a “competitor” (see the license for details)
3. If I am working for a company, can I use potato to annotate my data?
    
    Yes, this is allowed with the license
4. If I am working for a company, can I use potato within my company’s pipelines for data annotation (e.g., integrate potato within my company’s internal infrastructure)?
    
    Yes, this is allowed with the license—we’d love to hear about these to advertise, so please contact us at jurgens@umich.edu.
5. Can I integrate potato within a larger annotation pipeline and release that pipeline as an open-source library or service for others to use?
    
    Yes, this is allowed with the license—we’d love to hear about these to advertise, so please contact us
6. Can I integrate potato within a larger annotation pipeline and release that publicly as commercial software/service/resource for others to use?
   
   No, this is not allowed by Polyform Shield but commercial licensing of potato for this purpose is available. Please reach out to us at jurgens@umich.edu for details.
7. I am working for a crowdsourcing platform, can I combine potato in our platform to provide better service for my customers?
   
   No, this is not allowed by Polyform Shield but commercial licensing of potato for this purpose is available. Please reach out to us at jurgens@umich.edu for details.

Have a question or case not covered by the above? Please reach out to us and we’ll add it to the list!




## Cite us
Please use the following bibtex when referencing this work:
```
@inproceedings{pei2022potato,
  title={POTATO: The Portable Text Annotation Tool},
  author={Pei, Jiaxin and Ananthasubramaniam, Aparna and Wang, Xingyao and Zhou, Naitian and Dedeloudis, Apostolos and Sargent, Jackson and Jurgens, David},
  booktitle={Proceedings of the 2022 Conference on Empirical Methods in Natural Language Processing: System Demonstrations},
  year={2022}
}
```
