# Changelog

All notable changes to the Potato annotation platform are documented in this file.

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
- Integrated AI hint generation with support for 6 LLM providers:
  - OpenAI (GPT-4, GPT-3.5)
  - Anthropic (Claude)
  - Google Gemini
  - Hugging Face
  - Ollama (local deployment)
  - VLLM (local inference server)
- Configurable prompts for hints and keyword highlighting
- Environment variable support for API keys

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
- Enhanced `span-manager.js` (2,540 lines) for span annotation
- Enhanced `annotation.js` (2,682 lines) for annotation handling

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
