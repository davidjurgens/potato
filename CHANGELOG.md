# Changelog

All notable changes to the Potato annotation platform are documented in this file.

## [2.2.0] - Comprehensive Annotation & Export Platform

This release adds 9 new annotation schemas, intelligent annotation features (MACE, option highlighting, diversity ordering), a pluggable export system with 8 format backends, extended remote data source support, a standard survey instruments library, and major UX improvements including annotation navigation and form layout grids.

### New Annotation Schemas

#### N-ary Event Annotation
- Trigger-and-argument event annotation with hub-spoke arc visualization
- Define event types with typed argument roles (e.g., Agent, Patient, Location)
- Annotate triggers as spans, then attach argument spans to each trigger
- Configurable event type taxonomy with per-type argument constraints
- See [Event Annotation Guide](docs/event_annotation.md) for details

#### Entity Linking
- Link annotated spans to knowledge base entries (Wikidata, UMLS, or custom KBs)
- Inline search widget with auto-complete and candidate ranking
- Support for multiple KB backends with configurable endpoints
- See [Entity Linking Guide](docs/entity_linking.md) for configuration

#### Triage
- Rapid accept/reject/skip annotation for high-throughput screening tasks
- Single-click decisions with configurable keyboard shortcuts
- Progress indicators and throughput metrics
- See [Triage Guide](docs/triage.md) for setup

#### Pairwise Comparison
- Compare two items side-by-side with binary A/B selection or scale slider modes
- Configurable comparison dimensions and tie-breaking options
- Balanced pair generation strategies
- See [Pairwise Annotation Guide](docs/pairwise_annotation.md) for details

#### Conversation Tree Annotation
- Hierarchical annotation of multi-turn conversations as tree structures
- Branching dialogue support with parent-child turn relationships
- Per-turn and per-branch annotation labels
- See [Conversation Tree Guide](docs/conversation_tree_annotation.md) for details

#### Coreference Chain Annotation
- Mark and chain coreferring mentions across a document
- Color-coded chain visualization with merge and split operations
- Cluster-level and mention-level annotation support
- See [Coreference Annotation Guide](docs/coreference_annotation.md) for details

#### Segmentation Mask Tools
- Pixel-level fill and eraser tools for image segmentation
- Mask PNG export for downstream model training
- COCO RLE mask encoding for compact storage
- Configurable brush sizes and label-based mask layers

#### Bounding Box for PDF/Documents
- Draw bounding boxes on PDF pages and document images
- Per-page annotation with multi-page navigation
- Export in Pascal VOC and YOLO formats

#### Discontinuous/Multi-range Spans
- Select non-contiguous text spans as a single annotation unit
- Useful for capturing split antecedents and discontinuous entities

### Intelligent Annotation

#### MACE Annotator Competence Estimation
- Integration of Multi-Annotator Competence Estimation (MACE) for modeling annotator reliability
- Per-annotator competence scores surfaced in admin dashboard
- Weighted aggregation of annotations based on estimated competence
- See [MACE Guide](docs/mace.md) for details

#### LLM-based Option Highlighting
- AI-powered visual highlighting of likely correct options for discrete annotation tasks
- Uses configurable LLM backend to pre-score label options
- Subtle visual cues (not pre-selection) to guide annotators without biasing
- See [Option Highlighting Guide](docs/option_highlighting.md) for configuration

#### Embedding-based Diversity Ordering
- Reorder annotation queue to maximize diversity of consecutive items
- Uses sentence embeddings to compute pairwise distances
- Reduces annotator fatigue from repetitive content
- See [Diversity Ordering Guide](docs/diversity_ordering.md) for details

#### Video Object Tracking
- Keyframe interpolation for tracking objects across video frames
- Annotate objects in key frames and auto-interpolate bounding boxes between them

### Infrastructure

#### Pluggable Export System
- Unified export pipeline with 8 format backends:
  - COCO JSON (with RLE mask support)
  - YOLO darknet format
  - Pascal VOC XML
  - CoNLL-2003 and CoNLL-U for token-level annotations
  - Mask PNG for segmentation
  - EAF (ELAN) for audio/video time-aligned annotations
  - TextGrid (Praat) for phonetic segmentation
- CLI export command: `potato export <config> --format <fmt>`
- See [Export Formats Guide](docs/export_formats.md) for details

#### Extended Remote Data Sources
- Load annotation data from remote locations:
  - HTTP/HTTPS URLs
  - Google Drive (public and authenticated)
  - Dropbox shared links
  - Amazon S3 buckets
  - HuggingFace datasets
  - Google Sheets
  - Database connections
