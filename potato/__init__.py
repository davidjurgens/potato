"""
Potato Annotation Platform

A flexible, web-based platform for text annotation tasks.

This package provides a comprehensive annotation system with the following features:
- Multi-phase annotation workflows (consent, instructions, training, annotation, post-study)
- Support for various annotation types (labels, spans, text, likert scales, best-worst scaling)
- User authentication and session management
- Active learning capabilities
- Admin dashboard for monitoring progress
- Configurable assignment strategies
- Multi-language and multi-task support

Main Components:
- flask_server: Core Flask application and server logic
- routes: HTTP route handlers and request processing
- user_state_management: User progress tracking and state persistence
- item_state_management: Data item management and assignment
- authentificaton: User authentication backends
- admin: Admin dashboard functionality
- activelearning: Active learning algorithms and model training

Usage:
    from potato.flask_server import create_app
    app = create_app()
    app.run()
"""

from .flask_server import create_app

__version__ = "2.4.3"
__author__ = "Potato Annotation Platform Team"
__description__ = "A flexible, web-based platform for text annotation tasks"


def __getattr__(name):
    """Lazy imports for optional heavy dependencies."""
    if name == "load_as_dataset":
        from .datasets_integration import load_as_dataset
        return load_as_dataset
    if name == "load_annotations":
        from .datasets_integration import load_annotations
        return load_annotations
    raise AttributeError(f"module 'potato' has no attribute {name!r}")