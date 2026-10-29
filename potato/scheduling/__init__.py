"""
Scheduled sessions: waves, experience sampling, Delphi rounds, and the
notifications that bring participants back.

    schedule:            when sessions open and close, per participant
    notifications:       email (SMTP), SMS (Twilio), Prolific messages, log

A participant is enrolled when they finish the regular study flow. Their
sessions are computed then, in their time zone, and stored with the
notification plan in ``<output_annotation_dir>/scheduling/schedule.sqlite``;
contact details go to a separate store outside the output directory. A
background thread (started with the routes, never at import) sends what is
due. See docs/workflow/scheduling.md.

Modules: ``config`` (validation), ``planner`` (session times), ``store``
(SQLite), ``links`` (signed resume links), ``notify`` (channels), ``delphi``
(round statistics), ``manager`` (the loop), ``routes`` (pages).
"""
