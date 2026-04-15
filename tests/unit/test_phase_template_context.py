"""
Unit tests verifying that non-annotation phase pages (consent, instructions,
poststudy) can render the shared base template without UndefinedError.

Regression test for GitHub issue #146: the generated consent template
referenced `instance_index` which was not in the rendering context,
causing a Jinja2 crash on page load.
"""

import os

import pytest
from jinja2 import Environment, FileSystemLoader, UndefinedError


# Minimal context that get_current_page_html() provides for phase pages
PHASE_PAGE_CONTEXT = {
    'username': 'test_user',
    'annotation_task_name': 'Test Task',
    'annotation_codebook_url': '',
    'debug_mode': False,
    'ui_debug': False,
    'server_debug': False,
    'debug_phase': None,
    'instance': '',
    'instance_plain_text': '',
    'instance_id': '',
    'instance_index': 0,
    'finished': 0,
    'total_count': 0,
    'ui_config': {},
    'is_annotation_page': False,
    'annotation_instructions': '',
    'annotation_status': 'unlabeled',
    'instance_has_annotations': False,
    'can_go_back': False,
    'jumping_to_id_disabled': False,
}


def _get_template_dir():
    """Return the path to potato/templates/."""
    return os.path.normpath(os.path.join(
        os.path.dirname(__file__), '..', '..', 'potato', 'templates'
    ))


def _make_jinja_env():
    """Create a Jinja2 environment that can render the base template.

    Registers stub globals/filters for Flask builtins (url_for, sanitize_html)
    so we can test template variable resolution without a full Flask app.
    """
    template_dir = _get_template_dir()
    env = Environment(loader=FileSystemLoader(template_dir))
    # Stub Flask's url_for
    env.globals['url_for'] = lambda endpoint, **kw: f'/static/{kw.get("filename", "")}'
    # Stub the custom sanitize_html filter
    env.filters['sanitize_html'] = lambda x: x
    return env


def _generate_phase_template(config, phase_name, annotation_schemes):
    """Generate a phase template using the real front_end pipeline."""
    from potato.server_utils.front_end import generate_html_from_schematic

    return generate_html_from_schematic(
        annotation_schemes,
        False,  # allow_jumping_to_id
        False,  # hide_navbar
        phase_name,
        config,
        None,  # task_layout_file
    )


class TestPhaseTemplateContext:
    """Verify that phase page contexts render without UndefinedError."""

    @pytest.fixture(autouse=True)
    def setup_test_dir(self, tmp_path):
        self.test_dir = str(tmp_path / "phase_template_test")
        os.makedirs(self.test_dir, exist_ok=True)
        yield

    def _simple_config(self):
        return {
            'annotation_task_name': 'Phase Template Test',
            'task_dir': self.test_dir,
            'site_dir': _get_template_dir(),
            'output_annotation_dir': os.path.join(self.test_dir, 'output'),
            'jumping_to_id_disabled': False,
            'hide_navbar': False,
        }

    def _simple_schemes(self):
        return [
            {
                'annotation_type': 'radio',
                'name': 'test_question',
                'description': 'A test question',
                'labels': ['Yes', 'No'],
            }
        ]

    def _render_generated_template(self, template_fname, context):
        """Render a generated template with the given context.

        Raises UndefinedError if any required variable is missing.
        """
        env = _make_jinja_env()
        template = env.get_template(os.path.join('generated', template_fname))
        return template.render(**context)

    def test_consent_template_renders_with_phase_context(self):
        """Issue #146: consent page must not crash on instance_index."""
        config = self._simple_config()
        schemes = self._simple_schemes()
        template_fname = _generate_phase_template(config, 'consent', schemes)

        html = self._render_generated_template(template_fname, PHASE_PAGE_CONTEXT)
        assert 'Test Task' in html

    def test_instructions_template_renders_with_phase_context(self):
        """Instructions page uses the same base template and must not crash."""
        config = self._simple_config()
        schemes = self._simple_schemes()
        template_fname = _generate_phase_template(config, 'instructions', schemes)

        html = self._render_generated_template(template_fname, PHASE_PAGE_CONTEXT)
        assert 'Test Task' in html

    def test_poststudy_template_renders_with_phase_context(self):
        """Poststudy page uses get_current_page_html and must not crash."""
        config = self._simple_config()
        schemes = self._simple_schemes()
        template_fname = _generate_phase_template(config, 'poststudy', schemes)

        html = self._render_generated_template(template_fname, PHASE_PAGE_CONTEXT)
        assert 'Test Task' in html

    def test_instance_index_shown_on_annotation_context(self):
        """When instance_index is provided, it should appear in the rendered HTML."""
        config = self._simple_config()
        schemes = self._simple_schemes()
        template_fname = _generate_phase_template(config, 'annotation', schemes)

        annotation_context = dict(PHASE_PAGE_CONTEXT)
        annotation_context['instance_index'] = 4
        annotation_context['is_annotation_page'] = True

        html = self._render_generated_template(template_fname, annotation_context)
        assert '#5' in html  # instance_index 4 → display as #5

    def test_instance_index_hidden_when_undefined(self):
        """When instance_index is not in context, the section should not render."""
        config = self._simple_config()
        schemes = self._simple_schemes()
        template_fname = _generate_phase_template(config, 'consent', schemes)

        # Remove instance_index from context entirely
        context_without_index = {
            k: v for k, v in PHASE_PAGE_CONTEXT.items()
            if k != 'instance_index'
        }

        # Must not crash
        html = self._render_generated_template(template_fname, context_without_index)
        assert 'instance-number' not in html

    def test_jumping_to_id_disabled_hides_nav_controls(self):
        """When jumping_to_id_disabled is True, nav controls should be hidden."""
        config = self._simple_config()
        schemes = self._simple_schemes()
        template_fname = _generate_phase_template(config, 'consent', schemes)

        context = dict(PHASE_PAGE_CONTEXT)
        context['jumping_to_id_disabled'] = True

        html = self._render_generated_template(template_fname, context)
        assert 'jump-unannotated-btn' not in html