- Configurable caching and refresh policies
- See [Remote Data Sources Guide](docs/remote_data_sources.md) for setup

#### External AI Config File Support
- Factor AI endpoint configuration into separate YAML files
- Share AI configs across multiple annotation projects
- Override AI parameters per-project while inheriting defaults

#### Format Handlers
- Native rendering for PDF, Word (.docx), code files, and spreadsheets
- In-browser previews with syntax highlighting for code
- Page-level navigation for multi-page documents

#### Standard Survey Instruments Library
- 55 validated questionnaires ready to deploy (SUS, NASA-TLX, UMUX, AttrakDiff, etc.)
- Pre-configured scoring, reverse-coding, and normative benchmarks
- Drop-in YAML includes for post-study surveys
- See [Survey Instruments Guide](docs/survey_instruments.md) for the full catalog

### UX Improvements

#### Annotation Navigation
- Navigate between items with status badges showing annotation progress
- Skip-to-unannotated button for efficient queue management
- Filter items by annotation status (annotated, unannotated, skipped)
- See [Annotation Navigation Guide](docs/annotation_navigation.md) for details

#### Form Layout Grid
- Arrange annotation schemas in multi-column grid layouts
- CSS Grid-based positioning with configurable column spans
- See [Form Layout Guide](docs/form_layout.md) for configuration

#### Resizable Instance Display
- Draggable resize handles on instance display panels
- Persist user-preferred panel sizes across sessions

#### Conditional Display Logic
- Show or hide annotation fields based on prior responses
- Branching annotation flows within a single instance
- See [Conditional Logic Guide](docs/conditional_logic.md) for details

### Bug Fixes
- Fixed Peaks.js waveform rendering and overview/zoom synchronization
- Fixed dependency arc persistence and span deletion issues
- Fixed image annotation display and mask zoom synchronization
- Fixed CSS visual issues: Likert alignment, whitespace, and textbox width
- Fixed span annotation positioning for code and document displays
- Fixed test infrastructure for login flow and obsolete JS functions

### Documentation
- 28+ new documentation pages added covering all new features
- Project-hub examples reorganized with external AI config support
- New guides: Event Annotation, Entity Linking, Triage, Pairwise Comparison, Coreference, Conversation Trees, Export Formats, Remote Data Sources, MACE, Option Highlighting, Diversity Ordering, Survey Instruments, Annotation Navigation, Form Layout, Conditional Logic, Tiered Annotation, Format Support, Layout Customization, Embedding Visualization, Annotation Filtering

---

## [2.1.0] - Adjudication & Multi-Modal Annotation

This release adds a complete adjudication workflow for resolving inter-annotator disagreements, a flexible instance display system, span linking for relation extraction, and expanded AI support for visual annotation tasks.

### New Features

#### Adjudication System
- Dedicated adjudication interface (`/adjudicate`) for designated reviewers to resolve annotator disagreements and produce gold-standard labels
- Queue-based workflow with items sorted by agreement level, showing all annotators' responses, timing data, and agreement scores side by side
- Per-annotator behavioral signal analysis detecting fast decisions, excessive label changes, and low agreement patterns
- Configurable error taxonomy for classifying disagreement sources (ambiguous text, guideline gaps, annotator errors, edge cases)
- Decision metadata including confidence ratings, free-text notes, and guideline update flags
- Optional semantic similarity engine for surfacing related items during review (requires `sentence-transformers`)
- Export CLI for merging unanimous agreements and adjudicated decisions into a final dataset with provenance tracking
- Admin API endpoint for monitoring adjudication progress across adjudicators
- Browser-style navigation history so Previous button works across filter changes
- Pre-loaded annotation demo with `setup_demo.py` for immediate hands-on testing
- See [Adjudication Guide](docs/adjudication.md) for full documentation

#### Instance Display System
- New `instance_display` configuration to separate content display from annotation schemes
- Display any combination of media (text, images, video, audio, dialogues) alongside any annotation type
- Text display fields can be marked as `span_target: true` to enable span annotation on that field
- Replaces the previous workaround of using annotation schemas with `min_annotations: 0` for content display
- See [Instance Display Guide](docs/instance_display.md) for configuration details

#### Multi-Field Span Annotation
- Span annotation across multiple text fields within a single instance, with each field tracking spans independently
- Per-field overlay containers and field-aware span storage with `target_field` metadata
- Useful for tasks like aligning phrases between premise and hypothesis, or annotating both source text and summary

