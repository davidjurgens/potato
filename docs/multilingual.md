# Multilingual UI

Potato supports translating the annotation interface into any language by configuring UI string overrides in your YAML config file.

## Configuration

Add a `ui_language` section to your config file to override the default English strings:

```yaml
ui_language:
  next_button: "Weiter"
  previous_button: "Zurück"
  labeled_badge: "Beschriftet"
  not_labeled_badge: "Nicht beschriftet"
  submit_button: "Absenden"
  progress_label: "Fortschritt"
  go_button: "Los"
  logout: "Abmelden"
  loading: "Annotationsoberfläche wird geladen..."
  error_heading: "Fehler"
  retry_button: "Wiederholen"
  adjudicate: "Adjudikation"
```

## Available Keys

| Key | Default (English) | Description |
|-----|-------------------|-------------|
| `next_button` | Next | Navigation button to go to next instance |
| `previous_button` | Previous | Navigation button to go to previous instance |
| `labeled_badge` | Labeled | Status badge when instance has annotations |
| `not_labeled_badge` | Not labeled | Status badge when instance has no annotations |
| `submit_button` | Submit | Form submission button |
| `progress_label` | Progress | Label for progress counter |
| `go_button` | Go | "Go to instance" button |
| `logout` | Logout | Logout link text |
| `loading` | Loading annotation interface... | Loading state message |
| `error_heading` | Error | Error state heading |
| `retry_button` | Retry | Error retry button |
| `adjudicate` | Adjudicate | Adjudication mode link |

## Notes

- All keys are optional. Any key not specified will use the English default.
- This feature only covers the annotation interface UI chrome. Schema descriptions, labels, and instructions are controlled by your annotation scheme configuration.
- For translating surveyflow content (consent, instructions), write those HTML/JSON files directly in the target language.
- This feature works alongside the existing `[KEY]` substitution system in `setup_multilingual_config.py` for config-level translations.

## Example

Chinese interface:

```yaml
ui_language:
  next_button: "下一个"
  previous_button: "上一个"
  labeled_badge: "已标注"
  not_labeled_badge: "未标注"
  progress_label: "进度"
  logout: "退出"
  loading: "正在加载标注界面..."
```
