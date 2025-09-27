from flask import render_template_string
from typing import Optional, Dict, Any
from ai.ai_cache import get_ai_cache_manager
from ai.ai_prompt import get_ai_prompt
from server_utils.config_module import config

# Global instance
DYNAMICAIHELP = None

def init_dynamic_ai_help():
    if not config["ai_support"]["enabled"]:
        return
    global DYNAMICAIHELP
    if DYNAMICAIHELP is None:
        DYNAMICAIHELP = DynamicAIHelp()

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
        if ai_prompts[annotation_type].get(ai_assistant).get("img"):
            str_html += f'<span class="ai-assistant-img"><img src={ai_prompts[annotation_type].get(ai_assistant).get("img")} alt={ai_assistant}></span>'
        str_html += f'<span>{ai_prompts[annotation_type].get(ai_assistant).get("name", ai_assistant)}</span>'
        str_html += "</div>"
        return str_html

    def get_ai_help_data(self, instance: int, annotation_id: int, annotation_type: str) -> Dict[str, Any]:
        """Get current AI help configuration with the new prompt structure"""
        try:
            context = {
                'ai_assistant': None,
                'error_message': None,
            }
            ai_prompts = get_ai_prompt()
            if not ai_prompts:
                context["error_message"] = f'No AI prompt configured'
            elif not ai_prompts[annotation_type]:
                context["error_message"] = f'annotation type {annotation_type} does not exist in ai_prompts'
            
            ai_cache_manager = get_ai_cache_manager()
            ai_assistant_html_parts = []
            
            # Check if user specified specific ones
            special_include_types = ai_cache_manager.get_special_include(instance, annotation_id)
            print("special_include_types:", special_include_types)
            
            if special_include_types:  # This is now just checking if the list exists and is not empty
                # Generate HTML for specific included keys
                print("Using special include types:", special_include_types)
                for key in special_include_types:  # special_include_types is ['hint']
                    if key in ai_prompts[annotation_type]:
                        ai_assistant_html_parts.append(self.generate_ai_assistant(ai_prompts, annotation_type, key))
                    else:
                        raise Exception(f'{key} does not exist in ai_prompt')
                        
            elif ai_cache_manager.get_include_all():  
                # Generate HTML for all keys in the annotation type
                for key in ai_prompts[annotation_type]:
                    ai_assistant_html_parts.append(self.generate_ai_assistant(ai_prompts, annotation_type, key))

            # Combine all HTML parts
            ai_assistant_html = '<span>|</span>'.join(ai_assistant_html_parts) if ai_assistant_html_parts else None
            if ai_assistant_html:
                context['ai_assistant'] = ai_assistant_html
            
            return context
        except Exception as e:
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
  
    return DYNAMICAIHELP.render(instance, annotation_id, annotation_type)

def get_ai_wrapper():
    helper = get_dynamic_ai_help()
    return helper.get_empty_wrapper() if helper else ""