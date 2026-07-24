# Localization & Multilingual UI

Potato localizes the entire interface -- the login page, navigation, annotation controls, content headings, footer, the **annotator progress dashboard**, and the **admin dashboard** -- via the `ui_language` config. RTL (right-to-left) languages like Arabic are supported through the existing `html_dir` setting.

There are two ways to set a language:

1. **Bundled language (easiest):** point `ui_language` at a shipped language code and get a complete translated UI with zero hand-translation.
2. **Inline overrides:** provide your own strings key-by-key (also used to tweak a bundled language).

## Quick Start: use a bundled language

Set `ui_language` to a single language **code** (a string):

```yaml
ui_language: es      # Spanish UI, out of the box
```

Bundled catalogs ship for 10 languages:

| Code | Language | Code | Language |
|------|----------|------|----------|
| `es` | Spanish | `pt` | Portuguese |
| `zh` | Chinese (Simplified) | `hi` | Hindi |
| `fr` | French | `ja` | Japanese |
| `de` | German | `ru` | Russian |
| `ar` | Arabic (RTL) | `ko` | Korean |

An unknown code logs a warning and falls back to English -- it never crashes the server. The catalogs live in `potato/i18n/<code>.yaml`; they are machine-assisted and community-improvable, so corrections and new languages via pull request are welcome.

### Start from a bundled language and override a few strings

Use the `_base` key to load a bundled catalog, then override individual strings on top:

```yaml
ui_language:
  _base: es                       # start from bundled Spanish
  login_title: "Mi Proyecto"      # override just the title
  next_button: "Continuar"        # ...and one button
```

Precedence is: English defaults → bundled catalog → your inline overrides.

## Quick Start: fully custom (inline) strings

To supply your own translation without a bundled base, give `ui_language` a dict of keys:

```yaml
ui_language:
  html_lang: de                        # HTML lang attribute
  next_button: "Weiter"
  previous_button: "Zurück"
  logout: "Abmelden"
  sign_in_button: "Anmelden"
  username_label: "Benutzername"
```

All keys are optional. Any key not specified uses the English default.

## What Gets Localized

Potato localizes five areas of the interface:

### 1. Annotation Interface (main annotation page)

| Key | Default | Where It Appears |
|-----|---------|-----------------|
| `next_button` | Next | Navigation: next instance button |
| `previous_button` | Previous | Navigation: previous instance button |
| `submit_button` | Submit | Form submission button |
| `go_button` | Go | "Go to instance" jump button |
| `retry_button` | Retry | Error recovery button |
| `logout` | Logout | Logout link in header |
| `labeled_badge` | Labeled | Status badge (annotated instances) |
| `not_labeled_badge` | Not labeled | Status badge (unannotated instances) |
| `progress_label` | Progress | Label next to progress counter |
| `loading` | Loading annotation interface... | Loading spinner message |
| `error_heading` | Error | Error panel heading |
| `adjudicate` | Adjudicate | Adjudication mode link |
| `codebook` | Codebook | Codebook link |
| `instructions_heading` | Instructions | Collapsible instructions heading |
| `text_to_annotate` | Text to Annotate: | Content heading for text instances |
| `video_to_annotate` | Video to Annotate: | Content heading for video instances |
| `audio_to_annotate` | Audio to Annotate: | Content heading for audio instances |

### 2. Login & Registration Page

| Key | Default | Where It Appears |
|-----|---------|-----------------|
| `login_title` | Annotation Platform | Page title and main heading |
| `login_subtitle_password` | Sign in to continue | Subtitle when password required |
| `login_subtitle_username` | Enter your username to continue | Subtitle for username-only login |
| `sign_in_tab` | Sign In | Login tab label |
| `register_tab` | Register | Registration tab label |
| `username_label` | Username | Username field label |
| `password_label` | Password | Password field label |
| `sign_in_button` | Sign In | Login submit button |
| `continue_button` | Continue | Username-only submit button |
| `register_button` | Register | Registration submit button |
| `forgot_password` | Forgot Password? | Password reset link |
| `username_placeholder` | Enter your username | Login username placeholder |
| `choose_username_placeholder` | Choose a username | Registration username placeholder |
| `create_password_placeholder` | Create a password | Registration password placeholder |
| `sign_in_with` | Sign in with | OAuth button prefix |
| `or_divider` | or | Divider between OAuth and local login |

