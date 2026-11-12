/**
 * Point-cloud sequences: after a frame loads, its neighbours are fetched and
 * parsed in the background, so stepping to them does not wait on the network.
 * The cache holds parsed clouds by URL, shares a fetch still in flight, keeps
 * no failures, and stays small.
 */

window.ObjectAttributes = require('../../potato/static/object-attributes.js');
const wire = require('../../potato/static/pointcloud/pc-wire.js');
window.PointCloudWire = window.PointCloudWire || wire;
window.PointCloudSequence = require('../../potato/static/pointcloud/pc-sequence.js');
const Manager = require('../../potato/static/pointcloud/pc-viewer.js');

const FRAMES = Array.from({ length: 13 }, (_v, i) => `f${i}.bin`);

function manager() {
    document.body.innerHTML = `
      <div class="pointcloud-annotation-container annotation-form">
        <input type="hidden" id="input-objects" value="[]">
        <p class="pc-status"></p><p class="pc-announce" aria-live="polite"></p>
      </div>`;
    const m = new Manager('pc-canvas-objects', 'input-objects',
                          { schema: 'objects', labels: [{ name: 'car', color: '#f00' }], lod: false });
    Object.assign(m, {
        container: document.querySelector('.pointcloud-annotation-container'),
        _buildPoints: jest.fn(), _setOrigin: jest.fn(), _render: () => {},
    });
    m.frames = FRAMES.slice();
    m.frameIndex = 0;
    return m;
}

let requested;
let failing;
beforeEach(() => {
    requested = [];
    failing = new Set();
    jest.spyOn(wire, 'parseWire').mockImplementation((buffer) => ({ header: { n: buffer.byteLength }, positions: new Float32Array(3) }));
    jest.spyOn(wire, 'originOf').mockReturnValue([0, 0, 0]);
    jest.spyOn(wire, 'describeCloud').mockReturnValue('cloud');
    global.fetch = jest.fn(async (url) => {
        requested.push(url.replace('/media/pointcloud/', ''));
        if (failing.has(url.replace('/media/pointcloud/', ''))) {
            return { ok: false, status: 404, json: async () => ({ error: 'no such cloud' }) };
        }
        return { ok: true, arrayBuffer: async () => new ArrayBuffer(8), json: async () => ({ manifest: url }) };
    });
});
afterEach(() => jest.restoreAllMocks());

const settle = () => new Promise((resolve) => setTimeout(resolve, 0));

test('loading a frame fetches the next, the previous and the one after next', async () => {
    const m = manager();
    m.frameIndex = 3;
    await m._loadCloud();
    await settle();
    expect(requested).toEqual(['f3.bin', 'f4.bin', 'f2.bin', 'f5.bin']);
});

test('stepping to a prefetched frame does not fetch it again', async () => {
    const m = manager();
    await m._loadCloud();
    await settle();
    expect(requested).toEqual(['f0.bin', 'f1.bin', 'f2.bin']);   // nothing before frame 0
    requested = [];
    m.frameIndex = 1;
    await m._loadCloud();
    await settle();
    // f1 came from the cache; only f3 (two ahead) is new.
    expect(requested).toEqual(['f3.bin']);
    expect(m._buildPoints).toHaveBeenCalledTimes(2);
});

test('a frame asked for while its prefetch is in flight shares that fetch', async () => {
    const m = manager();
    const first = m._fetchParsed('/media/pointcloud/f6.bin');
    const second = m._fetchParsed('/media/pointcloud/f6.bin');
    expect(second).toBe(first);
    await first;
    expect(requested).toEqual(['f6.bin']);
});

test('a failed fetch is not cached, and its message reaches the status line', async () => {
    const m = manager();
    failing.add('f0.bin');
    await m._loadCloud();
    expect(document.querySelector('.pc-status').textContent).toBe('no such cloud');
    expect(m._cloudCache.has('/media/pointcloud/f0.bin')).toBe(false);
    failing.clear();
    await m._loadCloud();
    expect(requested.filter((u) => u === 'f0.bin')).toHaveLength(2);
    expect(m._buildPoints).toHaveBeenCalledTimes(1);
});

test('the cache keeps the ten most recently used entries', async () => {
    const m = manager();
    for (const name of FRAMES.slice(0, 12)) await m._fetchParsed(`/media/pointcloud/${name}`);
    expect(Array.from(m._cloudCache.keys())).toEqual(
        FRAMES.slice(2, 12).map((n) => `/media/pointcloud/${n}`));
    await m._fetchParsed('/media/pointcloud/f2.bin');      // used again: now newest
    await m._fetchParsed('/media/pointcloud/f12.bin');     // evicts f3, the oldest
    expect(m._cloudCache.has('/media/pointcloud/f2.bin')).toBe(true);
    expect(m._cloudCache.has('/media/pointcloud/f3.bin')).toBe(false);
});

test('an octree cloud prefetches each neighbour\'s manifest and root node', async () => {
    const m = manager();
    window.PointCloudOctree = window.PointCloudOctree || {};
    m.config.lod = true;
    m.frameIndex = 4;
    m._prefetchNeighbours();
    await settle();
    expect(requested).toEqual([
        'f5.bin?lod=1', 'f5.bin?lod=1&node=r',
        'f3.bin?lod=1', 'f3.bin?lod=1&node=r',
        'f6.bin?lod=1', 'f6.bin?lod=1&node=r']);
    expect(await m._fetchParsed('/media/pointcloud/f5.bin?lod=1', 'json'))
        .toEqual({ manifest: '/media/pointcloud/f5.bin?lod=1' });
    expect(requested).toHaveLength(6);   // the manifest came from the cache
});

test('a single cloud prefetches nothing', async () => {
    const m = manager();
    m.frames = null;
    m._cloudPath = () => 'scan.bin';
    await m._loadCloud();
    await settle();
    expect(requested).toEqual(['scan.bin']);
});
