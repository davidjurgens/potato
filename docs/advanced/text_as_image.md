# Text as Image

Potato can render each item's text to a picture. The annotator reads the
picture. The words never reach the browser, so an annotator cannot select the
text, copy it, or paste it into a chatbot.

Turn the feature on with one key:

```yaml
text_as_image: true
```

## What the feature stops

An annotator who wants a shortcut usually selects the item text, copies it, and
pastes it into a chatbot. Three routes make that easy:

- The visible text in the item box.
- The `data-original-text` attribute, which span annotation reads.
- The item record, which the page embeds as JSON for dynamic schemas.

The server blanks all three and sends a PNG instead. "Select all", "copy" and
"view source" then return nothing to paste.

## What the feature does not stop

An annotator can still read the picture and retype the words. An annotator can
also screenshot the picture and run OCR on it, or point a phone camera at the
screen. The feature raises the cost of the shortcut. It does not remove the
shortcut.

Treat it as one control among several. Combine it with
[keystroke logging](keystroke_logging.md), which reports whether free text was
typed or pasted.

## Span schemes are refused

Every span scheme anchors its annotations to character offsets in the instance
text. The feature removes that text, so an annotator has nothing to select.

Potato refuses to start when `text_as_image` meets one of these schemes:

- `span`
- `span_link`
- `error_span`
- `coreference`
- `event_annotation`
- `extractive_qa`
- `context_attribution`
- `multi_document_event`

The message names the scheme:

```text
Configuration error: text_as_image is incompatible with these annotation
schemes: span. Each one anchors its annotations to character offsets in the
instance text, and text_as_image removes that text from the page, so an
annotator would have nothing to select. Turn off text_as_image, or use a
scheme that does not select text.
```

## Schemes that read the item text are refused

Some schemes name the data field they read with an attribute of their own:

- `text_edit` reads `source_field`
- `card_sort` reads `items_field`
- `conjoint` reads `profiles_field`
- `pairwise` reads `items_key`

About thirty such attributes exist across the registry. If the attribute names
the item text field, the scheme reads a field the feature blanks, and the scheme
renders empty. Potato refuses to start and names the scheme and the attribute:

```text
Configuration error: text_as_image is incompatible with these annotation
schemes: post_edit (source_field: text). Each one reads a data field that
text_as_image removes from the page, so the scheme would render empty. Point
the scheme at a different field, or turn off text_as_image.
```

Point the scheme at a different field, or turn `text_as_image` off. A
`text_edit` scheme that post-edits a separate `mt_output` field, for example,
runs beside the feature without trouble.

## Why these are errors

A warning is easy to miss, and both failures are quiet. The annotator sees a
picture, the scheme finds nothing, and the study collects empty annotations. It
looks like it worked. The same reasoning applies to live ingestion with the
BATCH assignment strategy.

Potato checks in this order:

1. Does the feature apply at all? A media or `instance_display` project renders
   the item itself, so the feature stays inert and nothing can conflict.
2. Is a span scheme present? Refuse.
3. Does a scheme read the blanked field? Refuse.

Step 1 comes first on purpose. An image project sets `text_key` to `image_url`
and its scheme reads `source_field: image_url`. That looks like a conflict, but
the feature never runs there, so it is not one.

## The one cost

**A screen reader gets nothing.** The alt text stays generic on purpose. Real
alt text would put the words back into the page and undo the feature. If your
study must stay accessible, leave `text_as_image` off.

Potato writes a warning at startup to state this.

## Options

The mapping form takes two more keys:

```yaml
text_as_image:
  enabled: true
  font_size: 20      # points, default 18
  max_width: 800     # CSS pixels, default 900
```

Potato renders the picture at twice `font_size` and `max_width`, then displays
it at half. The text therefore stays sharp on a high-density screen.

The picture uses a white background and near-black text, to match the light card
that holds the item.

## Where the feature applies

The feature replaces the item text box. It does nothing on a project that
renders the item some other way:

- A project with an `instance_display` block.
- A project with a `video_annotation`, `audio_annotation` or `image_annotation`
  scheme.
- A project with a `tiered_annotation` scheme whose `media_type` is `video` or
  `audio`.

On these projects the text box is a hidden fallback, not the thing the annotator
reads. Potato writes a warning at startup and changes nothing.

Practice questions in the [training phase](../guides/getting-started.md) get the
same treatment as items.

## How it works

`potato/server_utils/text_to_image.py` renders the PNG with Pillow and inlines
it as a `data:` URI. The markup comes from a base64 payload, never from
annotation content.

The result is cached per text, font size and width, so a page reload costs
nothing. A typical paragraph produces 20 to 30 KB.

## Related

- [Keystroke Logging](keystroke_logging.md)
- [Behavioral Tracking](behavioral_tracking.md)
- [Configuration Reference](../configuration/config_reference.md)
