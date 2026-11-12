"""A plugin whose entry point names a module with a register() function."""


def register(api):
    from potato_test_plugin import ShoutDisplay
    api.add_display("test_module_display", ShoutDisplay())
