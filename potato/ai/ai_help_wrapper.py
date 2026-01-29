from flask import render_template_string
from typing import Optional, Dict, Any
from potato.ai.ai_cache import get_ai_cache_manager
from potato.ai.ai_prompt import get_ai_prompt
from potato.server_utils.config_module import config

# Global instance
DYNAMICAIHELP = None

def init_dynamic_ai_help():
    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"[init_dynamic_ai_help] Called. ai_support.enabled={config.get('ai_support', {}).get('enabled', False)}")

    if not config["ai_support"]["enabled"]:
        logger.info("[init_dynamic_ai_help] AI support disabled, returning")
        return
    global DYNAMICAIHELP
    if DYNAMICAIHELP is None:
        DYNAMICAIHELP = DynamicAIHelp()
        logger.info(f"[init_dynamic_ai_help] Created DYNAMICAIHELP instance: {id(DYNAMICAIHELP)}")
    else:
        logger.info(f"[init_dynamic_ai_help] DYNAMICAIHELP already exists: {id(DYNAMICAIHELP)}")

    return DYNAMICAIHELP

def get_dynamic_ai_help():
    global DYNAMICAIHELP
    return DYNAMICAIHELP

class DynamicAIHelp:
    def __init__(self):
        self.template = """
        {% if ai_assistant %}
        {{ ai_assistant | safe }}
        {% elif error_message %}
        <span class="error">{{ error_message }}</span>
        {% endif %}
        """

    def get_empty_wrapper(self): 
        return f'<div class="ai-help none"><div class="tooltip"></div></div>'

    def generate_ai_assistant(self, ai_prompts, annotation_type, ai_assistant):
        str_html = f'<div class="{ai_assistant} ai-assistant-containter">'
        img_url = ai_prompts[annotation_type].get(ai_assistant).get("img")
        if img_url:
            # Use empty alt since the button already has a text label
            str_html += f'<span class="ai-assistant-img"><img src="{img_url}" alt=""></span>'
        name = ai_prompts[annotation_type].get(ai_assistant).get("name", ai_assistant.capitalize())
        str_html += f'<span>{name}</span>'
        str_html += "</div>"
        return str_html

    def get_ai_help_data(self, instance: int, annotation_id: int, annotation_type: str) -> Dict[str, Any]:
        """Get current AI help configuration with the new prompt structure"""
        import logging
        logger = logging.getLogger(__name__)

        try:
            context = {
                'ai_assistant': None,
                'error_message': None,
            }
            ai_prompts = get_ai_prompt()
            logger.debug(f"[get_ai_help_data] ai_prompts keys: {list(ai_prompts.keys()) if ai_prompts else 'None'}")

            if not ai_prompts:
                context["error_message"] = f'No AI prompt configured'
                logger.debug("[get_ai_help_data] No AI prompts configured")
                return context
            elif annotation_type not in ai_prompts:
                context["error_message"] = f'annotation type {annotation_type} does not exist in ai_prompts'
                logger.debug(f"[get_ai_help_data] annotation type {annotation_type} not in prompts")
                return context

            ai_cache_manager = get_ai_cache_manager()
            logger.debug(f"[get_ai_help_data] ai_cache_manager: {ai_cache_manager is not None}")

            if ai_cache_manager is None:
                context["error_message"] = "AI cache manager not initialized"
                logger.debug("[get_ai_help_data] AI cache manager is None")
                return context

            ai_assistant_html_parts = []

            # Check if user specified specific ones
            special_include_types = ai_cache_manager.get_special_include(instance, annotation_id)
            logger.debug(f"[get_ai_help_data] special_include_types: {special_include_types}")

            if special_include_types:  # This is now just checking if the list exists and is not empty
                # Generate HTML for specific included keys
                logger.debug(f"[get_ai_help_data] Using special include types: {special_include_types}")
                for key in special_include_types:
                    if key in ai_prompts[annotation_type]:
                        ai_assistant_html_parts.append(self.generate_ai_assistant(ai_prompts, annotation_type, key))
                    else:
                        raise Exception(f'{key} does not exist in ai_prompt')

            elif ai_cache_manager.get_include_all():
                # Generate HTML for all keys in the annotation type
                logger.debug(f"[get_ai_help_data] include_all=True, generating HTML for: {list(ai_prompts[annotation_type].keys())}")
                for key in ai_prompts[annotation_type]:
                    ai_assistant_html_parts.append(self.generate_ai_assistant(ai_prompts, annotation_type, key))
            else:
                logger.debug("[get_ai_help_data] No special includes and include_all=False")

            # Combine all HTML parts
            ai_assistant_html = '<span>|</span>'.join(ai_assistant_html_parts) if ai_assistant_html_parts else None
            logger.debug(f"[get_ai_help_data] ai_assistant_html_parts count: {len(ai_assistant_html_parts)}")

            if ai_assistant_html:
                context['ai_assistant'] = ai_assistant_html

            logger.debug(f"[get_ai_help_data] Final context: ai_assistant={'set' if context['ai_assistant'] else 'None'}, error={'set' if context['error_message'] else 'None'}")
            return context
        except Exception as e:
            logger.error(f"[get_ai_help_data] Exception: {e}", exc_info=True)
            return {
                'ai_assistant': None,
                'error_message': f'Error loading AI help: {str(e)}',
            }

    def render(self, instance: int, annotation_id: int, annotation_type) -> str:
        """Render AI help HTML with current data"""
        context = self.get_ai_help_data(instance, annotation_id, annotation_type)
        context.update({
            'instance': instance,
            'annotation_id': annotation_id
        })
        return render_template_string(self.template, **context)

def generate_ai_help_html(instance: int, annotation_id: int, annotation_type: str) -> Optional[str]:
    """
    Generates dynamic AI help HTML using template rendering.
    Now works with the new prompt structure: {annotation_type: {prompt: ..., outputformat: ...}}
    """
    import logging
    logger = logging.getLogger(__name__)

    if DYNAMICAIHELP is None:
        logger.debug("[generate_ai_help_html] DYNAMICAIHELP is None - AI support not enabled")
        return ""  # AI support not enabled

    result = DYNAMICAIHELP.render(instance, annotation_id, annotation_type)
    logger.debug(f"[generate_ai_help_html] Rendered result: '{result[:100] if result else 'empty'}...'")
    return result

def get_ai_wrapper():
    import logging
    logger = logging.getLogger(__name__)
    helper = get_dynamic_ai_help()
    logger.debug(f"[get_ai_wrapper] DYNAMICAIHELP is {'set' if helper else 'None'}")
    result = helper.get_empty_wrapper() if helper else ""
    logger.debug(f"[get_ai_wrapper] Returning: '{result[:50] if result else 'empty'}...'")
    return result