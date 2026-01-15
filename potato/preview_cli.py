#!/usr/bin/env python3
"""
Potato Preview CLI

A command-line tool for previewing annotation task configurations.
Helps administrators validate configs and see how schemas will render
without running the full server.

Usage:
    potato preview config.yaml              # Summary output (default)
    potato preview config.yaml --format html    # HTML output
    potato preview config.yaml --format json    # JSON output

    # Or run as module:
    python -m potato.preview_cli config.yaml
"""

import argparse
import json
import os
import sys
import yaml
import logging
from typing import Dict, Any, List, Tuple, Optional

# Set up logging
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def load_config(config_path: str) -> Dict[str, Any]:
    """
    Load and parse a YAML configuration file.

    Args:
        config_path: Path to the configuration file

    Returns:
        Parsed configuration dictionary

    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If config is invalid YAML
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        raise ValueError("Configuration must be a YAML object (dictionary)")

    return config


def validate_config(config: Dict[str, Any]) -> List[str]:
    """
    Validate configuration and return list of issues.

    Args:
        config: Configuration dictionary

    Returns:
        List of validation error/warning messages
    """
    issues = []

    # Required fields
    required = ['annotation_task_name', 'item_properties', 'task_dir', 'output_annotation_dir']
    for field in required:
        if field not in config:
            issues.append(f"ERROR: Missing required field '{field}'")

    # Data source validation
    has_data_files = config.get('data_files') and len(config.get('data_files', [])) > 0
    has_data_directory = bool(config.get('data_directory'))
    if not has_data_files and not has_data_directory:
        issues.append("ERROR: Must have either 'data_files' or 'data_directory'")

    # Annotation schemes validation
    has_schemes = 'annotation_schemes' in config
    has_phases = 'phases' in config and config['phases']

    if not has_schemes and not has_phases:
        issues.append("ERROR: Must have either 'annotation_schemes' or 'phases'")

    if has_schemes and has_phases:
        # Check for potential conflict
        if isinstance(config['phases'], list):
            phases_with_schemes = [p.get('name', f'phase[{i}]')
                                  for i, p in enumerate(config['phases'])
                                  if 'annotation_schemes' in p]
        else:
            phases_with_schemes = [name for name, p in config['phases'].items()
                                  if name != 'order' and isinstance(p, dict) and 'annotation_schemes' in p]

        if phases_with_schemes:
            issues.append(f"ERROR: Both top-level and phase-level annotation_schemes found in: {', '.join(phases_with_schemes)}")

    return issues


def get_annotation_schemes(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract all annotation schemes from config.

    Args:
        config: Configuration dictionary

    Returns:
        List of annotation scheme dictionaries
    """
    schemes = []

    if 'annotation_schemes' in config:
        schemes.extend(config['annotation_schemes'])

    if 'phases' in config and config['phases']:
        phases = config['phases']
        if isinstance(phases, list):
            for phase in phases:
                if 'annotation_schemes' in phase:
                    schemes.extend(phase['annotation_schemes'])
        else:
            for name, phase in phases.items():
                if name != 'order' and isinstance(phase, dict) and 'annotation_schemes' in phase:
                    schemes.extend(phase['annotation_schemes'])

    return schemes


def detect_keybinding_conflicts(schemes: List[Dict[str, Any]]) -> List[str]:
    """
    Detect keyboard shortcut conflicts across all schemes.

    Args:
        schemes: List of annotation scheme dictionaries

    Returns:
        List of conflict warning messages
    """
    conflicts = []
    global_keys = {}  # key -> (schema_name, label)

    for scheme in schemes:
        schema_name = scheme.get('name', 'unknown')
        labels = scheme.get('labels', [])

        for i, label_data in enumerate(labels):
            key_value = None

            # Check for explicit key_value
            if isinstance(label_data, dict) and 'key_value' in label_data:
                key_value = str(label_data['key_value'])
                label_name = label_data.get('name', f'label[{i}]')
            elif scheme.get('sequential_key_binding') and len(labels) <= 10:
                key_value = str((i + 1) % 10)
                label_name = label_data if isinstance(label_data, str) else label_data.get('name', f'label[{i}]')
            else:
                continue

            if key_value:
                key_id = f"{key_value}"
                if key_id in global_keys:
                    prev_schema, prev_label = global_keys[key_id]
                    if prev_schema != schema_name:  # Only warn for cross-schema conflicts
                        conflicts.append(
                            f"WARNING: Key '{key_value}' used by both "
                            f"'{prev_schema}:{prev_label}' and '{schema_name}:{label_name}'"
                        )
                else:
                    global_keys[key_id] = (schema_name, label_name)

    return conflicts


