/**
 * AI-usage telemetry names the scheme, not its position.
 *
 * ai_assistant_manager.js passed the numeric annotation id to
 * interactionTracker.trackAIRequest/trackAIResponse, so AIUsageEvent.schema_name
 * was stored as "0", "1", ... and the save path -- which stamps
 * final_annotation by scheme name -- never matched an event. Nothing could say
 * what an annotator did after asking for a hint.
 */
global.aiDebugLog = () => {};
const fs = require('fs');
const path = require('path');

const SRC = path.join(__dirname, '..', '..', 'potato', 'static', 'ai_assistant_manager.js');
// The file declares a class and wires itself to the page; only the class is
// needed here.
const source = fs.readFileSync(SRC, 'utf8');
const classOnly = source.slice(source.indexOf('class AIAssistantManager'));
const AIAssistantManager = new Function(
    `${classOnly.split(/\n(?=document\.addEventListener|window\.addEventListener|if \(typeof module)/)[0]}; return AIAssistantManager;`)();

describe('schemaNameFor', () => {
    beforeEach(() => {
        document.body.innerHTML = `
          <form class="annotation-form" data-annotation-id="0" data-schema-name="sentiment"></form>
          <form class="annotation-form" data-annotation-id="1" id="toxicity"></form>`;
    });

    test('reads data-schema-name', () => {
        const m = Object.create(AIAssistantManager.prototype);
        expect(m.schemaNameFor(0)).toBe('sentiment');
    });

    test('falls back to the form id, then the id itself', () => {
        const m = Object.create(AIAssistantManager.prototype);
        expect(m.schemaNameFor('1')).toBe('toxicity');
        expect(m.schemaNameFor(7)).toBe('7');
    });

    test('the tracker receives the name', async () => {
        const calls = [];
        window.interactionTracker = {
            trackAIRequest: (name) => calls.push(['request', name]),
            trackAIResponse: (name) => calls.push(['response', name]),
        };
        const m = Object.create(AIAssistantManager.prototype);
        m.assistantConfig = { hint: { className: 'hint' } };
        m.startLoading = () => {};
        m.fetchAssistantData = async () => ({ hint: 'x' });
        m.extractSuggestionsFromData = () => ['x'];
        m.renderAssistant = () => {};
        await m.getAiAssistantDefault('hint', 0, document.createElement('div'));
        expect(calls).toEqual([['request', 'sentiment'], ['response', 'sentiment']]);
    });
});
