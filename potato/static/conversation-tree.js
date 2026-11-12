/**
 * Conversation Tree Interaction Manager
 *
 * Handles expand/collapse, node selection for annotation,
 * and path selection in conversation tree displays.
 */

(function() {
    'use strict';

    function initConversationTrees() {
        // Expand/collapse toggle
        document.querySelectorAll('.conv-tree-toggle').forEach(function(toggle) {
            toggle.addEventListener('click', function(e) {
                e.stopPropagation();
                var node = toggle.closest('.conv-tree-node');
                var children = node.querySelector('.conv-tree-children');
                if (!children) return;

                var isCollapsed = toggle.dataset.collapsed === 'true';
                if (isCollapsed) {
                    children.style.display = 'block';
                    toggle.textContent = '▼';
                    toggle.dataset.collapsed = 'false';
                } else {
                    children.style.display = 'none';
                    toggle.textContent = '▶';
                    toggle.dataset.collapsed = 'true';
                }
            });
        });

        // Expand All / Collapse All buttons
        document.querySelectorAll('.conv-tree-expand-all').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var tree = btn.closest('.conv-tree');
                tree.querySelectorAll('.conv-tree-children').forEach(function(el) {
                    el.style.display = 'block';
                });
                tree.querySelectorAll('.conv-tree-toggle').forEach(function(t) {
                    t.textContent = '▼';
                    t.dataset.collapsed = 'false';
                });
            });
        });

        document.querySelectorAll('.conv-tree-collapse-all').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var tree = btn.closest('.conv-tree');
                tree.querySelectorAll('.conv-tree-children').forEach(function(el) {
                    el.style.display = 'none';
                });
                tree.querySelectorAll('.conv-tree-toggle').forEach(function(t) {
                    t.textContent = '▶';
                    t.dataset.collapsed = 'true';
                });
            });
        });

        // Tree annotation: make nodes selectable
        initTreeAnnotation();
    }

    function initTreeAnnotation() {
        document.querySelectorAll('.tree-ann-container').forEach(function(container) {
            var configStr = container.dataset.treeAnnConfig;
            if (!configStr) return;

            var config;
            try {
                config = JSON.parse(configStr);
            } catch (e) {
                return;
            }

            var schemaName = config.schemaName;
            var nodeAnnotations = {};
            var selectedPath = [];
            var openNodeId = null;      // the node whose panel is showing

            // Make tree nodes selectable
            var treeContainer = document.querySelector('.conv-tree-root');
            if (treeContainer) {
                treeContainer.querySelectorAll('.conv-tree-node').forEach(function(node) {
                    node.classList.add('selectable');
                    node.addEventListener('click', function(e) {
                        // Don't trigger on toggle click or child nodes
                        if (e.target.closest('.conv-tree-toggle')) return;
                        if (e.target.closest('.conv-tree-children')) {
                            // Only if the click is directly on a child node, not this one
                            var clickedNode = e.target.closest('.conv-tree-node');
                            if (clickedNode !== node) return;
                        }
                        e.stopPropagation();

                        var nodeId = node.dataset.nodeId;
                        if (!nodeId) return;

                        // Handle path selection
                        if (config.pathSelection && config.pathSelection.enabled) {
                            togglePathNode(nodeId, node);
                        }

                        // Show node annotation panel
                        showNodePanel(nodeId, node);
                    });
                });
            }

            function showNodePanel(nodeId, nodeElement) {
                var panel = document.getElementById(schemaName + '_node_panel');
                var activeLabel = document.getElementById(schemaName + '_active_node');
                if (!panel || !activeLabel) return;

                // Deselect all, select this one
                document.querySelectorAll('.conv-tree-node.selected').forEach(function(n) {
                    n.classList.remove('selected');
                });
                nodeElement.classList.add('selected');
                openNodeId = nodeId;

                // Show panel
                var speaker = nodeElement.querySelector('.conv-tree-speaker');
                var text = nodeElement.querySelector('.conv-tree-node-text');
                var label = (speaker ? speaker.textContent : '') + ': ' +
                           (text ? text.textContent.substring(0, 50) : nodeId);
                activeLabel.textContent = label;
                panel.style.display = 'block';

                renderNodeQuestions(nodeId);
            }

            /**
             * Fill the panel body with `node_scheme`'s control.
             *
             * The body used to be emitted empty and left that way, so the page
             * announced a node annotation type over a blank box and
             * `node_annotations` could never be anything but {}. The server now
             * renders the scheme into the same hidden <template> the audio and
             * video widgets use for per-segment questions; this clones it for
             * the selected node. SegmentQuestions.neutralize() strips the
             * `annotation-input` class and the schema/label_name attributes on
             * clone, so the cloned control cannot be mistaken for a top-level
             * answer -- its only home is nodeAnnotations[nodeId].
             */
            function renderNodeQuestions(nodeId) {
                var body = document.getElementById(schemaName + '_node_panel_body');
                if (!body) return;
                // SegmentQuestions.render binds its change/input listeners on
                // the container it is given. Reusing one body for every node
                // stacked a listener per node shown, and each kept writing the
                // panel's answers into ITS node: answering node B after
                // opening node A also saved B's answers under A. A fresh,
                // listener-free body per render keeps one node per panel.
                var fresh = body.cloneNode(false);
                body.parentNode.replaceChild(fresh, body);
                body = fresh;

                if (!nodeAnnotations[nodeId]) nodeAnnotations[nodeId] = {};

                // Say which of the two ways this can be empty it is. Returning
                // quietly is what the panel used to do, and an empty box under
                // the words "Node annotation type: likert" tells the annotator
                // nothing about whether they are supposed to wait, scroll, or
                // give up.
                var template = document.getElementById(
                    'segment-questions-template-' + schemaName);
                if (!template) {
                    body.innerHTML = '<p class="tree-ann-hint">' +
                        'This tree has no node_scheme, so there is nothing to ' +
                        'annotate on a node.</p>';
                    return;
                }
                if (!window.SegmentQuestions) {
                    body.innerHTML = '<p class="tree-ann-hint">' +
                        'The node question form could not be loaded.</p>';
                    return;
                }

                // SegmentQuestions keys its work off `segment.id` and writes
                // answers into `segment.annotations`; a node is the same shape.
                var record = {id: nodeId, annotations: nodeAnnotations[nodeId]};
                var rendered = window.SegmentQuestions.render({
                    schemaName: schemaName,
                    container: body,
                    segment: record,
                    onChange: function () {
                        nodeAnnotations[nodeId] = record.annotations;
                        saveNodeAnnotations();
                        markAnswered(nodeId);
                    }
                });
                if (!rendered) {
                    body.innerHTML = '<p class="tree-ann-hint">' +
                        'The node question form could not be built.</p>';
                }
            }

            /** Show the tick on a node as soon as it has an answer, not only on
             *  restore -- otherwise the only way to find out which nodes are
             *  done is to click every one of them in turn. */
            function markAnswered(nodeId) {
                var node = document.querySelector(
                    '.conv-tree-node[data-node-id="' +
                    (window.CSS && CSS.escape ? CSS.escape(nodeId) : nodeId) + '"]');
                if (!node) return;
                var answers = nodeAnnotations[nodeId];
                var answered = !!(answers && Object.keys(answers).length);
                node.classList.toggle('has-annotation', answered);
            }

            function saveNodeAnnotations() {
                writeValue(schemaName + '_node_annotations',
                           JSON.stringify(pruneEmpty(nodeAnnotations)));
            }

            /** Nodes the annotator opened but did not answer are not answers. */
            function pruneEmpty(byNode) {
                var out = {};
                Object.keys(byNode).forEach(function (nodeId) {
                    var answers = byNode[nodeId];
                    if (answers && Object.keys(answers).length > 0) {
                        out[nodeId] = answers;
                    }
                });
                return out;
            }

            /**
             * Write one of the two hidden inputs and tell the page.
             *
             * `data-modified` plus a bubbling `change` is the contract the rest
             * of the form uses: syncAnnotationsFromDOM reads the value,
             * annotation.js's autosave listens for the event, and
             * validateRequiredFields distinguishes an answer from a default.
             */
            function writeValue(inputId, value) {
                var input = document.getElementById(inputId);
                if (!input) return;
                input.value = value;
                input.setAttribute('data-modified', 'true');
                input.dispatchEvent(new Event('change', {bubbles: true}));
            }

            // Close panel
            var closeBtn = document.getElementById(schemaName + '_close_panel');
            if (closeBtn) {
                closeBtn.addEventListener('click', function() {
                    var panel = document.getElementById(schemaName + '_node_panel');
                    if (panel) panel.style.display = 'none';
                    openNodeId = null;
                    document.querySelectorAll('.conv-tree-node.selected').forEach(function(n) {
                        n.classList.remove('selected');
                    });
                });
            }

            function togglePathNode(nodeId, nodeElement) {
                var idx = selectedPath.indexOf(nodeId);
                if (idx !== -1) {
                    selectedPath.splice(idx, 1);
                    nodeElement.classList.remove('on-path');
                } else {
                    selectedPath.push(nodeId);
                    nodeElement.classList.add('on-path');
                }
                updatePathDisplay();
                savePathData();
            }

            function updatePathDisplay() {
                var display = document.getElementById(schemaName + '_selected_path');
                if (!display) return;
                if (selectedPath.length === 0) {
                    // The text is the server's (tree_annotation.py NO_PATH_TEXT),
                    // so an emptied path reads as it does on a fresh load.
                    var empty = document.createElement('span');
                    empty.className = 'tree-ann-no-path';
                    empty.textContent = (config.pathSelection && config.pathSelection.emptyText) || '';
                    display.replaceChildren(empty);
                } else {
                    display.textContent = selectedPath.join(' → ');
                }
            }

            function savePathData() {
                writeValue(schemaName + '_selected_path_data',
                           selectedPath.length ? JSON.stringify(selectedPath) : '');
            }

            /**
             * Adopt what the server sent back, before any click happens.
             *
             * Annotation pages re-render server-side and inject `value` plus
             * `data-server-set` onto the hidden inputs. Nothing here read them,
             * so revisiting an annotated tree showed an empty path and empty
             * node panels over stored answers -- and the first click would then
             * overwrite the stored value with a fresh one.
             *
             * Read-only: it must not stamp `data-modified`, or arriving at an
             * item would count as answering it.
             */
            function restoreFromServer() {
                var pathInput = document.getElementById(schemaName + '_selected_path_data');
                if (pathInput && pathInput.value) {
                    try {
                        var stored = JSON.parse(pathInput.value);
                        if (Array.isArray(stored)) {
                            selectedPath = stored;
                            selectedPath.forEach(function (nodeId) {
                                var node = document.querySelector(
                                    '.conv-tree-node[data-node-id="' +
                                    (window.CSS && CSS.escape ? CSS.escape(nodeId) : nodeId) + '"]');
                                if (node) node.classList.add('on-path');
                            });
                            updatePathDisplay();
                        }
                    } catch (e) { /* a malformed value is not worth losing the tree over */ }
                }

                var nodeInput = document.getElementById(schemaName + '_node_annotations');
                if (nodeInput && nodeInput.value) {
                    try {
                        var byNode = JSON.parse(nodeInput.value);
                        if (byNode && typeof byNode === 'object') {
                            nodeAnnotations = byNode;
                            Object.keys(byNode).forEach(function (nodeId) {
                                var node = document.querySelector(
                                    '.conv-tree-node[data-node-id="' +
                                    (window.CSS && CSS.escape ? CSS.escape(nodeId) : nodeId) + '"]');
                                if (node) node.classList.add('has-annotation');
                            });
                        }
                    } catch (e) { /* as above */ }
                }
            }

            restoreFromServer();

            /**
             * Live collaborative sessions: show a teammate's answer, which
             * collab.js has already written into both hidden inputs. Unlike
             * restoreFromServer() it replaces: nodes no longer on the path or
             * no longer answered lose their classes, an empty input means
             * none, and an open node panel is rebuilt from the new answers.
             * Nothing is written back and no change event fires.
             */
            function applyFromInputs() {
                var root = document.querySelector('.conv-tree-root') || document;
                var parse = function (inputId, isValid, empty) {
                    var input = document.getElementById(inputId);
                    if (!input || !input.value) return empty;
                    try {
                        var v = JSON.parse(input.value);
                        return isValid(v) ? v : empty;
                    } catch (e) { return empty; }
                };
                selectedPath = parse(schemaName + '_selected_path_data', Array.isArray, []).map(String);
                nodeAnnotations = parse(schemaName + '_node_annotations', function (v) {
                    return !!v && typeof v === 'object' && !Array.isArray(v);
                }, {});
                root.querySelectorAll('.conv-tree-node[data-node-id]').forEach(function (node) {
                    var id = node.dataset.nodeId;
                    var answers = nodeAnnotations[id];
                    node.classList.toggle('on-path', selectedPath.indexOf(id) !== -1);
                    node.classList.toggle('has-annotation', !!(answers && Object.keys(answers).length));
                });
                updatePathDisplay();
                var panel = document.getElementById(schemaName + '_node_panel');
                if (openNodeId !== null && panel && panel.style.display !== 'none') {
                    renderNodeQuestions(openNodeId);
                }
                return true;
            }
            container._treeAnnApplyLive = applyFromInputs;

            // Clear path button
            var clearBtn = document.getElementById(schemaName + '_clear_path');
            if (clearBtn) {
                clearBtn.addEventListener('click', function() {
                    selectedPath = [];
                    document.querySelectorAll('.conv-tree-node.on-path').forEach(function(n) {
                        n.classList.remove('on-path');
                    });
                    updatePathDisplay();
                    savePathData();
                });
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initConversationTrees);
    } else {
        initConversationTrees();
    }

    window.potatoCollabWidgets = window.potatoCollabWidgets || {};
    window.potatoCollabWidgets.tree_annotation = {
        apply: function (ctx) {
            var form = ctx && ctx.form;
            if (!form || typeof form._treeAnnApplyLive !== 'function') return false;
            return form._treeAnnApplyLive() === true;
        }
    };
})();
