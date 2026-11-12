/**
 * The in-browser model tools are assistance, and are off for an annotator in
 * the study's no-assistance comparison group (ai_support.holdout) or on a
 * blind labeling-engine item. The server says which through
 * window.config.assist_withheld; the image tool drops its segmentation and
 * text-prompt config, refuses the SAM tool and hides both controls.
 */

global.fabric = {};
require('../../potato/static/mask-buffer.js');
const ImageAnnotationManager = require('../../potato/static/image-annotation.js');

const CONFIG = {schemaName: 'objects', labels: ['car'], tools: ['bbox', 'sam'],
                segmentation: {model: 'mobile_sam'}, textPrompt: {model: 'gdino'}};

function page() {
    document.body.innerHTML = `
      <div class="image-annotation-container" data-schema="objects">
        <button class="tool-btn" data-tool="bbox"></button>
        <button class="tool-btn" data-tool="sam"></button>
        <div class="text-prompt-group"><button class="text-prompt-run"></button></div>
      </div>`;
}

afterEach(() => { delete window.config; });

test('withheld: no model tools in the config, and SAM cannot be selected', () => {
    window.config = {assist_withheld: true};
    const m = new ImageAnnotationManager('c', 'i', CONFIG);
    expect(m.assistWithheld).toBe(true);
    expect(m.config.segmentation).toBeNull();
    expect(m.config.textPrompt).toBeNull();
    expect(CONFIG.segmentation).toEqual({model: 'mobile_sam'});  // the shared config is untouched
    m._telemetry = () => {};
    m.setTool('sam');
    expect(m.currentTool).not.toBe('sam');
});

test('withheld: the SAM button and the prompt box are hidden', () => {
    page();
    window.config = {assist_withheld: true};
    const m = new ImageAnnotationManager('c', 'i', CONFIG);
    m._hideAssistControls();
    expect(document.querySelector('[data-tool="sam"]').hidden).toBe(true);
    expect(document.querySelector('.text-prompt-group').hidden).toBe(true);
    expect(document.querySelector('[data-tool="bbox"]').hidden).toBe(false);
});

test('assisted: nothing changes', () => {
    window.config = {assist_withheld: false};
    const m = new ImageAnnotationManager('c', 'i', CONFIG);
    expect(m.assistWithheld).toBe(false);
    expect(m.config.segmentation).toEqual({model: 'mobile_sam'});
});
