"""
Survey importers: questionnaires from other tools as Potato survey pages.

See :mod:`potato.importers.surveys.base` for the result type and
:mod:`potato.importers.surveys.writer` for what gets written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .beiwe import BeiweImporter
from .limesurvey import LimeSurveyImporter
from .network_canvas import NetworkCanvasImporter
from .qualtrics import QualtricsImporter
from .redcap import REDCapImporter
from .surveyjs import SurveyJSImporter
from .xlsform import XLSFormImporter

IMPORTERS = {
    "qualtrics": QualtricsImporter(),
    "surveyjs": SurveyJSImporter(),
    "redcap": REDCapImporter(),
    "beiwe": BeiweImporter(),
    "limesurvey": LimeSurveyImporter(),
    "xlsform": XLSFormImporter(),
    "network_canvas": NetworkCanvasImporter(),
}

ALIASES = {
    "qsf": "qualtrics",
    "survey-js": "surveyjs",
    "survey_js": "surveyjs",
    "redcap-dictionary": "redcap",
    "redcap_dictionary": "redcap",
    "lss": "limesurvey",
    "lime": "limesurvey",
    "odk": "xlsform",
    "kobo": "xlsform",
    "kobotoolbox": "xlsform",
    "xls-form": "xlsform",
    "netcanvas": "network_canvas",
    "networkcanvas": "network_canvas",
    "network-canvas": "network_canvas",
}


def resolve(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    key = ALIASES.get(name.lower(), name.lower())
    return key if key in IMPORTERS else None


def detect(path: str) -> Optional[str]:
    for name, importer in IMPORTERS.items():
        try:
            if importer.detect_path(Path(path)):
                return name
        except (OSError, ValueError):
            continue
    return None


def list_importers():
    return [{"name": name, "description": imp.description,
             "file_extensions": imp.file_extensions}
            for name, imp in IMPORTERS.items()]
