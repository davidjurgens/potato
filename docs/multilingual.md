# Localization & Multilingual UI

Potato supports localizing the entire annotation interface -- including the login page, navigation, annotation controls, content headings, and footer -- into any language via YAML configuration. RTL (right-to-left) languages like Arabic and Hebrew are also supported.

## Quick Start

Add a `ui_language` section to your project config:

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

Potato localizes three areas of the interface:

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

This creates per-language config files with `[KEY]` placeholders replaced by translations from the CSV. See the script's `--help` for details.

## Related Documentation

- [Configuration Reference](configuration.md) -- All configuration options
- [Quick Start](quick-start.md) -- Getting started with Potato