def generate_preview_html(schemes: List[Dict[str, Any]]) -> str:
    """
    Generate HTML preview for annotation schemes.

    Args:
        schemes: List of annotation scheme dictionaries

    Returns:
        HTML string with rendered schemes
    """
    from potato.server_utils.schemas.registry import schema_registry

    html_parts = []
    all_keybindings = []

    html_parts.append("""
<!DOCTYPE html>
<html>
<head>
    <title>Annotation Preview</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body { padding: 20px; font-family: system-ui, sans-serif; }
        .scheme-preview { border: 1px solid #ddd; padding: 20px; margin: 10px 0; border-radius: 8px; }
        .scheme-title { color: #333; margin-bottom: 10px; }
        .scheme-type { color: #666; font-size: 0.9em; }
        .error { color: #dc3545; background: #f8d7da; padding: 10px; border-radius: 4px; }
    </style>
</head>
<body>
<div class="container">
<h1>Annotation Preview</h1>
""")

    for idx, scheme in enumerate(schemes):
        scheme_name = scheme.get('name', 'unknown')
        scheme_type = scheme.get('annotation_type', 'unknown')

        html_parts.append(f"""
<div class="scheme-preview">
    <h3 class="scheme-title">{scheme_name}</h3>
    <p class="scheme-type">Type: {scheme_type}</p>
    <div class="scheme-content">
""")

        try:
            # Set annotation_id before generating (required by schema generators)
            scheme["annotation_id"] = idx
            html, keybindings = schema_registry.generate(scheme)
            html_parts.append(html)
            all_keybindings.extend(keybindings)
        except Exception as e:
            html_parts.append(f'<div class="error">Error generating preview: {str(e)}</div>')

        html_parts.append("</div></div>")

    # Add keybindings summary
    if all_keybindings:
        html_parts.append("<h2>Keyboard Shortcuts</h2><table class='table'><thead><tr><th>Key</th><th>Action</th></tr></thead><tbody>")
        for key, action in all_keybindings:
            html_parts.append(f"<tr><td><kbd>{key}</kbd></td><td>{action}</td></tr>")
        html_parts.append("</tbody></table>")

    html_parts.append("</div></body></html>")

    return "\n".join(html_parts)


def generate_preview_json(config: Dict[str, Any], schemes: List[Dict[str, Any]], issues: List[str]) -> str:
    """
    Generate JSON preview output.

    Args:
        config: Full configuration dictionary
        schemes: List of annotation schemes
        issues: List of validation issues

    Returns:
        JSON string with preview data
    """
    from potato.server_utils.schemas.registry import schema_registry

    result = {
        "task_name": config.get('annotation_task_name', 'Unknown'),
        "validation_issues": issues,
        "schema_count": len(schemes),
        "schemas": []
    }

    for idx, scheme in enumerate(schemes):
        schema_info = {
            "name": scheme.get('name'),
            "type": scheme.get('annotation_type'),
            "description": scheme.get('description'),
            "labels": None,
            "keybindings": [],
            "error": None
        }

        # Extract labels
        if 'labels' in scheme:
            labels = scheme['labels']
            schema_info['labels'] = [
                l if isinstance(l, str) else l.get('name', str(l))
                for l in labels
            ]

        # Try to generate and get keybindings
        try:
            # Set annotation_id before generating (required by schema generators)
            scheme["annotation_id"] = idx
            _, keybindings = schema_registry.generate(scheme)
            schema_info['keybindings'] = [{"key": k, "action": a} for k, a in keybindings]
        except Exception as e:
            schema_info['error'] = str(e)

        result['schemas'].append(schema_info)

    return json.dumps(result, indent=2)


