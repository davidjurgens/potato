# """
# slider Layout
# """

# # Needed for the fall-back radio layout
# from ai.ai_help_wrapper import get_ai_wrapper, get_dynamic_ai_help
# from .radio import generate_radio_layout
# from .identifier_utils import (
#     safe_generate_layout,
#     generate_element_identifier,
#     escape_html_content
# )

# def test_and_get(key, d):
#     val = d[key]
#     try:
#         return int(val)
#     except:
#         raise Exception(
#             'Slider scale %s\'s value for "%s" is not an int' % (d["name"], key)
#         )

# def generate_slider_layout(annotation_scheme):
#     """
#     Generate HTML for a slider input interface.

#     Args:
#         annotation_scheme (dict): Configuration including:
#             - name: Schema identifier
#             - description: Display description
#             - starting_value: Initial slider value
#             - min_value: Minimum allowed value
#             - max_value: Maximum allowed value
#             - show_labels: Whether to show min/max labels
#             - labels: If present, fall back to radio layout

#     Returns:
#         tuple: (html_string, key_bindings)
#             html_string: Complete HTML for the slider interface
#             key_bindings: Empty list (no keyboard shortcuts)
#     """
#     return safe_generate_layout(annotation_scheme, generate_slider_layout_internal)

# def generate_slider_layout_internal(annotation_scheme):
#     from .identifier_utils import escape_html_content, generate_element_identifier
    
#     if "labels" in annotation_scheme:
#         return generate_radio_layout(annotation_scheme, horizontal=False)
    
#     for required in ["starting_value", "min_value", "max_value"]:
#         if required not in annotation_scheme:
#             raise Exception(
#                 f'Slider scale for "{annotation_scheme["name"]}" did not include {required}'
#             )
    
#     min_value = test_and_get("min_value", annotation_scheme)
#     max_value = test_and_get("max_value", annotation_scheme)
#     starting_value = test_and_get("starting_value", annotation_scheme)
    
#     if min_value >= max_value:
#         raise Exception(
#             f'Slider scale for "{annotation_scheme["name"]}" must have minimum value < max value ({min_value} >= {max_value})'
#         )
    
#     show_labels = annotation_scheme.get("show_labels", True)
#     min_label = str(min_value) if show_labels else ''
#     max_label = str(max_value) if show_labels else ''
    
#     identifiers = generate_element_identifier(annotation_scheme["name"], "slider", "range")
    
#     # Get step from annotation_scheme or default to 5
#     step_value = annotation_scheme.get("step", 1)
#     print(step_value)
#     max_tick = annotation_scheme.get("maxTick", 8)
#     print("max_tick")
#     print(max_tick)
    
#     schematic = f"""

#     <form id="{identifiers['schema']}" class="annotation-form slider" action="/action_page.php" data-annotation-id="{annotation_scheme["annotation_id"]}" >
#             {get_ai_wrapper()}
#         <fieldset schema="{identifiers['schema']}">
#             <legend class="custom-slider-title">{annotation_scheme['description']}</legend>
            
#             <div class="custom-slider-container" id="customSlider_{identifiers['id']}" tabindex="0">
#                 <!-- Hidden actual input for form submission -->
#                 <input type="range"
#                     min="{min_value}"
#                     max="{max_value}"
#                     step="{step_value}"
#                     value="{starting_value}"
#                     class="custom-slider-input annotation-input"
#                     onclick="registerAnnotation(this);"
#                     oninput="updateCustomSlider(this);"
#                     label_name="{identifiers['label_name']}"
#                     name="{identifiers['name']}"
#                     id="{identifiers['id']}"
#                     schema="{identifiers['schema']}">
                    
#                 <!-- Custom visual elements -->
#                 <div class="custom-slider-track">
#                     <div class="custom-slider-track-active" id="sliderTrackActive_{identifiers['id']}"></div>
#                     <div class="custom-slider-thumb" id="sliderThumb_{identifiers['id']}"></div>
#                 </div>
#                 <div class="custom-slider-ticks" id="sliderTicks_{identifiers['id']}"></div>
#             </div>
#         </fieldset>
#     </form>

