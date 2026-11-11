"""Live collaborative sessions: a team annotating the same items together.

A team's shared answer for each item is stored under one team user
(``team-<slug>``), so exports, agreement and adjudication see the team as one
annotator. Members work on the ordinary annotation page; each save is merged
into the team's answer (``state.py``), logged with its author
(``manager.py``), and shown on teammates' pages by ``static/collab.js``.

- ``config``   the ``collab:`` block
- ``models``   the event-sourced session
- ``state``    snapshots, diffs and the three-way merge
- ``manager``  sessions, logs, team users, presence (singleton)
- ``writes``   the /updateinstance interceptor
- ``context``  which user a data request reads or writes
- ``describe`` readable change lines
- ``routes``   the /collab blueprint
"""

from .manager import clear_collab_manager, get_collab_manager, init_collab_manager

__all__ = ["init_collab_manager", "get_collab_manager", "clear_collab_manager"]
