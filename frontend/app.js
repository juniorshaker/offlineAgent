/**
 * OfflineAgent Web UI — Application Logic
 * OpenClaw-inspired design with SSE streaming and inline tool blocks.
 */

(function () {
  'use strict';

  // -- DOM refs --
  const messagesEl = document.getElementById('messages');
  const inputEl = document.getElementById('user-input');
  const sendBtn = document.getElementById('btn-send');
  const clearBtn = document.getElementById('btn-clear');
  const statusDot = document.getElementById('status-dot');
  const modelNameEl = document.getElementById('model-name');
  const chatEl = document.getElementById('chat');

  let isStreaming = false;
  let currentAgentMsg = null;

  // -- Init --
  fetchStatus();
  inputEl.focus();

  // -- Event listeners --
  sendBtn.addEventListener('click', sendMessage);
  clearBtn.addEventListener('click', clearHistory);

  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
    // Ctrl+L to clear
    if (e.key === 'l' && e.ctrlKey) {
      e.preventDefault();
      clearHistory();
    }
  });

  // Auto-resize textarea
  inputEl.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 160) + 'px';
  });

  // -- Functions --

  function sendMessage() {
    if (isStreaming) return;
    const text = inputEl.value.trim();
    if (!text) return;

    // Clear welcome message
    const welcome = messagesEl.querySelector('.welcome');
    if (welcome) welcome.remove();

    addMessage('user', text);
    inputEl.value = '';
    inputEl.style.height = 'auto';

    setStreaming(true);

    // Create agent message element
    currentAgentMsg = addMessage('agent', '');
    currentAgentMsg.classList.add('streaming-cursor');

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
        if (currentAgentMsg) {
          currentAgentMsg.textContent = '';
          currentAgentMsg.classList.remove('streaming-cursor');
        }
        addToolBlock('error', 'Connection Error', err.message, false);
        setStreaming(false);
      });
  }

  function readSSE(response) {
    var reader = response.body.getReader();
    var decoder = new TextDecoder();
    var buffer = '';

    function pump() {
      return reader.read().then(function (result) {
        if (result.done) {
          finishStreaming();
          return;
        }

        buffer += decoder.decode(result.value, { stream: true });

        var parts = buffer.split('\n\n');
        buffer = parts.pop() || '';

        for (var i = 0; i < parts.length; i++) {
          var block = parts[i].trim();
          if (!block) continue;

          var eventType = null;
          var dataStr = '';

          var lines = block.split('\n');
          for (var j = 0; j < lines.length; j++) {
            var line = lines[j];
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              dataStr += line.slice(6);
            }
          }

          if (eventType && dataStr) {
            handleSSEEvent(eventType, dataStr);
          }
        }

        return pump();
      });
    }

    return pump();
  }

  function handleSSEEvent(event, dataStr) {
    var data;
    try {
      data = JSON.parse(dataStr);
    } catch (e) {
      return;
    }

    switch (event) {
      case 'status':
        var label = data.text || 'Processing...';
        if (data.type === 'tool') {
          addToolBlock('running', data.tool || 'Tool', label);
        }
        break;

      case 'message':
        finishStreaming();
        if (currentAgentMsg) {
          currentAgentMsg.textContent = data.text || '';
        } else {
          currentAgentMsg = addMessage('agent', data.text || '');
        }
        scrollToBottom();
        break;

      case 'done':
        finishStreaming();
        break;

      case 'error':
        finishStreaming();
        if (currentAgentMsg) {
          currentAgentMsg.textContent = '';
          currentAgentMsg.classList.remove('streaming-cursor');
        }
        addToolBlock('error', 'Error', data.text || 'Unknown error', true);
        break;
    }
  }

  function finishStreaming() {
    setStreaming(false);
    // Finalize all running tool blocks
    var running = messagesEl.querySelectorAll('.tool-block-icon.running');
    for (var i = 0; i < running.length; i++) {
      running[i].classList.remove('running');
      running[i].classList.add('done');
    }
    // Remove streaming cursor
    if (currentAgentMsg) {
      currentAgentMsg.classList.remove('streaming-cursor');
    }
  }

  function addToolBlock(status, name, detail, expanded) {
    var block = document.createElement('div');
    block.className = 'tool-block' + (expanded ? ' expanded' : '');
    block.setAttribute('data-tool', name);

    var header = document.createElement('div');
    header.className = 'tool-block-header';

    var icon = document.createElement('span');
    icon.className = 'tool-block-icon ' + status;

    var nameEl = document.createElement('span');
    nameEl.className = 'tool-block-name';
    nameEl.textContent = name;

    var statusEl = document.createElement('span');
    statusEl.className = 'tool-block-status';
    statusEl.textContent = status === 'running' ? 'executing...' : status === 'done' ? 'done' : 'failed';

    var chevron = document.createElement('span');
    chevron.className = 'tool-block-chevron';
    chevron.textContent = '▸';

    header.appendChild(icon);
    header.appendChild(nameEl);
    header.appendChild(statusEl);
    header.appendChild(chevron);

    var body = document.createElement('div');
    body.className = 'tool-block-body';
    body.textContent = detail;

    // Toggle expand on click
    header.addEventListener('click', function () {
      block.classList.toggle('expanded');
    });

    block.appendChild(header);
    block.appendChild(body);
    messagesEl.appendChild(block);

    scrollToBottom();
    return block;
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
    chatEl.scrollTop = chatEl.scrollHeight;
  }

  function setStreaming(active) {
    isStreaming = active;
    sendBtn.disabled = active;
    inputEl.disabled = active;

    if (active) {
      statusDot.classList.add('active');
      statusDot.title = 'active';
    } else {
      statusDot.classList.remove('active', 'error');
      statusDot.title = 'idle';
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
        // Restore welcome
        var welcome = document.createElement('div');
        welcome.className = 'message system welcome';
        welcome.innerHTML = '<div class="welcome-icon">OA</div><div class="welcome-text"><strong>OfflineAgent 已就绪</strong><span>输入 /help 查看可用命令</span></div>';
        messagesEl.appendChild(welcome);
      })
      .catch(function () {
        addMessage('system', '清空历史失败');
      });
  }

  function fetchStatus() {
    fetch('/api/status')
      .then(function (r) { return r.json(); })
      .then(function (status) {
        modelNameEl.textContent = status.model || '--';
        statusDot.title = 'connected: ' + (status.model || '--');
      })
      .catch(function () {
        modelNameEl.textContent = '--';
        statusDot.classList.add('error');
        statusDot.title = 'disconnected';
      });
  }
})();
