"""
slider Layout
"""

# Needed for the fall-back radio layout
from .radio import generate_radio_layout

def test_and_get(key, d):
    val = d[key]
    try:
        return int(val)
    except:
        raise Exception(
            'Slider scale %s\'s value for "%s" is not an int' % (annotation_scheme["name"], key)
        )



def generate_slider_layout(annotation_scheme):

    # If the user specified the more complicated likert layout, default to the
    # radio layout
    if "labels" in annotation_scheme:
        return generate_radio_layout(annotation_scheme, horizontal=False)

    # Check all the configurations are present
    for required in ["starting_value", "min_value", "max_value"]:
        if required not in annotation_scheme:
            raise Exception(
                'Slider scale for "%s" did not include %s' % (annotation_scheme["name"], required)
            )

    # Check the values make sense
    min_value = test_and_get("min_value", annotation_scheme)
    max_value = test_and_get("max_value", annotation_scheme)
    starting_value = test_and_get("starting_value", annotation_scheme)

    if min_value >= max_value:
        raise Exception(
            'Slider scale for "%s" must have minimum value < max value (%d >= %d)' \
                % (annotation_scheme["name"], min_value, max_value)
        )

    # Optionally show the labels for the ends of the sliders
    show_labels = True if 'show_labels' not in annotation_scheme \
        else annotation_scheme['show_labels']
    min_label = str(min_value) if show_labels else ''
    max_label = str(max_value) if show_labels else ''

    schema_name = annotation_scheme["name"]
    name = schema_name + ':::' + 'slider'

    schematic = f"""
    <style>
        .shadcn-slider-container {{
            display: flex;
            flex-direction: column;
            width: 100%;
            max-width: 100%;
            margin: 1.5rem auto;
            font-family: ui-sans-serif, system-ui, sans-serif;
        }}

        .shadcn-slider-title {{
            font-size: 1rem;
            font-weight: 500;
            color: var(--heading-color);
            margin-bottom: 1rem;
            text-align: left;
            width: 100%;
        }}

        .shadcn-slider-wrapper {{
            display: flex;
            align-items: center;
            width: 100%;
            gap: 1rem;
            padding: 0.5rem 0;
        }}

        .shadcn-slider-label {{
            flex: 0 0 auto;
            width: 2.5rem;
            text-align: center;
            font-size: 0.875rem;
            color: var(--muted-foreground);
        }}

        .shadcn-slider-track {{
            flex: 1;
            position: relative;
            height: 1.5rem;
        }}

        .shadcn-slider-input {{
            -webkit-appearance: none;
            appearance: none;
            width: 100%;
            height: 0.25rem;
            background: var(--border);
            border-radius: 1rem;
            outline: none;
            cursor: pointer;
        }}

        .shadcn-slider-input::-webkit-slider-thumb {{
            -webkit-appearance: none;
            appearance: none;
            width: 1.25rem;
            height: 1.25rem;
            background-color: var(--primary);
            border-radius: 50%;
            border: 2px solid var(--background);
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
            cursor: pointer;
            transition: var(--transition);
        }}

        .shadcn-slider-input::-moz-range-thumb {{
            width: 1.25rem;
            height: 1.25rem;
            background-color: var(--primary);
            border-radius: 50%;
            border: 2px solid var(--background);
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
            cursor: pointer;
            transition: var(--transition);
        }}

        .shadcn-slider-input:focus {{
            outline: none;
        }}

        .shadcn-slider-input:focus::-webkit-slider-thumb {{
            box-shadow: 0 0 0 4px rgba(110, 86, 207, 0.25);
        }}

        .shadcn-slider-input:focus::-moz-range-thumb {{
            box-shadow: 0 0 0 4px rgba(110, 86, 207, 0.25);
        }}
    </style>

    <form id="{schema_name}" class="annotation-form slider shadcn-slider-container" action="/action_page.php">
        <fieldset schema="{schema_name}">
            <legend class="shadcn-slider-title">{annotation_scheme["description"]}</legend>
            <div class="shadcn-slider-wrapper">
                <div class="shadcn-slider-label">{min_label}</div>
                <div class="shadcn-slider-track">
                    <input type="range"
                           min="{min_value}"
                           max="{max_value}"
                           value="{starting_value}"
                           class="shadcn-slider-input annotation-input"
                           onclick="registerAnnotation(this);"
                           label_name="slider"
                           name="{name}"
                           id="{name}"
                           schema="{schema_name}">
                </div>
                <div class="shadcn-slider-label">{max_label}</div>
            </div>
        </fieldset>
    </form>
    """

    key_bindings = []
    return schematic, key_bindings