#     <script>
#         // Initialize the slider on page load
#         (function() {{
#             const sliderId = "{identifiers['id']}";
#             const sliderInput = document.getElementById(sliderId);
            
#             if (!sliderInput) return;
            
#             // Set up the slider initially
#             setupCustomSlider(sliderInput);
            
#             // Update positions on input change
#             sliderInput.addEventListener('input', function() {{
#                 updateCustomSlider(this);
#             }});
#         }})();
        
#         function setupCustomSlider(sliderInput) {{
#             const sliderId = sliderInput.id;
#             const min = parseInt(sliderInput.min);
#             const max = parseInt(sliderInput.max);
#             const step = parseInt(sliderInput.step) || 1;
            
#             // Get references to custom elements
#             const container = document.getElementById('customSlider_' + sliderId);
#             const sliderThumb = document.getElementById('sliderThumb_' + sliderId);
#             const sliderTrackActive = document.getElementById('sliderTrackActive_' + sliderId);
#             const sliderTicks = document.getElementById('sliderTicks_' + sliderId);
            
#             if (!container || !sliderThumb || !sliderTrackActive || !sliderTicks) return;
            
#             // Initialize slider position
#             updateSliderPosition({starting_value}, min, max, sliderThumb, sliderTrackActive);
            
#             // Create tick marks
#             createTicks(min, max, step, sliderTicks);
            
#             // Add direct click handling for better UX
#             container.addEventListener('click', function(e) {{
#                 // Skip if the click is on the input or thumb (to prevent jumps during dragging)
#                 if (e.target === sliderThumb || e.target === sliderInput) return;
                
#                 // Get click position relative to the track
#                 const rect = container.getBoundingClientRect();
#                 const clickPosition = e.clientX - rect.left;
#                 const percentClicked = (clickPosition / rect.width) * 100;
                
#                 // Calculate the new value based on the click position
#                 let newValue = min + (percentClicked / 100) * (max - min);
                
#                 // Snap to the nearest step
#                 newValue = Math.round(newValue / step) * step;
                
#                 // Ensure the value is within bounds
#                 newValue = Math.max(min, Math.min(max, newValue));
                
#                 // Update the input value
#                 sliderInput.value = newValue;
                
#                 // Update the visual position
#                 updateSliderPosition(newValue, min, max, sliderThumb, sliderTrackActive);
                
#                 // Trigger change event for any listeners
#                 const event = new Event('input', {{ bubbles: true }});
#                 sliderInput.dispatchEvent(event);
                
#                 // If registerAnnotation exists, call it
#                 if (typeof registerAnnotation === 'function') {{
#                     registerAnnotation(sliderInput);
#                 }}
#             }});

#             // Add keyboard control
#             container.addEventListener('keydown', function(e) {{
#                 // Only process arrow keys
#                 if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
                
#                 // Prevent default to avoid page scrolling
#                 e.preventDefault();
                
#                 // Get current value
#                 let currentValue = parseFloat(sliderInput.value);
                
                
#                 // Update value based on arrow key
#                 if (e.key === 'ArrowDown') {{
#                     currentValue = Math.max(min, currentValue - step);
#                 }} else if (e.key === 'ArrowUp') {{
#                     currentValue = Math.min(max, currentValue + step);
#                 }}
                
#                 // Update the input value
#                 sliderInput.value = currentValue;
                
#                 // Update the visual position
#                 updateSliderPosition(currentValue, min, max, sliderThumb, sliderTrackActive);
                
#                 // Trigger change event for any listeners
#                 const event = new Event('input', {{ bubbles: true }});
#                 sliderInput.dispatchEvent(event);
                
#                 // If registerAnnotation exists, call it
#                 if (typeof registerAnnotation === 'function') {{
#                     registerAnnotation(sliderInput);
#                 }}
#             }});
            
#             // Add focus styles for keyboard users
#             container.addEventListener('focus', function() {{
#                 container.classList.add('focus');
#             }});
            
