# Merge Plan: backend-refactor → master

## Branch Summary

| Branch | Commits Ahead | Key Changes |
|--------|--------------|-------------|
| `backend-refactor` | 160 commits | Major refactoring, new features, test infrastructure |
| `master` | 25 commits | Bug fixes, SSL support, span annotation improvements, emphasis feature |

## Conflict Analysis

### Total Conflicts: 23 files

#### Critical Conflicts (Core Python - Require Careful Review)

| File | Conflict Type | Resolution Strategy |
|------|--------------|---------------------|
| `potato/flask_server.py` | Content | Manual merge - this is the main server file with significant changes on both sides |
| `potato/server_utils/config_module.py` | Content | Manual merge - configuration handling differs |
| `potato/server_utils/arg_utils.py` | Content | Manual merge - CLI argument handling |

#### Schema Files (Moderate Complexity)

| File | Conflict Type | Resolution Strategy |
|------|--------------|---------------------|
| `potato/server_utils/schemas/span.py` | Content | Keep backend-refactor's registry pattern, incorporate master's `data-schema` attribute fix |
| `potato/server_utils/schemas/likert.py` | Content | Keep backend-refactor's registry integration |
| `potato/server_utils/schemas/multirate.py` | Content | Keep backend-refactor's registry integration |
| `potato/server_utils/schemas/multiselect.py` | Content | Keep backend-refactor's registry integration |
| `potato/server_utils/schemas/number.py` | Content | Keep backend-refactor's registry integration |
| `potato/server_utils/schemas/radio.py` | Content | Keep backend-refactor's registry integration |
| `potato/server_utils/schemas/select.py` | Content | Keep backend-refactor's registry integration |
| `potato/server_utils/schemas/slider.py` | Content | Keep backend-refactor's registry integration |
| `potato/server_utils/schemas/textbox.py` | Content | Keep backend-refactor's registry integration |

#### Template Files (Modify/Delete Conflicts)

| File | Conflict Type | Resolution Strategy |
|------|--------------|---------------------|
| `potato/base_html/header.html` | Modify/Delete | Evaluate if master's changes need porting to new template system |
| `potato/base_html/examples/*.html` | Modify/Delete | Backend-refactor deleted these; check if master's changes are needed |
| `potato/templates/single_multiple_choice.html` | Modify/Delete | Similar - evaluate master's changes |

#### Other Conflicts

| File | Conflict Type | Resolution Strategy |
|------|--------------|---------------------|
| `.gitignore` | Content | Merge both additions |
| `docs/schemas_and_templates.md` | Content | Merge documentation |
| `potato/static/styles/emphasis.css` | Add/Add | Both branches added this file - merge styles |
| `project-hub/simple_examples/configs/simple-pairwise-comparison.yaml` | Content | Merge config changes |
| `project-hub/simple_examples/configs/all-phases-example-templates/instructions-layout.html` | Content | Merge template changes |
| `setup.py` | Content | Merge version and dependency changes |

---

## Key Changes to Integrate from Master

### 1. SSL Certificate Support (PR #106)
- **Commit**: `72c107e`
- **Files**: `potato/server_utils/arg_utils.py`, `potato/flask_server.py`
- **Action**: Port SSL cert handling to backend-refactor

### 2. Span Annotation Fixes
- **Commits**: `76db6cf`, `b2fdbcf`, `bc0b5f3`, `42c4c47`
- **Changes**:
  - Changed 'schema' to 'data-schema' attribute in span highlights
  - Fixed no-span option tracking in multiple schemas
  - Fixed missing span title bug
  - Added abbreviation support for span display names
- **Action**: Review and integrate into backend-refactor's span.py

### 3. Emphasis/Suggestion Feature
- **Commits**: `6c8bbcd`, `b8cffac`, `992b29b`, `6561146`, `b34cf90`
- **Files**: `node/src/emphasis.ts`, `potato/static/styles/emphasis.css`, frontend code
- **Action**: Evaluate if this feature should be integrated or if it conflicts with backend-refactor's approach

### 4. Security Policy
- **Commit**: `74714cc`
- **File**: `SECURITY.md`
- **Action**: Simply accept from master (new file)

