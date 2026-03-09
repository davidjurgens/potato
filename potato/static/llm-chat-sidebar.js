/**
 * LLM Chat Sidebar for Annotator Assistance
 *
 * Self-contained IIFE that builds a chat sidebar UI, manages conversations
 * with the backend chat API, and tracks instance changes.
 */
(function () {
    'use strict';

    let chatConfig = null;
    let currentInstanceId = null;
    let isOpen = false;
    let isSending = false;

    // DOM references (populated on init)
    let sidebar = null;
    let messagesContainer = null;
    let inputEl = null;
    let sendBtn = null;
    let typingIndicator = null;
    let toggleBtn = null;

    // ========================================================================
    // Initialization
    // ========================================================================

    function init() {
        fetch('/api/chat/config')
            .then(function (r) { return r.json(); })
            .then(function (cfg) {
                chatConfig = cfg;
                if (!cfg.enabled) return;
                buildUI(cfg);
                observeInstanceChanges();
                detectInitialInstance();
            })
            .catch(function (err) {
                console.warn('[LLM Chat] Failed to load config:', err);
            });
    }

    // ========================================================================
    // UI Construction
    // ========================================================================

    function buildUI(cfg) {
        // -- Sidebar --
        sidebar = document.createElement('div');
        sidebar.className = 'llm-chat-sidebar';
        sidebar.setAttribute('role', 'complementary');
        sidebar.setAttribute('aria-label', cfg.title || 'Chat Assistant');
        if (cfg.sidebar_width) {
            sidebar.style.width = cfg.sidebar_width + 'px';
        }

        // Header
        var header = document.createElement('div');
        header.className = 'llm-chat-header';

        var title = document.createElement('h3');
        title.textContent = cfg.title || 'Ask AI';
        header.appendChild(title);

        var closeBtn = document.createElement('button');
        closeBtn.className = 'llm-chat-close-btn';
        closeBtn.innerHTML = '&times;';
        closeBtn.title = 'Close chat';
        closeBtn.addEventListener('click', toggleSidebar);
        header.appendChild(closeBtn);

        sidebar.appendChild(header);

        // Messages
        messagesContainer = document.createElement('div');
        messagesContainer.className = 'llm-chat-messages';

        var emptyMsg = document.createElement('div');
        emptyMsg.className = 'llm-chat-empty';
        emptyMsg.textContent = 'Ask a question about the current annotation.';
        messagesContainer.appendChild(emptyMsg);

        // Typing indicator
        typingIndicator = document.createElement('div');
        typingIndicator.className = 'llm-chat-typing';
        for (var i = 0; i < 3; i++) {
            var dot = document.createElement('span');
            dot.className = 'llm-chat-typing-dot';
            typingIndicator.appendChild(dot);
        }
        messagesContainer.appendChild(typingIndicator);

        sidebar.appendChild(messagesContainer);

        // Input area
        var inputArea = document.createElement('div');
        inputArea.className = 'llm-chat-input-area';

        inputEl = document.createElement('textarea');
        inputEl.className = 'llm-chat-input';
        inputEl.placeholder = cfg.placeholder || 'Ask about this annotation...';
        inputEl.rows = 1;

        // Prevent keyboard shortcuts from firing while typing in chat
        inputEl.addEventListener('keydown', function (e) {
            e.stopPropagation();
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
        inputEl.addEventListener('keypress', function (e) { e.stopPropagation(); });
        inputEl.addEventListener('keyup', function (e) { e.stopPropagation(); });

        // Auto-resize textarea
        inputEl.addEventListener('input', function () {
            this.style.height = 'auto';
            this.style.height = Math.min(this.scrollHeight, 100) + 'px';
        });

        inputArea.appendChild(inputEl);

        sendBtn = document.createElement('button');
        sendBtn.className = 'llm-chat-send-btn';
        sendBtn.textContent = 'Send';
        sendBtn.addEventListener('click', sendMessage);
        inputArea.appendChild(sendBtn);

        sidebar.appendChild(inputArea);
        document.body.appendChild(sidebar);

        // Update sidebar width in CSS for body margin
        if (cfg.sidebar_width && cfg.sidebar_width !== 380) {
            var style = document.createElement('style');
            style.textContent =
                'body.llm-chat-open .container-fluid,' +
                'body.llm-chat-open .main-container{margin-right:' +
                cfg.sidebar_width + 'px}' +
                '@media(max-width:768px){body.llm-chat-open .container-fluid,' +
                'body.llm-chat-open .main-container{margin-right:0}}';
            document.head.appendChild(style);
        }

        // -- Navbar toggle button --
        var navEnd = document.querySelector('.navbar-end');
        if (navEnd) {
            toggleBtn = document.createElement('button');
            toggleBtn.className = 'llm-chat-toggle-btn';
            toggleBtn.title = cfg.title || 'Ask AI';
            toggleBtn.innerHTML = '<i class="fas fa-comments"></i> ' + (cfg.title || 'Ask AI');
            toggleBtn.addEventListener('click', toggleSidebar);
            navEnd.insertBefore(toggleBtn, navEnd.firstChild);
        }
    }

    // ========================================================================
    // Sidebar Toggle
    // ========================================================================

    function toggleSidebar() {
        isOpen = !isOpen;
        if (sidebar) {
            sidebar.classList.toggle('open', isOpen);
        }
        document.body.classList.toggle('llm-chat-open', isOpen);
        if (toggleBtn) {
            toggleBtn.classList.toggle('active', isOpen);
        }
        if (isOpen && inputEl) {
            setTimeout(function () { inputEl.focus(); }, 300);
        }
    }

    // ========================================================================
    // Instance Change Detection
    // ========================================================================

    function observeInstanceChanges() {
        // Watch for changes to the hidden #instance_id input
        var instanceInput = document.getElementById('instance_id');
        if (instanceInput) {
            var observer = new MutationObserver(function () {
                var newId = instanceInput.value;
                if (newId && newId !== currentInstanceId) {
                    currentInstanceId = newId;
                    loadHistory(newId);
                }
            });
            observer.observe(instanceInput, { attributes: true, attributeFilter: ['value'] });
        }

        // Also listen for custom navigation events
        document.addEventListener('instanceChanged', function (e) {
            var newId = e.detail && e.detail.instance_id;
            if (newId && newId !== currentInstanceId) {
                currentInstanceId = newId;
                loadHistory(newId);
            }
        });
    }

    function detectInitialInstance() {
        var instanceInput = document.getElementById('instance_id');
        if (instanceInput && instanceInput.value) {
            currentInstanceId = instanceInput.value;
            loadHistory(currentInstanceId);
        }
    }

    // ========================================================================
    // Chat History
    // ========================================================================

    function loadHistory(instanceId) {
        if (!messagesContainer) return;

        fetch('/api/chat/history?instance_id=' + encodeURIComponent(instanceId))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                clearMessages();
                var messages = data.messages || [];
                if (messages.length === 0) {
                    showEmpty();
                } else {
                    messages.forEach(function (msg) {
                        appendMessage(msg.role, msg.content);
                    });
                }
            })
            .catch(function (err) {
                console.warn('[LLM Chat] Failed to load history:', err);
            });
    }

    // ========================================================================
    // Sending Messages
    // ========================================================================

    function sendMessage() {
        if (isSending || !inputEl) return;
        var text = inputEl.value.trim();
        if (!text) return;

        isSending = true;
        sendBtn.disabled = true;
        inputEl.value = '';
        inputEl.style.height = 'auto';

        // Remove empty state if present
        var empty = messagesContainer.querySelector('.llm-chat-empty');
        if (empty) empty.remove();

        appendMessage('user', text);
        showTyping(true);
        scrollToBottom();

        fetch('/api/chat/send', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                message: text,
                instance_id: currentInstanceId || '',
            }),
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                showTyping(false);
                if (data.error) {
                    appendMessage('error', data.error);
                } else {
                    appendMessage('assistant', data.content || '');
                }
                scrollToBottom();
            })
            .catch(function (err) {
                showTyping(false);
                appendMessage('error', 'Network error. Please try again.');
                console.warn('[LLM Chat] Send failed:', err);
            })
            .finally(function () {
                isSending = false;
                sendBtn.disabled = false;
                if (inputEl) inputEl.focus();
            });
    }

    // ========================================================================
    // DOM Helpers
    // ========================================================================

    function appendMessage(role, content) {
        if (!messagesContainer) return;
        var div = document.createElement('div');
        div.className = 'llm-chat-message ' + role;
        div.textContent = content;
        // Insert before typing indicator
        messagesContainer.insertBefore(div, typingIndicator);
    }

    function clearMessages() {
        if (!messagesContainer) return;
        var msgs = messagesContainer.querySelectorAll('.llm-chat-message, .llm-chat-empty');
        msgs.forEach(function (el) { el.remove(); });
    }

    function showEmpty() {
        if (!messagesContainer) return;
        var div = document.createElement('div');
        div.className = 'llm-chat-empty';
        div.textContent = 'Ask a question about the current annotation.';
        messagesContainer.insertBefore(div, typingIndicator);
    }

    function showTyping(show) {
        if (typingIndicator) {
            typingIndicator.classList.toggle('visible', show);
        }
    }

    function scrollToBottom() {
        if (messagesContainer) {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
    }

    // ========================================================================
    // Start
    // ========================================================================

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
