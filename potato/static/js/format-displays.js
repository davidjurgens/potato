/**
 * Format Display Components
 *
 * JavaScript for spreadsheet and code display interactivity.
 */

// ============================================
// Spreadsheet Display
// ============================================

/**
 * Initialize all spreadsheet displays on the page.
 */
function initSpreadsheetDisplays() {
    const containers = document.querySelectorAll('.spreadsheet-display');
    containers.forEach(container => {
        if (!container.dataset.initialized) {
            new SpreadsheetController(container);
            container.dataset.initialized = 'true';
        }
    });
}

/**
 * Spreadsheet controller class.
 */
class SpreadsheetController {
    constructor(container) {
        this.container = container;
        this.table = container.querySelector('.spreadsheet-table');
        this.mode = container.dataset.annotationMode || 'row';
        this.selectable = container.dataset.selectable !== 'false';
        this.selectedRows = new Set();
        this.selectedCells = new Set();

        this.init();
    }

    init() {
        if (!this.table || !this.selectable) return;

        if (this.mode === 'row') {
            this.initRowSelection();
        } else if (this.mode === 'cell') {
            this.initCellSelection();
        }

        this.initSorting();
    }

    initRowSelection() {
        const rows = this.table.querySelectorAll('tbody tr.selectable-row');
        rows.forEach(row => {
            row.addEventListener('click', (e) => {
                // Don't toggle if clicking checkbox directly
                if (e.target.type === 'checkbox') return;

                const rowIdx = parseInt(row.dataset.row);
                this.toggleRowSelection(rowIdx, row);
            });
        });

        // Handle checkboxes
        const checkboxes = this.table.querySelectorAll('.row-select');
        checkboxes.forEach(checkbox => {
            checkbox.addEventListener('change', (e) => {
                const rowIdx = parseInt(checkbox.dataset.row);
                const row = this.table.querySelector(`tr[data-row="${rowIdx}"]`);
                if (e.target.checked) {
                    this.selectRow(rowIdx, row);
                } else {
                    this.deselectRow(rowIdx, row);
                }
            });
        });
    }

    toggleRowSelection(rowIdx, row) {
        if (this.selectedRows.has(rowIdx)) {
            this.deselectRow(rowIdx, row);
        } else {
            this.selectRow(rowIdx, row);
        }
    }

    selectRow(rowIdx, row) {
        this.selectedRows.add(rowIdx);
        row.classList.add('selected');
        const checkbox = row.querySelector('.row-select');
        if (checkbox) checkbox.checked = true;
        this.updateSelectionCount();
        this.emitSelectionChange();
    }

    deselectRow(rowIdx, row) {
        this.selectedRows.delete(rowIdx);
        row.classList.remove('selected');
        const checkbox = row.querySelector('.row-select');
        if (checkbox) checkbox.checked = false;
        this.updateSelectionCount();
        this.emitSelectionChange();
    }

    initCellSelection() {
        const cells = this.table.querySelectorAll('td.selectable-cell');
        cells.forEach(cell => {
            cell.addEventListener('click', () => {
                const cellRef = cell.dataset.cellRef;
                this.toggleCellSelection(cellRef, cell);
            });
        });
    }

    toggleCellSelection(cellRef, cell) {
        if (this.selectedCells.has(cellRef)) {
            this.selectedCells.delete(cellRef);
            cell.classList.remove('selected');
        } else {
            this.selectedCells.add(cellRef);
            cell.classList.add('selected');
        }
        this.emitSelectionChange();
    }

    updateSelectionCount() {
        const summary = this.container.querySelector('.selected-count');
        if (summary) {
            summary.textContent = this.selectedRows.size;
        }
    }

    emitSelectionChange() {
        const event = new CustomEvent('spreadsheet:selection-change', {
            detail: {
                mode: this.mode,
                selectedRows: Array.from(this.selectedRows),
                selectedCells: Array.from(this.selectedCells),
            },
            bubbles: true,
        });
        this.container.dispatchEvent(event);
    }

    initSorting() {
        const sortableHeaders = this.table.querySelectorAll('th[data-sortable="true"]');
        sortableHeaders.forEach(th => {
            th.addEventListener('click', () => {
                const colIdx = parseInt(th.dataset.col);
                this.sortByColumn(colIdx, th);
            });
        });
    }