### 3. Footer & Page Metadata

| Key | Default | Where It Appears |
|-----|---------|-----------------|
| `powered_by` | Powered by | Footer attribution prefix |
| `cite_us` | Cite Us | Citation link text |
| `html_lang` | en | HTML `lang` attribute (affects browser behavior, accessibility) |
| `html_dir` | ltr | HTML `dir` attribute (`ltr` or `rtl`) |

### 4. Annotator Progress Dashboard

The opt-in annotator progress page (`/progress`, enabled via `annotator_dashboard`).

| Key | Default | Where It Appears |
|-----|---------|-----------------|
| `dash_subtitle` | Your annotation progress | Page subtitle |
| `dash_your_progress` | Your progress | Personal progress heading |
| `dash_project_progress` | Project progress | Project progress heading |
| `dash_stat_annotated` | Annotated | Personal stat card |
| `dash_stat_assigned` | Assigned | Personal stat card |
| `dash_stat_complete` | Complete | Personal stat card |
| `dash_stat_total_items` | Total items | Project stat card |
| `dash_stat_items_started` | Items started | Project stat card |
| `dash_stat_annotations` | Annotations | Project stat card |
| `dash_stat_active_annotators` | Active annotators | Project stat card |
| `dash_loading` | Loading… | Progress-bar caption while loading |
| `dash_error` | Could not load progress right now. | Error message |
| `dash_back_to_annotating` | Back to annotating | Return link |
| `dash_readonly` | Read-only view | View badge |
| `dash_no_items_assigned` | No items assigned to you yet | Caption (0 assigned) |
| `dash_assigned_completed` | `{n} of {total} assigned items completed` | Caption (placeholders `{n}`, `{total}`) |
| `dash_no_items_project` | No items in this project yet | Caption (empty project) |
| `dash_items_started_pct` | `{started} of {total} items started ({pct}%)` | Caption (placeholders `{started}`, `{total}`, `{pct}`) |

> **Placeholders** in `{braces}` (e.g. `{n}`, `{total}`, `{pct}`) are filled in at runtime and must be preserved verbatim in any translation.

### 5. Admin Dashboard

The admin dashboard (`/admin`) and its API-key gate (`admin_login.html`).

| Key | Default | Where It Appears |
|-----|---------|-----------------|
| `admin_mode_badge` | Admin Mode | Header badge |
| `admin_page_title` | Admin Dashboard | Page title / header |
| `admin_tab_overview` | Overview | Tab label |
| `admin_tab_annotators` | Annotators | Tab label |
| `admin_tab_instances` | Instances | Tab label |
| `admin_tab_questions` | Questions | Tab label |
| `admin_tab_behavioral` | Behavioral | Tab label |
| `admin_tab_crowdsourcing` | Crowdsourcing | Tab label |
| `admin_tab_bws` | BWS Scoring | Tab label (if enabled) |
| `admin_tab_mace` | MACE | Tab label (if enabled) |
| `admin_tab_embeddings` | Embeddings | Tab label (if enabled) |
| `admin_tab_datasets` | Datasets & Experiments | Header link (if enabled) |
| `admin_tab_configuration` | Configuration | Tab label |
| `admin_section_system_info` | System Information | Overview section heading |
| `admin_section_ai_usage` | AI Assistance Usage | Section heading |
| `admin_section_quality` | Quality Indicators | Section heading |
| `admin_section_bws_scores` | BWS Item Scores | Section heading |
| `admin_section_competence` | Annotator Competence | Section heading |
| `admin_err_overview` … `admin_err_config` | Failed to load … | JS status/error toasts |
| `admin_ok_config_saved` | Configuration updated successfully | Success toast |
| `admin_btn_computing` | Computing… | BWS button (busy state) |
| `admin_btn_generate_scores` | Generate Scores | BWS button |
| `admin_login_title` | Admin Access | Login gate heading |
| `admin_login_key_label` | Admin API key | Login field label |
| `admin_login_key_placeholder` | Admin API key | Login field placeholder |
| `admin_login_submit` | Access Dashboard | Login submit button |
| `admin_login_help` | The admin API key is stored in admin_api_key.txt… | Login help text |