#             container.addEventListener('blur', function() {{
#                 container.classList.remove('focus');
#             }});
            
#             // Add drag and hold functionality
#             let isDragging = false;
            
#             // Mouse events for drag and hold
#             sliderThumb.addEventListener('mousedown', function(e) {{
#                 isDragging = true;
#                 e.preventDefault(); // Prevent text selection during drag
                
#                 // Add event listeners for drag and release
#                 document.addEventListener('mousemove', handleMouseDrag);
#                 document.addEventListener('mouseup', stopDrag);
                
#                 // Add a class to indicate dragging state
#                 sliderThumb.classList.add('dragging');
#             }});
            
#             // Touch events for mobile devices
#             sliderThumb.addEventListener('touchstart', function(e) {{
#                 isDragging = true;
#                 e.preventDefault(); // Prevent scrolling during drag
                
#                 // Add event listeners for drag and release
#                 document.addEventListener('touchmove', handleTouchDrag);
#                 document.addEventListener('touchend', stopDrag);
#                 document.addEventListener('touchcancel', stopDrag);
                
#                 // Add a class to indicate dragging state
#                 sliderThumb.classList.add('dragging');
#             }});
            
#             // Handle mouse drag
#             function handleMouseDrag(e) {{
#                 if (!isDragging) return;
                
#                 // Get the slider's position and dimensions
#                 const rect = container.getBoundingClientRect();
                
#                 // Calculate position within the slider (constrain to slider width)
#                 let position = e.clientX - rect.left;
#                 position = Math.max(0, Math.min(position, rect.width));
                
#                 // Calculate value and update slider
#                 updateSliderFromPosition(position, rect.width);
#             }}
            
#             // Handle touch drag
#             function handleTouchDrag(e) {{
#                 if (!isDragging || !e.touches[0]) return;
                
#                 const touch = e.touches[0];
#                 const rect = container.getBoundingClientRect();
                
#                 // Calculate position within the slider (constrain to slider width)
#                 let position = touch.clientX - rect.left;
#                 position = Math.max(0, Math.min(position, rect.width));
                
#                 // Calculate value and update slider
#                 updateSliderFromPosition(position, rect.width);
#             }}
            
#             // Helper function to update slider from mouse/touch position
#             function updateSliderFromPosition(position, width) {{
#                 // Convert position to a percentage
#                 const percent = (position / width) * 100;
                
#                 // Calculate the value based on percentage
#                 let newValue = min + (percent / 100) * (max - min);
                
#                 // Snap to the nearest step
#                 newValue = Math.round(newValue / step) * step;
                
#                 // Ensure the value is within bounds
#                 newValue = Math.max(min, Math.min(max, newValue));
                
#                 // Update the input value
#                 sliderInput.value = newValue;
                
#                 // Update the visual position
#                 updateSliderPosition(newValue, min, max, sliderThumb, sliderTrackActive);
                
#                 // Trigger change event
#                 const event = new Event('input', {{ bubbles: true }});
#                 sliderInput.dispatchEvent(event);
                
#                 // If registerAnnotation exists, call it
#                 if (typeof registerAnnotation === 'function') {{
#                     registerAnnotation(sliderInput);
#                 }}
#             }}
            
#             // Stop dragging
#             function stopDrag() {{
#                 if (!isDragging) return;
                
#                 isDragging = false;
#                 sliderThumb.classList.remove('dragging');
                
#                 // Remove the event listeners
#                 document.removeEventListener('mousemove', handleMouseDrag);
#                 document.removeEventListener('touchmove', handleTouchDrag);
#                 document.removeEventListener('mouseup', stopDrag);
#                 document.removeEventListener('touchend', stopDrag);
#                 document.removeEventListener('touchcancel', stopDrag);
#             }}
#         }}
        
#         function updateCustomSlider(sliderInput) {{
#             const sliderId = sliderInput.id;
#             const min = parseInt(sliderInput.min);
#             const max = parseInt(sliderInput.max);
            
#             const sliderThumb = document.getElementById('sliderThumb_' + sliderId);
#             const sliderTrackActive = document.getElementById('sliderTrackActive_' + sliderId);
            
