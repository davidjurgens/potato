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

__version__ = "2.8.2"
__author__ = "Potato Annotation Platform Team"
__description__ = "A flexible, web-based platform for text annotation tasks"

__all__ = ["create_app", "load_as_dataset", "load_annotations", "__version__"]


def __getattr__(name):
    """Lazy imports, so importing a submodule does not build the server.

    ``create_app`` used to be imported eagerly here, which meant that
    ``import potato.anything`` pulled in Flask, the route table and both state
    managers. That is wasteful everywhere and wrong in one place: the training
    subprocess is supposed to be able to load a trainer without the web stack,
    and it could not, because reaching ``potato.training.worker`` ran this
    module first.

    ``from potato import create_app`` still works -- PEP 562 resolves it on
    first access.
    """
    if name == "create_app":
        from .flask_server import create_app
        return create_app
    if name == "load_as_dataset":
        from .datasets_integration import load_as_dataset
        return load_as_dataset
    if name == "load_annotations":
        from .datasets_integration import load_annotations
        return load_annotations
    raise AttributeError(f"module 'potato' has no attribute {name!r}")