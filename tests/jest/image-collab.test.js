/**
 * image_annotation's live-session applier (collab.js applyWidget).
 *
 * A teammate's shapes replace this page's. The exception is a canvas another
 * scheme draws on: grounding_eval shows one phrase's regions at a time on an
 * image scheme, so the image answer a teammate saved holds THEIR active
 * phrase. Loaded here it put that phrase's regions on screen under this
 * member's phrase; grounding_eval redraws its own canvas from its own answer.
 */

global.fabric = { Point: function () {}, Rect: function () {}, util: { transformPoint: (p) => p } };
require('../../potato/static/mask-buffer.js');
require('../../potato/static/image-annotation.js');

function page(companion) {
    document.body.innerHTML = `
        <form data-schema-name="objects" data-annotation-type="image_annotation">
          <div class="image-annotation-container" data-schema="objects"></div>
          <input type="hidden" class="annotation-data-input" name="objects">
        </form>`;
    const input = document.querySelector('input');
    if (companion) input.dataset.companionCanvas = 'true';
    const manager = { applyRemoteAnswer: jest.fn(() => true) };
    document.querySelector('.image-annotation-container').annotationManager = manager;
    return { form: document.querySelector('form'), input, manager };
}

const apply = (ctx) => window.potatoCollabWidgets.image_annotation.apply(
    Object.assign({ schema: 'objects', value: '[{"id":"a"}]' }, ctx));

test("a teammate's shapes are loaded onto this page's canvas", () => {
    const { form, input, manager } = page(false);
    expect(apply({ form, input })).toBe(true);
    expect(manager.applyRemoteAnswer).toHaveBeenCalledWith('[{"id":"a"}]');
});

test("a companion canvas is left to the scheme that draws on it", () => {
    const { form, input, manager } = page(true);
    expect(apply({ form, input })).toBe(true);
    expect(manager.applyRemoteAnswer).not.toHaveBeenCalled();
});

test('with no manager on the page it is not shown', () => {
    const { form, input } = page(false);
    document.querySelector('.image-annotation-container').annotationManager = undefined;
    expect(apply({ form, input })).toBe(false);
});
