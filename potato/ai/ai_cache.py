from __future__ import annotations
import json
import logging
import os
from typing import Any, Dict, Union
import requests
from tqdm import tqdm
import time
from concurrent.futures import ThreadPoolExecutor
import threading
from builtins import open
from potato.server_utils.config_module import config

logger = logging.getLogger(__name__)

from potato.item_state_management import get_item_state_manager
from potato.ai.ai_endpoint import (
    AIEndpointFactory,
    Annotation_Type,
    AnnotationInput,
    ImageData,
    VisualAnnotationInput,
    ModelCapabilities,
)
from potato.ai.ollama_endpoint import OllamaEndpoint
from potato.ai.openrouter_endpoint import OpenRouterEndpoint
from potato.ai.ai_prompt import ModelManager, get_ai_prompt 


AICACHEMANAGER = None

def _get_instance_text(instance_id: int) -> str:
    """Get the text content from an instance using the configured text_key."""
    item = get_item_state_manager().items()[instance_id]
    item_data = item.get_data()

    # Get the configured text_key
    text_key = config.get("item_properties", {}).get("text_key", "text")

    # Try the configured text_key first
    if text_key in item_data:
        return item_data[text_key]

    # Fall back to common keys
    for key in ['text', 'content', 'message']:
        if key in item_data:
            return item_data[key]

    # Last resort: return any string value
    for value in item_data.values():
        if isinstance(value, str):
            return value

    return str(item_data)

def _is_image_url(text: str) -> bool:
    """Check if text appears to be an image URL."""
    if not isinstance(text, str):
        return False
    text_lower = text.lower()
    # Check for image extensions
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp']
    if any(ext in text_lower for ext in image_extensions):
        return True
    # Check for common image hosting services
    image_hosts = ['unsplash.com', 'imgur.com', 'flickr.com', 'picsum.photos']
    if any(host in text_lower for host in image_hosts):
        return True
    # Check if URL starts with http and might be an image
    if text_lower.startswith(('http://', 'https://')) and 'image' in text_lower:
        return True
    return False

def _get_image_data_from_url(url: str) -> ImageData:
    """Download image from URL and return as ImageData."""
    import base64
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        b64_data = base64.b64encode(response.content).decode('utf-8')
        # Determine mime type from content-type header or URL
        content_type = response.headers.get('content-type', 'image/jpeg')
        return ImageData(source='base64', data=b64_data, mime_type=content_type)
    except Exception as e:
        logger.error(f"Failed to download image from {url}: {e}")
        return None

def init_ai_cache_manager():
    global AICACHEMANAGER
    if AICACHEMANAGER is None:
        AICACHEMANAGER = AiCacheManager()    

    return AICACHEMANAGER