#             if (!sliderThumb || !sliderTrackActive) return;
            
#             updateSliderPosition(sliderInput.value, min, max, sliderThumb, sliderTrackActive);
#         }}
        
#         function updateSliderPosition(value, min, max, thumbElement, trackElement) {{
#             const percent = ((value - min) / (max - min)) * 100;
#             thumbElement.style.left = `${{percent}}%`;
#             trackElement.style.width = `${{percent}}%`;
#         }}
        
#         function createTicks(min, max, step, tickContainer) {{
#             // Clear existing ticks
#             tickContainer.innerHTML = '';
            
#             // Calculate optimal ticks
#             const ticks = calculateOptimalTicks(min, max, step);
            
#             ticks.forEach(tick => {{
#                 const percent = ((tick.value - min) / (max - min)) * 100;
                
#                 const tickElement = document.createElement('div');
#                 tickElement.className = 'custom-slider-tick';
#                 tickElement.style.left = `${{percent}}%`;
                
#                 const tickMark = document.createElement('div');
#                 tickMark.className = tick.showLabel ? 'custom-slider-tick-mark major' : 'custom-slider-tick-mark';
#                 tickElement.appendChild(tickMark);
                
#                 if (tick.showLabel) {{
#                     const tickLabel = document.createElement('div');
#                     tickLabel.className = 'custom-slider-tick-label';
#                     tickLabel.textContent = tick.value;
#                     tickElement.appendChild(tickLabel);
#                 }}
                
#                 tickContainer.appendChild(tickElement);
#             }});
#         }}
        
#         function calculateOptimalTicks(min, max, sliderStep, maxTicks = {max_tick}) {{
#             const range = max - min;
            
#             // Generate all possible slider positions based on the step
#             const possibleValues = [];
#             for (let value = min; value <= max; value += sliderStep) {{
#                 possibleValues.push(Math.round(value));
#             }}
            
#             // If we have few enough values, show them all
#             if (possibleValues.length <= maxTicks) {{
#                 return possibleValues.map(value => ({{ value, showLabel: true }}));
#             }}
            
#             // Calculate a "nice" interval for major ticks
#             const targetInterval = range / (maxTicks - 1);
            
#             // Find nice intervals: 1, 2, 5, 10, 20, 50, 100, etc.
#             const candidates = [];
#             for (let magnitude = 1; magnitude <= range; magnitude *= 10) {{
#                 candidates.push(magnitude);      // 1, 10, 100...
#                 candidates.push(2 * magnitude);  // 2, 20, 200...
#                 candidates.push(5 * magnitude);  // 5, 50, 500...
#             }}
            
#             // Choose the candidate closest to our target
#             let bestInterval = candidates[0];
#             let bestDiff = Math.abs(candidates[0] - targetInterval);
            
#             for (const candidate of candidates) {{
#                 const diff = Math.abs(candidate - targetInterval);
#                 if (diff < bestDiff) {{
#                     bestInterval = candidate;
#                     bestDiff = diff;
#                 }}
#             }}
            
#             // Generate major ticks using the best interval
#             const majorTicks = [];
            
#             // Always start with min
#             majorTicks.push({{ value: min, showLabel: true }});
            
#             // Add ticks at nice intervals
#             for (let tickValue = bestInterval; tickValue < max; tickValue += bestInterval) {{
#                 if (tickValue > min) {{
#                     majorTicks.push({{ value: tickValue, showLabel: true }});
#                 }}
#             }}
            
#             // Always end with max (if it's not the same as the last tick)
#             if (majorTicks[majorTicks.length - 1].value !== max) {{
#                 majorTicks.push({{ value: max, showLabel: true }});
#             }}
            
#             // Add minor ticks for values between major ticks
#             const allTicks = [...majorTicks];
            
