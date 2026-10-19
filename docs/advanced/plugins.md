# Plugins

A plugin is a Python package that adds annotation types or display types to
Potato without changing Potato itself. A project turns a plugin on by naming it
in its config, and the plugin's types are then used like the built-in ones:
`potato validate` checks them, the annotation page renders them, and their
answers are saved, exported and counted in agreement the same way.

## Using a plugin

Install the package, then list the plugins it provides:

```bash
pip install potato-plugin-example
potato plugins
```

```
counter              potato-plugin-example 0.1.0  (potato_plugin_example:register)
```

Name the plugin under `plugins:` and use its types:

```yaml
plugins:
  - counter

instance_display:
  fields:
    - key: text
      type: word_count        # a display type from the plugin

annotation_schemes:
  - annotation_type: counter  # an annotation type from the plugin
    name: people
    description: How many people does the scene mention?
    min: 0
    max: 50
```

Editors that check configs against the published JSON Schema (the
`yaml-language-server` line at the top of the example configs) mark plugin
types as unknown, because the schema lists built-in types only. `potato
validate` loads the listed plugins and checks their types.

Coding agents connected through the [MCP server](../tools/mcp_server.md) can
call `list_plugins`, which reads package metadata and imports nothing
(`list_plugins(name)` loads one plugin and lists its types), and
`list_annotation_types` and `list_display_types`
give each type's `plugin` (`null` for a built-in).

`potato plugins counter` loads one plugin and prints the types, scripts and
styles it registers. Use it to check an install.

| Key | Default | Meaning |
|---|---|---|
| `plugins` | none | Installed plugins to load, by entry-point name |

### Validation checks

- Each listed plugin must be installed. An unknown name is an error that lists
  the installed ones.
- A plugin may not reuse the name of a built-in type or of another plugin's
  type. If it tries, none of its types are registered.
- Questions in survey-phase files (`phases: ... file:`) are checked the same
  way as `annotation_schemes`: each type must be built in or come from a
  listed plugin.
- A config that uses a plugin's type must list that plugin. This matters when
  one process validates several configs, as the MCP server does: without the
  check, a config could pass there and fail on a fresh `potato start`.

## Security

A plugin is ordinary Python. It runs inside the server process with the
server's permissions, and can read the data, the annotations and the
credentials the server can. Install plugins only from sources you would trust
with that access.

Two rules limit what a config alone can do:

- Only plugins listed under `plugins:` are loaded. Installing a package does
  not change any project that does not name it.
- `plugins:` takes entry-point names, not file paths or module names. A config
  cannot load code from a path, so editing a config cannot run code that was
  not installed into the environment.

## Writing a plugin

The example in `examples/plugins/counter/` is a complete plugin and project.
Install it and run the project from the repository root:

```bash
pip install -e examples/plugins/counter/plugin
python potato/flask_server.py start examples/plugins/counter/config.yaml -p 8000
```

### Package layout

```
plugin/
├── pyproject.toml
└── potato_plugin_example/
    ├── __init__.py          # register(api)
    └── static/
        ├── counter.js
        └── counter.css
```

The entry point goes in the `potato.plugins` group. Its name is what configs
list:

```toml
[project.entry-points."potato.plugins"]
counter = "potato_plugin_example:register"
```

The entry point can name a function, or a module that has a `register`
function. Include the static folder as package data so it is installed with
the code.

### The register function

```python
def register(api):
    api.add_schema("counter", generate_counter_layout,
                   optional_fields=["min", "max", "step", "start"],
                   description="A number with - and + buttons")
    api.add_display("word_count", WordCountDisplay())
    api.add_assets("static", scripts=["counter.js"], styles=["counter.css"])
```

| Method | What it registers |
|---|---|
| `add_schema(name, generator, required_fields=("name", "description"), optional_fields=(), description="", supports_keybindings=False)` | An annotation type |
| `add_display(name, display)` | A display type: an instance of `potato.server_utils.displays.base.BaseDisplay` |
| `add_assets(static_dir, scripts=(), styles=())` | A folder served at `/plugin-static/<plugin>/`, and the files in it to load on every page |

Nothing is registered until `register` returns. If it raises, or if any name
is taken, the plugin registers no types and validation reports the error.

### Annotation types

A generator takes the scheme's config and returns `(html, keybindings)`, like
the built-in generators in `potato/server_utils/schemas/`. List every config
key the generator reads in `optional_fields`; validation warns about any other
key on a scheme of that type.

The HTML must use inputs the annotation page already knows how to save and
restore, or the answer is lost when the annotator moves to another item:

- an `<input>` with class `annotation-input`, a `schema` attribute set to the
  scheme name, and a `label_name` attribute;
- `generate_element_identifier(scheme_name, label_name, element_type)` from
  `potato.server_utils.schemas.identifier_utils` builds the `id`, `name`,
  `schema` and `label_name` values;
- number, text, radio, checkbox and hidden inputs are saved and restored by
  the page. A hidden input needs the `data-modified` attribute set when the
  plugin's script changes it.

A script that changes an input's value should dispatch `input` and `change`
events on it, as `counter.js` does, so the page saves it.

To check persistence, answer an item, press Next, press Previous, and confirm
the answer is still shown. A page refresh is not a check: browsers restore form
values across a refresh even when nothing was saved.

### Scripts and styles

Files named in `add_assets` load on every annotation and phase page, after
`annotation.js`, at
`/plugin-static/<plugin>/<file>?v=<package version>`. Bump the package
version when a file changes so browsers fetch the new copy. The page's design
tokens (`--border`, `--ring`, `--space-sm`, `--text-sm` and others in
`potato/static/styles.css`) are available to plugin CSS.

## Troubleshooting

| Message | Cause |
|---|---|
| `plugin 'x' is not installed` | The package is not installed in the environment running Potato, or its entry point is in another group. `potato plugins` shows what is installed. |
| `uses names that already exist` | A type name collides with a built-in or with another plugin. Rename the type. |
| `annotation type 'x' comes from plugin 'y'; add 'y' to plugins` | The config uses a plugin type without listing the plugin. |
| `raised while registering` | The plugin's `register` function failed; the message ends with its error. |

## Related

- [Display types](../annotation-types/instance_display.md)
- [Configuration reference](../configuration/config_reference.md)