def generate_preview_summary(config: Dict[str, Any], schemes: List[Dict[str, Any]],
                             issues: List[str], conflicts: List[str]) -> str:
    """
    Generate text summary preview.

    Args:
        config: Full configuration dictionary
        schemes: List of annotation schemes
        issues: List of validation issues
        conflicts: List of keybinding conflicts

    Returns:
        Text summary string
    """
    lines = []
    lines.append("=" * 60)
    lines.append(f"ANNOTATION TASK PREVIEW")
    lines.append("=" * 60)
    lines.append(f"Task Name: {config.get('annotation_task_name', 'Unknown')}")
    lines.append(f"Task Directory: {config.get('task_dir', 'Not set')}")
    lines.append("")

    # Validation issues
    if issues:
        lines.append("VALIDATION ISSUES:")
        for issue in issues:
            lines.append(f"  {issue}")
        lines.append("")
    else:
        lines.append("Validation: PASSED")
        lines.append("")

    # Keybinding conflicts
    if conflicts:
        lines.append("KEYBINDING CONFLICTS:")
        for conflict in conflicts:
            lines.append(f"  {conflict}")
        lines.append("")

    # Schema summary
    lines.append(f"ANNOTATION SCHEMAS ({len(schemes)} total):")
    lines.append("-" * 40)

    from potato.server_utils.schemas.registry import schema_registry

    for idx, scheme in enumerate(schemes):
        name = scheme.get('name', 'unknown')
        ann_type = scheme.get('annotation_type', 'unknown')
        desc = scheme.get('description', '')[:50]

        lines.append(f"  [{ann_type}] {name}")
        if desc:
            lines.append(f"          {desc}...")

        # Count labels if present
        if 'labels' in scheme:
            label_count = len(scheme['labels'])
            lines.append(f"          Labels: {label_count}")

        # Try to get keybindings
        try:
            # Set annotation_id before generating (required by schema generators)
            scheme["annotation_id"] = idx
            _, keybindings = schema_registry.generate(scheme)
            if keybindings:
                lines.append(f"          Keybindings: {len(keybindings)}")
        except Exception as e:
            lines.append(f"          ERROR: {str(e)}")

        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def generate_layout_html(schemes: List[Dict[str, Any]]) -> str:
    """
    Generate just the task layout HTML snippet (no wrapper page).

    This outputs the HTML that would go inside {{ TASK_LAYOUT }} in the
    annotation template, allowing admins to prototype and debug their
    task layout without running the full server.

    Args:
        schemes: List of annotation scheme dictionaries

    Returns:
        HTML string with the annotation schema div and all schema forms
    """
    from potato.server_utils.schemas.registry import schema_registry

    html_parts = []
    html_parts.append('<div class="annotation_schema">')

    for idx, scheme in enumerate(schemes):
        # Set annotation_id before generating (required by schema generators)
        scheme["annotation_id"] = idx
        try:
            html, _ = schema_registry.generate(scheme)
            html_parts.append(html)
        except Exception as e:
            schema_name = scheme.get('name', 'unknown')
            html_parts.append(f'<!-- Error generating {schema_name}: {e} -->')

    html_parts.append('</div>')
    return "\n".join(html_parts)


def main():
    """Main entry point for preview CLI."""
    parser = argparse.ArgumentParser(
        description="Preview annotation task configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m potato.preview_cli config.yaml              # Summary output
  python -m potato.preview_cli config.yaml --format html    # Full HTML page preview
  python -m potato.preview_cli config.yaml --format json    # JSON output
  python -m potato.preview_cli config.yaml --layout-only    # Just the task layout HTML snippet

  # Save HTML to file:
  python -m potato.preview_cli config.yaml --format html > preview.html

  # Get just the annotation schema div for embedding:
  python -m potato.preview_cli config.yaml --layout-only > task_layout.html
"""
    )

    parser.add_argument(
        'config_file',
        help='Path to YAML configuration file'
    )
    parser.add_argument(
        '--format', '-f',
        choices=['summary', 'html', 'json'],
        default='summary',
        help='Output format (default: summary)'
    )
    parser.add_argument(
        '--layout-only', '-l',
        action='store_true',
        help='Output only the task layout HTML snippet (no wrapper page). This is the HTML that goes inside {{ TASK_LAYOUT }}.'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose output'
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    try:
        # Load configuration
        config = load_config(args.config_file)

        # Validate
        issues = validate_config(config)

        # Get schemes
        schemes = get_annotation_schemes(config)
        if not schemes:
            print("WARNING: No annotation schemes found in configuration", file=sys.stderr)

        # Detect conflicts
        conflicts = detect_keybinding_conflicts(schemes)

        # Generate output
        if args.layout_only:
            # Output just the task layout HTML snippet
            print(generate_layout_html(schemes))
        elif args.format == 'html':
            print(generate_preview_html(schemes))
        elif args.format == 'json':
            print(generate_preview_json(config, schemes, issues))
        else:  # summary
            print(generate_preview_summary(config, schemes, issues, conflicts))

        # Exit with error code if there are issues (skip for layout-only mode)
        if not args.layout_only:
            error_count = len([i for i in issues if i.startswith('ERROR')])
            sys.exit(1 if error_count > 0 else 0)

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error: Invalid YAML in configuration file: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