#             // Only add minor ticks if there's reasonable spacing
#             if (majorTicks.length > 1) {{
#                 const majorSpacing = bestInterval;
#                 if (majorSpacing > sliderStep * 2) {{
#                     possibleValues.forEach(value => {{
#                         if (!allTicks.some(t => t.value === value)) {{
#                             allTicks.push({{ value, showLabel: false }});
#                         }}
#                     }});
#                 }}
#             }}
            
#             return allTicks.sort((a, b) => a.value - b.value);
#         }}
#     </script>
#     """
#     key_bindings = []
#     return schematic, key_bindings


"""
slider Layout
"""

import logging

# Needed for the fall-back radio layout
from ai.ai_help_wrapper import get_ai_wrapper, get_dynamic_ai_help
from .radio import generate_radio_layout
from .identifier_utils import (
    safe_generate_layout,
    generate_element_identifier,
    escape_html_content
)

logger = logging.getLogger(__name__)

def test_and_get(key, d):
    val = d[key]
    try:
        return int(val)
    except:
        raise Exception(
            'Slider scale %s\'s value for "%s" is not an int' % (d["name"], key)
        )

def generate_slider_layout(annotation_scheme):
    """
    Generate HTML for a slider input interface.

    Args:
        annotation_scheme (dict): Configuration including:
            - name: Schema identifier
            - description: Display description
            - starting_value: Initial slider value
            - min_value: Minimum allowed value
            - max_value: Maximum allowed value
            - show_labels: Whether to show min/max labels
            - labels: If present, fall back to radio layout

    Returns:
        tuple: (html_string, key_bindings)
            html_string: Complete HTML for the slider interface
            key_bindings: Empty list (no keyboard shortcuts)
    """
    return safe_generate_layout(annotation_scheme, generate_slider_layout_internal)

