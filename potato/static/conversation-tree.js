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

                // Show panel
                var speaker = nodeElement.querySelector('.conv-tree-speaker');
                var text = nodeElement.querySelector('.conv-tree-node-text');
                var label = (speaker ? speaker.textContent : '') + ': ' +
                           (text ? text.textContent.substring(0, 50) : nodeId);
                activeLabel.textContent = label;
                panel.style.display = 'block';
            }

            // Close panel
            var closeBtn = document.getElementById(schemaName + '_close_panel');
            if (closeBtn) {
                closeBtn.addEventListener('click', function() {
                    var panel = document.getElementById(schemaName + '_node_panel');
                    if (panel) panel.style.display = 'none';
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
                    display.innerHTML = '<span class="tree-ann-no-path">No path selected.</span>';
                } else {
                    display.textContent = selectedPath.join(' → ');
                }
            }

            function savePathData() {
                var input = document.getElementById(schemaName + '_selected_path_data');
                if (input) {
                    input.value = JSON.stringify(selectedPath);
                }
            }

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
})();
