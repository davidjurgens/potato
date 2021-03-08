# potato: portable text annotation tool

To run the latest demo with keyboard shortcuts and quick jump:

    python3 potato/flask_server.py config/config_single.yaml 
    
The latest multi-choice template supporting all the functions is:
    
    templates/single_multiple_choice.html
    
Please check `config/config_single.yaml` to see how to set up single-choice/likert schema and keyboard shortcuts.
    
## How to use `video_as_label`

Please refer to `config/config_single_video_label.yaml` for reference.

Note in order for server to access the video path specfied in the yaml, it is needed to link the directory where video is stored under `potato/data/files` (where the `files` would be a soft link):

    ln -s /a/folder/contains/video potato/data/files

Access `http://<annotation-server-url>:<port>/files/a/b/c.mp4` would be able to direct access the video file `/a/folder/contains/video/a/b/c.mp4`.
