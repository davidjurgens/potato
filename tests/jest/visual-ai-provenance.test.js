/**
 * An accepted detection names the model that proposed it.
 *
 * `ai_model` was declared in PROVENANCE_KEYS, carried by the serializer, and
 * exported by COCO before anything produced a value for it — a field correct
 * in the model and empty in practice. Two halves had to be wired: the server
 * naming the model on the response, and this file reading it off and passing
 * it to `addAnnotation`.
 *
 * This drives the second half. The first is a one-line stamp in
 * `ai_cache.generate_image_annotation`, and the function between it and the
 * wire (`validate_suggested_choice`) mutates in place, so the key survives.
 */

const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'potato', 'static',
                      'visual_ai_assistant.js');

function loadManager() {
    const source = fs.readFileSync(SRC, 'utf8');
    const module_ = { exports: {} };
    // eslint-disable-next-line no-new-func
    (new Function('module', 'exports', 'window', 'document', source))(
        module_, module_.exports, {}, { addEventListener() {} });
    return module_.exports;
}

const VisualAIAssistantManager = loadManager();

/** An assistant with only what the two methods under test touch. */
function makeAssistant() {
    const added = [];
    const assistant = Object.create(VisualAIAssistantManager.prototype);
    assistant.suggestionObjects = new Map();
    assistant.annotationType = 'image_annotation';
    assistant._getLabelColor = () => '#0f0';
    assistant._renderDetections = () => {};
    assistant._showHint = () => {};
    assistant.annotationManager = {
        setLabel: () => {},
        addAnnotation: (obj) => { added.push(obj); return true; },
    };
    assistant.added = added;
    return assistant;
}

const DETECTION = {
    id: 'd1',
    data: { label: 'cell', confidence: 0.63,
            bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.25 } },
};

describe('the model that proposed a detection', () => {
    test('is read off the response and travels with the accepted shape', () => {
        const assistant = makeAssistant();
        assistant._handleSuggestionResponse('detection', {
            model: 'yolov8n', detections: [DETECTION.data],
        });
        assistant._convertDetectionToAnnotation(DETECTION);

        expect(assistant.added).toHaveLength(1);
        expect(assistant.added[0].source).toBe('ai');
        expect(assistant.added[0].ai_model).toBe('yolov8n');
        expect(assistant.added[0].confidence).toBeCloseTo(0.63, 5);
    });

    test('a response that names no model still marks the shape as a model\'s', () => {
        // The origin is known even when the model's name is not. `carryProvenance`
        // drops the empty string, so nothing claims a model called "".
        const assistant = makeAssistant();
        assistant._handleSuggestionResponse('detection', {
            detections: [DETECTION.data],
        });
        assistant._convertDetectionToAnnotation(DETECTION);

        expect(assistant.added[0].source).toBe('ai');
        expect(assistant.added[0].ai_model).toBe('');
    });

    test('a detection with no score does not claim a confidence of zero', () => {
        // Absent means unknown. Zero means the model was not confident, which
        // is a different fact and a real one.
        const assistant = makeAssistant();
        assistant._handleSuggestionResponse('detection', { model: 'yolov8n' });
        assistant._convertDetectionToAnnotation({
            id: 'd2',
            data: { label: 'cell',
                    bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.25 } },
        });

        expect(assistant.added[0].confidence).toBeUndefined();
    });

    test('a score of exactly zero survives', () => {
        const assistant = makeAssistant();
        assistant._handleSuggestionResponse('detection', { model: 'yolov8n' });
        assistant._convertDetectionToAnnotation({
            id: 'd3',
            data: { label: 'cell', confidence: 0,
                    bbox: { x: 0.1, y: 0.2, width: 0.3, height: 0.25 } },
        });

        expect(assistant.added[0].confidence).toBe(0);
    });
});
