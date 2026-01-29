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
    """Deprecated: Use GeneralRationaleFormat instead."""
    random: str


class LabelRationale(BaseModel):
    """Rationale/reasoning for why a specific label might apply."""
    label: str
    reasoning: str


class GeneralRationaleFormat(BaseModel):
    """Rationale format: explanations for how each label might apply to the text.

    Example output:
    {
        "rationales": [
            {"label": "positive", "reasoning": "The phrase 'excellent quality' suggests satisfaction"},
            {"label": "negative", "reasoning": "The mention of 'delayed shipping' indicates frustration"}
        ]
    }
    """
    rationales: List[LabelRationale]


CLASS_REGISTRY = {
    "default_hint": GeneralHintFormat,
    "default_keyword": GeneralKeywordFormat,
    "default_random": GeneralRandomFormat,  # Keep for backwards compatibility
    "default_rationale": GeneralRationaleFormat
}