    sortByColumn(colIdx, header) {
        const tbody = this.table.querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));

        // Determine sort direction
        const currentDir = header.dataset.sortDir || 'none';
        const newDir = currentDir === 'asc' ? 'desc' : 'asc';

        // Reset other headers
        this.table.querySelectorAll('th').forEach(th => {
            th.dataset.sortDir = 'none';
        });
        header.dataset.sortDir = newDir;

        // Sort rows
        rows.sort((a, b) => {
            const aCell = a.querySelector(`td[data-col="${colIdx}"]`);
            const bCell = b.querySelector(`td[data-col="${colIdx}"]`);
            const aVal = aCell ? aCell.textContent.trim() : '';
            const bVal = bCell ? bCell.textContent.trim() : '';

            // Try numeric sort first
            const aNum = parseFloat(aVal);
            const bNum = parseFloat(bVal);
            if (!isNaN(aNum) && !isNaN(bNum)) {
                return newDir === 'asc' ? aNum - bNum : bNum - aNum;
            }

            // Fall back to string sort
            return newDir === 'asc'
                ? aVal.localeCompare(bVal)
                : bVal.localeCompare(aVal);
        });

        // Re-append rows in sorted order
        rows.forEach(row => tbody.appendChild(row));
    }

    getSelection() {
        return {
            mode: this.mode,
            selectedRows: Array.from(this.selectedRows),
            selectedCells: Array.from(this.selectedCells),
        };
    }

    clearSelection() {
        this.selectedRows.clear();
        this.selectedCells.clear();
        this.table.querySelectorAll('.selected').forEach(el => {
            el.classList.remove('selected');
        });
        this.table.querySelectorAll('.row-select').forEach(cb => {
            cb.checked = false;
        });
        this.updateSelectionCount();
        this.emitSelectionChange();
    }
}


// ============================================
// Code Display
// ============================================

/**
 * Initialize all code displays on the page.
 */
function initCodeDisplays() {
    const containers = document.querySelectorAll('.code-display');
    containers.forEach(container => {
        if (!container.dataset.initialized) {
            new CodeController(container);
            container.dataset.initialized = 'true';
        }
    });
}

/**
 * Code display controller class.
 */
class CodeController {
    constructor(container) {
        this.container = container;
        this.copyBtn = container.querySelector('.code-copy-btn');
        this.codeContent = container.querySelector('.code-content');

        this.init();
    }

    init() {
        if (this.copyBtn) {
            this.copyBtn.addEventListener('click', () => this.copyToClipboard());
        }

        // Line selection for span annotation
        if (this.container.classList.contains('span-target-code')) {
            this.initLineSelection();
        }
    }

    copyToClipboard() {
        // Get plain text content
        let text = '';
        const lines = this.container.querySelectorAll('.line-content code');
        lines.forEach((line, idx) => {
            if (idx > 0) text += '\n';
            text += line.textContent;
        });

        navigator.clipboard.writeText(text).then(() => {
            this.copyBtn.classList.add('copied');
            this.copyBtn.innerHTML = '&#x2713;';

            setTimeout(() => {
                this.copyBtn.classList.remove('copied');
                this.copyBtn.innerHTML = `
                    <svg viewBox="0 0 24 24" width="16" height="16">
                        <path fill="currentColor" d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
                    </svg>
                `;
            }, 2000);
        }).catch(err => {
            console.error('Copy failed:', err);
        });
    }

    initLineSelection() {
        const lines = this.container.querySelectorAll('.code-line');
        lines.forEach(line => {
            line.addEventListener('click', () => {
                line.classList.toggle('span-selected');
                this.emitLineSelection();
            });
        });
    }

    emitLineSelection() {
        const selectedLines = [];
        this.container.querySelectorAll('.code-line.span-selected').forEach(line => {
            const lineNum = line.querySelector('.line-number');
            if (lineNum) {
                selectedLines.push(parseInt(lineNum.dataset.line));
            }
        });

        const event = new CustomEvent('code:line-selection', {
            detail: { selectedLines },
            bubbles: true,
        });
        this.container.dispatchEvent(event);
    }

    getCode() {
        let text = '';
        const lines = this.container.querySelectorAll('.line-content code');
        lines.forEach((line, idx) => {
            if (idx > 0) text += '\n';
            text += line.textContent;
        });
        return text;
    }
}


// ============================================
// Document Display
// ============================================

/**
 * Initialize document display features.
 */
function initDocumentDisplays() {
    // Outline navigation
    document.querySelectorAll('.outline-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const offset = parseInt(link.dataset.offset);
            // Find element at offset and scroll to it
            // This would require coordination with the annotation system
            console.log('Navigate to offset:', offset);
        });
    });
}


// ============================================
// Auto-initialization
// ============================================

function initAllFormatDisplays() {
    initSpreadsheetDisplays();
    initCodeDisplays();
    initDocumentDisplays();
}

// Auto-initialize on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAllFormatDisplays);
} else {
    initAllFormatDisplays();
}

// Re-initialize when new content is loaded
document.addEventListener('potato:content-loaded', initAllFormatDisplays);

// Export for external use
window.SpreadsheetController = SpreadsheetController;
window.CodeController = CodeController;
window.initSpreadsheetDisplays = initSpreadsheetDisplays;
window.initCodeDisplays = initCodeDisplays;
window.initDocumentDisplays = initDocumentDisplays;
