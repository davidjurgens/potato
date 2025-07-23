from __future__ import annotations
import json
import os
from typing import Any, Dict, OrderedDict
import requests
from tqdm import tqdm
import time
from concurrent.futures import ThreadPoolExecutor
import threading
from builtins import open

from item_state_management import get_item_state_manager


class AIEndpointClient:
    def __init__(self, endpoint: str, api_key: str):
        self.endpoint = endpoint
        self.api_key = api_key

    def get_ai_response(self, message: str) -> str:
        response = requests.post(
            self.endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"message": message},
        )
        return response.json()["response"]


def get_ai_endpoint(config: dict):
    # Check what kind of endpoint the admin was requested

    # Get the AI support option from the config
    ai_support = config["ai_support"]

    # If the AI support is enabled, get the endpoint type
    if ai_support["enabled"]:
        print("ai_support enabled")
        endpoint_type = ai_support["endpoint_type"]
        if endpoint_type == "ollama":

            # Only do the import if we need it prevent unnecessary imports on small systems
            from .ollama_endpoint import OllamaEndpoint

            return OllamaEndpoint(config)
        # Open AI API
        elif endpoint_type == "openai":
            from .openai_endpoint import OpenAIEndpoint

            return OpenAIEndpoint(config)
        
        # Huggingface API
        elif endpoint_type == "huggingface":
            from .huggingface_endpoint import HuggingfaceEndpoint
            return HuggingfaceEndpoint(config)
        
        # Gemini API
        elif endpoint_type == "gemini":
            from .gemini_endpoint import GeminiEndpoint

            return GeminiEndpoint(config)
        else:
            raise ValueError(f"Unknown endpoint type: {endpoint_type}")

    # If the AI support is disabled, return None
    return None


AICACHEMANAGER = None

def init_ai_cache_manager(config: dict):
    global AICACHEMANAGER
    if AICACHEMANAGER is None:
        AICACHEMANAGER = AiCacheManager(config)    

    return AICACHEMANAGER

def get_ai_cache_manager():
    global AICACHEMANAGER
    if AICACHEMANAGER is None:
        raise ValueError("AI state manager has not been initialized")
    return AICACHEMANAGER

