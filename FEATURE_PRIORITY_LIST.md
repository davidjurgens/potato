# Feature Priority List: Blog-Claimed Features Worth Implementing

This document ranks the non-existent features claimed in blog posts by **usefulness** and **implementation effort**.

---

## Scoring Criteria

- **Usefulness**: How valuable is this for real annotation workflows?
  - High (3): Essential for many annotation projects
  - Medium (2): Nice to have, benefits specific use cases
  - Low (1): Edge case or rarely needed

- **Effort**: How hard to implement given existing infrastructure?
  - Easy (1): Few hours, mostly config/glue code
  - Medium (2): Few days, new module but straightforward
  - Hard (3): Week+, significant new functionality

- **Priority Score**: `Usefulness × 2 - Effort` (higher = do first)

---

## Tier 1: Quick Wins (High Value, Low Effort)

### 1. `server:` YAML Config Block
| Usefulness | Effort | Priority |
|------------|--------|----------|
| High (3) | Easy (1) | **5** |

**What it does:** Allow `server: port: 8000` in YAML instead of `-p 8000` CLI flag.

**Why valuable:** Makes configs self-contained and shareable. Every blog uses this pattern because it's intuitive.

**Implementation:**
```python
# In config_module.py, add:
if "server" in config:
    if "port" in config["server"]:
        # Set default port, can still be overridden by CLI
        config["_default_port"] = config["server"]["port"]
```

**Estimated time:** 1-2 hours

---

### 2. Pre-annotation Support (Model Predictions)
| Usefulness | Effort | Priority |
|------------|--------|----------|
| High (3) | Easy-Medium (1.5) | **4.5** |

**What it does:** Pre-fill annotation forms with model predictions from data file.

**Why valuable:** Dramatically speeds up annotation when you have ML predictions. Common in active learning and correction workflows.

**Implementation:**
- Data already supports arbitrary JSON fields
- Add config option: `pre_annotation: {field: "predictions", allow_modification: true}`
- In frontend, pre-select/pre-fill values from the data item
- For span annotation: render predicted spans as editable

**Estimated time:** 1-2 days

---

### 3. Waveform Color Customization
| Usefulness | Effort | Priority |
|------------|--------|----------|
| Medium (2) | Easy (1) | **3** |

**What it does:** Allow `waveform_color: "#6366F1"` in audio annotation config.

**Why valuable:** Branding, accessibility, visual consistency.

**Implementation:**
- Add optional fields to `audio_annotation` schema config
- Pass colors to Peaks.js initialization in JavaScript

**Estimated time:** 2-4 hours

---

### 4. Top-Level `keyboard_shortcuts:` Config
| Usefulness | Effort | Priority |
|------------|--------|----------|
| Medium (2) | Easy (1) | **3** |

**What it does:** Global keyboard shortcuts like `submit: "Enter"`, `skip: "s"`.

**Why valuable:** Currently shortcuts are scattered per-schema. Global config is cleaner.

**Implementation:**
- Add config section parsing
- Merge with existing keybinding system

**Estimated time:** 3-4 hours

---

## Tier 2: High Value, Moderate Effort

### 5. HuggingFace Dataset Export
| Usefulness | Effort | Priority |
|------------|--------|----------|
| High (3) | Medium (2) | **4** |

**What it does:** `potato export --format huggingface --output ./dataset/`

**Why valuable:** HuggingFace is the standard for ML datasets. Direct export removes friction.

**Implementation:**
- Add `export` subcommand to CLI (existing argparse infrastructure)
- Read annotation output files
- Convert to HuggingFace `datasets` format
- Support train/val/test splits

**Estimated time:** 2-3 days

---

### 6. Attention Checks with Failure Handling
| Usefulness | Effort | Priority |
|------------|--------|----------|
| High (3) | Medium (2) | **4** |

**What it does:** Insert known-answer items, track failures, warn/block annotators.

**Why valuable:** Essential for crowdsourcing quality control.

**Implementation:**
- Add `attention_checks:` config section
- Mix attention items into assignment queue
- Track correct/incorrect per user
- Add failure handling logic (warn, block)

