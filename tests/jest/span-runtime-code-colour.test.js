/**
 * Codes minted at runtime get a colour of their own.
 *
 * /api/colors only knows the labels the config declared. Everything the
 * annotator mints during open coding falls through to the fallback, and that
 * fallback was a single constant: every new code highlighted in the same faint
 * purple as the first built-in label, and its palette chip was transparent.
 * In a QDA project, minting codes is the work — so the feature's main output
 * was a set of visually identical codes.
 *
 * codebook.js had already documented the intended behaviour ("color is
 * hash-derived in SpanManager (getSpanColor)"). It was not implemented.
 */

const { SpanManager } = require('../../potato/static/span-core.js');

/** A manager with a loaded colour map, as it is after loadColors(). */
function managerWithColors(schema, colors) {
    const m = Object.create(SpanManager.prototype);
    m.currentSchema = schema;
    m.colors = { [schema]: colors };
    return m;
}

const CONFIGURED = {
    'access barriers': '(110, 86, 207)',
    'cost concerns': '(239, 68, 68)',
};

describe('configured labels still come from the server', () => {
    const m = managerWithColors('codes', CONFIGURED);

    test('the server colour wins', () => {
        expect(m.getSpanColor('access barriers')).toBe('rgba(110, 86, 207, 0.15)');
        expect(m.getSpanColor('cost concerns')).toBe('rgba(239, 68, 68, 0.15)');
    });
});

describe('a code minted at runtime', () => {
    const m = managerWithColors('codes', CONFIGURED);

    test('does not come back as the default purple', () => {
        // The regression: every minted code used to return this exact string,
        // which is also 'access barriers' — the first built-in label.
        const colour = m.getSpanColor('transport burden');
        expect(colour).not.toBe(m.getSpanColor('access barriers'));
    });

    test('gets a colour from the shared palette', () => {
        const colour = m.getSpanColor('transport burden');
        expect(colour).toMatch(/^rgba\(\d+, \d+, \d+, 0\.15\)$/);
        const triple = colour.replace('rgba', '').replace(', 0.15)', ')');
        expect(SpanManager.FALLBACK_PALETTE).toContain(triple);
    });

    test('gets the same colour every time', () => {
        // Stable across reloads and across annotators: hashed, not counted.
        const first = m.getSpanColor('transport burden');
        const second = managerWithColors('codes', CONFIGURED)
            .getSpanColor('transport burden');
        expect(second).toBe(first);
    });

    test('different codes generally get different colours', () => {
        const names = ['transport burden', 'wait times', 'staff attitude',
                       'referral loops', 'cost of parking', 'language access'];
        const colours = new Set(names.map((n) => m.getSpanColor(n)));
        // A 22-entry palette over 6 names: collisions are possible but a
        // single colour for all of them is the bug.
        expect(colours.size).toBeGreaterThan(3);
    });
});

describe('the fallback holds when nothing is loaded', () => {
    test('no schema set', () => {
        const m = Object.create(SpanManager.prototype);
        m.currentSchema = null;
        m.colors = {};
        expect(m.getSpanColor('anything')).toMatch(/^rgba\(\d+, \d+, \d+, 0\.15\)$/);
    });

    test('colours not fetched yet', () => {
        const m = Object.create(SpanManager.prototype);
        m.currentSchema = 'codes';
        m.colors = {};
        expect(m.getSpanColor('anything')).toMatch(/^rgba\(\d+, \d+, \d+, 0\.15\)$/);
    });

    test('an unknown schema', () => {
        const m = managerWithColors('other', CONFIGURED);
        m.currentSchema = 'codes';
        expect(m.getSpanColor('anything')).toMatch(/^rgba\(\d+, \d+, \d+, 0\.15\)$/);
    });

    test('an empty or null label does not throw', () => {
        const m = managerWithColors('codes', CONFIGURED);
        expect(() => m.getSpanColor('')).not.toThrow();
        expect(() => m.getSpanColor(null)).not.toThrow();
        expect(() => m.getSpanColor(undefined)).not.toThrow();
    });
});

describe('paletteColorFor', () => {
    const m = Object.create(SpanManager.prototype);

    test('returns the triple shape /api/colors uses', () => {
        expect(m.paletteColorFor('anything')).toMatch(/^\(\d+, \d+, \d+\)$/);
    });

    test('always lands inside the palette', () => {
        for (let i = 0; i < 200; i++) {
            expect(SpanManager.FALLBACK_PALETTE)
                .toContain(m.paletteColorFor(`code ${i}`));
        }
    });
});
