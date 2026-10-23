"""
The jsPsych build Potato ships, and the plugins a `type: jspsych` phase can name.

The files live in ``potato/static/vendor/jspsych-<version>/`` and are
downloaded and SRI-verified by ``scripts/vendor_assets.py``, which reads this
table, so the server's list and the vendored files cannot drift apart.

Each plugin is the browser build, which defines one global (the ``global``
column) that a timeline uses as its ``type``.
"""

JSPSYCH_VERSION = "8.3.0"

VENDOR_SUBDIR = f"jspsych-{JSPSYCH_VERSION}"

#: The core files and their jsDelivr-published SHA-256 (base64).
CORE = {
    "jspsych.js": ("jspsych@8.3.0/dist/index.browser.min.js",
                   "tYxp5gfy3b0oLy2uxD2ILKwY2ePv2tgWIVuBjRQG1s4="),
    "jspsych.css": ("jspsych@8.3.0/css/jspsych.css",
                    "wSpyU00WdqvQ5qeMUECnjerleY7mRihCkNO+RlKRo6Q="),
}

#: name -> (npm version, browser global, jsDelivr SHA-256 of dist/index.browser.min.js)
PLUGINS = {
    "html-keyboard-response": ("2.2.0", "jsPsychHtmlKeyboardResponse",
                               "8/EnqrdUMW31uRtVDfO5lrkU+P8gMq8llh8p7JIhrwE="),
    "html-button-response": ("2.1.0", "jsPsychHtmlButtonResponse",
                             "1N8uv9ffrBRRGY3LKz6kWtgQ7aeqJOReaFHhtTHL8Mk="),
    "html-slider-response": ("2.1.0", "jsPsychHtmlSliderResponse",
                             "DWLPtIlG3CycVupOFkMJNeLdgg/By11R6kVzpHNN0k4="),
    "image-keyboard-response": ("2.2.0", "jsPsychImageKeyboardResponse",
                                "fwXnuqnRs7uJi4FWy6ABYIIdjTz4csEd0W+qPZuORRw="),
    "image-button-response": ("2.2.0", "jsPsychImageButtonResponse",
                              "orRbCCg+5m8QNb9EyihDGsziDMLD4FA8gGS5TL4hJgc="),
    "audio-keyboard-response": ("2.2.0", "jsPsychAudioKeyboardResponse",
                                "Kt/vzsHoECL1gMsC2fOapODo9JNWPl7mrUUXN3dv7pI="),
    "audio-button-response": ("2.1.1", "jsPsychAudioButtonResponse",
                              "z9klca7iVrg6CLkO9l6oWY3BvMaTsKTow6ChMt63IwM="),
    "video-keyboard-response": ("2.2.0", "jsPsychVideoKeyboardResponse",
                                "teZJRDgPi7S2JiVT4YSKxTAT7MEJov9lWJcA1ANOEMo="),
    "instructions": ("2.1.0", "jsPsychInstructions",
                     "Btx9K1wIdKoZyfAjBR2tXEB22Dc1KxndeQwETyMaaEw="),
    "preload": ("2.1.0", "jsPsychPreload",
                "V7xzrNNRxC9zBpYRrK/49l+0wdV1SvfW+WVwUc6N7mY="),
    "fullscreen": ("2.1.0", "jsPsychFullscreen",
                   "wb6DmrSWpSQfXfVqc+cs4KX+rpW1ADOvHRTPA2czY1Q="),
    "survey-likert": ("2.2.0", "jsPsychSurveyLikert",
                      "G+/lwauA1/LeM33vcRoR/YPrT20+FGJBC4RlQ6xz8+A="),
    "survey-text": ("2.1.1", "jsPsychSurveyText",
                    "8Nax80rlPhLrj2seJbRf8ERaKcmLq+Pj+D88BMN5+OM="),
    "survey-multi-choice": ("2.2.1", "jsPsychSurveyMultiChoice",
                            "ZTYs9R/P5vtCe+UDOxTcZIIBjdlgrSW4BdMDzep/0BE="),
    "call-function": ("2.1.0", "jsPsychCallFunction",
                      "1zw/IFGxQWyjfm0gl+zxAilKn0vW8dWlQTgQm4WVYrw="),
}


def plugin_static_path(name: str) -> str:
    """Path under potato/static/ for a vendored plugin."""
    return f"vendor/{VENDOR_SUBDIR}/plugins/plugin-{name}.js"


def core_static_path(fname: str) -> str:
    return f"vendor/{VENDOR_SUBDIR}/{fname}"
