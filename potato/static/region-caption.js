/**
 * Region captioning: one description per region drawn on the image.
 *
 * ## The index is the whole problem
 *
 * A caption is attached to a region by its position in the image schema's
 * annotation list. That is fine while regions are only added, and wrong the
 * moment one is deleted: removing the second of three regions must carry the
 * third region's caption up with it, and a caption list kept in parallel would
 * silently leave it attached to the wrong shape — looking exactly like a
 * correct caption of a different object.
 *
 * So the list is **rebuilt from the canvas on every change**, and captions are
 * carried across by matching the region they were written about rather than by
 * index. Matching by geometry rather than by position is what makes deletion,
 * reordering and undo all behave.
 */
(function (global) {
    'use strict';

    class RegionCaptionManager {
        constructor(container, config) {
            this.container = container;
            this.config = config || {};
            this.schemaName = this.config.schemaName;
            /** [{key, caption, region}] — parallel to the canvas, rebuilt often. */
            this.entries = [];
            this.imageManager = null;
            this.input = document.getElementById('input-' + this.schemaName);
            this.list = document.getElementById(
                'region-caption-list-' + this.schemaName);
            this.progress = document.getElementById(
                'region-caption-progress-' + this.schemaName);
            this.announcer = document.getElementById(
                'region-caption-announce-' + this.schemaName);
        }

        init() {
            this._restoreFromInput();
            this._findImageManager();
            this._installNavGuard();
        }

        _findImageManager(attempt) {
            attempt = attempt || 0;
            for (const element of document.querySelectorAll(
                    '.image-annotation-container')) {
                if (element.annotationManager) {
                    this.imageManager = element.annotationManager;
                    this._wireCapture();
                    this.sync();
                    return;
                }
            }
            if (attempt > 60) {
                this._showError(
                    'No image annotation schema was found on this page. A '
                    + 'region_caption schema needs one alongside it to draw on.');
                return;
            }
            setTimeout(() => this._findImageManager(attempt + 1), 250);
        }

        /**
         * Follow the canvas.
         *
         * Through `addAnnotationChangeListener`, not the `onAnnotationChange`
         * slot and not a `change` event on the hidden input. The input's value
         * is assigned directly, and assigning a value fires no event; and the
         * single callback slot is *assigned* by the image schema's own
         * bootstrap, which silently discards anything already there. Chaining
         * it made this schema order-dependent — whichever companion attached
         * first stopped receiving events, and captions never saved.
         */
        _wireCapture() {
            if (this._captureWired) return;
            this._captureWired = true;
            this.imageManager.addAnnotationChangeListener(() => this.sync());
        }

        // -- state -----------------------------------------------------------

        /**
         * A stable-enough identity for a region, so a caption survives a redraw.
         *
         * Rounded to four decimals: a region re-created by undo/redo or by a
         * resize round-trip is the same region and must keep its caption, but
         * floating-point noise in the last digits would make it a new one.
         */
        _key(region) {
            if (!region) return '';
            const coordinates = region.coordinates;
            const round = (value) => Math.round(Number(value) * 10000) / 10000;
            if (Array.isArray(coordinates)) {
                return region.type + ':' + coordinates
                    .map((p) => round(p.x) + ',' + round(p.y)).join(';');
            }
            if (coordinates && typeof coordinates === 'object') {
                return region.type + ':' + Object.keys(coordinates).sort()
                    .map((k) => k + '=' + round(coordinates[k])).join(',');
            }
            if (region.rle && region.rle.counts) {
                return region.type + ':rle:' + region.rle.counts.length
                    + ':' + (region.rle.counts[0] || 0);
            }
            return region.type + ':' + (region.label || '');
        }

        /**
         * Rebuild the list from the canvas, carrying captions across by region.
         *
         * ## A region that vanishes is not necessarily deleted
         *
         * The image manager's own restore cycle *removes every object and adds
         * it back*: the save path clears the canvas and re-deserializes, so for
         * a moment the canvas honestly reports zero regions. A naive sync reads
         * that as "the annotator deleted everything", drops the captions, and
         * then sees the regions return with nothing attached — which is
         * exactly what happened, and it destroyed a caption typed seconds
         * earlier.
         *
         * So a caption whose region is not currently on the canvas moves to an
         * **orphan pool** rather than being discarded, and is re-attached if
         * that region comes back. Orphans are never serialized, so a genuinely
         * deleted region contributes nothing to the saved value; they only
         * exist to survive the round trip.
         */
        sync() {
            if (!this.imageManager) return;
            let regions = [];
            try {
                const parsed = JSON.parse(
                    this.imageManager._serializeAnnotations() || '[]');
                if (Array.isArray(parsed)) regions = parsed;
            } catch (error) {
                console.warn('Could not read the canvas annotations:', error);
                return;
            }

            this._orphans = this._orphans || new Map();
            const existing = new Map(
                this.entries.map((entry) => [entry.key, entry.caption]));

            this.entries = regions.map((region) => {
                const key = this._key(region);
                const caption = existing.get(key)
                    || this._orphans.get(key) || '';
                this._orphans.delete(key);
                return { key: key, region: region, caption: caption };
            });

            const present = new Set(this.entries.map((entry) => entry.key));
            for (const [key, caption] of existing.entries()) {
                if (!present.has(key) && caption) {
                    this._orphans.set(key, caption);
                }
            }

            this._save();
            this._render();
        }

        setCaption(index, value) {
            if (!this.entries[index]) return;
            this.entries[index].caption = value;
            this._save();
            this._renderProgress();
        }

        /** The shortest a caption may be and still count as written. */
        _minLength() {
            const n = parseInt(this.config.minLength, 10);
            return Number.isFinite(n) && n > 0 ? n : 1;
        }

        /**
         * Regions still without a usable caption.
         *
         * `min_length` was computed by the schema, shipped to the client and
         * read by nobody: with `min_length: 10`, a caption of "box" counted and
         * the panel said "All 2 regions described." A caption below the
         * configured floor is not a caption.
         */
        undescribed() {
            const floor = this._minLength();
            return this.entries
                .map((entry, index) =>
                    (entry.caption.trim().length >= floor ? -1 : index))
                .filter((index) => index >= 0);
        }

        serialize() {
            return {
                captions: this.entries.map((entry) => ({
                    region: entry.region,
                    caption: entry.caption,
                })),
            };
        }

        _save() {
            if (!this.input) return;
            this.input.value = JSON.stringify(this.serialize());
            this.input.setAttribute('data-modified', 'true');
            // Assigning `.value` fires nothing; the shared autosave in
            // annotation.js listens for this, and without it the captions
            // reach the server only when the annotator navigates.
            this.input.dispatchEvent(new Event('change', { bubbles: true }));
        }

        _restoreFromInput() {
            if (!this.input || !this.input.value) return;
            try {
                const stored = JSON.parse(this.input.value);
                this.entries = (stored.captions || []).map((entry) => ({
                    key: this._key(entry.region),
                    region: entry.region,
                    caption: entry.caption || '',
                }));
            } catch (error) {
                console.warn('Stored captions could not be parsed:', error);
            }
        }

        clearAnnotations() {
            this.entries = [];
            // A real instance switch, unlike the transient empties sync()
            // guards against, so the orphan pool goes too: keeping it would
            // let the previous image's captions reattach to this one's regions
            // if a shape happened to land in the same place.
            if (this._orphans) this._orphans.clear();
            if (this.input) this.input.value = '';
            if (this._rows) {
                for (const row of this._rows.values()) row.item.remove();
                this._rows.clear();
            }
            this._render();
        }

        getAnnotationCount() {
            return this.entries.filter((entry) => entry.caption.trim()).length;
        }

        // -- rendering -------------------------------------------------------

        /**
         * Reconcile the list with the entries. Does NOT rebuild the DOM.
         *
         * `innerHTML = ''` and re-create is the obvious implementation and it
         * loses keystrokes: `sync()` runs on every canvas change, the image
         * manager fires several per drag, and a character typed between the
         * textarea being destroyed and its replacement being wired is simply
         * gone. Restoring focus and caret afterwards does not help, because the
         * value itself was never committed.
         *
         * So a row that is already correct is left alone entirely — its
         * textarea is never replaced, and typing into it is safe no matter what
         * the canvas is doing.
         */
        _render() {
            if (!this.list) return;

            this._rows = this._rows || new Map();
            const wanted = new Set();

            this.entries.forEach((entry, index) => {
                wanted.add(entry.key);
                let row = this._rows.get(entry.key);
                if (!row) {
                    row = this._createRow(entry, index);
                    this._rows.set(entry.key, row);
                }
                // The index changes when an earlier region is deleted, so the
                // handler reads it off the element rather than closing over it.
                row.field.dataset.captionIndex = String(index);
                row.label.textContent = this._describeRegion(entry.region, index);
                if (document.activeElement !== row.field
                        && row.field.value !== entry.caption) {
                    // Never overwrite the box the annotator is typing in.
                    row.field.value = entry.caption;
                }
                row.item.className = 'region-caption-item'
                    + (entry.caption.trim() ? ' described' : ' undescribed');
                this.list.appendChild(row.item);   // moves if already present
            });

            for (const [key, row] of Array.from(this._rows.entries())) {
                if (!wanted.has(key)) {
                    row.item.remove();
                    this._rows.delete(key);
                }
            }
            this._renderProgress();
        }

        _createRow(entry, index) {
            const item = document.createElement('li');
            item.className = 'region-caption-item';

            const inputId = `caption-${this.schemaName}-${index}-`
                + Math.random().toString(36).slice(2, 8);
            const label = document.createElement('label');
            label.setAttribute('for', inputId);
            label.className = 'region-caption-label';
            item.appendChild(label);

            const field = document.createElement('textarea');
            field.id = inputId;
            field.className = 'region-caption-input';
            field.rows = 2;
            field.placeholder = this.config.placeholder || '';
            field.value = entry.caption;
            if (this.config.maxLength) field.maxLength = this.config.maxLength;
            if (this.config.minLength > 0) {
                field.minLength = this.config.minLength;
                field.setAttribute(
                    'aria-describedby',
                    'region-caption-progress-' + this.schemaName);
            }
            field.addEventListener('input', (event) => this.setCaption(
                Number(event.target.dataset.captionIndex), event.target.value));
            item.appendChild(field);

            return { item: item, label: label, field: field };
        }

        /** A label a person can match to a shape on the canvas. */
        _describeRegion(region, index) {
            if (!region) return `Region ${index + 1}`;
            const label = region.label ? ` (${region.label})` : '';
            const coordinates = region.coordinates;
            if (coordinates && !Array.isArray(coordinates)
                && coordinates.x !== undefined) {
                const x = Math.round(coordinates.x * 100);
                const y = Math.round(coordinates.y * 100);
                return `Region ${index + 1}${label} — at ${x}%, ${y}%`;
            }
            return `Region ${index + 1}${label} — ${region.type}`;
        }

        _renderProgress() {
            if (!this.progress) return;
            const total = this.entries.length;
            if (!total) {
                this.progress.textContent =
                    'No regions yet. Draw one on the image to describe it.';
                return;
            }
            const remaining = this.undescribed().length;
            const floor = this._minLength();
            const rule = floor > 1
                ? ` A description needs at least ${floor} characters.` : '';
            this.progress.textContent = remaining
                ? `${total - remaining} of ${total} regions described.${rule}`
                : `All ${total} regions described.`;
        }

        _showError(message) {
            this.container.classList.add('error');
            if (this.progress) this.progress.textContent = message;
            if (this.announcer) this.announcer.textContent = message;
        }

        /**
         * Warn once before advancing with regions undescribed.
         *
         * Once, not every time: an annotator legitimately draws every region
         * first and captions them afterwards, and a hard gate mid-pass is an
         * obstacle. `require_all` is therefore a nudge, not a rule -- the
         * second Next goes through. This is documented on the schema; if you
         * need a gate, use `label_requirement.required`.
         *
         * document + capture + stopImmediatePropagation: `#next-btn` navigates
         * from an inline onclick registered at parse time, so a listener on the
         * button runs second and the warning flashes past.
         */
        _installNavGuard() {
            if (!this.config.requireAll) return;
            this._warned = false;
            document.addEventListener('click', (event) => {
                const target = event.target && event.target.closest
                    ? event.target.closest('#next-btn, #submit-btn') : null;
                if (!target) return;
                const remaining = this.undescribed();
                if (!remaining.length || this._warned) return;
                event.preventDefault();
                event.stopImmediatePropagation();
                this._warned = true;
                const message = `${remaining.length} region(s) still have no `
                    + 'description. Press Next again to continue anyway.';
                if (this.progress) this.progress.textContent = message;
                if (this.announcer) this.announcer.textContent = message;
            }, true);
        }
    }

    global.RegionCaptionManager = RegionCaptionManager;
})(typeof window !== 'undefined' ? window : globalThis);
