/**
 * Shared base for every browser-side ONNX model Potato runs.
 *
 * WHY A BASE CLASS RATHER THAN COPY-PASTE
 * ---------------------------------------
 * Three models now run in the annotator's browser — click-to-segment, text
 * prompting, and video tracking — and a fourth will follow. Everything they
 * share is the part that took the longest to get right the first time:
 *
 *  * **Resolving the runtime.** ONNX Runtime Web is fetched, not vendored, so
 *    "is it here?" is a real question with three different answers.
 *  * **Telling a missing MODEL from a missing RUNTIME.** These have different
 *    fixes, and a wrong guess sends an administrator to run the wrong command.
 *    An earlier version reported "the mobile_sam model is not installed" when
 *    the ORT wasm glue module was missing, which is false and unfixable by the
 *    command it suggested.
 *  * **Having a named state for every failure.** Missing model, dead runtime,
 *    failed inference: each is reachable in normal use and each needs to say
 *    what to do next. A tool that silently does nothing when the weights are
 *    absent is worse than one that is absent.
 *
 * A model that inherits this needs to supply only its own graphs and its own
 * tensor work.
 *
 * WHAT SUBCLASSES OVERRIDE
 * ------------------------
 *  * `graphFiles()` — map of graph name to URL. Required.
 *  * `modelLabel()` — the key used in "run potato download-models X".
 *  * `extraStatusMessage(kind)` — model-specific wording, optional.
 */