**Estimated time:** 2-3 days

---

### 7. Gold Standard Items with Accuracy Tracking
| Usefulness | Effort | Priority |
|------------|--------|----------|
| High (3) | Medium (2) | **4** |

**What it does:** Load expert-labeled items, compare annotator responses, compute accuracy.

**Why valuable:** Quality assurance, annotator training, filtering bad annotators.

**Implementation:**
- Similar to attention checks but with accuracy metrics
- Store gold labels separately
- Compare on submission
- Expose metrics in admin dashboard

**Estimated time:** 2-3 days

---

### 8. Agreement Metrics in Admin Dashboard
| Usefulness | Effort | Priority |
|------------|--------|----------|
| High (3) | Medium (2) | **4** |

**What it does:** Show Cohen's Kappa, Fleiss' Kappa, Krippendorff's Alpha in real-time.

**Why valuable:** `agreement.py` already exists! Just needs integration.

**Implementation:**
- Import existing `simpledorff` calculations
- Add endpoint to compute agreement on demand
- Display in admin dashboard

**Estimated time:** 1-2 days

---

### 9. Inline Field Mapping in `data_files:`
| Usefulness | Effort | Priority |
|------------|--------|----------|
| Medium (2) | Easy (1) | **3** |

**What it does:** `data_files: [{path: x.json, text_field: text, id_field: id}]`

**Why valuable:** More intuitive than separate `item_properties` section. Blogs use this because it makes sense.

**Implementation:**
- Parse inline field names from data_files entries
- Fall back to `item_properties` if not specified

**Estimated time:** 2-3 hours

---

### 10. `window.Potato` JavaScript API
| Usefulness | Effort | Priority |
|------------|--------|----------|
| Medium (2) | Medium (2) | **2** |

**What it does:** `window.Potato.setAnnotation()`, `window.Potato.getAnnotations()`, events.

**Why valuable:** Enables custom templates to interact with annotation state programmatically.

**Implementation:**
- Create global Potato object in annotation.js
- Expose getter/setter methods
- Emit custom events on state changes

**Estimated time:** 1-2 days

---

## Tier 3: Specialized Features (Medium Value, Various Effort)

### 11. Rate Limiting for AI Requests
| Usefulness | Effort | Priority |
|------------|--------|----------|
| Medium (2) | Easy (1) | **3** |

**What it does:** `ai_support: rate_limit: 60` (requests per minute)

**Why valuable:** Prevents API cost overruns, handles rate limits gracefully.

**Implementation:**
- Add token bucket or sliding window in ai_help_wrapper.py
- Queue requests that exceed limit

**Estimated time:** 3-4 hours

---

### 12. Redis/Memory Caching for AI
| Usefulness | Effort | Priority |
|------------|--------|----------|
| Medium (2) | Medium (2) | **2** |

**What it does:** `cache_config: backend: redis`

**Why valuable:** Better performance for multi-server deployments.

**Implementation:**
- Abstract cache interface (already have disk cache)
- Add Redis adapter
- Add in-memory adapter

**Estimated time:** 1-2 days

---

### 13. Stopping Criteria for Active Learning
| Usefulness | Effort | Priority |
|------------|--------|----------|
| Medium (2) | Easy (1) | **3** |

**What it does:** `stopping_criteria: {target_accuracy: 0.9, max_annotations: 2000}`

**Why valuable:** Automatically stop when quality threshold reached.

**Implementation:**
- Add config parsing
- Check criteria after each retraining
- Notify admin when criteria met

**Estimated time:** 3-4 hours

---

### 14. Bonus Payment Configuration (Prolific/MTurk)
| Usefulness | Effort | Priority |
|------------|--------|----------|
| Medium (2) | Medium (2) | **2** |

**What it does:** Define bonus criteria, export bonus CSV.

**Why valuable:** Incentivizes quality, rewards good annotators.

**Implementation:**
- Add bonus config section
- Track qualifying criteria
- Export payment file

**Estimated time:** 1-2 days

---

### 15. Segment Merge/Split for Audio
| Usefulness | Effort | Priority |
|------------|--------|----------|
| Medium (2) | Medium (2) | **2** |