#### Span Linking
- Relation extraction via typed relationships between previously annotated spans
- Supports directed (e.g., "works_for"), undirected (e.g., "collaborates_with"), and n-ary links
- Label constraints restrict which span types can participate in each link type
- Relationships visualized as colored arcs above the text
- See [Span Linking Guide](docs/span_linking.md) for configuration details

#### Visual AI Support
- AI-powered assistance for image and video annotation using YOLO object detection and Vision-Language Models (GPT-4o, Claude, Ollama vision models)
- Automatic object detection with bounding boxes and pre-annotation for human review
- Image classification with AI-generated rationales
- Video scene detection and keyframe identification
- Configurable visual endpoints that can run alongside text-based LLM endpoints
- See [Visual AI Guide](docs/visual_ai_support.md) for setup instructions

#### AI Rationale
- AI-generated explanations for each possible label, helping annotators understand the reasoning behind different classifications
- Works with both text and vision-capable models, displayed as tooltips on label options
- Provides balanced reasoning across all labels, useful for training annotators or difficult edge cases

### Improvements

#### Frontend
- Improved responsive layout and form state isolation between annotation instances
- Capability-based filtering for AI assistant endpoints

#### Project Organization
- Project-hub examples reorganized into self-contained directories, each with its own `config.yaml` and `data/` folder
- All examples runnable from the repository root without directory changes

#### Bug Fixes
- Fixed span text normalization for multi-field annotation
- Fixed YOLO prompt label parsing for detect and natural language patterns
- Fixed label button styling overlap in image annotation toolbar
- Fixed `total_working_time()` to handle `BehavioralData` objects
- Fixed skipped server tests with absolute paths and free ports
- Fixed `task_dir` resolution for project-hub examples
- Registered behavioral tracking routes in `configure_routes()`
- Fixed pre-existing test failures

### Documentation
- New guides: Adjudication, Instance Display, Span Linking, Visual AI Support
- Updated README with Potato Showcase link and corrected readthedocs URL

---

## [2.0.0] - Backend Refactor

This release represents a major architectural overhaul of the Potato annotation platform, introducing new features, improved state management, and enhanced security.

### Breaking Changes

- **YAML-only configuration**: JSON configuration format is no longer supported. All config files must use YAML format.
- **Annotation type renamed**: The `highlight` annotation type has been renamed to `span`. Update all configs using `annotation_type: highlight` to `annotation_type: span`.
- **New required field `task_dir`**: All configuration files must now include a `task_dir` field specifying the root directory for the annotation task.
- **Config file location**: Configuration files must now be located within the `task_dir` directory for security purposes.
- **Path resolution**: All relative paths in configuration files are now resolved relative to `task_dir` instead of the current working directory.
- **Import paths**: Python imports now use the `potato.` prefix (e.g., `from potato.flask_server import main`).

### New Features

#### AI Support
- Integrated AI assistance with support for 7 LLM providers:
  - OpenAI (GPT-4, GPT-3.5)
  - Anthropic (Claude)
  - Google Gemini
  - Hugging Face
  - OpenRouter (access to multiple providers)
  - Ollama (local deployment)
  - VLLM (local inference server)
- Three AI assistance features:
  - **Intelligent Hints**: Contextual guidance with optional suggested labels
  - **Keyword Highlighting**: AI-identified keywords with amber box overlays
  - **Label Suggestions**: Visual highlighting of suggested labels with sparkle indicators
- Configurable prompts per annotation type (JSON prompt files in `potato/ai/prompt/`)
- Environment variable support for API keys
- Caching system with disk persistence and prefetching for performance
- Multi-schema support with per-annotation AI configuration

#### Active Learning
- ML-based instance prioritization using uncertainty sampling
- Multiple classifier options: LogisticRegression, RandomForest, SVC, MultinomialNB
- Multiple vectorizer options: TfidfVectorizer, CountVectorizer, HashingVectorizer
- Model persistence with automatic versioning and retention policies
- LLM integration for confidence-based instance selection
- Resolution strategies: MAJORITY_VOTE, RANDOM, CONSENSUS, WEIGHTED_AVERAGE
- Optional database persistence for large-scale deployments
- Asynchronous, non-blocking model training

#### Training Phase
- Practice annotation phase before main task
- Configurable passing criteria (minimum correct, require all correct)
- Immediate feedback with explanations for incorrect answers
- Retry functionality for failed attempts
- Progress tracking in admin dashboard
- Training data format with correct answers and explanations