(function (global) {
    'use strict';

    const MODEL_STATE = {
        IDLE: 'idle',
        LOADING_RUNTIME: 'loading-runtime',
        LOADING_MODEL: 'loading-model',
        RUNNING: 'running',
        READY: 'ready',
        ERROR: 'error',
    };

    /** Errors the UI is expected to render differently. */
    const MODEL_ERROR = {
        RUNTIME_UNAVAILABLE: 'runtime-unavailable',
        MODEL_MISSING: 'model-missing',
        INPUT_FAILED: 'input-failed',
        INFERENCE_FAILED: 'inference-failed',
    };

    class ModelSession {
        /**
         * @param {object} options
         * @param {string} [options.model]        model key, e.g. 'mobile_sam'
         * @param {string} [options.modelBaseUrl] where the .onnx files live
         * @param {object} [options.runtime]      injected ONNX runtime
         * @param {function} [options.onStateChange] called with (state, detail)
         */
        constructor(options = {}) {
            this.model = options.model || this.constructor.DEFAULT_MODEL || '';
            this.modelBaseUrl = (options.modelBaseUrl || '/models')
                .replace(/\/+$/, '');
            this.runtime = options.runtime || null;
            this.onStateChange = options.onStateChange || null;

            this.state = MODEL_STATE.IDLE;
            this.error = null;
            this.errorKind = null;

            /** Loaded InferenceSessions, by graph name. */
            this.graphs = {};
        }

        _setState(state, detail) {
            this.state = state;
            if (this.onStateChange) this.onStateChange(state, detail);
        }

        _fail(kind, message) {
            this.errorKind = kind;
            this.error = message;
            this._setState(MODEL_STATE.ERROR, { kind, message });
            return null;
        }

        _clearError() {
            this.errorKind = null;
            this.error = null;
        }

        /** Where this model's files are served from. */
        baseUrl() {
            return `${this.modelBaseUrl}/${this.model}`;
        }

        /**
         * Graph name -> URL. Subclasses override.
         *
         * A subclass may return absolute URLs (the model zoo resolves them
         * server-side) or bare file names, which are taken as relative to
         * `baseUrl()`.
         */
        graphFiles() {
            return {};
        }

        /** The key an administrator would pass to `potato download-models`. */
        modelLabel() {
            return this.model;
        }

        _resolveUrl(nameOrUrl) {
            if (/^(https?:)?\/\//.test(nameOrUrl) || nameOrUrl.startsWith('/')) {
                return nameOrUrl;
            }
            return `${this.baseUrl()}/${nameOrUrl}`;
        }

        /** True once every declared graph is loaded. */
        isReady() {
            const names = Object.keys(this.graphFiles());
            return names.length > 0 && names.every((n) => !!this.graphs[n]);
        }

        /** Resolve the ONNX runtime, preferring an injected or global one. */
        async _getRuntime() {
            if (this.runtime) return this.runtime;
            if (typeof global !== 'undefined' && global.ort) {
                this.runtime = global.ort;
                return this.runtime;
            }
            return this._fail(
                MODEL_ERROR.RUNTIME_UNAVAILABLE,
                'ONNX Runtime Web is not loaded');
        }

        /**
         * Load every graph. Safe to call repeatedly.
         *
         * @returns {Promise<boolean>} true when the model can run
         */
        async load() {
            if (this.isReady()) return true;

            this._setState(MODEL_STATE.LOADING_RUNTIME);
            const runtime = await this._getRuntime();
            if (!runtime) return false;

            this._setState(MODEL_STATE.LOADING_MODEL, { model: this.model });
            const files = this.graphFiles();
            try {
                const names = Object.keys(files);
                const sessions = await Promise.all(names.map(
                    (name) => runtime.InferenceSession.create(
                        this._resolveUrl(files[name]))));
                names.forEach((name, i) => { this.graphs[name] = sessions[i]; });
            } catch (err) {
                this.graphs = {};
                const message = (err && err.message) || String(err);
                return !!this._fail(this._classifyLoadError(message), message);
            }

            this._clearError();
            this._setState(MODEL_STATE.READY);
            return true;
        }

        /**
         * Decide whether a load failure is the MODEL's fault or the RUNTIME's.
         *
         * This distinction is the whole value of the error: the two have
         * different fixes. The runtime's own failures name its internals
         * (backend, wasm, initWasm, .mjs), so they are checked FIRST and win.
         */
        _classifyLoadError(message) {
            const text = String(message || '');
            if (/no available backend|initWasm|ort-wasm|\.mjs|wasm/i.test(text)) {
                return MODEL_ERROR.RUNTIME_UNAVAILABLE;
            }
            if (/404|not found|failed to fetch/i.test(text)) {
                return MODEL_ERROR.MODEL_MISSING;
            }
            return MODEL_ERROR.RUNTIME_UNAVAILABLE;
        }

        /** Model-specific wording. Return '' to use the shared message. */
        extraStatusMessage() {
            return '';
        }

        /**
         * What the annotator can still do without this model.
         *
         * Appended to the shared messages. A tool that is unavailable is far
         * less alarming when the sentence that says so also says what still
         * works, and only the subclass knows what that is.
         */
        fallbackHint() {
            return '';
        }

        /**
         * A message the UI can show verbatim. Each names the next action,
         * because "unavailable" tells the annotator nothing.
         */
        statusMessage() {
            const specific = this.extraStatusMessage(this.errorKind);
            if (specific) return specific;
            const hint = this.fallbackHint();
            switch (this.errorKind) {
                case MODEL_ERROR.RUNTIME_UNAVAILABLE:
                    // Covers both "the browser cannot" and "the runtime files
                    // are missing", because from here they are
                    // indistinguishable and both fixes are worth naming.
                    return 'The inference runtime could not start. An '
                         + 'administrator can install it with:  '
                         + 'potato download-models onnxruntime  — if it is '
                         + 'already installed, this browser has WebAssembly '
                         + 'disabled.' + hint;
                case MODEL_ERROR.MODEL_MISSING:
                    return `The ${this.modelLabel()} model is not installed. An `
                         + `administrator can add it with:  `
                         + `potato download-models ${this.modelLabel()}` + hint;
                case MODEL_ERROR.INPUT_FAILED:
                    return 'This input could not be prepared for the model.';
                case MODEL_ERROR.INFERENCE_FAILED:
                    return 'The model could not produce a result for that '
                         + 'input. Try again, or use the manual tools.';
                default:
                    return '';
            }
        }

        /**
         * Run one graph.
         *
         * Wraps the failure so every model reports inference errors the same
         * way rather than each inventing its own.
         */
        async run(graphName, feeds) {
            const session = this.graphs[graphName];
            if (!session) {
                return this._fail(MODEL_ERROR.MODEL_MISSING,
                                  `graph ${graphName} is not loaded`);
            }
            try {
                return await session.run(feeds);
            } catch (err) {
                return this._fail(MODEL_ERROR.INFERENCE_FAILED,
                                  (err && err.message) || String(err));
            }
        }

        /** Build a runtime tensor without every caller naming the runtime. */
        tensor(type, data, dims) {
            return new this.runtime.Tensor(type, data, dims);
        }

        /** Release graphs. Subclasses that cache more should extend this. */
        reset() {
            this.graphs = {};
            this._clearError();
            this.state = MODEL_STATE.IDLE;
        }
    }

    /**
     * A least-recently-used map.
     *
     * Every model here caches something expensive per input — an image
     * embedding, a tokenized prompt, a frame's features — and every one of
     * them grows without bound in a long session. Insertion order is the wrong
     * eviction order: an annotator flipping between two images evicts the one
     * they keep returning to. Re-inserting on read fixes that, and is easy to
     * forget, so it lives here once.
     */
    class LruCache {
        constructor(limit = 4) {
            this.limit = limit;
            this._map = new Map();
        }

        get(key) {
            if (!this._map.has(key)) return undefined;
            const value = this._map.get(key);
            // Re-insert to mark it recently USED, not recently inserted.
            this._map.delete(key);
            this._map.set(key, value);
            return value;
        }

        has(key) {
            return this._map.has(key);
        }

        set(key, value) {
            if (this._map.has(key)) this._map.delete(key);
            this._map.set(key, value);
            while (this._map.size > this.limit) {
                const oldest = this._map.keys().next().value;
                this._map.delete(oldest);
            }
            return value;
        }

        delete(key) {
            return this._map.delete(key);
        }

        clear() {
            this._map.clear();
        }

        get size() {
            return this._map.size;
        }
    }

    const api = { ModelSession, MODEL_STATE, MODEL_ERROR, LruCache };
    if (typeof module !== 'undefined' && module.exports) {
        module.exports = api;
    }
    if (global) {
        global.ModelSession = ModelSession;
        global.MODEL_STATE = MODEL_STATE;
        global.MODEL_ERROR = MODEL_ERROR;
        global.LruCache = LruCache;
    }
})(typeof window !== 'undefined' ? window : this);
