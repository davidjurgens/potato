/**
 * Agent Chat UI
 *
 * Handles the interactive chat interface for agent testing annotation.
 * Communicates with /agent_chat/ routes on the Flask backend.
 */

(function() {
    'use strict';

    var chatPanel = null;
    var messagesContainer = null;
    var inputField = null;
    var sendBtn = null;
    var finishBtn = null;
    var stepCounter = null;
    var isSending = false;

    /**
     * Initialize the chat UI on page load.
     * Checks for an existing session and restores state if needed.
     */
    function agentChatInit() {
        chatPanel = document.getElementById('agent-chat-panel');
        if (!chatPanel) return;

        messagesContainer = document.getElementById('agent-chat-messages');
        inputField = document.getElementById('agent-chat-input');
        sendBtn = document.getElementById('agent-chat-send-btn');
        finishBtn = document.getElementById('agent-chat-finish-btn');
        stepCounter = document.getElementById('agent-chat-step-counter');

        // Check if chat is in active mode (data-chat-active on container)
        var container = chatPanel.closest('[data-chat-active]');
        if (container && container.getAttribute('data-chat-active') === 'false') {
            // Conversation is already finalized, nothing to do
            return;
        }

        // Disable annotation forms while chat is active
        document.body.classList.add('agent-chat-active');

        // Set up Enter key handler
        if (inputField) {
            inputField.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    agentChatSend();
                }
            });
        }

        // Check for existing session (handles page refresh)
        fetch('/agent_chat/status', {
            method: 'GET',
            credentials: 'same-origin'
        })
        .then(function(resp) { return resp.json(); })
        .then(function(data) {
            if (data.active) {
                // Restore messages from existing session
                restoreMessages(data.messages || []);
                updateStepCounter(data.step_count || 0, data.max_steps || 20);
            }
        })
        .catch(function(err) {
            console.log('No active agent session:', err);
        });
    }

    /**
     * Send a message to the agent.
     */
    function agentChatSend() {
        if (isSending || !inputField) return;

        var message = inputField.value.trim();
        if (!message) return;

        isSending = true;
        inputField.value = '';
        inputField.disabled = true;
        if (sendBtn) sendBtn.disabled = true;
        if (finishBtn) finishBtn.disabled = true;

        // Clear placeholder
        var placeholder = messagesContainer.querySelector('.agent-chat-placeholder');
        if (placeholder) placeholder.remove();

        // Add user message
        appendMessage('user', message);

        // Show typing indicator
        var typingEl = showTypingIndicator();

        fetch('/agent_chat/send', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message: message })
        })
        .then(function(resp) { return resp.json(); })
        .then(function(data) {
            removeTypingIndicator(typingEl);

            if (data.error) {
                appendMessage('error', data.error);
            } else {
                appendMessage('agent', data.content || '');
                updateStepCounter(data.step_count || 0, data.max_steps || 20);
            }
        })
        .catch(function(err) {
            removeTypingIndicator(typingEl);
            appendMessage('error', 'Failed to send message: ' + err.message);
        })
        .finally(function() {
            isSending = false;
            inputField.disabled = false;
            if (sendBtn) sendBtn.disabled = false;
            if (finishBtn) finishBtn.disabled = false;
            inputField.focus();
        });
    }

    /**
     * Finish the chat and transition to annotation mode.
     */
    function agentChatFinish() {
        if (isSending) return;

        // Confirm if there are no messages
        var messages = messagesContainer.querySelectorAll('.agent-chat-message');
        if (messages.length === 0) {
            if (!confirm('No messages have been sent. Are you sure you want to finish?')) {
                return;
            }
        }

        isSending = true;
        if (sendBtn) sendBtn.disabled = true;
        if (finishBtn) finishBtn.disabled = true;
        inputField.disabled = true;

        fetch('/agent_chat/finish', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' }
        })
        .then(function(resp) { return resp.json(); })
        .then(function(data) {
            if (data.error) {
                appendMessage('error', data.error);
                isSending = false;
                if (sendBtn) sendBtn.disabled = false;
                if (finishBtn) finishBtn.disabled = false;
                inputField.disabled = false;
            } else {
                // Reload page to show the trace display with annotation forms
                window.location.reload();
            }
        })
        .catch(function(err) {
            appendMessage('error', 'Failed to finish: ' + err.message);
            isSending = false;
            if (sendBtn) sendBtn.disabled = false;
            if (finishBtn) finishBtn.disabled = false;
            inputField.disabled = false;
        });
    }

    /**
     * Append a message bubble to the chat.
     */
    function appendMessage(role, content) {
        var msgDiv = document.createElement('div');
        msgDiv.className = 'agent-chat-message ' + role;

        var senderDiv = document.createElement('div');
        senderDiv.className = 'agent-chat-sender';
        senderDiv.textContent = role === 'user' ? 'You' : role === 'agent' ? 'Agent' : '';

        var bubbleDiv = document.createElement('div');
        bubbleDiv.className = 'agent-chat-bubble';
        bubbleDiv.textContent = content;

        if (role !== 'error') {
            msgDiv.appendChild(senderDiv);
        }
        msgDiv.appendChild(bubbleDiv);
        messagesContainer.appendChild(msgDiv);

        // Scroll to bottom
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }

    /**
     * Restore messages from session state (after page refresh).
     */
    function restoreMessages(messages) {
        // Clear placeholder
        var placeholder = messagesContainer.querySelector('.agent-chat-placeholder');
        if (placeholder) placeholder.remove();

        for (var i = 0; i < messages.length; i++) {
            var msg = messages[i];
            appendMessage(msg.role, msg.content);
        }
    }

    /**
     * Show a typing indicator.
     */
    function showTypingIndicator() {
        var el = document.createElement('div');
        el.className = 'agent-chat-typing';
        el.innerHTML = '<div class="dot"></div><div class="dot"></div><div class="dot"></div>';
        messagesContainer.appendChild(el);
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
        return el;
    }

    /**
     * Remove a typing indicator element.
     */
    function removeTypingIndicator(el) {
        if (el && el.parentNode) {
            el.parentNode.removeChild(el);
        }
    }

    /**
     * Update the step counter display.
     */
    function updateStepCounter(current, max) {
        if (stepCounter) {
            stepCounter.textContent = 'Step ' + current + ' / ' + max;
        }
    }

    // Expose functions globally for onclick handlers
    window.agentChatSend = agentChatSend;
    window.agentChatFinish = agentChatFinish;
    window.agentChatInit = agentChatInit;

    // Initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', agentChatInit);
    } else {
        agentChatInit();
    }

})();