class AiCacheManager:
    def __init__(self, config):
        cache_config = config["ai_support"]["cache_config"]
        if not cache_config["enabled"]:
            return
        
        # up to what number do we have in cache
        self.hint_prefetch_to = 0
        self.lenAnnScheme = len(config["annotation_schemes"])
        
        # Memory cache configuration
        self.memory_cache_enabled = cache_config["memory_cache"]["enabled"]
        self.memory_limit = cache_config["memory_cache"]["limit"]
        self.cache = OrderedDict() if self.memory_cache_enabled else None
        
        # Disk cache configuration
        self.disk_cache_enabled = cache_config["disk_cache"]["enabled"]
        self.disk_persistence_path = cache_config["disk_cache"]["path"] if self.disk_cache_enabled else None
        
        # Prefetch configuration
        self.warm_up_page_count = cache_config["prefetch"]["warm_up_page_count"]
        self.prefetch_page_count_on_next = cache_config["prefetch"]["on_next"]
        self.prefetch_page_count_on_prev = cache_config["prefetch"]["on_prev"]
        
        # AI modules to cache
        self.cache_hint = cache_config["ai_to_cache"]["hint"]
        self.cache_keyword = cache_config["ai_to_cache"]["keyword"]
        
        # Threading
        self.in_progress = {}
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=20)
        
        # Initialize cache
        if (self.memory_cache_enabled or self.disk_cache_enabled) and :
            self.load_cache_from_disk()
            self.progress_bar()
            
    
    def progress_bar(self):
        if not (self.cache_hint or self.cache_keyword):
            return
            
        if self.cache_hint and self.cache_keyword:
            desc = f"Preloading hint and keyword for {self.warm_up_page_count} page(s)"
            total = self.warm_up_page_count * self.lenAnnScheme * 2
        elif self.cache_hint:
            desc = f"Preloading hint for {self.warm_up_page_count} page(s)"
            total = self.warm_up_page_count * self.lenAnnScheme
        elif self.cache_keyword:
            desc = f"Preloading keyword for {self.warm_up_page_count} page(s)"
            total = self.warm_up_page_count * self.lenAnnScheme

        progress_bar = tqdm(total=total, desc=desc, unit="item")

        def count_completed():
            return total - len(self.in_progress)
        
        self.start_prefetch(self.warm_up_page_count)

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
        """populates the in-memory cache from a disk file if it exists."""
        if not self.disk_cache_enabled or not self.disk_persistence_path:
            return

        if os.path.exists(self.disk_persistence_path):
            data = self.load_disk_cache_data(self.disk_persistence_path)
            if self.memory_cache_enabled:
                for key_str, value in data.items():
                    try:
                        key = eval(key_str)
                        if isinstance(key, tuple) and len(key) == 3:
                            self.add_to_cache_memory_only(key, value)
                    except:
                        continue
                print(f"Loaded {len(self.cache)} items from disk cache to memory")
            else:
                print(f"Disk cache enabled with {len(data)} items")
        else: 
            try:
                # Create parent directory if it doesn't exist
                os.makedirs(os.path.dirname(self.disk_persistence_path), exist_ok=True)
                with open(self.disk_persistence_path, 'w', encoding='utf-8') as file:
                    json.dump({}, file)
                print(f"Initialized empty disk cache at {self.disk_persistence_path}")
            except Exception as e:
                print(f"Failed to create disk cache: {e}")

    def save_cache_to_disk(self):
        """saves the current in-memory cache to disk as a JSON file using an atomic rename."""
        if not self.disk_cache_enabled or not self.disk_persistence_path:
            return

        try:
            os.makedirs(os.path.dirname(self.disk_persistence_path), exist_ok=True)
            
            # Load existing disk data first
            existing_disk_data = {}
            if os.path.exists(self.disk_persistence_path):
                existing_disk_data = self.load_disk_cache_data(self.disk_persistence_path)
            
            # Merge with current memory cache (memory cache takes precedence for conflicts)
            merged_cache = existing_disk_data.copy()
            
            # Add memory cache items if enabled
            if self.memory_cache_enabled:
                for k, v in self.cache.items():
                    merged_cache[str(k)] = v
            
            temp_path = self.disk_persistence_path + ".tmp"
            with open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(merged_cache, f, indent=2, ensure_ascii=False)
            os.rename(temp_path, self.disk_persistence_path)
        except Exception as e:
            print(f"Error saving cache to disk: {e}")

    def add_to_cache(self, key, value):
        """inserts a key-value into the LRU cache and persists it to disk."""
        with self.lock:
            if self.memory_cache_enabled:
                self.cache.pop(key, None)
                self.cache[key] = value
                while len(self.cache) > self.memory_limit:
                    oldest_key, _ = self.cache.popitem(last=False)
                    print(f"LRU evicted: {oldest_key}")
            
            if self.disk_cache_enabled:
                self.save_cache_to_disk()

    def add_to_cache_memory_only(self, key, value):
        """adds an item to the memory cache without writing to disk (used for loading from disk)."""
        if not self.memory_cache_enabled:
            return
            
        self.cache.pop(key, None)
        self.cache[key] = value
        while len(self.cache) > self.memory_limit:
            oldest_key, _ = self.cache.popitem(last=False)
            print(f"LRU evicted: {oldest_key}")

    def get_from_cache(self, key):
        """Tries to retrieve the item from memory or disk and updates LRU order on memory hit."""
        with self.lock:
            # Try memory cache first if enabled
            if self.memory_cache_enabled and key in self.cache:
                value = self.cache.pop(key)
                self.cache[key] = value
                return value

            # Try disk cache if enabled and memory cache missed
            if self.disk_cache_enabled and self.disk_persistence_path and os.path.exists(self.disk_persistence_path):
                try:
                    disk_data = self.load_disk_cache_data(self.disk_persistence_path)
                    key_str = str(key)
                    if key_str in disk_data:
                        value = disk_data[key_str]
                        if self.memory_cache_enabled:
                            self.add_to_cache_memory_only(key, value)
                            print(f"Loaded from disk to memory: {key}")
                        return value
                except Exception as e:
                    print(f"Error reading from disk: {e}")
            return None

    def get_hint_prefetch_to(self):
        with self.lock:
            return self.hint_prefetch_to

    def increment_hint_prefetch_to(self, num):
        with self.lock:
            self.hint_prefetch_to += num

    def generate_help(self, text: str, annotation_id: int) -> str:
        """sends a prompt to the AI model to generate a helpful hint."""
        from server_utils.config_module import config
        description = config["annotation_schemes"][annotation_id]["description"]
        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        prompt = f"""You are assisting a user with an annotation task. Here is the annotation instruction: {description} \nHere is the annotation task type: {annotation_type}\nHere is the sentence (or item) to annotate: {text}\nBased on the instruction, task type, and the given sentence, generate a short, helpful hint that guides the user on how to approach this annotation.\nAlso, give a short reason of your answer and the relevant part(keyword or text).\nThe hint should not provide the label or answer directly, but should highlight what the user might consider or look for."""
        try:
            response = requests.post(
                'http://localhost:11434/api/generate',
                json={"model": "qwen3:0.6b", "prompt": prompt, "stream": False},
                timeout=120
            )
            response.raise_for_status()
            return response.json()['response']
        except Exception as e:
            print(f"Error generating hint: {e}")
            return f"Error generating hint: {str(e)}"

    def start_prefetch(self, prefechTo):
        """prefetches a fixed number of upcoming items to warm the cache."""
        if not (self.memory_cache_enabled or self.disk_cache_enabled):
            return

        ism = get_item_state_manager()
        
        with self.lock:
            if self.hint_prefetch_to == len(ism.items()):
                print("Already fetched all")
                return None
            
            start_idx = self.hint_prefetch_to
            end_idx = min(start_idx + prefechTo, len(ism.items()))
            for i in range(start_idx, end_idx):
                item = ism.items()[i]
                text = item.get_data()["text"]
                item_id = item.get_data()["id"]
                
                keys = []
                if self.cache_hint:
                    keys.extend([(item_id, annotation_id, "hint") for annotation_id in range(self.lenAnnScheme)])
                if self.cache_keyword:
                    keys.extend([(item_id, annotation_id, "keyword") for annotation_id in range(self.lenAnnScheme)])
                
                self.prefetch(text, keys)
                self.hint_prefetch_to += 1

    def prefetch(self, text: str, keys: list):
        """checks if keys are already cached and asynchronously generates missing ones"""
        with self.lock:
            for key in keys:
                if self.get_from_cache(key) is None and key not in self.in_progress:
                    instance_id, annotation_id, help_type = key
                    
                    if (help_type == "hint" and self.cache_hint) or (help_type == "keyword" and self.cache_keyword):
                        future = self.executor.submit(self.compute_help, text, annotation_id, help_type)
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

    def get_ai_help(self, instance_id: int, annotation_id: int, text: str, help_type: str) -> str:
        """retrieves AI help either from cache, waits for in-progress, or computes on-demand."""
        key = (instance_id, annotation_id, help_type)
        
        # Check if caching is enabled for this help type
        if (help_type == "hint" and not self.cache_hint) or (help_type == "keyword" and not self.cache_keyword):
            return self.compute_help(text, annotation_id, help_type)
            
        # Try to get from cache if caching is enabled
        if self.memory_cache_enabled or self.disk_cache_enabled:
            cached_value = self.get_from_cache(key)
            if cached_value is not None:
                print(f"Cache hit for key: {key}")
                return cached_value

        with self.lock:
            if key in self.in_progress:
                future = self.in_progress[key]
            else:
                future = self.executor.submit(self.compute_help, text, annotation_id, help_type)
                self.in_progress[key] = future

        try:
            result = future.result(timeout=60)
            if self.memory_cache_enabled or self.disk_cache_enabled:
                self.add_to_cache(key, result)
            with self.lock:
                self.in_progress.pop(key, None)
            return result
        except Exception as e:
            print(f"Error computing help for key {key}: {e}")
            with self.lock:
                self.in_progress.pop(key, None)
            return f"Error: {str(e)}"

    def compute_help(self, text: str, annotation_id: int, help_type: str) -> str:
        """dispatches the appropriate generation method for a help type."""
        if help_type == "hint":
            return self.generate_help(text, annotation_id)
        elif help_type == "keyword":
            return f"Keyword for annotation {annotation_id}"
        elif help_type == "highlight":
            return f"Highlight for annotation {annotation_id}"
        elif help_type == "ai_answer":
            return f"AI answer for annotation {annotation_id} with text: {text}"
        else:
            raise ValueError(f"Unknown help_type: {help_type}")

    def get_cache_stats(self) -> Dict[str, int]:
        """returns statistics on in-memory, disk, and in-progress cache entries."""
        with self.lock:
            memory_count = len(self.cache) if self.memory_cache_enabled else 0
            
            disk_count = 0
            if self.disk_cache_enabled and self.disk_persistence_path and os.path.exists(self.disk_persistence_path):
                try:
                    disk_data = self.load_disk_cache_data(self.disk_persistence_path)
                    disk_count = len(disk_data)
                except:
                    pass
                    
            return {
                'memory_cache_enabled': self.memory_cache_enabled,
                'disk_cache_enabled': self.disk_cache_enabled,
                'cached_items_memory': memory_count,
                'cached_items_disk': disk_count,
                'in_progress_items': len(self.in_progress),
                'prefetch_position': self.hint_prefetch_to
            }

    def clear_cache(self):
        """clears memory and disk cache and cancels any ongoing generation."""
        with self.lock:
            if self.memory_cache_enabled:
                self.cache.clear()
                
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

    def force_save_cache(self):
        """forcibly writes the current cache to disk."""
        if self.disk_cache_enabled:
            self.save_cache_to_disk()

    def __del__(self):
        """ensures cache is saved when the object is garbage collected"""
        try:
            self.force_save_cache()
        except:
            pass