/**
 * PDF Viewer Component
 *
 * Initializes PDF.js viewers for PDF display fields.
 * Supports text layer for span annotation.
 */

// PDF.js library is loaded from CDN
const PDFJS_CDN = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174';

// Track initialized viewers
const pdfViewers = new Map();

/**
 * Initialize all PDF viewers on the page.
 */
function initPDFViewers() {
    const containers = document.querySelectorAll('.pdf-display[data-pdf-source]');
    containers.forEach(container => {
        if (!pdfViewers.has(container)) {
            const viewer = new PDFViewer(container);
            pdfViewers.set(container, viewer);
        }
    });
}

/**
 * PDF Viewer class
 */
class PDFViewer {
    constructor(container) {
        this.container = container;
        this.pdfSource = container.dataset.pdfSource;
        this.viewMode = container.dataset.viewMode || 'scroll';
        this.textLayerEnabled = container.dataset.textLayer === 'true';
        this.initialPage = parseInt(container.dataset.initialPage) || 1;
        this.zoom = container.dataset.zoom || 'auto';

        this.pdfDoc = null;
        this.currentPage = this.initialPage;
        this.totalPages = 0;
        this.scale = 1.0;
        this.rendering = false;
        this.pageNumPending = null;

        // DOM elements
        this.canvas = container.querySelector('.pdf-canvas');
        this.canvasContainer = container.querySelector('.pdf-canvas-container');
        this.textLayer = container.querySelector('.pdf-text-layer');
        this.loadingEl = container.querySelector('.pdf-loading');
        this.errorEl = container.querySelector('.pdf-error');
        this.currentPageEl = container.querySelector('.pdf-current-page');
        this.totalPagesEl = container.querySelector('.pdf-total-pages');
        this.prevBtn = container.querySelector('.pdf-prev-btn');
        this.nextBtn = container.querySelector('.pdf-next-btn');
        this.zoomSelect = container.querySelector('.pdf-zoom-select');

        this.ctx = this.canvas ? this.canvas.getContext('2d') : null;

        this.init();
    }

    async init() {
        try {
            await this.loadPDFJS();
            await this.loadDocument();
        } catch (error) {
            this.showError(error.message);
        }
    }

