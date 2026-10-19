/**
 * Grid labeling: one radio or multiselect scheme over a page of items.
 *
 * Selection is local to the page. Saving posts each labelled tile to
 * /updateinstance in the same shape annotation.js sends, one request per item,
 * so the server's own save path (user side, item side, history, quality
 * control) handles every grid label. Tiles left unlabelled are not saved and
 * come back on the next page.
 */
(function () {
    'use strict';

    const root = document.getElementById('grid-root');
    if (!root) return;
    const scheme = root.dataset.scheme;
    const multiple = root.dataset.multiple === 'true';
    const tiles = Array.from(document.querySelectorAll('.grid-tile'));
    const status = document.querySelector('.grid-status');
    const unlabelled = document.querySelector('.grid-unlabelled');
    const saveButton = document.getElementById('grid-save');

    /** instance id -> Set of label names */
    const answers = new Map(tiles.map(t => [t.dataset.instanceId, new Set()]));
    let anchor = 0;

    function selected() {
        return tiles.filter(t => t.getAttribute('aria-selected') === 'true');
    }

    function setSelected(tile, on) {
        tile.setAttribute('aria-selected', on ? 'true' : 'false');
        tile.classList.toggle('is-selected', on);
    }

    function focusTile(index) {
        if (!tiles.length) return;
        const i = Math.max(0, Math.min(tiles.length - 1, index));
        tiles.forEach((t, j) => t.setAttribute('tabindex', j === i ? '0' : '-1'));
        tiles[i].focus();
        return i;
    }

    function render(tile) {
        const labels = Array.from(answers.get(tile.dataset.instanceId));
        const holder = tile.querySelector('.grid-tile-labels');
        holder.textContent = '';
        labels.forEach(name => {
            const chip = document.createElement('span');
            chip.className = 'grid-chip';
            chip.textContent = name;
            holder.appendChild(chip);
        });
        tile.classList.toggle('is-labelled', labels.length > 0);
        const left = tiles.filter(t => !answers.get(t.dataset.instanceId).size).length;
        if (unlabelled) {
            unlabelled.textContent = left
                ? `${left} of ${tiles.length} not labelled yet (they come back next page)`
                : `All ${tiles.length} labelled`;
        }
    }

    function apply(label) {
        const chosen = selected();
        if (!chosen.length) {
            status.textContent = 'Select one or more tiles first.';
            return;
        }
        // In a multiselect, a label already on every selected tile comes off;
        // otherwise it goes on.
        const allHave = chosen.every(t => answers.get(t.dataset.instanceId).has(label));
        chosen.forEach(tile => {
            const set = answers.get(tile.dataset.instanceId);
            if (!multiple) {
                set.clear();
                set.add(label);
            } else if (allHave) {
                set.delete(label);
            } else {
                set.add(label);
            }
            render(tile);
        });
        status.textContent = `${label} applied to ${chosen.length} item${chosen.length === 1 ? '' : 's'}.`;
    }

    function clearLabels() {
        selected().forEach(tile => {
            answers.get(tile.dataset.instanceId).clear();
            render(tile);
        });
    }

    // ---------------------------------------------------------- selection
    tiles.forEach((tile, index) => {
        tile.addEventListener('click', event => {
            if (event.shiftKey) {
                const [a, b] = [Math.min(anchor, index), Math.max(anchor, index)];
                tiles.forEach((t, j) => setSelected(t, j >= a && j <= b));
            } else if (event.ctrlKey || event.metaKey) {
                setSelected(tile, tile.getAttribute('aria-selected') !== 'true');
                anchor = index;
            } else {
                tiles.forEach(t => setSelected(t, t === tile));
                anchor = index;
            }
            focusTile(index);
        });
    });

    document.querySelectorAll('.grid-label-btn').forEach(button => {
        button.addEventListener('click', () => {
            if (button.dataset.clear) clearLabels();
            else apply(button.dataset.label);
        });
    });

    function columns() {
        if (tiles.length < 2) return 1;
        const top = tiles[0].getBoundingClientRect().top;
        const n = tiles.findIndex(t => t.getBoundingClientRect().top !== top);
        return n === -1 ? tiles.length : n;
    }

    document.addEventListener('keydown', event => {
        if (event.target.closest && event.target.closest('input, textarea, select')) return;
        const current = tiles.indexOf(document.activeElement);
        const moves = { ArrowRight: 1, ArrowLeft: -1, ArrowDown: columns(), ArrowUp: -columns() };
        if (event.key in moves && tiles.length) {
            event.preventDefault();
            const next = focusTile((current === -1 ? 0 : current) + moves[event.key]);
            if (event.shiftKey) setSelected(tiles[next], true);
            return;
        }
        if (event.key === ' ' && current !== -1) {
            event.preventDefault();
            const tile = tiles[current];
            setSelected(tile, tile.getAttribute('aria-selected') !== 'true');
            anchor = current;
            return;
        }
        if ((event.key === 'a' || event.key === 'A') && !event.ctrlKey && !event.metaKey) {
            event.preventDefault();
            tiles.forEach(t => setSelected(t, true));
            return;
        }
        const button = document.querySelector(`.grid-label-btn[data-key="${CSS.escape(event.key)}"]`);
        if (button) {
            event.preventDefault();
            apply(button.dataset.label);
        }
    });

    // --------------------------------------------------------------- save
    async function saveOne(instanceId, labels) {
        const annotations = {};
        labels.forEach(name => { annotations[`${scheme}:${name}`] = name; });
        const response = await fetch('/updateinstance', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                instance_id: instanceId,
                annotations: annotations,
                cleared_schemas: [],
                span_annotations: [],
                client_timestamp: new Date().toISOString(),
                source_view: 'grid',
            }),
        });
        let body = {};
        try { body = await response.json(); } catch (e) { /* non-JSON error */ }
        if (!response.ok || body.status === 'error' || body.status === 'blocked') {
            throw new Error(body.message || `HTTP ${response.status}`);
        }
    }

    if (saveButton) {
        saveButton.addEventListener('click', async () => {
            const todo = tiles.filter(t => answers.get(t.dataset.instanceId).size);
            if (!todo.length) {
                status.textContent = 'Label at least one item before saving.';
                return;
            }
            saveButton.disabled = true;
            status.textContent = `Saving ${todo.length} item${todo.length === 1 ? '' : 's'}...`;
            const failed = [];
            for (const tile of todo) {
                try {
                    await saveOne(tile.dataset.instanceId,
                                  Array.from(answers.get(tile.dataset.instanceId)));
                    tile.classList.add('is-saved');
                } catch (error) {
                    failed.push(tile);
                    tile.classList.add('is-failed');
                    tile.setAttribute('title', `Not saved: ${error.message}`);
                }
            }
            if (failed.length) {
                saveButton.disabled = false;
                status.textContent = `${failed.length} item${failed.length === 1 ? ' was' : 's were'} not saved `
                    + `(marked in red). The rest are saved; press Save again to retry.`;
                return;
            }
            status.textContent = 'Saved. Loading the next page...';
            window.location.reload();
        });
    }

    tiles.forEach(render);
}());