def get_ai_cache_manager():
    """Get the AI cache manager instance. Returns None if not initialized (AI support disabled)."""
    global AICACHEMANAGER
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

        # Register visual AI endpoints
        try:
            from potato.ai.yolo_endpoint import YOLOEndpoint
            AIEndpointFactory.register_endpoint("yolo", YOLOEndpoint)
        except ImportError:
            logger.debug("YOLO endpoint not available (ultralytics not installed)")

        try:
            from potato.ai.ollama_vision_endpoint import OllamaVisionEndpoint
            AIEndpointFactory.register_endpoint("ollama_vision", OllamaVisionEndpoint)
        except ImportError:
            logger.debug("Ollama Vision endpoint not available")

        try:
            from potato.ai.openai_vision_endpoint import OpenAIVisionEndpoint
            AIEndpointFactory.register_endpoint("openai_vision", OpenAIVisionEndpoint)
        except ImportError:
            logger.debug("OpenAI Vision endpoint not available")

        try:
            from potato.ai.anthropic_vision_endpoint import AnthropicVisionEndpoint
            AIEndpointFactory.register_endpoint("anthropic_vision", AnthropicVisionEndpoint)
        except ImportError:
            logger.debug("Anthropic Vision endpoint not available")

        self.ai_endpoint = AIEndpointFactory.create_endpoint(config)

        # Create visual endpoint if different from main endpoint
        self.visual_endpoint = None
        visual_endpoint_type = config.get("ai_support", {}).get("visual_endpoint_type")
        if visual_endpoint_type and visual_endpoint_type != config.get("ai_support", {}).get("endpoint_type"):
            visual_config = {
                "ai_support": {
                    "enabled": True,
                    "endpoint_type": visual_endpoint_type,
                    "ai_config": config.get("ai_support", {}).get("visual_ai_config", config.get("ai_support", {}).get("ai_config", {}))
                }
            }
            self.visual_endpoint = AIEndpointFactory.create_endpoint(visual_config)

        annotation_scheme = config.get("annotation_schemes")
        self.annotations = []
        for scheme in annotation_scheme:
            self.annotations.append(scheme)

        # Check if main endpoint supports vision
        self.endpoint_supports_vision = hasattr(self.ai_endpoint, 'query_with_image')
        logger.info(f"AI endpoint supports vision: {self.endpoint_supports_vision}")

        # Initialize cache
        if self.disk_cache_enabled:
            self.load_cache_from_disk()
            self.start_warmup()

    def _validate_assistant_compatibility(
        self, instance_id: int, annotation_id: int, ai_assistant: str
    ) -> tuple:
        """
        Validate that the AI assistant is compatible with the input type and model capabilities.

        Args:
            instance_id: The instance/item index
            annotation_id: The annotation scheme index
            ai_assistant: Type of assistance ('hint', 'keyword', 'rationale', 'detection', etc.)

        Returns:
            Tuple of (is_valid: bool, error_message: str)
            If valid, error_message is empty string.
        """
        try:
            text = _get_instance_text(instance_id)
            is_image = _is_image_url(text)

            # Determine which endpoint to use
            if is_image and self.visual_endpoint:
                endpoint = self.visual_endpoint
            elif is_image and self.endpoint_supports_vision:
                endpoint = self.ai_endpoint
            else:
                endpoint = self.ai_endpoint

            # Get capabilities from endpoint
            capabilities = getattr(endpoint, 'CAPABILITIES', None)

            if capabilities is None:
                # No capabilities declared - allow all (backward compatibility)
                logger.debug(f"Endpoint {type(endpoint).__name__} has no CAPABILITIES, allowing {ai_assistant}")
                return True, ""

            # Check if the assistant type is supported
            if not capabilities.supports_assistant(ai_assistant, is_image):
                input_type = "image" if is_image else "text"
                return False, (
                    f"Model {type(endpoint).__name__} does not support '{ai_assistant}' "
                    f"for {input_type} content"
                )

            return True, ""

        except Exception as e:
            logger.warning(f"Error validating assistant compatibility: {e}")
            # On validation error, allow the request (fail open for now)
            return True, ""

    def get_endpoint_capabilities(self, for_image: bool = False) -> ModelCapabilities:
        """
        Get the capabilities of the appropriate endpoint for the given input type.

        Args:
            for_image: Whether the input is an image

        Returns:
            ModelCapabilities instance, or a default permissive one if not declared
        """
        if for_image and self.visual_endpoint:
            endpoint = self.visual_endpoint
        elif for_image and self.endpoint_supports_vision:
            endpoint = self.ai_endpoint
        else:
            endpoint = self.ai_endpoint

        capabilities = getattr(endpoint, 'CAPABILITIES', None)
        if capabilities is None:
            # Return permissive defaults for backward compatibility
            return ModelCapabilities(
                text_generation=True,
                vision_input=for_image,
                bounding_box_output=False,
                text_classification=True,
                image_classification=for_image,
                rationale_generation=True,
                keyword_extraction=not for_image,
            )
        return capabilities

    def _get_ai_with_vision_support(self, text: str, prompt: str, output_format) -> str:
        """
        Get AI response, using vision if text is an image URL and endpoint supports it.
        """
        # Check if we should use vision
        if self.endpoint_supports_vision and _is_image_url(text):
            logger.debug(f"Using vision query for image URL: {text[:50]}...")
            image_data = _get_image_data_from_url(text)
            if image_data:
                try:
                    return self.ai_endpoint.query_with_image(prompt, image_data, output_format)
                except Exception as e:
                    logger.error(f"Vision query failed: {e}")
                    # Fall back to text query

        # Fall back to regular text query
        return self.ai_endpoint.query(prompt, output_format)
    
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
            logger.error(f"Error loading disk cache: {e}")
            return {}

    def load_cache_from_disk(self):
        """Initializes disk cache file if it doesn't exist."""
        if not self.disk_cache_enabled or not self.disk_persistence_path:
            return

        if os.path.exists(self.disk_persistence_path):
            data = self.load_disk_cache_data(self.disk_persistence_path)
            logger.info(f"Disk cache initialized with {len(data)} items")
        else: 
            try:
                # Create parent directory if it doesn't exist
                os.makedirs(os.path.dirname(self.disk_persistence_path), exist_ok=True)
                with open(self.disk_persistence_path, 'w', encoding='utf-8') as file:
                    json.dump({}, file)
                logger.info(f"Initialized empty disk cache at {self.disk_persistence_path}")
            except Exception as e:
                logger.error(f"Failed to create disk cache: {e}")

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
            logger.error(f"Error saving cache to disk: {e}")

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
                    logger.error(f"Error reading from disk: {e}")
            return None
    
    def generate_likert(self, instance_id: int, annotation_id: int, ai_assistant: str) -> str:
        from string import Template
        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        description = config["annotation_schemes"][annotation_id]["description"]
        text = _get_instance_text(instance_id)
        min_label = config["annotation_schemes"][annotation_id]["min_label"]
        max_label = config["annotation_schemes"][annotation_id]["max_label"]
        size = config["annotation_schemes"][annotation_id]["size"]

        ai_prompt = get_ai_prompt()
        output_format = self.model_manager.get_model_class_by_name(ai_prompt[annotation_type].get(ai_assistant).get("output_format"))

        # Check if we should use vision endpoint for image-based content
        if self.endpoint_supports_vision and _is_image_url(text):
            logger.debug(f"Using vision for likert {ai_assistant} on image: {text[:50]}...")
            image_data = _get_image_data_from_url(text)
            if image_data:
                # Build vision-specific prompts based on ai_assistant type
                if ai_assistant == "hint":
                    prompt = f"""Look at this image and help with the following annotation task:

Task: {description}
Rating scale: {size} points, from "{min_label}" (1) to "{max_label}" ({size})

Please analyze the image and suggest an appropriate rating with a brief explanation.
Respond in JSON format: {{"hint": "<explanation>", "suggestive_choice": "<rating label>"}}"""
                elif ai_assistant == "rationale":
                    prompt = f"""Look at this image and explain the reasoning for different rating choices:

Task: {description}
Rating scale: {size} points, from "{min_label}" (1) to "{max_label}" ({size})

For each possible rating, explain what visual evidence in the image would support that rating.
Respond in JSON format: {{"rationales": [{{"label": "<rating>", "reasoning": "<explanation>"}}]}}"""
                elif ai_assistant == "keyword":
                    prompt = f"""Look at this image and identify visual features relevant to the rating task:

Task: {description}
Rating scale: {size} points, from "{min_label}" (1) to "{max_label}" ({size})

Identify key visual elements that would influence the rating.
Respond in JSON format: {{"keywords": ["<visual_feature_1>", "<visual_feature_2>"]}}"""
                else:
                    prompt = f"Analyze this image for: {description}"

                try:
                    return self.ai_endpoint.query_with_image(prompt, image_data, output_format)
                except Exception as e:
                    logger.error(f"Vision query failed for likert {ai_assistant}: {e}")

        # Fall back to standard text-based generation
        data = AnnotationInput(
            ai_assistant=ai_assistant,
            annotation_type=annotation_type,
            text=text,
            description=description,
            min_label=min_label,
            max_label=max_label,
            size=size
        )
        res = self.ai_endpoint.get_ai(data, output_format)
        return res
    
    def generate_multiselect(self, instance_id: int, annotation_id: int, ai_assistant: str) -> str:
        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        description = config["annotation_schemes"][annotation_id]["description"]
        labels = config["annotation_schemes"][annotation_id]["labels"]
        text = _get_instance_text(instance_id)

        ai_prompt = get_ai_prompt()
        output_format = self.model_manager.get_model_class_by_name(ai_prompt[annotation_type].get(ai_assistant).get("output_format"))

        # Check if we should use vision endpoint for image-based content
        if self.endpoint_supports_vision and _is_image_url(text):
            logger.debug(f"Using vision for multiselect {ai_assistant} on image: {text[:50]}...")
            image_data = _get_image_data_from_url(text)
            if image_data:
                # Format labels for the prompt
                label_names = [l.get('name', l) if isinstance(l, dict) else l for l in labels]
                labels_str = ', '.join(f'"{name}"' for name in label_names)

                # Build vision-specific prompts based on ai_assistant type
                if ai_assistant == "hint":
                    prompt = f"""Look at this image and help with the following annotation task:

Task: {description}
Available options (select all that apply): {labels_str}

Please analyze the image and suggest which options apply.
Respond in JSON format: {{"hint": "<explanation>", "suggestive_choices": ["<option1>", "<option2>"]}}"""
                elif ai_assistant == "rationale":
                    prompt = f"""Look at this image and explain the reasoning for each option:

Task: {description}
Available options: {labels_str}

For each option, explain what visual evidence supports or contradicts it.
Respond in JSON format: {{"rationales": [{{"label": "<option>", "reasoning": "<explanation>"}}]}}"""
                elif ai_assistant == "keyword":
                    prompt = f"""Look at this image and identify visual features for each option:

Task: {description}
Available options: {labels_str}

For each option, identify visual cues that indicate its presence.
Respond in JSON format: {{"label_keywords": [{{"label": "<option>", "keywords": ["<feature1>", "<feature2>"]}}]}}"""
                else:
                    prompt = f"Analyze this image for: {description}. Options: {labels_str}"

                try:
                    return self.ai_endpoint.query_with_image(prompt, image_data, output_format)
                except Exception as e:
                    logger.error(f"Vision query failed for multiselect {ai_assistant}: {e}")

        # Fall back to standard text-based generation
        data = AnnotationInput(
            ai_assistant=ai_assistant,
            annotation_type=annotation_type,
            text=text,
            description=description,
            labels=labels
        )
        res = self.ai_endpoint.get_ai(data, output_format)
        return res
    
    def generate_radio(self, instance_id: int, annotation_id: int, ai_assistant: str) -> str:
        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        description = config["annotation_schemes"][annotation_id]["description"]
        text = _get_instance_text(instance_id)
        labels = config["annotation_schemes"][annotation_id]["labels"]

        ai_prompt = get_ai_prompt()
        output_format = self.model_manager.get_model_class_by_name(ai_prompt[annotation_type].get(ai_assistant).get("output_format"))

        # Check if we should use vision endpoint for image-based content
        if self.endpoint_supports_vision and _is_image_url(text):
            logger.debug(f"Using vision for radio {ai_assistant} on image: {text[:50]}...")
            image_data = _get_image_data_from_url(text)
            if image_data:
                # Format labels for the prompt
                label_names = [l.get('name', l) if isinstance(l, dict) else l for l in labels]
                labels_str = ', '.join(f'"{name}"' for name in label_names)

                # Build vision-specific prompts based on ai_assistant type
                if ai_assistant == "hint":
                    prompt = f"""Look at this image and help with the following annotation task:

Task: {description}
Available options: {labels_str}

Please analyze the image and suggest the most appropriate option.
Respond in JSON format: {{"hint": "<explanation>", "suggestive_choice": "<selected option>"}}"""
                elif ai_assistant == "rationale":
                    prompt = f"""Look at this image and explain the reasoning for each option:

Task: {description}
Available options: {labels_str}

For each option, explain what visual evidence in the image supports or contradicts it.
Respond in JSON format: {{"rationales": [{{"label": "<option>", "reasoning": "<explanation>"}}]}}"""
                elif ai_assistant == "keyword":
                    prompt = f"""Look at this image and identify visual features for each option:

Task: {description}
Available options: {labels_str}

For each option, identify visual cues that would indicate its presence.
Respond in JSON format: {{"label_keywords": [{{"label": "<option>", "keywords": ["<feature1>", "<feature2>"]}}]}}"""
                else:
                    prompt = f"Analyze this image for: {description}. Options: {labels_str}"

                try:
                    return self.ai_endpoint.query_with_image(prompt, image_data, output_format)
                except Exception as e:
                    logger.error(f"Vision query failed for radio {ai_assistant}: {e}")

        # Fall back to standard text-based generation
        data = AnnotationInput(
            ai_assistant=ai_assistant,
            annotation_type=annotation_type,
            text=text,
            description=description,
            labels=labels
        )
        res = self.ai_endpoint.get_ai(data, output_format)
        return res
    
    def generate_number(self, instance_id: int, annotation_id: int, ai_assistant: str) -> str:
        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        description = config["annotation_schemes"][annotation_id]["description"]
        text = _get_instance_text(instance_id)

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
        text = _get_instance_text(instance_id)


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
        text = _get_instance_text(instance_id)

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
        text = _get_instance_text(instance_id)

        data = AnnotationInput(
            ai_assistant=ai_assistant,
            annotation_type=annotation_type,
            text=text,
            description=description,
            labels=labels
        )
        ai_prompt = get_ai_prompt();
        logger.debug(f"Generating span annotation with labels: {labels}")
        output_format = self.model_manager.get_model_class_by_name(ai_prompt[annotation_type].get(ai_assistant).get("output_format"))
        res = self.ai_endpoint.get_ai(data, output_format)
        return res
    
    def generate_textbox(self, instance_id: int, annotation_id: int, ai_assistant: str) -> str:
        logger.debug(f"Generating textbox for annotation_id: {annotation_id}")
        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        description = config["annotation_schemes"][annotation_id]["description"]
        text = _get_instance_text(instance_id)

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

    def generate_image_annotation(self, instance_id: int, annotation_id: int, ai_assistant: str) -> Dict:
        """Generate AI assistance for image annotation tasks.

        Args:
            instance_id: The instance/item index
            annotation_id: The annotation scheme index
            ai_assistant: Type of assistance ('detection', 'classification', 'hint', 'pre_annotate', etc.)

        Returns:
            Dict with AI suggestions (detections, classifications, hints, etc.)
        """
        logger.debug(f"Generating image annotation for instance={instance_id}, annotation={annotation_id}, assistant={ai_assistant}")

        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        description = config["annotation_schemes"][annotation_id].get("description", "")
        labels = config["annotation_schemes"][annotation_id].get("labels", [])

        # Extract label names if labels are dicts
        if labels and isinstance(labels[0], dict):
            labels = [l.get("name", str(l)) for l in labels]

        # Get image URL from item data
        item_data = get_item_state_manager().items()[instance_id].get_data()
        image_url = self._extract_image_url(item_data)

        if not image_url:
            return {"error": "No image URL found in instance data"}

        # Determine which endpoint to use
        endpoint = self._get_visual_endpoint()
        if not endpoint:
            return {"error": "No visual AI endpoint configured"}

        # Check if endpoint supports visual queries
        if not hasattr(endpoint, 'query_with_image'):
            # Fall back to text-based hint
            return self._generate_text_hint_for_visual(instance_id, annotation_id, ai_assistant)

        # Prepare image data
        image_data = self._prepare_image_data(image_url)

        # Get confidence threshold from config
        confidence_threshold = config["annotation_schemes"][annotation_id].get(
            "ai_support", {}
        ).get("confidence_threshold", 0.5)

        # Build VisualAnnotationInput
        data = VisualAnnotationInput(
            ai_assistant=ai_assistant,
            annotation_type=annotation_type,
            task_type=ai_assistant,  # detection, classification, hint, etc.
            image_data=image_data,
            description=description,
            labels=labels,
            confidence_threshold=confidence_threshold
        )

        # Get output format from prompt config
        ai_prompt = get_ai_prompt()
        prompt_config = ai_prompt.get(annotation_type, {}).get(ai_assistant, {})
        output_format_name = prompt_config.get("output_format", "visual_detection")
        output_format = self.model_manager.get_model_class_by_name(output_format_name)

        # Query the visual endpoint
        result = endpoint.get_visual_ai(data, output_format)
        return result

    def generate_video_annotation(self, instance_id: int, annotation_id: int, ai_assistant: str) -> Dict:
        """Generate AI assistance for video annotation tasks.

        Args:
            instance_id: The instance/item index
            annotation_id: The annotation scheme index
            ai_assistant: Type of assistance ('scene_detection', 'frame_classification', etc.)

        Returns:
            Dict with AI suggestions (segments, keyframes, etc.)
        """
        logger.debug(f"Generating video annotation for instance={instance_id}, annotation={annotation_id}, assistant={ai_assistant}")

        annotation_type = config["annotation_schemes"][annotation_id]["annotation_type"]
        description = config["annotation_schemes"][annotation_id].get("description", "")
        labels = config["annotation_schemes"][annotation_id].get("labels", [])

        # Extract label names if labels are dicts
        if labels and isinstance(labels[0], dict):
            labels = [l.get("name", str(l)) for l in labels]

        # Get video URL from item data
        item_data = get_item_state_manager().items()[instance_id].get_data()
        video_url = self._extract_video_url(item_data)

        if not video_url:
            return {"error": "No video URL found in instance data"}

        # Determine which endpoint to use
        endpoint = self._get_visual_endpoint()
        if not endpoint:
            return {"error": "No visual AI endpoint configured"}

        # Check if endpoint supports visual queries
        if not hasattr(endpoint, 'query_with_image'):
            return self._generate_text_hint_for_visual(instance_id, annotation_id, ai_assistant)

        # Extract video frames
        try:
            frames = endpoint.extract_video_frames(video_url)
            video_metadata = endpoint.get_video_metadata(video_url)
        except Exception as e:
            logger.error(f"Failed to extract video frames: {e}")
            return {"error": f"Failed to process video: {str(e)}"}

        # Build VisualAnnotationInput
        data = VisualAnnotationInput(
            ai_assistant=ai_assistant,
            annotation_type=annotation_type,
            task_type=ai_assistant,
            image_data=frames,  # List of frame images
            description=description,
            labels=labels,
            video_metadata=video_metadata
        )

        # Get output format
        ai_prompt = get_ai_prompt()
        prompt_config = ai_prompt.get(annotation_type, {}).get(ai_assistant, {})
        output_format_name = prompt_config.get("output_format", "video_scene_detection")
        output_format = self.model_manager.get_model_class_by_name(output_format_name)

        # Query the visual endpoint
        result = endpoint.get_visual_ai(data, output_format)
        return result

    def _get_visual_endpoint(self):
        """Get the appropriate endpoint for visual tasks."""
        # Use dedicated visual endpoint if configured
        if self.visual_endpoint:
            return self.visual_endpoint

        # Check if main endpoint supports vision
        if hasattr(self.ai_endpoint, 'query_with_image'):
            return self.ai_endpoint

        # Try to find a visual endpoint from registered types
        visual_types = ['yolo', 'ollama_vision', 'openai_vision', 'anthropic_vision']
        for vtype in visual_types:
            if vtype in AIEndpointFactory._endpoints:
                try:
                    visual_config = {
                        "ai_support": {
                            "enabled": True,
                            "endpoint_type": vtype,
                            "ai_config": config.get("ai_support", {}).get("ai_config", {})
                        }
                    }
                    return AIEndpointFactory.create_endpoint(visual_config)
                except Exception as e:
                    logger.debug(f"Could not create {vtype} endpoint: {e}")
                    continue

        return None

    def _extract_image_url(self, item_data: Dict) -> str:
        """Extract image URL from item data.

        Looks for common field names that might contain image URLs.
        """
        # Common field names for images
        image_fields = ['image', 'image_url', 'img', 'img_url', 'url', 'path', 'file', 'src']

        for field in image_fields:
            if field in item_data:
                value = item_data[field]
                if isinstance(value, str) and (
                    value.startswith(('http://', 'https://', '/')) or
                    value.endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))
                ):
                    return value

        # Check 'text' field for URL (common in simple configs)
        if 'text' in item_data:
            text = item_data['text']
            if isinstance(text, str) and (
                text.startswith(('http://', 'https://')) and
                any(ext in text.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp'])
            ):
                return text

        return None

    def _extract_video_url(self, item_data: Dict) -> str:
        """Extract video URL from item data."""
        # Common field names for videos
        video_fields = ['video', 'video_url', 'url', 'path', 'file', 'src', 'media']

        for field in video_fields:
            if field in item_data:
                value = item_data[field]
                if isinstance(value, str) and (
                    value.startswith(('http://', 'https://', '/')) or
                    value.endswith(('.mp4', '.webm', '.ogg', '.avi', '.mov'))
                ):
                    return value

        # Check 'text' field for URL
        if 'text' in item_data:
            text = item_data['text']
            if isinstance(text, str) and (
                text.startswith(('http://', 'https://')) and
                any(ext in text.lower() for ext in ['.mp4', '.webm', '.ogg', '.avi', '.mov'])
            ):
                return text

        return None

    def _prepare_image_data(self, image_url: str) -> ImageData:
        """Prepare ImageData from URL or path."""
        if image_url.startswith(('http://', 'https://')):
            return ImageData(source="url", data=image_url)
        else:
            # Local file path - encode as base64
            from potato.ai.visual_ai_endpoint import BaseVisualAIEndpoint
            return BaseVisualAIEndpoint.encode_image_to_base64(image_url)

    def _generate_text_hint_for_visual(self, instance_id: int, annotation_id: int, ai_assistant: str) -> Dict:
        """Generate text-based hint when visual endpoint is not available."""
        description = config["annotation_schemes"][annotation_id].get("description", "")
        labels = config["annotation_schemes"][annotation_id].get("labels", [])

        if labels and isinstance(labels[0], dict):
            labels = [l.get("name", str(l)) for l in labels]

        return {
            "hint": f"Review the {'image' if 'image' in config['annotation_schemes'][annotation_id]['annotation_type'] else 'video'} carefully. "
                    f"Look for: {', '.join(labels) if labels else 'relevant content'}. "
                    f"Task: {description}",
            "suggestive_choice": ""
        }

    def get_include_all(self): 
        return self.include_all 
    
    def get_special_include(self, page_number_int, annotation_id_int):
        logger.debug(f"get_special_include: page={page_number_int}, annotation_id={annotation_id_int}")
        if not self.special_includes.get(page_number_int):
            return None
        elif not self.special_includes.get(page_number_int).get(annotation_id_int):
            return None
        return self.special_includes.get(page_number_int).get(annotation_id_int)

    def start_prefetch(self, page_id, prefetch_amount):
        """Prefetches a fixed number of upcoming items to warm the cache."""
        if not config.get("ai_support", {}).get("enabled") or not self.disk_cache_enabled:
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

            logger.debug(f"Prefetch range: start_idx={start_idx}, end_idx={end_idx}")
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
                                    logger.error(f"Prefetch failed for key {cache_key}: {e}")
                                self.in_progress.pop(cache_key, None)

                    future.add_done_callback(callback)

    def get_ai_help(self, instance_id: int, annotation_id: int, ai_assistant: str) -> str:
        """retrieves AI help either from cache, waits for in-progress, or computes on-demand."""
        key = (instance_id, annotation_id, ai_assistant)

        # Check if caching is enabled for this help type
        if not self.disk_cache_enabled:
            return self.compute_help(instance_id, annotation_id, ai_assistant)

        # Try to get from cache if caching is enabled
        cached_value = self.get_from_cache(key)
        if cached_value is not None:
            logger.debug(f"Cache hit for key: {key}")
            return cached_value

        with self.lock:
            if key in self.in_progress:
                future = self.in_progress[key]
            else:
                future = self.executor.submit(self.compute_help, instance_id, annotation_id, ai_assistant)
                self.in_progress[key] = future
        try:
            result = future.result(timeout=60)
            # Don't cache error responses
            is_error_response = (
                isinstance(result, str) and
                (result.startswith("Unable to generate") or
                 result.startswith("Error:") or
                 "error" in result.lower()[:50])
            )
            if self.disk_cache_enabled and not is_error_response:
                self.add_to_cache(key, result)
            elif is_error_response:
                logger.warning(f"Not caching error response for key {key}: {result[:100]}")
            with self.lock:
                self.in_progress.pop(key, None)
            return result
        except Exception as e:
            logger.error(f"Error computing help for key {key}: {e}")
            with self.lock:
                self.in_progress.pop(key, None)
            return f"Error: {str(e)}"

    def compute_help(self, instance_id: int, annotation_id: int, ai_assistant: str):
        # Validate that the assistant type is compatible with the model and input
        is_valid, error_message = self._validate_assistant_compatibility(
            instance_id, annotation_id, ai_assistant
        )
        if not is_valid:
            logger.warning(f"Assistant compatibility check failed: {error_message}")
            return {"error": error_message}

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
            case Annotation_Type.IMAGE_ANNOTATION:
                return self.generate_image_annotation(instance_id, annotation_id, ai_assistant)
            case Annotation_Type.VIDEO_ANNOTATION:
                return self.generate_video_annotation(instance_id, annotation_id, ai_assistant)
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
                    logger.info("Disk cache file removed")
                except Exception as e:
                    logger.error(f"Error removing disk cache file: {e}")
            logger.info("Cache cleared")



