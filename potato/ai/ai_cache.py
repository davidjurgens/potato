from __future__ import annotations
import json
import os
from typing import Any, Dict, Union
import requests
from tqdm import tqdm
import time
from concurrent.futures import ThreadPoolExecutor
import threading
from builtins import open
from server_utils.config_module import config

from item_state_management import get_item_state_manager
from ai.ai_endpoint import AIEndpointFactory, Annotation_Type, AnnotationInput
from ai.ollama_endpoint import OllamaEndpoint
from ai.openrouter_endpoint import OpenRouterEndpoint
from ai.ai_prompt import ModelManager, get_ai_prompt 


AICACHEMANAGER = None

def init_ai_cache_manager():
    global AICACHEMANAGER
    if AICACHEMANAGER is None:
        AICACHEMANAGER = AiCacheManager()    

    return AICACHEMANAGER

def get_ai_cache_manager():
    global AICACHEMANAGER
    if AICACHEMANAGER is None:
        raise ValueError("AI state manager has not been initialized")
    return AICACHEMANAGER

class AiCacheManager:
    def __init__(self):
        ai_support = config["ai_support"]
        if not ai_support["enabled"]:
            return
        cache_config = ai_support["cache_config"]
        ai_config = ai_support["ai_config"]
        include = ai_config.get("include")
        special_include = include.get("special_include", None)
        self.include_all = include["all"]
        self.special_includes = {}

        self.model_manager = ModelManager()
        self.model_manager.load_models_module()
        
        if special_include:
            for page_key, page_value in special_include.items():
                # Convert string keys to integers for easier lookup
                page_index = int(page_key)
                self.special_includes[page_index] = {}
                for annotation_id, annotation_types in page_value.items():
                    annotation_id_int = int(annotation_id)
                    self.special_includes[page_index][annotation_id_int] = annotation_types

        # Disk cache configuration
        self.disk_cache_enabled = cache_config["disk_cache"]["enabled"]

        # Disk cache configuration
        if self.disk_cache_enabled and not cache_config["disk_cache"]["path"]:
            raise Exception("You have enable disk cache, but you did not specific the path!")
        self.disk_persistence_path = cache_config["disk_cache"]["path"] 
        
        # Prefetch configuration
        self.warm_up_page_count = cache_config["prefetch"]["warm_up_page_count"]
        self.prefetch_page_count_on_next = cache_config["prefetch"]["on_next"]
        self.prefetch_page_count_on_prev = cache_config["prefetch"]["on_prev"]
        
        # Threading
        self.in_progress = {}
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=20)
        
        AIEndpointFactory.register_endpoint("ollama", OllamaEndpoint)
        AIEndpointFactory.register_endpoint("open_router", OpenRouterEndpoint)

        self.ai_endpoint = AIEndpointFactory.create_endpoint(config)

        annotation_scheme = config.get("annotation_schemes")
        self.annotations = []
        for scheme in annotation_scheme:
            self.annotations.append(scheme)

        # Initialize cache
        if self.disk_cache_enabled:
            self.load_cache_from_disk()
            self.start_warmup()
    
    def start_warmup(self):
        self.start_prefetch(0, self.warm_up_page_count)

        total = len(self.in_progress)
        desc = "Preloading the AI"

        progress_bar = tqdm(total=total, desc=desc, unit="item")

        def count_completed():
            return total - len(self.in_progress)
        
        prev_done = 0
        while self.in_progress:
            current_done = count_completed()
            progress_bar.update(current_done - prev_done)
            prev_done = current_done
            time.sleep(0.2)

        final_done = count_completed()
        if final_done > prev_done:
            progress_bar.update(final_done - prev_done)

        progress_bar.close()

    def load_disk_cache_data(self, file_path: str) -> Dict[str, Any]:
        """loads the cache JSON from disk and returns a dictionary of stringified keys to values."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading disk cache: {e}")
            return {}

    def load_cache_from_disk(self):
        """Initializes disk cache file if it doesn't exist."""
        if not self.disk_cache_enabled or not self.disk_persistence_path:
            return

        if os.path.exists(self.disk_persistence_path):
            data = self.load_disk_cache_data(self.disk_persistence_path)
            print(f"Disk cache initialized with {len(data)} items")
        else: 
            try:
                # Create parent directory if it doesn't exist
                os.makedirs(os.path.dirname(self.disk_persistence_path), exist_ok=True)
                with open(self.disk_persistence_path, 'w', encoding='utf-8') as file:
                    json.dump({}, file)
                print(f"Initialized empty disk cache at {self.disk_persistence_path}")
            except Exception as e:
                print(f"Failed to create disk cache: {e}")

    def save_cache_to_disk(self, key, value):
        """saves a single key-value pair to disk cache using atomic write."""
        if not self.disk_cache_enabled or not self.disk_persistence_path:
            return

        try:
            os.makedirs(os.path.dirname(self.disk_persistence_path), exist_ok=True)
            
            # Load existing disk data first
            existing_disk_data = {}
            if os.path.exists(self.disk_persistence_path):
                existing_disk_data = self.load_disk_cache_data(self.disk_persistence_path)
            
            # Add the new key-value pair
            existing_disk_data[str(key)] = value
            
            temp_path = self.disk_persistence_path + ".tmp"
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(existing_disk_data, f, indent=2, ensure_ascii=False)
            os.rename(temp_path, self.disk_persistence_path)
        except Exception as e:
            print(f"Error saving cache to disk: {e}")

    def add_to_cache(self, key, value):
        """inserts a key-value into the disk cache."""
        with self.lock:
            if self.disk_cache_enabled:
                self.save_cache_to_disk(key, value)

    def get_from_cache(self, key):
        """Tries to retrieve the item from disk cache."""
        with self.lock:
            # Try disk cache
            if self.disk_cache_enabled and self.disk_persistence_path and os.path.exists(self.disk_persistence_path):
                try:
                    disk_data = self.load_disk_cache_data(self.disk_persistence_path)
                    key_str = str(key)
                    if key_str in disk_data:
                        return disk_data[key_str]
                except Exception as e:
                    print(f"Error reading from disk: {e}")
            return None
    
    def generate_likert(self, instance_id: int, annotation_id: int, ai_assistant: str) -> str:
        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        description = config["annotation_schemes"][annotation_id]["description"]
        text = get_item_state_manager().items()[instance_id].get_data()["text"]
        min_label = config["annotation_schemes"][annotation_id]["min_label"]
        max_label = config["annotation_schemes"][annotation_id]["max_label"]
        size = config["annotation_schemes"][annotation_id]["size"]

        data = AnnotationInput(
            ai_assistant=ai_assistant,
            annotation_type=annotation_type,
            text=text,
            description=description,
            min_label=min_label,
            max_label=max_label,
            size=size
        )
        ai_prompt = get_ai_prompt()
        output_format = self.model_manager.get_model_class_by_name(ai_prompt[annotation_type].get(ai_assistant).get("output_format"))
        res = self.ai_endpoint.get_ai(data, output_format)
        return res
    
    def generate_multiselect(self, instance_id: int, annotation_id: int, ai_assistant: str) -> str:
        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        description = config["annotation_schemes"][annotation_id]["description"]
        labels = config["annotation_schemes"][annotation_id]["labels"]
        text = get_item_state_manager().items()[instance_id].get_data()["text"]

        data = AnnotationInput(
            ai_assistant=ai_assistant,
            annotation_type=annotation_type,
            text=text,
            description=description,
            labels=labels
        )
        ai_prompt = get_ai_prompt();
        output_format = self.model_manager.get_model_class_by_name(ai_prompt[annotation_type].get(ai_assistant).get("output_format"))
        res = self.ai_endpoint.get_ai(data, output_format)
        return res
    
    def generate_radio(self, instance_id: int, annotation_id: int, ai_assistant: str) -> str:
        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        description = config["annotation_schemes"][annotation_id]["description"]
        text = get_item_state_manager().items()[instance_id].get_text()
        labels = config["annotation_schemes"][annotation_id]["labels"]
        
        data = AnnotationInput(
            ai_assistant=ai_assistant,
            annotation_type=annotation_type,
            text=text,
            description=description, 
            labels=labels
        )
        ai_prompt = get_ai_prompt();
        output_format = self.model_manager.get_model_class_by_name(ai_prompt[annotation_type].get(ai_assistant).get("output_format"))
        res = self.ai_endpoint.get_ai(data, output_format)
        return res
    
    def generate_number(self, instance_id: int, annotation_id: int, ai_assistant: str) -> str:
        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        description = config["annotation_schemes"][annotation_id]["description"]
        text = get_item_state_manager().items()[instance_id].get_data()["text"]

        data = AnnotationInput(
            ai_assistant=ai_assistant,
            annotation_type=annotation_type,
            text=text,
            description=description,
        )
        ai_prompt = get_ai_prompt();
        output_format = self.model_manager.get_model_class_by_name(ai_prompt[annotation_type].get(ai_assistant).get("output_format"))
        res = self.ai_endpoint.get_ai(data, output_format)
        return res
    
    def generate_select(self, instance_id: int, annotation_id: int, ai_assistant: str) -> str:
        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        description = config["annotation_schemes"][annotation_id]["description"]
        labels = config["annotation_schemes"][annotation_id]["labels"]
        text = get_item_state_manager().items()[instance_id].get_data()["text"]


        data = AnnotationInput(
            ai_assistant=ai_assistant,
            annotation_type=annotation_type,
            text=text,
            description=description,
            labels=labels
        )
        ai_prompt = get_ai_prompt();
        output_format = self.model_manager.get_model_class_by_name(ai_prompt[annotation_type].get(ai_assistant).get("output_format"))
        res = self.ai_endpoint.get_ai(data, output_format)
        return res
    
    def generate_slider(self, instance_id: int, annotation_id: int, ai_assistant: str) -> str:
        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        description = config["annotation_schemes"][annotation_id]["description"]
        min_value = config["annotation_schemes"][annotation_id]["min_value"]
        max_value = config["annotation_schemes"][annotation_id]["max_value"]
        step = config["annotation_schemes"][annotation_id]["step"]
        text = get_item_state_manager().items()[instance_id].get_data()["text"]

        data = AnnotationInput(
            ai_assistant=ai_assistant,
            annotation_type=annotation_type,
            text=text,
            description=description,
            min_value=min_value,
            max_value=max_value,
            step=step
        )

        ai_prompt = get_ai_prompt();
        output_format = self.model_manager.get_model_class_by_name(ai_prompt[annotation_type].get(ai_assistant).get("output_format"))
        res = self.ai_endpoint.get_ai(data, output_format)
        return res
    
    def generate_span(self, instance_id: int, annotation_id: int, ai_assistant: str) -> str:
        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        description = config["annotation_schemes"][annotation_id]["description"]
        labels = config["annotation_schemes"][annotation_id]["labels"]
        text = get_item_state_manager().items()[instance_id].get_data()["text"]

        data = AnnotationInput(
            ai_assistant=ai_assistant,
            annotation_type=annotation_type,
            text=text,
            description=description,
            labels=labels
        )
        ai_prompt = get_ai_prompt();
        output_format = self.model_manager.get_model_class_by_name(ai_prompt[annotation_type].get(ai_assistant).get("output_format"))
        res = self.ai_endpoint.get_ai(data, output_format)
        return res
    
    def generate_textbox(self, instance_id: int, annotation_id: int, ai_assistant: str) -> str:
        print("generate_textbox", annotation_id)
        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        description = config["annotation_schemes"][annotation_id]["description"]
        text = get_item_state_manager().items()[instance_id].get_data()["text"]

        data = AnnotationInput(
            ai_assistant=ai_assistant,
            annotation_type=annotation_type,
            text=text,
            description=description,
        )
        ai_prompt = get_ai_prompt();
        output_format = self.model_manager.get_model_class_by_name(ai_prompt[annotation_type].get(ai_assistant).get("output_format"))
        res = self.ai_endpoint.get_ai(data, output_format)
        return res
    
    def get_include_all(self): 
        return self.include_all 
    
    def get_special_include(self, page_number_int, annotation_id_int):
        print("get_special_include", self.special_includes, page_number_int, annotation_id_int)
        if not self.special_includes.get(page_number_int):
            return None
        elif not self.special_includes.get(page_number_int).get(annotation_id_int):
            return None
        return self.special_includes.get(page_number_int).get(annotation_id_int)

    def start_prefetch(self, page_id, prefetch_amount):
        """Prefetches a fixed number of upcoming items to warm the cache."""
        if not config["ai_support"]["enabled"] or not self.disk_cache_enabled:
            return
        
        ism = get_item_state_manager()
        with self.lock:
            # Calculate range bounds
            if prefetch_amount >= 0:
                start_idx = page_id
                end_idx = min(start_idx + prefetch_amount, len(ism.items()))
            else:
                start_idx = max(page_id - prefetch_amount, 0)
                end_idx = page_id
            
            print("start_idx, end_idx",start_idx, end_idx)
            keys = []
            
            for i in range(start_idx, end_idx):
                # Check if this page should be included
                if not self.should_include_page(i):
                    continue
                
                # Process each annotation scheme for this page
                for annotation_id, scheme in enumerate(config["annotation_schemes"]):
                    if not self.should_include_scheme(i, annotation_id):
                        continue
                    
                    annotation_type = scheme["annotation_type"]
                    ai_prompt = get_ai_prompt()
                    
                
                    if not ai_prompt[annotation_type]:
                        raise Exception(f"{annotation_type} is not defined in ai_prompt")
                    
                    # Generate keys for this page/scheme combination
                    scheme_keys = self.get_keys_for_scheme(i, annotation_type, annotation_id, ai_prompt)
                    keys.extend(scheme_keys)
            
            if keys:
                self.prefetch(keys)

    def should_include_page(self, page_index):
        """Determine if a page should be included based on include_all and special_includes."""
        if self.include_all:
            return True
        return page_index in self.special_includes

    def should_include_scheme(self, page_index, annotation_id):
        """Determine if a scheme should be included for a given page."""
        if self.include_all:
            return True
        
        # Check if page is in special_includes and scheme is specified
        if page_index in self.special_includes:
            page_includes = self.special_includes[page_index]
            # Handle both list and dict formats for page_includes
            if isinstance(page_includes, dict):
                return annotation_id in page_includes
            elif isinstance(page_includes, list):
                return annotation_id in page_includes
        
        return False

    def get_keys_for_scheme(self, page_index, annotation_type, annotation_id, ai_prompt):
        """Get all keys for a specific page combination."""
        keys = []
        
        # Check if this page/annotation has specific overrides in special_includes
        if (page_index in self.special_includes and 
            isinstance(self.special_includes[page_index], dict) and
            annotation_id in self.special_includes[page_index]):
            
            # Use special_includes (overrides include_all setting)
            specified_keys = self.special_includes[page_index][annotation_id]
            for key in specified_keys:
                keys.append((page_index, annotation_id, key))
        elif self.include_all:
            # No specific override, so include all available keys for this annotation type
            for key in ai_prompt[annotation_type]:
                keys.append((page_index, annotation_id, key))
        # If include_all is False and no special_include entry, return empty keys
        
        return keys
    
    def prefetch(self, keys: list):
        """checks if keys are already cached and asynchronously generates missing ones"""
        with self.lock:
            for key in keys:
                if self.get_from_cache(key) is None and key not in self.in_progress:
                    # i, annotation_id, annotation_type, ai_prompt
                    instance_id, annotation_id, ai_assistant = key

                    future = self.executor.submit(self.compute_help, instance_id, annotation_id, ai_assistant)
                    self.in_progress[key] = future
                    def callback(fut, cache_key=key):
                            with self.lock:
                                try:
                                    result = fut.result()
                                    self.add_to_cache(cache_key, result)
                                except Exception as e:
                                    print(f"Prefetch failed for key {cache_key}: {e}")
                                self.in_progress.pop(cache_key, None)

                    future.add_done_callback(callback)

    def get_ai_help(self, instance_id: int, annotation_id: int, ai_assistant: str) -> str:
        """retrieves AI help either from cache, waits for in-progress, or computes on-demand."""
        key = (instance_id, annotation_id, ai_assistant)
        
        print("1r23iju0f93ijno3hfg091h3")
        # Check if caching is enabled for this help type
        if not self.disk_cache_enabled:
            return self.compute_help(instance_id, annotation_id, ai_assistant)

        # Try to get from cache if caching is enabled
        cached_value = self.get_from_cache(key)
        if cached_value is not None:
            print(f"Cache hit for key: {key}")
            return cached_value

        with self.lock:
            if key in self.in_progress:
                future = self.in_progress[key]
            else:
                future = self.executor.submit(self.compute_help, instance_id, annotation_id, ai_assistant)
                self.in_progress[key] = future
        try:
            result = future.result(timeout=60)
            if self.disk_cache_enabled:
                self.add_to_cache(key, result)
            with self.lock:
                self.in_progress.pop(key, None)
            return result
        except Exception as e:
            print(f"Error computing help for key {key}: {e}")
            with self.lock:
                self.in_progress.pop(key, None)
            return f"Error: {str(e)}"

    def compute_help(self, instance_id: int, annotation_id: int, ai_assistant: str):
        annotation_type_str = config["annotation_schemes"][annotation_id]["annotation_type"]
        annotation_type = Annotation_Type(annotation_type_str)
        match annotation_type:
            case Annotation_Type.LIKERT:
                return self.generate_likert(instance_id, annotation_id, ai_assistant)
            case Annotation_Type.RADIO:
                return self.generate_radio(instance_id, annotation_id, ai_assistant)
            case Annotation_Type.MULTISELECT:
                return self.generate_multiselect(instance_id,annotation_id, ai_assistant)
            case Annotation_Type.NUMBER:
                return self.generate_number(instance_id,annotation_id, ai_assistant)
            case Annotation_Type.SELECT:
                return self.generate_select(instance_id,annotation_id, ai_assistant)
            case Annotation_Type.SLIDER:
                return self.generate_slider(instance_id, annotation_id, ai_assistant)
            case Annotation_Type.SPAN:
                return self.generate_span(instance_id, annotation_id, ai_assistant)
            case Annotation_Type.TEXTBOX:
                return self.generate_textbox(instance_id, annotation_id, ai_assistant)
            case _:
                raise ValueError(f"Unknown annotation type: {annotation_type}")

    def get_cache_stats(self) -> Dict[str, int]:
        """returns statistics on disk cache and in-progress cache entries."""
        with self.lock:
            disk_count = 0
            if self.disk_cache_enabled and self.disk_persistence_path and os.path.exists(self.disk_persistence_path):
                try:
                    disk_data = self.load_disk_cache_data(self.disk_persistence_path)
                    disk_count = len(disk_data)
                except:
                    pass
                    
            return {
                'disk_cache_enabled': self.disk_cache_enabled,
                'cached_items_disk': disk_count,
                'in_progress_items': len(self.in_progress)
            }

    def clear_cache(self):
        """clears disk cache and cancels any ongoing generation."""
        with self.lock:
            for future in self.in_progress.values():
                future.cancel()
            self.in_progress.clear()
            
            if self.disk_cache_enabled and self.disk_persistence_path and os.path.exists(self.disk_persistence_path):
                try:
                    os.remove(self.disk_persistence_path)
                    print("Disk cache file removed")
                except Exception as e:
                    print(f"Error removing disk cache file: {e}")
            print("Cache cleared")



