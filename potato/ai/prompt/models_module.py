from typing import Optional, Type, Union, Dict, List
from pydantic import BaseModel


class GeneralHintFormat(BaseModel):
    hint: str
    suggestive_choice: Union[str, int]


class LabelKeywords(BaseModel):
    """Keywords/phrases associated with a specific label."""
    label: str
    keywords: List[str]


class GeneralKeywordFormat(BaseModel):
    """Simplified keyword format: list of label -> keywords mappings.

    Example output:
    {
        "label_keywords": [
            {"label": "positive", "keywords": ["great", "love it", "excellent"]},
            {"label": "negative", "keywords": ["terrible", "awful"]}
        ]
    }
    """
    label_keywords: List[LabelKeywords]


class GeneralRandomFormat(BaseModel):
    random: str


CLASS_REGISTRY = {
    "default_hint": GeneralHintFormat,
    "default_keyword": GeneralKeywordFormat,
    "default_random": GeneralRandomFormat
}