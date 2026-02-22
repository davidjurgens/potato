import os.path

import requests
import zipfile
import io

# Paper-specific projects are now in the potato-showcase repository.
# Example templates are in the examples/ directory locally.
project_hub = {
    'dialogue_analysis': 'https://github.com/davidjurgens/potato-showcase/raw/main/dialogue_analysis.zip',
    'empathy': 'https://github.com/davidjurgens/potato-showcase/raw/main/empathy.zip',
    'gif_reply': 'https://github.com/davidjurgens/potato-showcase/raw/main/gif_reply.zip',
    'immigration_framing': 'https://github.com/davidjurgens/potato-showcase/raw/main/immigration_framing.zip',
    'match_finding': 'https://github.com/davidjurgens/potato-showcase/raw/main/match_finding.zip',
    'match_finding_with_prestudy': 'https://github.com/davidjurgens/potato-showcase/raw/main/match_finding_with_prestudy.zip',
    'sentiment_analysis': 'https://github.com/davidjurgens/potato-showcase/raw/main/sentiment_analysis.zip',
    'summarization_evaluation': 'https://github.com/davidjurgens/potato-showcase/raw/main/summarization_evaluation.zip',
    'textual_uncertainty': 'https://github.com/davidjurgens/potato-showcase/raw/main/textual_uncertainty.zip',
    'question_answering': 'https://github.com/davidjurgens/potato-showcase/raw/main/question_answering.zip',
    'reading_comprehension': 'https://github.com/davidjurgens/potato-showcase/raw/main/reading_comprehension.zip',
    'politeness_rating': 'https://github.com/davidjurgens/potato-showcase/raw/main/politeness_rating.zip',
    'offensiveness': 'https://github.com/davidjurgens/potato-showcase/raw/main/offensiveness.zip',
    'text_rewriting': 'https://github.com/davidjurgens/potato-showcase/raw/main/text_rewriting.zip',
    'prolific_api_example': 'https://github.com/davidjurgens/potato-showcase/raw/main/prolific_api_example.zip',
    'label_suggestions': 'https://github.com/davidjurgens/potato-showcase/raw/main/label_suggestions.zip',
}

# get a specific project from the hub
def get_project_from_hub(name):
    if name not in project_hub:
        print("%s not found in the project hub" % name)
        print("For example templates, see the examples/ directory in the repo.")
        print("For paper-specific projects, see: https://github.com/davidjurgens/potato-showcase")
        return
    response = requests.get(project_hub[name])

    while os.path.exists('%s/' % name):
        print("WARNING: %s already exists" % name)
        answer = input("Overwrite the %s? (y/n) " % name).lower()
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
        print("Downloadable paper-specific projects (from potato-showcase):")
        for key in project_hub:
            print("  " + key)
        print()
        print("For annotation templates, see the examples/ directory in the repo:")
        print("  examples/classification/  - Label selection and rating tasks")
        print("  examples/span/            - Text span annotation")
        print("  examples/audio/           - Audio annotation")
        print("  examples/video/           - Video annotation")
        print("  examples/image/           - Image and document annotation")
        print("  examples/advanced/        - Complex features and workflows")
        print("  examples/ai-assisted/     - AI/ML integration")
        print("  examples/custom-layouts/  - Layout customization")
