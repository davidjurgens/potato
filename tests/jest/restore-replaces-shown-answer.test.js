/**
 * annotation.js's restore pass, run over a page that already shows an answer.
 *
 * On page load the page shows nothing, so the restores only ever added: a
 * selected class, a highlight. A live session runs them again to show a
 * teammate's answer over this member's, and then the old selection stayed
 * lit beside the new one (pairwise, best-worst scaling), an unanswerable
 * extractive-QA answer kept the old highlight, and an answer with text kept
 * the "unanswerable" button active.
 */

const fs = require('fs');
const path = require('path');

const SOURCE = path.join(__dirname, '..', '..', 'potato', 'static', 'annotation.js');

function extractFunction(source, name) {
    const start = source.indexOf(`function ${name}(`);
    if (start === -1) throw new Error(`${name}() not found in annotation.js`);
    const open = source.indexOf('{', start);
    let depth = 0;
    for (let j = open; j < source.length; j++) {
        if (source[j] === '{') depth++;
        else if (source[j] === '}') {
            depth--;
            if (depth === 0) return source.slice(start, j + 1);
        }
    }
    throw new Error(`unbalanced braces reading ${name}()`);
}

function load(answers) {
    const src = fs.readFileSync(SOURCE, 'utf8');
    const names = ['restorePairwiseAnnotations', 'restoreBwsAnnotations',
                   'restoreExtractiveQaAnnotations', 'updatePairwiseRationaleCounter',
                   'savePairwiseJustification'];
    // eslint-disable-next-line no-new-func
    return new Function('currentAnnotations', `
        function debugLog() {}
        function syncPairwiseTileAria() {}
        ${names.map((n) => extractFunction(src, n)).join('\n')}
        return {restorePairwiseAnnotations, restoreBwsAnnotations, restoreExtractiveQaAnnotations};
    `)(answers);
}

const selected = (sel) => [...document.querySelectorAll(sel)]
    .filter((t) => t.classList.contains('selected')).map((t) => t.dataset.value);

test('pairwise: the teammate\'s choice replaces the one on screen', () => {
    document.body.innerHTML = `
        <form class="annotation-form pairwise-binary">
          <div class="pairwise-tile selected" data-value="A">A</div>
          <div class="pairwise-tile" data-value="B">B</div>
          <button class="pairwise-tie-btn" data-value="tie">Tie</button>
          <input type="hidden" class="pairwise-value" schema="pref" label_name="selection" value="A">
        </form>`;
    load({ pref: { selection: 'B' } }).restorePairwiseAnnotations();
    expect(selected('.pairwise-tile, .pairwise-tie-btn')).toEqual(['B']);

    load({ pref: { selection: 'tie' } }).restorePairwiseAnnotations();
    expect(selected('.pairwise-tile, .pairwise-tie-btn')).toEqual(['tie']);
});

test('pairwise: a justification without a rationale empties the one shown', () => {
    document.body.innerHTML = `
        <div class="pairwise-justification" data-schema="pref">
          <input type="checkbox" class="pairwise-reason-cb" value="clearer" checked>
          <textarea class="pairwise-rationale-textarea" data-schema="pref">my old reason</textarea>
          <span class="pairwise-rationale-counter"></span>
          <input type="hidden" class="pairwise-justification-value">
        </div>`;
    load({ pref: { justification: JSON.stringify({ reasons: [], rationale: '' }) } })
        .restorePairwiseAnnotations();
    expect(document.querySelector('.pairwise-rationale-textarea').value).toBe('');
    expect(document.querySelector('.pairwise-reason-cb').checked).toBe(false);
});

test('best-worst scaling: one best and one worst, the teammate\'s', () => {
    document.body.innerHTML = `
        <form class="annotation-form bws">
          <div class="bws-best-tile selected" data-value="1"></div><div class="bws-best-tile" data-value="2"></div>
          <div class="bws-worst-tile selected" data-value="2"></div><div class="bws-worst-tile" data-value="3"></div>
          <input type="hidden" class="bws-value" schema="bws" label_name="best" value="1">
          <input type="hidden" class="bws-value" schema="bws" label_name="worst" value="2">
        </form>`;
    load({ bws: { best: '2', worst: '3' } }).restoreBwsAnnotations();
    expect(selected('.bws-best-tile')).toEqual(['2']);
    expect(selected('.bws-worst-tile')).toEqual(['3']);
});

function eqaPage() {
    document.body.innerHTML = `
        <div class="shadcn-extractive-qa-container" data-schema-name="qa">
          <div id="qa-passage">The capital is Paris.</div>
          <span id="qa-answer-text"></span>
          <button id="qa-unanswerable"></button>
          <input type="hidden" class="eqa-data-input" label_name="answer">
        </div>`;
}

test('extractive QA: "unanswerable" over a highlighted answer drops the highlight', () => {
    eqaPage();
    load({ qa: { answer: JSON.stringify({ answer_text: 'Paris', start: 15, end: 20 }) } })
        .restoreExtractiveQaAnnotations();
    expect(document.querySelectorAll('#qa-passage .eqa-highlight')).toHaveLength(1);

    load({ qa: { answer: JSON.stringify({ unanswerable: true }) } }).restoreExtractiveQaAnnotations();
    expect(document.querySelectorAll('#qa-passage .eqa-highlight')).toHaveLength(0);
    expect(document.getElementById('qa-passage').textContent).toBe('The capital is Paris.');
    expect(document.getElementById('qa-unanswerable').classList.contains('eqa-unanswerable-active')).toBe(true);
});

test('extractive QA: an answer over "unanswerable" turns the button off', () => {
    eqaPage();
    load({ qa: { answer: JSON.stringify({ unanswerable: true }) } }).restoreExtractiveQaAnnotations();
    load({ qa: { answer: JSON.stringify({ answer_text: 'capital', start: 4, end: 11 }) } })
        .restoreExtractiveQaAnnotations();
    expect(document.getElementById('qa-unanswerable').classList.contains('eqa-unanswerable-active')).toBe(false);
    expect(document.querySelector('#qa-passage .eqa-highlight').textContent).toBe('capital');
});
