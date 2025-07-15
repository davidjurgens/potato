from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from server_utils.config_module import init_config, config
import requests
import threading
from typing import Dict, Tuple, Any, Optional

from item_state_management import get_item_state_manager

# Singleton instance of the ai state 
AISTATE = None

def init_ai_state(config: dict) -> AiState:
    '''
    Returns a empty AISTATE for tracking all the ai help either in cache or in progress
    '''
    global AISTATE

    if AISTATE is None:
        AISTATE = AiState()
        AISTATE.start_prefetch(config)

    return AISTATE


def get_ai_state() -> AiState:
    '''
    Returns the AISTATE for tracking all the ai help either in cache or in progress
    '''
    global AISTATE

    if AISTATE is None:
        raise ValueError('AI state manager has not been initialized')
    return AISTATE

class AiState:
    def __init__(self):
        self.hint_prefetch_to = 0
        
        # Cache for completed results
        self.cache = {}  # (instance_id, annotation_id, help_type) -> str
        
        # Track in-progress requests
        self.in_progress = {}  # (instance_id, annotation_id, help_type) -> Future
        
        # Lock for thread-safe operations
        self.lock = threading.RLock()
        
        # Thread pool for async operations
        self.executor = ThreadPoolExecutor(max_workers=20)
    
    def get_hint_prefetch_to(self):
        with self.lock:
            return self.hint_prefetch_to
    
    def increment_hint_prefetch_to(self, num):
        with self.lock:
            self.hint_prefetch_to += num
    
    def generate_hint(self, text: str, annotation_id: int) -> str:
        """
        Returns the AI hints for the given instance.
        """
        print(f"Generating hint for annotation_id: {annotation_id}")
        description = config["annotation_schemes"][annotation_id]["description"]
        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        
        prompt = f'''You are assisting a user with an annotation task. Here is the annotation instruction: {description} 
        Here is the annotation task type: {annotation_type}
        Here is the sentence (or item) to annotate: {text}
        Based on the instruction, task type, and the given sentence, generate a short, helpful hint that guides the user on how to approach this annotation. 
        Also, give a short reason of your answer and the relevant part(keyword or text).
        The hint should not provide the label or answer directly, but should highlight what the user might consider or look for.'''

        try:
            response = requests.post(
                'http://localhost:11434/api/generate',
                json={
                    'model': 'qwen3:0.6b',
                    'prompt': prompt,
                    'stream': False
                },
                timeout=30  # Add timeout to prevent hanging
            )
            response.raise_for_status()  # Raise exception for bad status codes
            return response.json()['response']
        except Exception as e:
            print(f"Error generating hint: {e}")
            return f"Error generating hint: {str(e)}"
    
    def start_prefetch(self, config): 
        """
        Start prefetching hints for upcoming items
        """
        print("Starting prefetch...")
        self.get_cache_stats()
        ism = get_item_state_manager()
        
        with self.lock:
            start_idx = self.hint_prefetch_to
            end_idx = min(start_idx + 3, len(ism.items()))
            
            for i in range(start_idx, end_idx):
                item = ism.items()[i]
                text = item.get_data()["text"]
                item_id = item.get_data()["id"]
                
                # Create prefetch keys for all annotation schemes
                keys = []
                for annotation_id, _ in enumerate(config["annotation_schemes"]):
                    keys.append((item_id, annotation_id, "hint"))
                
                self.prefetch(text, keys)
                self.hint_prefetch_to += 1
                
        print("Prefetch completed")

    def prefetch(self, text: str, keys: list):
        """
        Prefetch AI help for given keys if not already cached or in progress
        """
        with self.lock:
            for key in keys:
                if key not in self.cache and key not in self.in_progress:
                    instance_id, annotation_id, help_type = key
                    
                    if help_type == "hint":
                        print(f"Prefetching hint for key: {key}")
                        future = self.executor.submit(self.generate_hint, text, annotation_id)
                        self.in_progress[key] = future
                        
                        # Add callback to move completed results to cache
                        def callback(fut, cache_key=key):
                            with self.lock:
                                try:
                                    result = fut.result()
                                    self.cache[cache_key] = result
                                    if cache_key in self.in_progress:
                                        del self.in_progress[cache_key]
                                    print(f"Prefetch completed for key: {cache_key}")
                                except Exception as e:
                                    print(f"Prefetch failed for key {cache_key}: {e}")
                                    # Remove from in_progress even on failure
                                    if cache_key in self.in_progress:
                                        del self.in_progress[cache_key]
                        
                        future.add_done_callback(callback)

    def get_ai_help(self, instance_id: int, annotation_id: int, text: str, help_type: str) -> str:
        """
        Get AI help with improved caching and duplicate prevention
        """
        key = (instance_id, annotation_id, help_type)
        
        with self.lock:
            # Check cache first
            if key in self.cache:
                print(f"Cache hit for key: {key}")
                return self.cache[key]
            
            # Check if currently in progress
            if key in self.in_progress:
                print(f"Waiting for in-progress request: {key}")
                future = self.in_progress[key]
        
        # Wait for in-progress request outside the lock to avoid deadlock
        if key in self.in_progress:
            try:
                result = future.result(timeout=30)
                with self.lock:
                    self.cache[key] = result
                    if key in self.in_progress:
                        del self.in_progress[key]
                return result
            except Exception as e:
                print(f"Error waiting for in-progress request {key}: {e}")
                with self.lock:
                    if key in self.in_progress:
                        del self.in_progress[key]
                # Fall through to immediate computation
        
        # Not in cache or in progress - compute immediately
        print(f"Computing immediately for key: {key}")
        with self.lock:
            # Double-check it wasn't added while we were waiting
            if key in self.cache:
                return self.cache[key]
            
            # Mark as in progress to prevent duplicates
            future = self.executor.submit(self.compute_help, text, annotation_id, help_type)
            self.in_progress[key] = future
        
        try:
            result = future.result(timeout=30)
            with self.lock:
                self.cache[key] = result
                if key in self.in_progress:
                    del self.in_progress[key]
            return result
        except Exception as e:
            print(f"Error computing help for key {key}: {e}")
            with self.lock:
                if key in self.in_progress:
                    del self.in_progress[key]
            return f"Error: {str(e)}"
    
    def compute_help(self, text: str, annotation_id: int, help_type: str) -> str:
        """
        Internal method to compute different types of AI help
        """
        if help_type == "hint":
            return self.generate_hint(text, annotation_id)
        elif help_type == "highlight":
            return self.generate_highlight(annotation_id)
        elif help_type == "ai_answer":
            return self.generate_ai_answer(annotation_id, text)
        else:
            raise ValueError(f"Unknown help_type: {help_type}")
    
    def generate_highlight(self, annotation_id: int) -> str:
        """Placeholder for highlight generation"""
        return f"Highlight for annotation {annotation_id}"
    
    def generate_ai_answer(self, annotation_id: int, text: str) -> str:
        """Placeholder for AI answer generation"""
        return f"AI answer for annotation {annotation_id} with text: {text}"
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get statistics about cache usage"""
        with self.lock:
            return {
                'cached_items': len(self.cache),
                'in_progress_items': len(self.in_progress),
                'prefetch_position': self.hint_prefetch_to
            }
    
    def clear_cache(self):
        """Clear the cache and cancel in-progress requests"""
        with self.lock:
            self.cache.clear()
            # Cancel all in-progress futures
            for future in self.in_progress.values():
                future.cancel()
            self.in_progress.clear()
            print("Cache cleared")