from typing import Optional, Type, Union
from pydantic import BaseModel

class GeneralKeywordList(BaseModel):
    word_phrase: str
    reasoning: str

class GeneralHintFormat(BaseModel):
    hint: str
    suggestive_choice: Union[str, int]

class GeneralKeywordFormat(BaseModel):
    keywords: list[GeneralKeywordList]

class GeneralRandomFormat(BaseModel):
    random: str

CLASS_REGISTRY = {
    "default_hint": GeneralHintFormat,
    "default_keyword": GeneralKeywordFormat,
    "default_random": GeneralRandomFormat
}