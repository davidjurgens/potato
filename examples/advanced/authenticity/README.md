# Authenticity paradata

Page-level authenticity paradata (page leaves, item copies, external pastes, automation) on a rating task.

It works on every task type, not just free text. Potato records:

- when the annotator leaves the page or switches windows;
- when they copy the item, and whether they then left the page or pasted outside text;
- when the browser window is squeezed beside another window;
- signs of automation: `navigator.webdriver`, script-generated input, clicks that
  land in a new place with no mouse movement.

Copied and pasted text never leaves the browser. Only counts, durations and word
counts are sent.

```bash
python potato/flask_server.py start examples/advanced/authenticity/config.yaml -p 8000
```

To try it:

1. Rate an item.
2. Copy the statement and switch to another tab for 15 seconds.
3. Come back and rate the next item.
4. Open the admin dashboard, go to **Behavioral**, then **Authenticity**. The first
   item shows `copy_then_away`.

See [docs/advanced/authenticity_paradata.md](../../../docs/advanced/authenticity_paradata.md).
