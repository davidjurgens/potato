"""Built-in trainers.

Nothing is imported here. Trainers are resolved by name through
``potato.training.registry``, which holds module paths rather than classes, so
listing the available trainers costs nothing even when several of them would
pull in torch.
"""