    /**
     * Load PDF.js library dynamically if not already loaded.
     */
    async loadPDFJS() {
        if (window.pdfjsLib) {
            return;
        }

        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = `${PDFJS_CDN}/pdf.min.js`;
            script.onload = () => {
                // Set worker source
                window.pdfjsLib.GlobalWorkerOptions.workerSrc =
                    `${PDFJS_CDN}/pdf.worker.min.js`;
                resolve();
            };
            script.onerror = () => reject(new Error('Failed to load PDF.js'));
            document.head.appendChild(script);
        });
    }

    /**
     * Load the PDF document.
     */
    async loadDocument() {
        this.showLoading(true);

        try {
            const loadingTask = pdfjsLib.getDocument(this.pdfSource);
            this.pdfDoc = await loadingTask.promise;
            this.totalPages = this.pdfDoc.numPages;

            // Update UI
            if (this.totalPagesEl) {
                this.totalPagesEl.textContent = this.totalPages;
            }

            // Set up controls
            this.setupControls();

            // Render initial page
            await this.renderPage(this.currentPage);

            this.showLoading(false);
        } catch (error) {
            console.error('PDF load error:', error);
            throw new Error(`Failed to load PDF: ${error.message}`);
        }
    }

    /**
     * Set up page navigation and zoom controls.
     */
    setupControls() {
        if (this.prevBtn) {
            this.prevBtn.addEventListener('click', () => this.prevPage());
        }
        if (this.nextBtn) {
            this.nextBtn.addEventListener('click', () => this.nextPage());
        }
        if (this.zoomSelect) {
            this.zoomSelect.value = this.zoom;
            this.zoomSelect.addEventListener('change', (e) => {
                this.setZoom(e.target.value);
            });
        }

        // Keyboard navigation
        this.container.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
                this.prevPage();
            } else if (e.key === 'ArrowRight' || e.key === 'PageDown') {
                this.nextPage();
            }
        });
    }

    /**
     * Render a specific page.
     */
    async renderPage(pageNum) {
        if (!this.pdfDoc || !this.canvas) return;

        if (this.rendering) {
            this.pageNumPending = pageNum;
            return;
        }

        this.rendering = true;
        this.currentPage = pageNum;

        try {
            const page = await this.pdfDoc.getPage(pageNum);

            // Calculate scale
            const containerWidth = this.canvasContainer?.offsetWidth || 600;
            let scale = this.calculateScale(page, containerWidth);

            const viewport = page.getViewport({ scale });

            // Set canvas dimensions
            this.canvas.height = viewport.height;
            this.canvas.width = viewport.width;

            // Render page
            const renderContext = {
                canvasContext: this.ctx,
                viewport: viewport
            };

            await page.render(renderContext).promise;

            // Render text layer if enabled
            if (this.textLayerEnabled && this.textLayer) {
                await this.renderTextLayer(page, viewport);
            }

            // Update page display
            if (this.currentPageEl) {
                this.currentPageEl.textContent = pageNum;
            }

            // Update button states
            this.updateButtonStates();

        } catch (error) {
            console.error('Page render error:', error);
        } finally {
            this.rendering = false;

            // Render pending page if any
            if (this.pageNumPending !== null) {
                const pending = this.pageNumPending;
                this.pageNumPending = null;
                this.renderPage(pending);
            }
        }
    }

    /**
     * Calculate scale based on zoom setting.
     */
    calculateScale(page, containerWidth) {
        const viewport = page.getViewport({ scale: 1 });

        switch (this.zoom) {
            case 'auto':
            case 'page-width':
                return containerWidth / viewport.width;
            case 'page-fit':
                const containerHeight = this.container.offsetHeight || 600;
                const scaleX = containerWidth / viewport.width;
                const scaleY = containerHeight / viewport.height;
                return Math.min(scaleX, scaleY);
            default:
                const parsed = parseFloat(this.zoom);
                return isNaN(parsed) ? 1.0 : parsed;
        }
    }

    /**
     * Render the text layer for selection and annotation.
     */
    async renderTextLayer(page, viewport) {
        const textContent = await page.getTextContent();

        // Clear existing text layer
        this.textLayer.innerHTML = '';
        this.textLayer.style.width = `${viewport.width}px`;
        this.textLayer.style.height = `${viewport.height}px`;

        // Use PDF.js text layer rendering
        const textLayerFragment = document.createDocumentFragment();

        textContent.items.forEach((item, index) => {
            const tx = pdfjsLib.Util.transform(
                viewport.transform,
                item.transform
            );

            const span = document.createElement('span');
            span.textContent = item.str;
            span.style.left = `${tx[4]}px`;
            span.style.top = `${tx[5]}px`;
            span.style.fontSize = `${Math.abs(tx[0])}px`;
            span.style.fontFamily = item.fontName || 'sans-serif';
            span.dataset.index = index;

            textLayerFragment.appendChild(span);
        });

        this.textLayer.appendChild(textLayerFragment);
    }

    /**
     * Navigate to previous page.
     */
    prevPage() {
        if (this.currentPage > 1) {
            this.renderPage(this.currentPage - 1);
        }
    }

    /**
     * Navigate to next page.
     */
    nextPage() {
        if (this.currentPage < this.totalPages) {
            this.renderPage(this.currentPage + 1);
        }
    }

    /**
     * Go to a specific page.
     */
    goToPage(pageNum) {
        if (pageNum >= 1 && pageNum <= this.totalPages) {
            this.renderPage(pageNum);
        }
    }

    /**
     * Set zoom level.
     */
    setZoom(zoom) {
        this.zoom = zoom;
        this.renderPage(this.currentPage);
    }

    /**
     * Update navigation button states.
     */
    updateButtonStates() {
        if (this.prevBtn) {
            this.prevBtn.disabled = this.currentPage <= 1;
        }
        if (this.nextBtn) {
            this.nextBtn.disabled = this.currentPage >= this.totalPages;
        }
    }

    /**
     * Show/hide loading indicator.
     */
    showLoading(show) {
        if (this.loadingEl) {
            this.loadingEl.style.display = show ? 'flex' : 'none';
        }
    }

    /**
     * Show error message.
     */
    showError(message) {
        this.showLoading(false);
        if (this.errorEl) {
            this.errorEl.textContent = message;
            this.errorEl.style.display = 'block';
        }
    }

    /**
     * Clean up resources.
     */
    destroy() {
        if (this.pdfDoc) {
            this.pdfDoc.destroy();
            this.pdfDoc = null;
        }
        pdfViewers.delete(this.container);
    }
}

// Auto-initialize on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initPDFViewers);
} else {
    initPDFViewers();
}

// Re-initialize when new content is loaded (for dynamic updates)
document.addEventListener('potato:content-loaded', initPDFViewers);

// Export for external use
window.PDFViewer = PDFViewer;
window.initPDFViewers = initPDFViewers;
