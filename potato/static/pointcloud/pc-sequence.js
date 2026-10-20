/**
 * Point-cloud sequences: keyframed 3D tracks across frames.
 *
 * A sequence item's cloud field holds a list of cloud paths, one per frame.
 * The stored annotation is the same flat list a single cloud stores, each
 * object with `frame` (0-based) and `track_id`. Only keyframes are stored;
 * between two keyframes of a track the object is interpolated (centre, size
 * and point position linearly, rotation by quaternion slerp), and outside its
 * first and last keyframe the track is absent. The server applies the same
 * rule in potato/export/spatial_sequences.py.
 *
 * The viewer keeps `annotations` as the current frame's VIEW, so selection,
 * meshes and the slab panels are unchanged. This module builds that view from
 * the store and merges it back. Free of three.js so Jest can test it.
 */
(function (root) {
    'use strict';

    /** The frame paths in a cloud field, or null for a single cloud. */
    function framesOf(value) {
        if (value && !Array.isArray(value) && typeof value === 'object') value = value.frames;
        if (Array.isArray(value) && value.length
                && value.every((v) => typeof v === 'string')) {
            return value.map((v) => v.trim());
        }
        return null;
    }

    function lerp(a, b, t) {
        return a.map((x, i) => x + (b[i] - x) * t);
    }

    function slerp(q0, q1, t) {
        let b = q1.slice();
        let dot = q0.reduce((s, v, i) => s + v * b[i], 0);
        if (dot < 0) { b = b.map((v) => -v); dot = -dot; }
        let out;
        if (dot > 0.9995) {
            out = lerp(q0, b, t);
        } else {
            const theta = Math.acos(Math.min(1, Math.max(-1, dot)));
            const s0 = Math.sin((1 - t) * theta) / Math.sin(theta);
            const s1 = Math.sin(t * theta) / Math.sin(theta);
            out = q0.map((v, i) => s0 * v + s1 * b[i]);
        }
        const norm = Math.sqrt(out.reduce((s, v) => s + v * v, 0)) || 1;
        return out.map((v) => v / norm);
    }

    function clone(obj) {
        return JSON.parse(JSON.stringify(obj));
    }

    /**
     * Whether two coordinate values are the same geometry, to a micrometre.
     *
     * Not string equality: the view goes through the origin shift and back
     * (pc-wire toLocal/toStored), which rounds, so an untouched object would
     * otherwise look edited and become a keyframe.
     */
    function sameCoordinates(a, b) {
        if (typeof a === 'number' && typeof b === 'number') return Math.abs(a - b) < 1e-4;
        if (Array.isArray(a) && Array.isArray(b)) {
            return a.length === b.length && a.every((v, i) => sameCoordinates(v, b[i]));
        }
        if (a && b && typeof a === 'object' && typeof b === 'object') {
            const keys = Object.keys(a);
            return keys.length === Object.keys(b).length
                && keys.every((k) => sameCoordinates(a[k], b[k]));
        }
        return a === b;
    }

    /** A stored copy: no view-only keys. */
    function storedCopy(obj) {
        const out = clone(obj);
        delete out.interpolated;
        delete out._from;
        delete out._fromAttrs;
        return out;
    }

    /** `{track_id: [keyframe objects sorted by frame]}`. */
    function tracksOf(store) {
        const out = {};
        (store || []).forEach((obj) => {
            if (!obj || obj.track_id === undefined || obj.track_id === null
                    || !Number.isInteger(obj.frame)) return;
            (out[obj.track_id] = out[obj.track_id] || []).push(obj);
        });
        Object.values(out).forEach((list) => list.sort((a, b) => a.frame - b.frame));
        return out;
    }

    /** One track at `frame`: a keyframe copy, an interpolation, or null. */
    function objectAt(keyframes, frame) {
        if (!keyframes.length || frame < keyframes[0].frame
                || frame > keyframes[keyframes.length - 1].frame) return null;
        for (let i = 0; i < keyframes.length; i++) {
            const k = keyframes[i];
            if (k.frame === frame) return clone(k);
            if (k.frame > frame) {
                const a = keyframes[i - 1];
                const t = (frame - a.frame) / (k.frame - a.frame);
                const out = clone(a);
                out.frame = frame;
                out.interpolated = true;
                const ca = a.coordinates, cb = k.coordinates;
                if (a.type === 'cuboid_3d' && k.type === 'cuboid_3d' && ca && cb) {
                    out.coordinates = Object.assign({}, ca, {
                        center: lerp(ca.center, cb.center, t),
                        size: lerp(ca.size, cb.size, t),
                        rotation: slerp(ca.rotation || [0, 0, 0, 1],
                                        cb.rotation || [0, 0, 0, 1], t),
                    });
                } else if (a.type === 'point_3d' && k.type === 'point_3d'
                           && Array.isArray(ca) && Array.isArray(cb)) {
                    out.coordinates = lerp(ca, cb, t);
                } else {
                    // Polylines and painted points do not interpolate: they
                    // appear only on their keyframes.
                    return null;
                }
                // The geometry the view started with, so a merge can tell an
                // edited interpolation (which becomes a keyframe) from one
                // that was only looked at. The attributes too: changing a
                // per_keyframe one on an in-between frame also makes one.
                out._from = clone(out.coordinates);
                out._fromAttrs = clone(out.attributes || {});
                return out;
            }
        }
        return null;
    }

    function trackOrder(a, b) {
        return String(a).localeCompare(String(b), undefined, { numeric: true });
    }

    /** Every track's object at `frame`, ordered by track id. */
    function viewAt(store, frame) {
        const tracks = tracksOf(store);
        return Object.keys(tracks).sort(trackOrder)
            .map((id) => objectAt(tracks[id], frame))
            .filter(Boolean);
    }

    /** The next unused track id: t1, t2, ... */
    function nextTrackId(store) {
        let n = 0;
        (store || []).forEach((obj) => {
            const m = /^t(\d+)$/.exec(String(obj && obj.track_id));
            if (m) n = Math.max(n, parseInt(m[1], 10));
        });
        return `t${n + 1}`;
    }

    /**
     * Merge the current frame's view (in the store's coordinates) back into
     * the store.
     *
     * An interpolated object whose geometry changed since the view was built
     * becomes a keyframe at `frame`, as does one whose `keyframeAttributes`
     * (the per_keyframe attribute names) changed; an unchanged one stays
     * interpolated and is not stored. A new object gets `frame` and a fresh
     * track id. Keyframes missing from the view were deleted. Label, colour
     * and the other attributes belong to the track, so the view's values are
     * copied to every keyframe of the track; a per_keyframe attribute stays
     * on its own keyframe and holds until the next one.
     *
     * Mutates the view objects (track id, frame, the `interpolated` flag) so
     * the caller can copy them back. Returns the new store.
     */
    function mergeView(store, frame, view, keyframeAttributes) {
        const perKeyframe = new Set(keyframeAttributes || []);
        const changedAttributes = (obj) => [...perKeyframe].some((name) =>
            JSON.stringify((obj.attributes || {})[name]) !== JSON.stringify((obj._fromAttrs || {})[name]));
        const merged = (store || []).filter((obj) => obj.frame !== frame);
        view.forEach((obj) => {
            if (obj.track_id === undefined || obj.track_id === null) {
                obj.track_id = nextTrackId(merged.concat(view));
            }
            obj.frame = frame;
            if (obj.interpolated) {
                if (sameCoordinates(obj._from, obj.coordinates) && !changedAttributes(obj)) return;
                delete obj.interpolated;
                delete obj._from;
                delete obj._fromAttrs;
            }
            merged.push(storedCopy(obj));
        });
        view.forEach((obj) => {
            merged.forEach((k) => {
                if (k.track_id !== obj.track_id) return;
                k.label = obj.label;
                if (obj.color !== undefined) k.color = obj.color;
                if (k.frame === frame) return;   // the view's own copy, stored above
                const attributes = {};
                Object.entries(k.attributes || {}).forEach(([name, value]) => {
                    if (perKeyframe.has(name)) attributes[name] = value;
                });
                Object.entries(obj.attributes || {}).forEach(([name, value]) => {
                    if (!perKeyframe.has(name)) attributes[name] = clone(value);
                });
                k.attributes = attributes;
            });
        });
        // Frame, then track: the saved value reads in order.
        return merged.sort((a, b) => (a.frame - b.frame) || trackOrder(a.track_id, b.track_id));
    }

    /** A keyframe at `frame + 1` copied from `obj`, replacing one there. */
    function copyForward(store, obj, frame) {
        const next = frame + 1;
        const copy = storedCopy(obj);
        copy.frame = next;
        return (store || []).filter((k) => !(k.track_id === obj.track_id && k.frame === next))
            .concat([copy]);
    }

    function deleteTrack(store, trackId) {
        return (store || []).filter((k) => k.track_id !== trackId);
    }

    const api = {
        framesOf, objectAt, viewAt, tracksOf, mergeView, copyForward, deleteTrack,
        nextTrackId, sameCoordinates, slerp,
    };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    if (root) root.PointCloudSequence = api;
})(typeof window !== 'undefined' ? window
    : (typeof globalThis !== 'undefined' ? globalThis : null));
