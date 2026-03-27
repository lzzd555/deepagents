/**
 * Chat WebSocket handling for DeepAgents Web
 */

class ChatManager {
    constructor() {
        this.ws = null;
        this.sessionId = null;
        this.isShuttingDown = false;
        this.messagesEl = document.getElementById('messages');
        this.todoListEl = document.getElementById('todo-list');
        this.inputEl = document.getElementById('user-input');
        this.sendBtn = document.getElementById('send-btn');
        this.stopBtn = document.getElementById('stop-btn');
        this.progressEl = document.getElementById('chat-progress');
        this.progressTextEl = document.getElementById('progress-text');
        this.currentAssistantMessage = null;
        this.pendingInterrupt = null;
        this.isProcessing = false;
        this.thinkingStartTime = null; // Track thinking start time
        this.currentThinkingDuration = null; // Store actual thinking duration

        this.setupEventListeners();
    }

    setupEventListeners() {
        this.sendBtn.addEventListener('click', () => this.sendMessage());
        this.stopBtn.addEventListener('click', () => this.stopProcessing());
        this.inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        // Auto-resize textarea
        this.inputEl.addEventListener('input', () => {
            this.inputEl.style.height = 'auto';
            this.inputEl.style.height = Math.min(this.inputEl.scrollHeight, 200) + 'px';
        });

        // Interrupt modal buttons
        document.getElementById('approve-btn').addEventListener('click', () => {
            this.handleInterruptDecision('approve');
        });
        document.getElementById('reject-btn').addEventListener('click', () => {
            this.handleInterruptDecision('reject');
        });

        window.addEventListener('pagehide', () => {
            this.shutdownSession();
        });
        window.addEventListener('beforeunload', () => {
            this.shutdownSession();
        });
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/api/ws/chat`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.sendBtn.disabled = false;
        };

        this.ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            this.handleMessage(msg);
        };

        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            this.sendBtn.disabled = true;
            if (this.isShuttingDown) {
                return;
            }
            // Reconnect after delay
            setTimeout(() => this.connect(), 3000);
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    handleMessage(msg) {
        switch (msg.type) {
            case 'session':
                this.sessionId = msg.data.session_id;
                break;
            case 'text':
                this.appendText(msg.data);
                this.updateProgress('Processing...');
                break;
            case 'tool_call':
                this.showToolCall(msg.data);
                this.updateProgress(`Running: ${msg.data.name}`);
                break;
            case 'interrupt':
                this.showInterrupt(msg.data);
                break;
            case 'todo':
                this.updateTodoList(msg.data);
                break;
            case 'progress':
                this.updateProgress(msg.data);
                break;
            case 'error':
                this.showError(msg.data);
                this.setProcessing(false);
                break;
            case 'done':
                this.finishMessage();
                break;
        }
    }

    sendMessage() {
        const content = this.inputEl.value.trim();
        if (!content || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;

        // Show user message
        this.addMessage('user', content);

        // Send to server
        this.ws.send(JSON.stringify({
            type: 'message',
            content: content
        }));

        // Clear input and show processing state
        this.inputEl.value = '';
        this.inputEl.style.height = 'auto';
        this.setProcessing(true);
    }

    stopProcessing() {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;

        this.ws.send(JSON.stringify({
            type: 'stop'
        }));

        this.updateProgress('Stopping...');
    }

    shutdownSession() {
        if (this.isShuttingDown) return;
        this.isShuttingDown = true;

        if (this.sessionId) {
            fetch(`/api/sessions/${this.sessionId}`, {
                method: 'DELETE',
                keepalive: true
            }).catch((error) => {
                console.debug('Failed to close session cleanly:', error);
            });
        }

        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.close();
        }
    }

    setProcessing(processing) {
        this.isProcessing = processing;
        this.sendBtn.disabled = processing;
        this.stopBtn.classList.toggle('hidden', !processing);
        this.progressEl.classList.toggle('hidden', !processing);
        if (processing) {
            this.progressTextEl.textContent = 'Processing...';
        }
    }

    updateProgress(text) {
        if (this.progressTextEl) {
            this.progressTextEl.textContent = text;
        }
    }

    addMessage(role, content) {
        const msgEl = document.createElement('div');
        msgEl.className = `message ${role}`;
        msgEl.innerHTML = this.renderMarkdown(content);
        this.messagesEl.appendChild(msgEl);
        this.scrollToBottom();
        return msgEl;
    }

    appendText(text) {
        if (!this.currentAssistantMessage) {
            this.currentAssistantMessage = this.addMessage('assistant', '');
            this.currentAssistantMessage.textContent = '';
        }

        // Check for <think> tag start
        if (text.includes('<think>') && !this.thinkingStartTime) {
            this.thinkingStartTime = Date.now();
        }

        this.currentAssistantMessage.textContent += text;

        // Check for </think> tag end
        const fullContent = this.currentAssistantMessage.textContent;
        if (fullContent.includes('</think>') && this.thinkingStartTime && !this.currentThinkingDuration) {
            this.currentThinkingDuration = (Date.now() - this.thinkingStartTime) / 1000;
        }

        this.scrollToBottom();
    }

    showToolCall(data) {
        const msgEl = document.createElement('div');
        msgEl.className = 'message tool';
        msgEl.innerHTML = `<strong>🔧 ${data.name}</strong><pre>${JSON.stringify(data.args, null, 2)}</pre>`;
        this.messagesEl.appendChild(msgEl);
        this.scrollToBottom();
    }

    showInterrupt(data) {
        this.pendingInterrupt = data;
        const detailsEl = document.getElementById('interrupt-details');
        detailsEl.innerHTML = `
            <div class="tool-name">🔧 ${data.tool_name}</div>
            <p>${data.description || 'Tool requires approval'}</p>
            <pre>${JSON.stringify(data.args, null, 2)}</pre>
        `;
        document.getElementById('interrupt-modal').classList.remove('hidden');
        this.updateProgress(`Waiting for approval: ${data.tool_name}`);
    }

    handleInterruptDecision(decision) {
        if (!this.pendingInterrupt || !this.ws) return;

        this.ws.send(JSON.stringify({
            type: 'interrupt_response',
            data: {
                interrupt_id: this.pendingInterrupt.interrupt_id,
                decision: decision
            }
        }));

        document.getElementById('interrupt-modal').classList.add('hidden');
        this.pendingInterrupt = null;

        // Keep processing state active after approval
        if (decision === 'approve') {
            this.setProcessing(true);
            this.updateProgress('Resuming...');
        } else {
            this.setProcessing(false);
        }
    }

    updateTodoList(todos) {
        if (!todos || todos.length === 0) {
            this.todoListEl.classList.add('hidden');
            return;
        }

        this.todoListEl.classList.remove('hidden');
        this.todoListEl.innerHTML = '<h4>📋 Tasks</h4>';

        todos.forEach(todo => {
            const itemEl = document.createElement('div');
            itemEl.className = `todo-item ${todo.status}`;
            const icon = todo.status === 'completed' ? '✓' :
                        todo.status === 'in_progress' ? '⏳' : '○';
            itemEl.textContent = `${icon} ${todo.content}`;
            this.todoListEl.appendChild(itemEl);
        });
    }

    showError(error) {
        const msgEl = document.createElement('div');
        msgEl.className = 'message error';
        msgEl.textContent = `Error: ${error}`;
        this.messagesEl.appendChild(msgEl);
        this.scrollToBottom();
    }

    finishMessage() {
        if (this.currentAssistantMessage) {
            // Render markdown for the complete message
            const text = this.currentAssistantMessage.textContent;
            this.currentAssistantMessage.innerHTML = this.renderContentWithThinking(text, this.currentThinkingDuration);
        }
        this.currentAssistantMessage = null;
        this.thinkingStartTime = null;
        this.currentThinkingDuration = null;
        this.setProcessing(false);
    }

    // Parse and render content with thinking blocks
    renderContentWithThinking(content, actualDuration = null) {
        const thinkRegex = /<think>([\s\S]*?)<\/think>/g;
        let result = '';
        let lastIndex = 0;
        let match;
        let thinkingContent = '';

        while ((match = thinkRegex.exec(content)) !== null) {
            // Add text before the think tag
            if (match.index > lastIndex) {
                const textBefore = content.slice(lastIndex, match.index).trim();
                if (textBefore) {
                    result += this.renderMarkdown(textBefore);
                }
            }
            // Accumulate thinking content
            thinkingContent += (thinkingContent ? '\n\n' : '') + match[1].trim();
            lastIndex = match.index + match[0].length;
        }

        // Add thinking block if any
        if (thinkingContent) {
            let thinkingTime;
            if (actualDuration !== null && actualDuration !== undefined) {
                // Use actual duration
                if (actualDuration < 60) {
                    thinkingTime = `${actualDuration.toFixed(1)} 秒`;
                } else {
                    thinkingTime = `${(actualDuration / 60).toFixed(1)} 分钟`;
                }
            } else {
                // Fallback: estimate based on content length
                const wordCount = thinkingContent.split(/\s+/).length;
                const estimatedSeconds = Math.max(1, Math.round(wordCount / 50));
                thinkingTime = estimatedSeconds < 60
                    ? `${estimatedSeconds} 秒`
                    : `${(estimatedSeconds / 60).toFixed(1)} 分钟`;
            }

            const thinkingId = `thinking-${Date.now()}`;
            result = `
                <div class="thinking-block">
                    <button class="thinking-toggle" onclick="document.getElementById('${thinkingId}').classList.toggle('hidden'); this.querySelector('.chevron').classList.toggle('expanded')">
                        <span class="chevron">›</span>
                        <span class="thinking-icon">💡</span>
                        <span>已深度思考（用时 ${thinkingTime}）</span>
                    </button>
                    <div id="${thinkingId}" class="thinking-content hidden">
                        <pre>${this.escapeHtml(thinkingContent)}</pre>
                    </div>
                </div>
            ` + result;
        }

        // Add remaining text after last think tag
        if (lastIndex < content.length) {
            const remainingText = content.slice(lastIndex).trim();
            if (remainingText) {
                result += this.renderMarkdown(remainingText);
            }
        }

        // If no think tags found, return original rendered content
        if (!thinkingContent && result === '') {
            return this.renderMarkdown(content);
        }

        return result;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    renderMarkdown(text) {
        // Simple markdown rendering
        return text
            .replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
            .replace(/\*([^*]+)\*/g, '<em>$1</em>')
            .replace(/\n/g, '<br>');
    }

    scrollToBottom() {
        this.messagesEl.parentElement.scrollTop = this.messagesEl.parentElement.scrollHeight;
    }
}

// Export for use in app.js
window.ChatManager = ChatManager;
