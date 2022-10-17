# 🥔Potato: the POrtable Text Annotation TOol

##

Potato is an easy-to-use  web-based annotation tool to let you quickly mock-up and deploy a variety of text annotation tasks. Potato works in the back-end as a web server that you can launch locally and then annotators use the web-based front end to work through data. Our goal is to allow folks to quickly and easily annotate text data by themselves or in small teams&mdash;going from zero to annotating in a matter of a few lines of configuration.

Potato is driven by a single configuration file that specifies the type of task and data you want to use. Potato does not require any coding to get up and running. For most tasks, no additional web design is needed, though Potato is easily customizable so you can tweak the interface and elements your annotators see.

Please check out our [official documentation](https://potato-annotation-tutorial.readthedocs.io/) for detailed instructions.

## Feature hightlights 
Potato supports a wide ranges of features that can make your data annotation easier:

### Easy setup
Potato can be easily set up with simply editing a configuration file. You don't need to write any codes to set up your annotation webpage. Please check out our full [documentation](https://potato-annotation-tutorial.readthedocs.io/en/latest/schemas_and_templates.html) for all configuration options. Potato comes with a series of built-in [templates](https://potato-annotation-tutorial.readthedocs.io/en/latest/schemas_and_templates.html#existing-task-templates) which allows you to easily setup common forms of annotation tasks like Question Answering, Sentiment Analyisis, Text Classification, ...

### Improving Annotator Productivity
Potato is carefully desinged with a series of features that can make your annotators experience better and help you get your annotations faster. You can easily set up 
- [Keyboard Shortcuts](https://potato-annotation-tutorial.readthedocs.io/en/latest/productivity.html#keyboard-shortcuts): Annotators can direcly type in their answers with keyboards
- [Dynamic Highlighting](https://potato-annotation-tutorial.readthedocs.io/en/latest/productivity.html#dynamic-highlighting): For tasks that have a lot of labels or super long documents, you can setup dynamic highlighting which will smartly highlight the potential association between labels and keywords in the document (as defined by you). 
- [Label Tooltips](https://potato-annotation-tutorial.readthedocs.io/en/latest/productivity.html#tooltips): When you have a lot of labels (e.g. 30 labels in 4 categories), it'd be extremely hard for annotators to remember all the detailed descriptions of each of them. Potato allows you to set up label tooltips and annotators can hover the mouse over labels to view the description.


## Quick Start
Clone the github repo to your computer

    git clone https://github.com/davidjurgens/potato.git

Install all the required dependencies

    pip3 install -r requirements.txt

To run a simple check-box style annotation on text data, run

    python3 potato/flask_server.py config/examples/simple-check-box.yaml -p 8000
        
This will launch the webserver on port 8000 which can be accessed at [http://localhost:8000](http://localhost:8000). 

Clicking "Submit" will autoadvance to the next instance and you can navigate between items using the arrow keys.

The `config/examples` folder contains example `.yaml` configuration files that match many common simple use-cases. See the full [documentation](https://potato-annotation-tutorial.readthedocs.io/en/latest/usage.html) for all configuration options.



## Example projects
Potato comes with a list of predefined example projects:
Dialogue analysis

    python3 potato/flask_server.py example-projects/dialogue_analysis/configs/dialogue-analysis.yaml -p 8000

![plot](./images/summ_eval.png)

Sentiment analysis

    python3 potato/flask_server.py example-projects/sentiment_analysis/configs/sentiment-analysis.yaml -p 8000
    
Summarization evaluation

    python3 potato/flask_server.py example-projects/summarization_evaluation/configs/summ-eval.yaml -p 8000

    
## Design Team and Support

Potato is run by a small and engergetic team of academics doing the best they can. For support, please leave a issue on this git repo. Feature requests and issues are both welcomed!
If you have any questions or want to collaborate on this project, please email pedropei@umich.edu
   