def generate_slider_layout_internal(annotation_scheme):
    from .identifier_utils import escape_html_content, generate_element_identifier
    
    if "labels" in annotation_scheme:
        return generate_radio_layout(annotation_scheme, horizontal=False)
    
    for required in ["starting_value", "min_value", "max_value"]:
        if required not in annotation_scheme:
            raise Exception(
                f'Slider scale for "{annotation_scheme["name"]}" did not include {required}'
            )
    
    min_value = test_and_get("min_value", annotation_scheme)
    max_value = test_and_get("max_value", annotation_scheme)
    starting_value = test_and_get("starting_value", annotation_scheme)
    
    if min_value >= max_value:
        raise Exception(
            f'Slider scale for "{annotation_scheme["name"]}" must have minimum value < max value ({min_value} >= {max_value})'
        )
    
    show_labels = annotation_scheme.get("show_labels", True)
    min_label = str(min_value) if show_labels else ''
    max_label = str(max_value) if show_labels else ''
    
    identifiers = generate_element_identifier(annotation_scheme["name"], "slider", "range")
    
    # Get step from annotation_scheme or default to 1
    step_value = annotation_scheme.get("step", 1)
    max_tick = annotation_scheme.get("maxTick", 8)
    
    schematic = f"""
    <form id="{identifiers['schema']}" class="annotation-form slider" action="/action_page.php" data-annotation-id="{annotation_scheme["annotation_id"]}" >
            {get_ai_wrapper()}
        <fieldset schema="{identifiers['schema']}">
            <legend class="custom-slider-title">{annotation_scheme['description']}</legend>
            
            <div class="custom-slider-container" id="customSlider_{identifiers['id']}" tabindex="0">
                <!-- Hidden actual input for form submission -->
                <input type="range"
                    min="{min_value}"
                    max="{max_value}"
                    step="{step_value}"
                    value="{starting_value}"
                    class="custom-slider-input annotation-input"
                    onclick="registerAnnotation(this);"
                    oninput="updateCustomSlider(this);"
                    label_name="{identifiers['label_name']}"
                    name="{identifiers['name']}"
                    id="{identifiers['id']}"
                    schema="{identifiers['schema']}">
                    
                <!-- Custom visual elements -->
                <div class="custom-slider-track">
                    <div class="custom-slider-track-active" id="sliderTrackActive_{identifiers['id']}"></div>
                    <div class="custom-slider-thumb" id="sliderThumb_{identifiers['id']}">
                        <!-- Tooltip attached directly to thumb -->
                        <div class="slider-tooltip" id="sliderTooltip_{identifiers['id']}">{starting_value}</div>
                    </div>
                </div>
                <div class="custom-slider-ticks" id="sliderTicks_{identifiers['id']}"></div>
            </div>
        </fieldset>
    </form>

    <script>
        // Initialize the slider on page load
        (function() {{
            const sliderId = "{identifiers['id']}";
            const sliderInput = document.getElementById(sliderId);
            
            if (!sliderInput) return;
            
            // Set up the slider initially
            setupCustomSlider(sliderInput);
            
            // Update positions on input change
            sliderInput.addEventListener('input', function() {{
                updateCustomSlider(this);
            }});
        }})();
        
        function setupCustomSlider(sliderInput) {{
            const sliderId = sliderInput.id;
            const min = parseInt(sliderInput.min);
            const max = parseInt(sliderInput.max);
            const step = parseInt(sliderInput.step) || 1;
            
            // Get references to custom elements
            const container = document.getElementById('customSlider_' + sliderId);
            const sliderThumb = document.getElementById('sliderThumb_' + sliderId);
            const sliderTrackActive = document.getElementById('sliderTrackActive_' + sliderId);
            const sliderTicks = document.getElementById('sliderTicks_' + sliderId);
            const tooltip = document.getElementById('sliderTooltip_' + sliderId);
            
            if (!container || !sliderThumb || !sliderTrackActive || !sliderTicks || !tooltip) return;
            
            // Initialize slider position
            updateSliderPosition({starting_value}, min, max, sliderThumb, sliderTrackActive, tooltip);
            
            // Create tick marks
            createTicks(min, max, step, sliderTicks);
            
            container.addEventListener('click', function(e) {{
                // Skip if the click is on the input or thumb (to prevent jumps during dragging)
                if (e.target === sliderThumb || e.target === sliderInput) return;
                
                // Get click position relative to the track
                const rect = container.getBoundingClientRect();
                const clickPosition = e.clientX - rect.left;
                const percentClicked = (clickPosition / rect.width) * 100;
                
                // Calculate the new value based on the click position
                let newValue = min + (percentClicked / 100) * (max - min);
                
                // Snap to the nearest step
                newValue = Math.round(newValue / step) * step;
                
                // Ensure the value is within bounds
                newValue = Math.max(min, Math.min(max, newValue));
                
                // Update the input value
                sliderInput.value = newValue;
                
                // Update the visual position
                updateSliderPosition(newValue, min, max, sliderThumb, sliderTrackActive, tooltip);
                
                // Trigger change event for any listeners
                const event = new Event('input', {{ bubbles: true }});
                sliderInput.dispatchEvent(event);
                
                // If registerAnnotation exists, call it
                if (typeof registerAnnotation === 'function') {{
                    registerAnnotation(sliderInput);
                }}
            }});

            // Add keyboard control
            container.addEventListener('keydown', function(e) {{
                // Only process arrow keys
                if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
                
                // Prevent default to avoid page scrolling
                e.preventDefault();
                
                // Get current value
                let currentValue = parseFloat(sliderInput.value);
                
                
                // Update value based on arrow key
                if (e.key === 'ArrowDown') {{
                    currentValue = Math.max(min, currentValue - step);
                }} else if (e.key === 'ArrowUp') {{
                    currentValue = Math.min(max, currentValue + step);
                }}
                
                // Update the input value
                sliderInput.value = currentValue;
                
                // Update the visual position
                updateSliderPosition(currentValue, min, max, sliderThumb, sliderTrackActive, tooltip);
                
                // Trigger change event for any listeners
                const event = new Event('input', {{ bubbles: true }});
                sliderInput.dispatchEvent(event);
                
                // If registerAnnotation exists, call it
                if (typeof registerAnnotation === 'function') {{
                    registerAnnotation(sliderInput);
                }}
            }});
            
            // Add focus styles for keyboard users
            container.addEventListener('focus', function() {{
                container.classList.add('focus');
            }});
            
            container.addEventListener('blur', function() {{
                container.classList.remove('focus');
            }});
            
            // Add drag and hold functionality
            let isDragging = false;
            
            // Mouse events for drag and hold
            sliderThumb.addEventListener('mousedown', function(e) {{
                isDragging = true;
                e.preventDefault(); // Prevent text selection during drag
                
                // Show tooltip during drag
                sliderThumb.classList.add('dragging');
                
                // Add event listeners for drag and release
                document.addEventListener('mousemove', handleMouseDrag);
                document.addEventListener('mouseup', stopDrag);
            }});
            
            // Touch events for mobile devices
            sliderThumb.addEventListener('touchstart', function(e) {{
                isDragging = true;
                e.preventDefault(); // Prevent scrolling during drag
                
                // Show tooltip during drag
                sliderThumb.classList.add('dragging');
                
                // Add event listeners for drag and release
                document.addEventListener('touchmove', handleTouchDrag);
                document.addEventListener('touchend', stopDrag);
                document.addEventListener('touchcancel', stopDrag);
            }});
            
            // Handle mouse drag
            function handleMouseDrag(e) {{
                if (!isDragging) return;
                
                // Get the slider's position and dimensions
                const rect = container.getBoundingClientRect();
                
                // Calculate position within the slider (constrain to slider width)
                let position = e.clientX - rect.left;
                position = Math.max(0, Math.min(position, rect.width));
                
                // Calculate value and update slider
                updateSliderFromPosition(position, rect.width);
            }}
            
            // Handle touch drag
            function handleTouchDrag(e) {{
                if (!isDragging || !e.touches[0]) return;
                
                const touch = e.touches[0];
                const rect = container.getBoundingClientRect();
                
                // Calculate position within the slider (constrain to slider width)
                let position = touch.clientX - rect.left;
                position = Math.max(0, Math.min(position, rect.width));
                
                // Calculate value and update slider
                updateSliderFromPosition(position, rect.width);
            }}
            
            // Helper function to update slider from mouse/touch position
            function updateSliderFromPosition(position, width) {{
                // Convert position to a percentage
                const percent = (position / width) * 100;
                
                // Calculate the value based on percentage
                let newValue = min + (percent / 100) * (max - min);
                
                // Snap to the nearest step
                newValue = Math.round(newValue / step) * step;
                
                // Ensure the value is within bounds
                newValue = Math.max(min, Math.min(max, newValue));
                
                // Update the input value
                sliderInput.value = newValue;
                
                // Update the visual position
                updateSliderPosition(newValue, min, max, sliderThumb, sliderTrackActive, tooltip);
                
                // Trigger change event
                const event = new Event('input', {{ bubbles: true }});
                sliderInput.dispatchEvent(event);
                
                // If registerAnnotation exists, call it
                if (typeof registerAnnotation === 'function') {{
                    registerAnnotation(sliderInput);
                }}
            }}
            
            // Stop dragging
            function stopDrag() {{
                if (!isDragging) return;
                
                isDragging = false;
                sliderThumb.classList.remove('dragging');
                
                // Remove the event listeners
                document.removeEventListener('mousemove', handleMouseDrag);
                document.removeEventListener('touchmove', handleTouchDrag);
                document.removeEventListener('mouseup', stopDrag);
                document.removeEventListener('touchend', stopDrag);
                document.removeEventListener('touchcancel', stopDrag);
            }}
        }}
        
        function updateCustomSlider(sliderInput) {{
            const sliderId = sliderInput.id;
            const min = parseInt(sliderInput.min);
            const max = parseInt(sliderInput.max);
            
            const sliderThumb = document.getElementById('sliderThumb_' + sliderId);
            const sliderTrackActive = document.getElementById('sliderTrackActive_' + sliderId);
            const tooltip = document.getElementById('sliderTooltip_' + sliderId);
            
            if (!sliderThumb || !sliderTrackActive || !tooltip) return;
            
            updateSliderPosition(sliderInput.value, min, max, sliderThumb, sliderTrackActive, tooltip);
        }}
        
        function updateSliderPosition(value, min, max, thumbElement, trackElement, tooltipElement) {{
            const percent = ((value - min) / (max - min)) * 100;
            thumbElement.style.left = `${{percent}}%`;
            trackElement.style.width = `${{percent}}%`;
            
            // Update tooltip content only - it moves with the thumb automatically
            if (tooltipElement) {{
                tooltipElement.textContent = value;
            }}
        }}
        
        function createTicks(min, max, step, tickContainer) {{
            // Clear existing ticks
            tickContainer.innerHTML = '';
            
            // Calculate optimal ticks
            const ticks = calculateOptimalTicks(min, max, step);
            
            ticks.forEach(tick => {{
                const percent = ((tick.value - min) / (max - min)) * 100;
                
                const tickElement = document.createElement('div');
                tickElement.className = 'custom-slider-tick';
                tickElement.style.left = `${{percent}}%`;
                
                const tickMark = document.createElement('div');
                tickMark.className = tick.showLabel ? 'custom-slider-tick-mark major' : 'custom-slider-tick-mark';
                tickElement.appendChild(tickMark);
                
                if (tick.showLabel) {{
                    const tickLabel = document.createElement('div');
                    tickLabel.className = 'custom-slider-tick-label';
                    tickLabel.textContent = tick.value;
                    tickElement.appendChild(tickLabel);
                }}
                
                tickContainer.appendChild(tickElement);
            }});
        }}
        
        function calculateOptimalTicks(min, max, sliderStep, maxTicks = {max_tick}) {{
            const range = max - min;
            
            // Generate all possible slider positions based on the step
            const possibleValues = [];
            for (let value = min; value <= max; value += sliderStep) {{
                possibleValues.push(Math.round(value));
            }}
            
            // If we have few enough values, show them all
            if (possibleValues.length <= maxTicks) {{
                return possibleValues.map(value => ({{ value, showLabel: true }}));
            }}
            
            // Calculate a "nice" interval for major ticks
            const targetInterval = range / (maxTicks - 1);
            
            // Find nice intervals: 1, 2, 5, 10, 20, 50, 100, etc.
            const candidates = [];
            for (let magnitude = 1; magnitude <= range; magnitude *= 10) {{
                candidates.push(magnitude);      // 1, 10, 100...
                candidates.push(2 * magnitude);  // 2, 20, 200...
                candidates.push(5 * magnitude);  // 5, 50, 500...
            }}
            
            // Choose the candidate closest to our target
            let bestInterval = candidates[0];
            let bestDiff = Math.abs(candidates[0] - targetInterval);
            
            for (const candidate of candidates) {{
                const diff = Math.abs(candidate - targetInterval);
                if (diff < bestDiff) {{
                    bestInterval = candidate;
                    bestDiff = diff;
                }}
            }}
            
            // Generate major ticks using the best interval
            const majorTicks = [];
            
            // Always start with min
            majorTicks.push({{ value: min, showLabel: true }});
            
            // Add ticks at nice intervals
            for (let tickValue = bestInterval; tickValue < max; tickValue += bestInterval) {{
                if (tickValue > min) {{
                    majorTicks.push({{ value: tickValue, showLabel: true }});
                }}
            }}
            
            // Always end with max (if it's not the same as the last tick)
            if (majorTicks[majorTicks.length - 1].value !== max) {{
                majorTicks.push({{ value: max, showLabel: true }});
            }}
            
            // Add minor ticks for values between major ticks
            const allTicks = [...majorTicks];
            
            // Only add minor ticks if there's reasonable spacing
            if (majorTicks.length > 1) {{
                const majorSpacing = bestInterval;
                if (majorSpacing > sliderStep * 2) {{
                    possibleValues.forEach(value => {{
                        if (!allTicks.some(t => t.value === value)) {{
                            allTicks.push({{ value, showLabel: false }});
                        }}
                    }});
                }}
            }}
            
            return allTicks.sort((a, b) => a.value - b.value);
        }}
    </script>
    """
    key_bindings = []
    return schematic, key_bindings