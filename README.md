# potato: portable text annotation tool

### Start
To run the latest demo for text annotation:

    python3 potato/flask_server.py config/config_single.yaml 

by default, the website will running at 0.0.0.0:8000, to specify other ports (e.g. 8001), try this:

    python3 potato/flask_server.py -p 8001 config/config_single.yaml 

    
The latest multi-choice template supporting all the functions is:
    
    templates/single_multiple_choice.html
    
Please check `config/config_single.yaml` to set up the configurations.

### Recently added features
    [2021.03.16 Jiaxin] count and display the time spent on each instance
    [2021.03.08 Xingyao] video/image as labels
    [2021.03.08 Jiaxin] keyboard shortcut 
    [2021.03.08 Jiaxin] quick jump to the specific instance
    [2021.02.17 Jiaxin] single-choice scheme supporting likert scales
   
    


### How to use `video_as_label`

Please refer to `config/config_single_video_label.yaml` for reference.

Note in order for server to access the video path specfied in the yaml, it is needed to link the directory where video is stored under `potato/data/files` (where the `files` would be a soft link):

    ln -s /a/folder/contains/video potato/data/files

Access `http://<annotation-server-url>:<port>/files/a/b/c.mp4` would be able to direct access the video file `/a/folder/contains/video/a/b/c.mp4`.
