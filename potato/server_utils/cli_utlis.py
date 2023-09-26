import os.path

import requests
import zipfile
import io

# all the available examples in the project hub
project_hub = {
    'simple_schema_examples': 'https://github.com/davidjurgens/potato/raw/master/project-hub/simple_examples.zip',
    'dialogue_analysis': 'https://github.com/davidjurgens/potato/raw/master/project-hub/dialogue_analysis.zip',
    'empathy': 'https://github.com/davidjurgens/potato/raw/master/project-hub/empathy.zip',
    'gif_reply': 'https://github.com/davidjurgens/potato/raw/master/project-hub/gif_reply.zip',
    'immigration_framing': 'https://github.com/davidjurgens/potato/raw/master/project-hub/immigration_framing.zip',
    'match_finding': 'https://github.com/davidjurgens/potato/raw/master/project-hub/match_finding.zip',
    'match_finding_with_prestudy': 'https://github.com/davidjurgens/potato/raw/master/project-hub/match_finding_with_prestudy.zip',
    'sentiment_analysis': 'https://github.com/davidjurgens/potato/raw/master/project-hub/sentiment_analysis.zip',
    'summarization_evaluation': 'https://github.com/davidjurgens/potato/raw/master/project-hub/summarization_evaluation.zip',
    'textual_uncertainty': 'https://github.com/davidjurgens/potato/raw/master/project-hub/textual_uncertainty.zip',
    'question_answering': 'https://github.com/davidjurgens/potato/raw/master/project-hub/question_answering.zip',
    'reading_comprehension': 'https://github.com/davidjurgens/potato/raw/master/project-hub/reading_comprehension.zip',
    'politeness_rating': 'https://github.com/davidjurgens/potato/raw/master/project-hub/politeness_rating.zip',
    'offensiveness': 'https://github.com/davidjurgens/potato/raw/master/project-hub/offensiveness.zip',
    'text_rewriting': 'https://github.com/davidjurgens/potato/raw/master/project-hub/text_rewriting.zip',
}

# get a speicific project from the hub
def get_project_from_hub(name):
    if name not in project_hub:
        print("%s not found in the project_hub"%name)
        return
    response = requests.get(project_hub[name])

    while os.path.exists('%s/'%name):
        print("WARNING: %s already exists"%name)
        answer = input("Overwrite the %s? (y/n) "%name).lower()
        if answer == 'y':
            break
        else:
            answer = input("Please type in a different project name:")
            name = answer

    # Extract the contents of the ZIP archive
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        # Extract the contents of the archive to a directory
        archive.extractall('%s/' % name)
    print("successfully fetched %s" % name)

# show all the available projects in the hub
def show_project_hub(type):
    if type == 'all':
        print("all the available example projects that you can directly fetch")
        for key in project_hub:
            print(key)