"""
Regression tests for quality-control feedback handling in annotation.js.

These tests execute the real browser script through Node's vm module so we can
verify the frontend behavior without pulling in a separate Jest toolchain.
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def _run_annotation_qc_script() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script = r"""
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const annotationPath = path.join(process.cwd(), 'potato', 'static', 'annotation.js');
const source = fs.readFileSync(annotationPath, 'utf8');

const elements = {
  'main-content': { style: { display: 'block' } },
  'error-state': { style: { display: 'none' } },
  'error-message-text': { style: {}, textContent: '' },
};

const sandbox = {
  console,
  setTimeout,
  clearTimeout,
  Blob: class Blob {
    constructor(parts, options) {
      this.parts = parts;
      this.options = options;
    }
  },
  Event: class Event {
    constructor(type, options = {}) {
      this.type = type;
      this.options = options;
    }
  },
  MutationObserver: class MutationObserver {
    observe() {}
    disconnect() {}
  },
  AIAssistantManager: class AIAssistantManager {},
  navigator: { sendBeacon: () => true },
  window: {},
  document: {
    addEventListener: () => {},
    getElementById: (id) => elements[id] || null,
    querySelectorAll: () => [],
    body: { appendChild: () => {} },
  },
};

sandbox.window = sandbox;
sandbox.window.document = sandbox.document;
sandbox.window.addEventListener = () => {};
sandbox.window.location = { search: '' };

vm.runInNewContext(source, sandbox, { filename: annotationPath });

const calls = [];
sandbox.showNotification = (message, type = 'info') => {
  calls.push({ kind: 'notification', message, type });
};
sandbox.showError = (show, message = '') => {
  calls.push({ kind: 'error', show, message });
  if (show) {
    elements['error-state'].style.display = 'block';
    elements['main-content'].style.display = 'none';
    elements['error-message-text'].textContent = message;
  }
};

sandbox.handleQualityControlResponse({
  status: 'success',
  warning: true,
  warning_message: 'Please read items carefully before answering.',
  qc_result: {
    type: 'attention_check',
    warning: true,
    message: 'Please read items carefully before answering.',
  },
});

assert.deepStrictEqual(calls[0], {
  kind: 'notification',
  message: 'Please read items carefully before answering.',
  type: 'warning',
});
assert.strictEqual(calls.length, 1);

calls.length = 0;

sandbox.handleQualityControlResponse({
  status: 'blocked',
  message: 'You have been blocked due to too many incorrect attention check responses.',
  qc_result: {
    type: 'attention_check',
    blocked: true,
    message: 'You have been blocked due to too many incorrect attention check responses.',
  },
});

assert.deepStrictEqual(calls[0], {
  kind: 'notification',
  message: 'You have been blocked due to too many incorrect attention check responses.',
  type: 'error',
});
assert.deepStrictEqual(calls[1], {
  kind: 'error',
  show: true,
  message: 'You have been blocked due to too many incorrect attention check responses.',
});
assert.strictEqual(elements['error-state'].style.display, 'block');
assert.strictEqual(elements['main-content'].style.display, 'none');
assert.strictEqual(
  elements['error-message-text'].textContent,
  'You have been blocked due to too many incorrect attention check responses.'
);
"""

    result = subprocess.run(
        ["node", "-e", script],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise AssertionError(
            "Node regression script failed:\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )


def test_annotation_qc_feedback_is_visible():
    _run_annotation_qc_script()