---

## Recommended Merge Strategy

### Option A: Merge master INTO backend-refactor (Recommended)

```bash
git checkout backend-refactor
git merge origin/master
# Resolve conflicts
# Run full test suite
# Push updated backend-refactor
```

**Pros:**
- Keeps backend-refactor as the integration branch
- All 160 commits of work remain intact
- Easier to test incrementally

**Cons:**
- Need to manually resolve 23 conflicts

### Option B: Rebase backend-refactor ONTO master

```bash
git checkout backend-refactor
git rebase origin/master
```

**Pros:**
- Creates linear history

**Cons:**
- Risk of losing context in 160 commits
- Conflicts must be resolved multiple times during rebase
- NOT RECOMMENDED for this case

### Option C: Feature-by-feature integration

Create PRs for individual features from backend-refactor to master:
1. Test infrastructure improvements
2. Schema registry system
3. Video/audio/image annotation
4. ICL labeling feature
5. Admin dashboard
6. etc.

**Pros:**
- Easier to review
- Incremental integration

**Cons:**
- Time-consuming
- Risk of integration issues between features

---

## Step-by-Step Merge Plan (Option A)

### Phase 1: Preparation
1. [ ] Ensure all tests pass on backend-refactor
2. [ ] Create backup branch: `git branch backend-refactor-backup`
3. [ ] Document current test coverage baseline

### Phase 2: Merge
1. [ ] `git fetch origin`
2. [ ] `git merge origin/master`
3. [ ] Resolve conflicts in order:

#### 2a. Simple conflicts first
- [ ] `.gitignore` - merge both additions
- [ ] `SECURITY.md` - accept from master (new file)
- [ ] `setup.py` - merge version/dependencies
- [ ] `docs/schemas_and_templates.md` - merge documentation

#### 2b. Schema files (pattern-based)
For each schema file, the pattern is similar:
- Keep backend-refactor's registry integration
- Port any bug fixes from master
- Files: `span.py`, `likert.py`, `multirate.py`, `multiselect.py`, `number.py`, `radio.py`, `select.py`, `slider.py`, `textbox.py`

#### 2c. Core files (careful review)
- [ ] `potato/flask_server.py` - merge SSL support from master
- [ ] `potato/server_utils/config_module.py` - merge carefully
- [ ] `potato/server_utils/arg_utils.py` - add SSL cert arguments

#### 2d. Template conflicts (evaluate)
- [ ] Decide on deleted templates - keep deletion or restore with master's changes
- [ ] `potato/static/styles/emphasis.css` - merge styles

#### 2e. Config/Example files
- [ ] `project-hub/simple_examples/configs/simple-pairwise-comparison.yaml`
- [ ] `project-hub/simple_examples/configs/all-phases-example-templates/instructions-layout.html`

### Phase 3: Verification
1. [ ] Run unit tests: `pytest tests/unit/ -v`
2. [ ] Run server tests: `pytest tests/server/ -v`
3. [ ] Run integration tests: `pytest tests/integration/ -v`
4. [ ] Manual smoke test of key features:
   - [ ] Basic annotation workflow
   - [ ] Span annotation with multiple schemas
   - [ ] Video/audio/image annotation
   - [ ] SSL support (if enabled)

### Phase 4: Finalize
1. [ ] Commit the merge
2. [ ] Push to remote
3. [ ] Create PR from backend-refactor to master
4. [ ] Request code review

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Schema registry conflicts break annotation types | Medium | High | Run full test suite after each schema file resolution |
| SSL support integration issues | Low | Medium | Test SSL separately with self-signed cert |
| Span annotation fixes regression | Medium | High | Run span-specific tests after span.py merge |
| Template system incompatibility | Medium | Medium | Check that all example configs still work |

---

## Estimated Effort

- **Conflict resolution**: 2-4 hours
- **Testing**: 1-2 hours
- **Documentation updates**: 30 minutes
- **Total**: ~4-6 hours

---

## Post-Merge Tasks

1. Update CHANGELOG.md with merged features
2. Consider version bump (currently at 2.0.0b1)
3. Update documentation for any new features from master
4. Tag release candidate if appropriate