The bundled catalogs already translate all of these. Only override them if you are supplying a fully custom inline language.

The admin dashboard's tab bodies (table headers, filters, the configuration form) and the specialist admin sub-pages — IAA, judge alignment, annotation integrity, triage queue, catalog, datasets, experiment compare, arena, automation rules, eval analytics — are also fully covered by the bundled catalogs. Their keys are namespaced by page (`iaa_*`, `judge_*`, `datasets_*`, `arena_*`, `catalog_*`, `automation_*`, `evalanalytics_*`, `expcompare_*`, `dsdetail_*`, `integrity_*`, `triage_*`). Any key left untranslated falls back to English, so partial catalogs render cleanly.

## Language & Direction

Set `html_lang` to the appropriate [BCP 47 language tag](https://www.w3.org/International/articles/language-tags/) and `html_dir` for text direction:

```yaml
# Arabic (right-to-left)
ui_language:
  html_lang: ar
  html_dir: rtl
  next_button: "التالي"
  previous_button: "السابق"
  logout: "تسجيل الخروج"
  sign_in_button: "تسجيل الدخول"
  username_label: "اسم المستخدم"
  password_label: "كلمة المرور"

# Japanese
ui_language:
  html_lang: ja
  next_button: "次へ"
  previous_button: "前へ"
  logout: "ログアウト"
  progress_label: "進捗"

# Spanish
ui_language:
  html_lang: es
  next_button: "Siguiente"
  previous_button: "Anterior"
  logout: "Cerrar sesión"
  sign_in_button: "Iniciar sesión"
  register_button: "Registrarse"
  username_label: "Usuario"
  password_label: "Contraseña"
  loading: "Cargando interfaz de anotación..."
```

## Complete Example: German

```yaml
ui_language:
  html_lang: de
  # Annotation interface
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
  codebook: "Codebuch"
  instructions_heading: "Anweisungen"
  text_to_annotate: "Text zur Annotation:"
  video_to_annotate: "Video zur Annotation:"
  audio_to_annotate: "Audio zur Annotation:"
  # Login page
  login_title: "Annotationsplattform"
  login_subtitle_password: "Melden Sie sich an, um fortzufahren"
  login_subtitle_username: "Geben Sie Ihren Benutzernamen ein"
  sign_in_tab: "Anmelden"
  register_tab: "Registrieren"
  username_label: "Benutzername"
  password_label: "Passwort"
  sign_in_button: "Anmelden"
  continue_button: "Weiter"
  register_button: "Registrieren"
  forgot_password: "Passwort vergessen?"
  username_placeholder: "Benutzername eingeben"
  choose_username_placeholder: "Benutzername wählen"
  create_password_placeholder: "Passwort erstellen"
  sign_in_with: "Anmelden mit"
  or_divider: "oder"
  # Footer
  powered_by: "Betrieben von"
  cite_us: "Zitieren"
```

## Complete Example: Chinese

```yaml
ui_language:
  html_lang: zh
  next_button: "下一个"
  previous_button: "上一个"
  labeled_badge: "已标注"
  not_labeled_badge: "未标注"
  submit_button: "提交"
  progress_label: "进度"
  go_button: "跳转"
  logout: "退出"
  loading: "正在加载标注界面..."
  error_heading: "错误"
  retry_button: "重试"
  instructions_heading: "说明"
  text_to_annotate: "待标注文本："
  login_title: "标注平台"
  sign_in_button: "登录"
  register_button: "注册"
  username_label: "用户名"
  password_label: "密码"
```

## What Is NOT Covered by ui_language

The `ui_language` config localizes the **UI chrome** -- buttons, labels, headings, and navigation. The following content must be translated separately:

| Content | How to Localize |
|---------|----------------|
| Annotation schema descriptions and labels | Write them in the target language in `annotation_schemes` config |
| Survey flow pages (consent, instructions, training) | Write HTML/JSON files in the target language and reference them in `surveyflow` config |
| Instance data (text to annotate) | Provide data files in the target language |
| Schema tooltips | Write tooltip text in target language in config |

### Localizing Schema Content

Write schema descriptions and labels directly in the target language:

```yaml
annotation_schemes:
  - annotation_type: radio
    name: sentiment
    description: "テキストの感情を選択してください"  # Japanese
    labels:
      - name: positive
        tooltip: "ポジティブな感情"
      - name: negative
        tooltip: "ネガティブな感情"
      - name: neutral
        tooltip: "中立"
```

### Localizing Survey Flow

Write consent, instructions, and training content in the target language:

```yaml
surveyflow:
  on: true
  order:
    - consent
    - instructions
    - annotation
  consent: surveyflow/consent_ja.html     # Japanese consent page
  instructions: surveyflow/instructions_ja.html
```

## Font Support for Non-Latin Scripts

Potato's default font (Outfit) only supports Latin characters. For CJK, Arabic, Devanagari, or other scripts, the system font stack provides fallback (`system-ui`, `-apple-system`), but you can load specific fonts via the `base_css` config:

```yaml
# Load CJK font support
base_css: "project_assets/cjk-fonts.css"
```

Where `project_assets/cjk-fonts.css` contains:

```css
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;600&display=swap');

:root {
  --font-sans: 'Noto Sans SC', 'Outfit', ui-sans-serif, system-ui, sans-serif;
}
```

Common Google Fonts for non-Latin scripts:
- **Chinese (Simplified):** `Noto Sans SC`
- **Chinese (Traditional):** `Noto Sans TC`
- **Japanese:** `Noto Sans JP`
- **Korean:** `Noto Sans KR`
- **Arabic:** `Noto Sans Arabic`
- **Hebrew:** `Noto Sans Hebrew`
- **Hindi/Devanagari:** `Noto Sans Devanagari`
- **Thai:** `Noto Sans Thai`

## Batch Multilingual Setup

For projects that need the same annotation task in multiple languages (e.g., cross-lingual studies), use `setup_multilingual_config.py`:

```bash
python potato/setup_multilingual_config.py \
  --config template_config.yaml \
  --languages en,de,zh,ar \
  --translations translations.csv \
  --output-dir configs/
```

This creates per-language config files with `[KEY]` placeholders replaced by translations from the CSV. See the script's `--help` for details. With bundled languages you can now often skip this entirely and just set `ui_language: <code>` per deployment.

## Contributing or Adding a Bundled Language

Bundled catalogs are plain YAML files under `potato/i18n/<code>.yaml`. Each is a flat map of the same keys documented above (mirroring `ui_lang_defaults` in `potato/flask_server.py`). To improve a translation or add a new language:

1. Copy an existing catalog (e.g. `potato/i18n/es.yaml`) to `potato/i18n/<code>.yaml`.
2. Translate the values, keeping every **key** unchanged and preserving `{brace}` placeholders verbatim.
3. Set `html_lang` to the code and `html_dir` to `rtl` for right-to-left languages.
4. The file is picked up automatically — `ui_language: <code>` will resolve to it.

A drift-guard test (`tests/unit/test_i18n_loader.py`) checks that every catalog has exactly the expected keys and intact placeholders, so a missing or stray key is caught in CI.

## Related Documentation

- [Configuration Reference](configuration.md) -- All configuration options
- [Quick Start](../quick-start.md) -- Getting started with Potato
