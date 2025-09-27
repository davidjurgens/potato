import importlib
import json
import os
from pathlib import Path
from typing import Optional, Type
from pydantic import BaseModel
from server_utils.config_module import config
ANNOTATIONS = None

class ModelManager:
    def __init__(self):
        self.models_module = None
    
    def load_models_module(self):
        """Load the models module if not already loaded"""
        if self.models_module is None:
            # absolute pathing
            module_path = config.get("ai_support").get("model_module")
            if module_path:
                file_path = Path(module_path)
                if not file_path.exists():
                    raise FileNotFoundError(f"Model module file not found: {file_path}")
                module_name = file_path.stem  
                
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                self.models_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(self.models_module)

            else:
                default_path = Path(__file__).resolve().parent / "prompt" / "models_module.py"
                
                if not default_path.exists():
                    raise FileNotFoundError(f"Default model module file not found: {default_path}")
                
                module_name = default_path.stem  
                
                spec = importlib.util.spec_from_file_location(module_name, default_path)
                self.models_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(self.models_module)

        return self.models_module
    
    def get_model_class_by_name(self, name: str) -> Optional[Type[BaseModel]]:
        """
        Return a Pydantic model class based on the provided name.
        """
        print("namnamenamee", name)
        models_module = self.load_models_module()  
        return models_module.CLASS_REGISTRY.get(name)


def init_ai_prompt(config):
    global ANNOTATIONS
    if not config["ai_support"]["enabled"]:
        return
    try:
        annotation_paths = config.get("ai_support", {}).get("annotation_path")
        
        ANNOTATIONS = {}
        
        if annotation_paths:
            # Load files from specified paths
            for key, path in annotation_paths.items():
                if path and os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        ANNOTATIONS[key] = json.load(f)
                else:
                    raise Exception(f"File path for annotations does not exist: {path}")
        else:
            # Load all JSON files from default directory (parent/prompt)
            default_path = Path(__file__).resolve().parent / "prompt"
            
            if default_path.exists() and default_path.is_dir():
                # Find all JSON files in the directory
                json_files = list(default_path.glob("*.json"))
                
                if not json_files:
                    raise Exception(f"No JSON files found in default directory: {default_path}")
                
                # Load each JSON file, using filename (without extension) as key
                for file_path in json_files:
                    key = file_path.stem 
                    with open(file_path, "r", encoding="utf-8") as f:
                        ANNOTATIONS[key] = json.load(f)
            else:
                raise Exception(f"Default annotation directory does not exist: {default_path}")

    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in annotation file: {e}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error loading AI prompt: {e}")

def get_ai_prompt():
    global ANNOTATIONS
    print("ANNOTATIONANNOTATIONSANNOTATIONSANNOTATIONSS", ANNOTATIONS)
    return ANNOTATIONS