#### Database Backend
- MySQL/MariaDB support for user state persistence
- Connection pooling with configurable parameters
- Transaction management and prepared statements
- Fallback mechanisms for connection failures

#### Enhanced Admin Dashboard
- Real-time annotation progress tracking
- Annotator performance metrics and timing analysis
- Suspicious activity detection with scoring (LOW, MEDIUM, HIGH)
- Session-based behavioral analysis
- Training phase progress monitoring
- Instance-level annotation tracking with disagreement analysis

#### Annotation History
- Complete action tracking with unique IDs (UUID)
- Server and client timestamp recording
- Old/new value tracking for auditing
- Session tracking for behavioral analysis
- Performance metric calculation

#### Multi-Phase Workflow
- Configurable phase progression: LOGIN → CONSENT → PRESTUDY → INSTRUCTIONS → TRAINING → ANNOTATION → POSTSTUDY → DONE
- Phase-specific configuration files
- Multi-page support within phases

### Architecture Changes

#### State Management
- New `UserStateManager` singleton for comprehensive user progress tracking
- New `ItemStateManager` singleton for item/instance management
- Support for multiple assignment strategies (random, fixed, active learning, diversity-based)
- `TrainingState` dataclass for training phase metrics

#### Authentication System
- Pluggable authentication backends:
  - InMemoryAuthBackend (development)
  - DatabaseAuthBackend (production with MySQL)
  - ClerkAuthBackend (third-party SSO)
- PBKDF2 password hashing with salt
- API key authentication for admin endpoints
- Passwordless authentication support

#### Code Organization
- Routes extracted to separate `routes.py` module (2,570 lines)
- Admin functionality in dedicated `admin.py` module (1,170 lines)
- AI endpoints in `potato/ai/` module
- Database support in `potato/database/` module
- Schema utilities centralized in `identifier_utils.py`

#### Security Enhancements
- Path traversal validation in configuration
- SQL injection prevention with prepared statements
- CSRF protection via session-based authentication
- HTML escaping for user content

### Improvements

#### Testing
- Comprehensive test suite with 300+ test files
- Server integration tests using `FlaskTestServer`
- Selenium/browser tests using `BaseSeleniumTest`
- Jest tests for JavaScript functionality
- Test utilities in `tests/helpers/test_utils.py`
- Test file security policy (all test files within `tests/` directory)

#### Span Annotation
- Enhanced 22-color palette for better visual distinction
- Schema-aware color assignment
- Improved overlap handling
- Better positioning for overlapping spans

#### Frontend
- Modern HTML5 template system
- Shadcn design system CSS classes
- Responsive layout support
- Dark mode support via CSS variables
- New `span-core.js` with SpanManager class for unified span/highlight handling
- AI integration in SpanManager for keyword highlighting overlays
- Enhanced `span-manager.js` (2,540 lines) for span annotation
- Enhanced `annotation.js` (2,682 lines) for annotation handling
- Enhanced `ai_assistant_manager.js` with label suggestion highlighting

#### Configuration
- Enhanced YAML validation with detailed error messages
- Security hardening for path validation
- Support for environment variable substitution
- Comprehensive schema validation per annotation type

#### Documentation
- New guides: AI support, active learning, training phase, admin dashboard
- Configuration file structure documentation
- Assignment strategies summary
- Comprehensive testing documentation

### Audio Annotation Type
- New `audio_annotation` type for audio segmentation with waveform visualization
- Peaks.js integration for efficient rendering of long audio files
- Support for segment creation, labeling, and playback
- Zoom and scroll controls for navigating long recordings
- Pre-computed waveform data caching for performance

### Video Annotation Type
- New `video` annotation type for displaying video content
- Configurable video properties (autoplay, loop, muted, controls)
- Custom CSS support for dimensions

### Internal Changes

#### Dependencies
- Added scikit-learn for active learning classifiers
- Added simpledorff for agreement calculations
- Added MySQL connector for database backend
- Provider-specific AI libraries (openai, anthropic, google-generativeai)

#### File Statistics
- Core modules rewritten: ~8,000+ lines of new code
- Frontend enhanced: ~5,200+ lines
- Tests added: ~50,000+ lines
- Documentation added: ~2,500+ lines

---

## Migration

See [MIGRATION.md](MIGRATION.md) for detailed instructions on upgrading from v1.x to v2.0.0.

## New Features Guide

See [docs/new_features_v2.md](docs/new_features_v2.md) for detailed documentation on new features.
