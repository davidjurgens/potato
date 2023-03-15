# Quick start

Clone the github repo to your computer

``` console
git clone https://github.com/davidjurgens/potato.git
```

Install all the required dependencies

``` console
pip3 install -r requirements.txt
```

To run a simple check-box style annotation on text data, run

``` console
python3 potato/flask_server.py config/examples/simple-check-box.yaml -p 8000
```

This will launch the webserver on port 8000 which can be accessed at
<http://localhost:8000>.
