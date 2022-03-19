# Potato: the POrtable Text Annotation TOol

##

Potato is an easy-to-use  web-based annotation tool to let you quickly mock-up and deploy a variety of text annotation tasks. Potato works in the back-end as a web server that you can launch locally and then annotators use the web-based front end to work through data. Our goal is to allow folks to quickly and easily annotate text data by themselves or in small teams&mdash;going from zero to annotating in a matter of a few lines of configuration.

Potato is driven by a single configuration file that specifies the type of task and data you want to use. Potato does not require any coding to get up and running. For most tasks, no additional web design is needed, though Potato is easily customizable so you can tweak the interface and elements your annotators see.

Please check out our [official documentation](https://potato-annotation-tutorial.readthedocs.io/) for detailed instructions.



### Quick Start
Clone the github repo to your computer

    git clone https://github.com/davidjurgens/potato.git

Install all the required dependencies

    pip3 install -r requirements.txt

To run a simple check-box style annotation on text data, run

    python3 potato/flask_server.py config/examples/simple-check-box.yaml -p 8000
        
This will launch the webserver on port 8000 which can be accessed at [http://localhost:8000](http://localhost:8000). 

Clicking "Submit" will autoadvance to the next instance and you can navigate between items using the arrow keys.

The `config/examples` folder contains example `.yaml` configuration files that match many common simple use-cases. See the full [documentation](https://potato-annotation-tutorial.readthedocs.io/en/latest/usage.html) for all configuration options.


### Versions

  Partial version/commit log so far: 
  
    [2022.01.24 David] Initial public release
    [2021.06.19 David] Overhaul of rendering engine and support for new annotation schemes
    [2021.03.16 Jiaxin] count and display the time spent on each instance
    [2021.03.08 Xingyao] video/image as labels
    [2021.03.08 Jiaxin] keyboard shortcut 
    [2021.03.08 Jiaxin] quick jump to the specific instance
    [2021.02.17 Jiaxin] single-choice scheme supporting likert scales
   
### Design Team and Support

Potato is run by a small and engergetic team of academics doing the best they can. For support, please leave a issue on this git repo. Feature requests and issues are both welcomed!
   
### Citing Potato

Oh I sure hope we get to this.
