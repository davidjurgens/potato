# Importer fixtures: Label Studio and Argilla

Hand-built from each tool's documented export format (October 2026), not
exported from a running instance:

- `label_studio/*_project.json`: Label Studio "JSON" export (tasks with
  `data`, `annotations`, `predictions`), with the matching labeling config XML.
  `text_project.json` puts an emoji before a span so its JavaScript (UTF-16)
  offsets differ from Python's.
- `argilla/to_disk/`: `Dataset.to_disk()` layout (`.argilla/settings.json`,
  `.argilla/dataset.json`, `records.json`), record dicts as `Record.to_dict()`
  writes them (responses carry `value` and `user_id`, no status).
- `argilla/to_hub/`: a `to_hub` snapshot with flattened columns
  (`<q>.responses`, `.responses.users`, `.responses.status`, `<q>.suggestion`,
  `.suggestion.score`, `.suggestion.agent`), as JSON lines rather than parquet.
