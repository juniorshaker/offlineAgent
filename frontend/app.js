/**
 * OfflineAgent Web UI - Application Logic
 *
 * Zero-dependency vanilla JS. Connects to server.py via SSE.
 */

(function () {
  'use strict';

  // -- DOM refs --
  const messagesEl = document.getElementById('messages');
  const inputEl = document.getElementById('user-input');
  const sendBtn = document.getElementById('btn-send');
  const clearBtn = document.getElementById('btn-clear');
  const statusBtn = document.getElementById('btn-status');
  const statusBadge = document.getElementById('status-badge');
  const modelNameEl = document.getElementById('model-name');
  const toolIndicator = document.getElementById('tool-indicator');
  const toolLabel = document.getElementById('tool-label');

  let isStreaming = false;

  // -- Init --
  fetchStatus();
  inputEl.focus();

  // -- Event listeners --
  sendBtn.addEventListener('click', sendMessage);
  clearBtn.addEventListener('click', clearHistory);
  statusBtn.addEventListener('click', fetchStatus);

  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  });

  // Auto-resize textarea
  inputEl.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
  });

  // -- Functions --

  function sendMessage() {
    if (isStreaming) return;
    const text = inputEl.value.trim();
    if (!text) return;

    addMessage('user', text);
    inputEl.value = '';
    inputEl.style.height = 'auto';

    setStreaming(true);
    showToolIndicator(true, 'Thinking...');

    // Track the agent message element for streaming updates
    const agentMsg = addMessage('agent', '');

    fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text }),
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error('HTTP ' + response.status);
        }
        return readSSE(response);
      })
      .catch(function (err) {
        agentMsg.textContent = '[Error] ' + err.message;
        agentMsg.classList.add('system');
        setStreaming(false);
        showToolIndicator(false);
      });
  }

  function readSSE(response) {
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = '';
    var agentMsg = messagesEl.lastElementChild;

    function pump() {
      return reader.read().then(function (result) {
        if (result.done) {
          setStreaming(false);
          showToolIndicator(false);
          return;
        }

        buffer += decoder.decode(result.value, { stream: true });

        // Parse SSE events from buffer
        var lines = buffer.split('\n');
        buffer = lines.pop() || ''; // keep incomplete line

        var currentEvent = null;
        var currentData = '';

        for (var i = 0; i < lines.length; i++) {
          var line = lines[i];

          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith('data: ')) {
            currentData += line.slice(6);
          } else if (line === '' && currentEvent) {
            // End of event
            handleSSEEvent(currentEvent, currentData, agentMsg);
            currentEvent = null;
            currentData = '';
          }
        }

        return pump();
      });
    }

    return pump();
  }

  function handleSSEEvent(event, dataStr, agentMsg) {
    var data;
    try {
      data = JSON.parse(dataStr);
    } catch (e) {
      return;
    }

    switch (event) {
      case 'message':
        showToolIndicator(false);
        agentMsg.textContent = data.text || '';
        scrollToBottom();
        break;

      case 'tool':
        showToolIndicator(true, data.tool || 'Working...');
        break;

      case 'status':
        showToolIndicator(true, data.text || 'Processing...');
        if (data.type === 'tool') {
          agentMsg.innerHTML += '<span class="tool-step">🔧 ' + (data.text || '') + '</span>\n';
        }
        break;

      case 'done':
        setStreaming(false);
        showToolIndicator(false);
        break;

      case 'error':
        agentMsg.textContent = '[Error] ' + (data.text || 'Unknown');
        agentMsg.classList.add('system');
        setStreaming(false);
        showToolIndicator(false);
        break;
    }
  }

  function addMessage(role, text) {
    var el = document.createElement('div');
    el.className = 'message ' + role;
    el.textContent = text;
    messagesEl.appendChild(el);
    scrollToBottom();
    return el;
  }

  function scrollToBottom() {
    var chat = document.getElementById('chat');
    chat.scrollTop = chat.scrollHeight;
  }

  function setStreaming(active) {
    isStreaming = active;
    sendBtn.disabled = active;
    inputEl.disabled = active;
    statusBadge.textContent = active ? 'active' : 'idle';
    statusBadge.className = 'badge' + (active ? ' active' : '');
  }

  function showToolIndicator(show, label) {
    if (show) {
      toolIndicator.classList.remove('hidden');
      if (label) toolLabel.textContent = label;
    } else {
      toolIndicator.classList.add('hidden');
    }
  }

  function clearHistory() {
    if (isStreaming) return;
    fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: '/clear' }),
    })
      .then(function () {
        messagesEl.innerHTML = '';
        addMessage('system', 'Conversation cleared.');
      })
      .catch(function () {
        addMessage('system', 'Failed to clear history.');
      });
  }

  function fetchStatus() {
    fetch('/api/status')
      .then(function (r) { return r.json(); })
      .then(function (status) {
        modelNameEl.textContent = status.model || '--';

        // Show as a system message
        var info = [
          'Model: ' + (status.model || 'N/A'),
          'Skills: ' + (status.skills_count || 0),
          'Tools: ' + (status.tools || []).join(', '),
          'Tokens: ' + status.tokens_estimate + '/' + status.max_tokens + ' (' + status.usage_percent + '%)',
        ].join(' | ');

        addMessage('system', info);
      })
      .catch(function () {
        modelNameEl.textContent = 'offline';
      });
  }
})();