**What it does:** Press 'm' to merge adjacent segments, '/' to split at playhead.

**Why valuable:** Common editing operations for audio annotation.

**Implementation:**
- Add keyboard handlers
- Implement merge logic (combine segments, resolve labels)
- Implement split logic (divide at time point)

**Estimated time:** 1-2 days

---

## Tier 4: Complex Features (Consider Carefully)

### 16. Pattern Detection for Quality Control
| Usefulness | Effort | Priority |
|------------|--------|----------|
| Medium (2) | Hard (3) | **1** |

**What it does:** Detect rapid submissions, alternating patterns, position bias.

**Why valuable:** Catches low-effort annotators automatically.

**Implementation:**
- Analyze timing patterns
- Statistical tests for response patterns
- Heuristics for position bias

**Estimated time:** 3-5 days

---

### 17. Video Bounding Box Interpolation
| Usefulness | Effort | Priority |
|------------|--------|----------|
| Medium (2) | Hard (3) | **1** |

**What it does:** Draw box on keyframes, interpolate between.

**Why valuable:** Dramatically speeds up video object tracking.

**Implementation:**
- Track keyframe annotations
- Linear/spline interpolation between frames
- UI to show interpolated vs keyframe boxes

**Estimated time:** 1-2 weeks

---

### 18. Multi-Object Tracking (MOT)
| Usefulness | Effort | Priority |
|------------|--------|----------|
| Low (1) | Hard (3) | **-1** |

**What it does:** Full tracking annotation with ID persistence, occlusion handling.

**Why valuable:** Niche but important for computer vision.

**Implementation:**
- New annotation type
- Track ID management
- Occlusion state tracking
- Re-identification UI

**Estimated time:** 2-4 weeks

---

### 19. SAM (Segment Anything) Integration
| Usefulness | Effort | Priority |
|------------|--------|----------|
| Medium (2) | Hard (3) | **1** |

**What it does:** Click to auto-segment with SAM model.

**Why valuable:** Revolutionary for image segmentation annotation.

**Implementation:**
- SAM model server/API
- Click-to-segment UI
- Mask editing tools

**Estimated time:** 2-3 weeks

---

### 20. DICOM/Medical Imaging Viewer
| Usefulness | Effort | Priority |
|------------|--------|----------|
| Low (1) | Hard (3) | **-1** |

**What it does:** Multi-slice DICOM navigation, windowing, measurements.

**Why valuable:** Medical imaging is specialized market.

**Implementation:**
- DICOM parsing library
- 3D slice navigation
- Windowing controls
- Measurement tools

**Estimated time:** 4-8 weeks

---

## Summary: Recommended Implementation Order

### Phase 1: Quick Wins (1-2 weeks total)
1. `server:` YAML config block
2. Inline field mapping in `data_files:`
3. Waveform color customization
4. Top-level `keyboard_shortcuts:` config
5. Rate limiting for AI requests
6. Stopping criteria for active learning

### Phase 2: Core Quality Features (2-3 weeks total)
7. Pre-annotation support
8. Attention checks with failure handling
9. Gold standard items
10. Agreement metrics in admin dashboard

### Phase 3: Export & Integration (1-2 weeks total)
11. HuggingFace dataset export
12. `window.Potato` JavaScript API

### Phase 4: Advanced Features (evaluate need)
13. Bonus payment configuration
14. Redis caching for AI
15. Segment merge/split for audio
16. Pattern detection

### Phase 5: Major New Capabilities (future roadmap)
17. Video bounding box interpolation
18. SAM integration
19. Multi-object tracking
20. DICOM viewer

---

## Implementation Notes

### Existing Infrastructure to Leverage:
- **CLI**: `argparse` already set up in `arg_utils.py`
- **Agreement**: `agreement.py` has Krippendorff's alpha
- **AI Caching**: `ai_cache.py` has disk cache pattern
- **Config Parsing**: `config_module.py` handles YAML
- **Admin Dashboard**: Already exists, just needs new metrics

### Dependencies to Add:
- `datasets` (HuggingFace) for export
- `redis` (optional) for caching
- None required for Phase 1 features
