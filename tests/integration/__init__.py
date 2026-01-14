"""
Integration tests for Potato Annotation Platform.

These tests verify complete user workflows and ensure that real users
would experience the platform correctly. Unlike unit tests, these tests
start actual servers and use real browsers to interact with the UI.

Test Categories:
- smoke: Server startup and basic functionality
- workflows: Complete user journeys (onboarding, training, etc.)
- annotation_types: E2E tests for each annotation type
- persistence: State preservation across navigation/refresh
- error_handling: Graceful failure modes
- edge_cases: Boundary conditions and stress tests
"""
