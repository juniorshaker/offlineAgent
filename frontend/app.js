/**
 * OfflineAgent Web UI — Application Logic
 * SSE streaming + file browser + upload + responsive sidebar.
 */

(function () {
  'use strict';

  // ═══════════════ DOM Refs ═══════════════
  const messagesEl   = document.getElementById('messages');
  const inputEl      = document.getElementById('user-input');
  const sendBtn      = document.getElementById('btn-send');
  const stopBtn      = document.getElementById('btn-stop');
  const clearBtn     = document.getElementById('btn-clear');
  const filesBtn     = document.getElementById('btn-files');
  const attachBtn    = document.getElementById('btn-attach');
  const fileInput    = document.getElementById('file-input');
  const statusDot    = document.getElementById('status-dot');
  const modelNameEl  = document.getElementById('model-name');
  const chatEl       = document.getElementById('chat');
  const sidebar      = document.getElementById('sidebar');
  const sidebarClose = document.getElementById('btn-sidebar-close');
  const sidebarList  = document.getElementById('sidebar-list');
  const breadcrumb   = document.getElementById('sidebar-breadcrumb');

  // State
  var isStreaming      = false;
  var currentAgentMsg  = null;
  var abortController  = null;
  var sidebarOpen      = false;
  var currentDir       = '';     // current file browser path
  var uploadedFiles    = [];     // pending upload files: [{name, content, type}]
  var selectedFileRow  = null;

  // ═══════════════ Init ═══════════════
  fetchStatus();
  inputEl.focus();

  // ═══════════════ Event Listeners ═══════════════

  // Send
  sendBtn.addEventListener('click', sendMessage);

  // Stop
  stopBtn.addEventListener('click', stopGeneration);

  // Clear / new chat
  clearBtn.addEventListener('click', clearHistory);

  // File browser toggle
  filesBtn.addEventListener('click', toggleSidebar);
  sidebarClose.addEventListener('click', function () { closeSidebar(); });

  // Attach file button
  attachBtn.addEventListener('click', function () { fileInput.click(); });

  // File input change
  fileInput.addEventListener('change', handleFileSelect);

  // Drag & drop (input wrapper + sidebar upload zone)
  (function setupDragDrop() {
    function bindDropZone(el) {
      if (!el) return;
      el.addEventListener('dragover', function (e) {
        e.preventDefault(); e.stopPropagation();
        el.classList.add('drag-over');
      });
      el.addEventListener('dragleave', function (e) {
        e.preventDefault(); e.stopPropagation();
        el.classList.remove('drag-over');
      });
      el.addEventListener('drop', function (e) {
        e.preventDefault(); e.stopPropagation();
        el.classList.remove('drag-over');
        if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
          processFiles(e.dataTransfer.files);
        }
      });
    }
    bindDropZone(document.querySelector('.input-wrapper'));
    bindDropZone(document.getElementById('sidebar-upload-zone'));
  })();

  // Keyboard
  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
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

  // Click outside sidebar to close on mobile
  document.addEventListener('click', function (e) {
    if (sidebarOpen && window.innerWidth <= 900) {
      if (!sidebar.contains(e.target) && e.target !== filesBtn && !filesBtn.contains(e.target)) {
        closeSidebar();
      }
    }
  });

  // ═══════════════ Sidebar ═══════════════

  function toggleSidebar() {
    if (sidebarOpen) {
      closeSidebar();
    } else {
      openSidebar();
      if (!currentDir) {
        navigateTo('/');
      }
    }
  }

  function openSidebar() {
    sidebar.classList.remove('hidden');
    sidebarOpen = true;

    // Show overlay on narrow screens
    if (window.innerWidth <= 900) {
      var overlay = document.querySelector('.sidebar-overlay');
      if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'sidebar-overlay visible';
        overlay.addEventListener('click', closeSidebar);
        document.body.appendChild(overlay);
      } else {
        overlay.classList.add('visible');
      }
    }
  }

  function closeSidebar() {
    sidebar.classList.add('hidden');
    sidebarOpen = false;

    var overlay = document.querySelector('.sidebar-overlay');
    if (overlay) overlay.classList.remove('visible');
  }

  function navigateTo(path) {
    currentDir = path || currentDir;

    fetch('/api/files?path=' + encodeURIComponent(currentDir))
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(renderFileList)
      .catch(function (err) {
        sidebarList.innerHTML = '<div class="file-row" style="color:var(--red);cursor:default">' +
          escapeHtml('Error: ' + err.message) + '</div>';
        updateBreadcrumb(currentDir);
      });
  }

  function renderFileList(data) {
    if (data.error) {
      sidebarList.innerHTML = '<div class="file-row" style="color:var(--red);cursor:default">' +
        escapeHtml(data.error) + '</div>';
      updateBreadcrumb(data.path || currentDir);
      return;
    }

    // Update breadcrumb
    updateBreadcrumb(data.path);

    var html = '';

    // Parent directory
    if (data.parent !== null && data.parent !== undefined) {
      html += '<div class="file-row dir" data-path="' + escapeAttr(data.parent) + '">' +
        '<span class="file-icon">&#8617;</span>' +
        '<span class="file-name">..</span></div>';
    }

    // Drives (Windows root)
    if (data.drives && data.drives.length) {
      for (var i = 0; i < data.drives.length; i++) {
        var d = data.drives[i];
        html += '<div class="file-row dir" data-path="' + escapeAttr(d.name + '\\') + '">' +
          '<span class="file-icon">' + driveIcon() + '</span>' +
          '<span class="file-name">' + escapeHtml(d.name) + '</span></div>';
      }
    }

    // Items
    if (data.items && data.items.length) {
      for (var j = 0; j < data.items.length; j++) {
        var item = data.items[j];
        if (item.type === 'dir') {
          html += '<div class="file-row dir" data-path="' + escapeAttr(joinPath(data.path, item.name)) + '">' +
            '<span class="file-icon">' + folderIcon() + '</span>' +
            '<span class="file-name">' + escapeHtml(item.name) + '</span></div>';
        } else if (item.type === 'info') {
          html += '<div class="file-row" style="color:var(--text-tertiary);cursor:default">' +
            '<span class="file-name">' + escapeHtml(item.name) + '</span></div>';
        } else {
          var cls = fileRowClass(item.name);
          var icon = fileIcon(item.name);
          var sizeStr = formatSize(item.size);
          html += '<div class="file-row ' + cls + '" data-path="' + escapeAttr(joinPath(data.path, item.name)) + '">' +
            '<span class="file-icon">' + icon + '</span>' +
            '<span class="file-name">' + escapeHtml(item.name) + '</span>' +
            '<span class="file-meta">' + sizeStr + '</span></div>';
        }
      }
    } else if (!data.drives || !data.drives.length) {
      html += '<div class="file-row" style="color:var(--text-tertiary);cursor:default">' +
        '<span class="file-name">(empty)</span></div>';
    }

    sidebarList.innerHTML = html;

    // Attach click handlers
    var rows = sidebarList.querySelectorAll('.file-row');
    for (var k = 0; k < rows.length; k++) {
      rows[k].addEventListener('click', handleFileRowClick);
    }
  }

  function handleFileRowClick(e) {
    var row = e.currentTarget;
    var path = row.getAttribute('data-path');
    if (!path) return;

    // Highlight selection
    if (selectedFileRow) selectedFileRow.classList.remove('selected');
    row.classList.add('selected');
    selectedFileRow = row;

    if (row.classList.contains('dir')) {
      // Navigate into directory
      navigateTo(path);
      hidePreview();
    } else {
      // Read file
      readAndPreviewFile(path);
    }
  }

  function readAndPreviewFile(path) {
    fetch('/api/files?read=' + encodeURIComponent(path))
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(showPreview)
      .catch(function (err) {
        showPreview({ type: 'error', content: 'Error: ' + err.message });
      });
  }

  function showPreview(data) {
    var panel = document.getElementById('sidebar-preview');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'sidebar-preview';
      panel.className = 'sidebar-preview';
      panel.innerHTML = '<div class="preview-header"><span id="preview-title">Preview</span>' +
        '<button class="btn-icon" id="btn-preview-close" title="Close" style="width:22px;height:22px">' +
        '&times;</button></div>' +
        '<div class="preview-content" id="preview-content"></div>';
      sidebar.appendChild(panel);

      document.getElementById('btn-preview-close').addEventListener('click', hidePreview);
    }

    var titleEl = document.getElementById('preview-title');
    var contentEl = document.getElementById('preview-content');

    if (data.type === 'image' && data.data_url) {
      titleEl.textContent = (data.filename || 'Image') + ' (' + (data.dimensions ? data.dimensions[0] + 'x' + data.dimensions[1] : '') + ')';
      contentEl.innerHTML = '<img src="' + data.data_url + '" alt="preview" style="max-width:100%;border-radius:6px">';
    } else if (data.type === 'error') {
      titleEl.textContent = 'Error';
      contentEl.innerHTML = '<span style="color:var(--red)">' + escapeHtml(data.content) + '</span>';
    } else {
      var label = data.filename || data.format || data.type || 'File';
      titleEl.textContent = label + ' (' + (data.size ? formatSize(data.size) : '') + ')';
      contentEl.textContent = data.content || '(empty)';
    }

    panel.classList.add('visible');
  }

  function hidePreview() {
    var panel = document.getElementById('sidebar-preview');
    if (panel) panel.classList.remove('visible');
    if (selectedFileRow) {
      selectedFileRow.classList.remove('selected');
      selectedFileRow = null;
    }
  }

  function updateBreadcrumb(path) {
    if (!path || path === 'This PC') {
      breadcrumb.innerHTML = '<span class="breadcrumb-seg" data-path="/">This PC</span>';
      bindBreadcrumbClicks();
      return;
    }

    var parts = path.replace(/\\/g, '/').split('/').filter(Boolean);
    var html = '<span class="breadcrumb-seg" data-path="/">This PC</span>';
    var cumulative = '';

    for (var i = 0; i < parts.length; i++) {
      cumulative += parts[i];
      html += '<span class="breadcrumb-sep">/</span>';
      html += '<span class="breadcrumb-seg" data-path="' + escapeAttr(cumulative + '\\') + '">' +
        escapeHtml(parts[i]) + '</span>';
      cumulative += '\\';
    }

    breadcrumb.innerHTML = html;
    bindBreadcrumbClicks();
  }

  function bindBreadcrumbClicks() {
    var segs = breadcrumb.querySelectorAll('.breadcrumb-seg');
    for (var i = 0; i < segs.length; i++) {
      segs[i].addEventListener('click', function () {
        var p = this.getAttribute('data-path');
        navigateTo(p);
        hidePreview();
      });
    }
  }

  // ═══════════════ File Upload ═══════════════

  function handleFileSelect(e) {
    if (e.target.files && e.target.files.length) {
      processFiles(e.target.files);
    }
    fileInput.value = ''; // allow re-select same file
  }

  function processFiles(fileList) {
    var SUPPORTED = [
      '.jpg','.jpeg','.png','.gif','.webp','.bmp','.svg','.ico',
      '.txt','.sql','.md','.py','.js','.ts','.jsx','.tsx',
      '.json','.xml','.yaml','.yml','.toml','.ini','.cfg','.conf',
      '.csv','.log','.html','.css','.scss','.less',
      '.java','.kt','.swift','.rs','.go','.c','.cpp','.h','.hpp',
      '.sh','.bat','.ps1','.rb','.php','.lua','.r','.m',
      '.env','.gitignore','.docx','.xlsx','.pptx','.pdf'
    ];

    for (var i = 0; i < fileList.length; i++) {
      var file = fileList[i];
      var ext = '.' + file.name.split('.').pop().toLowerCase();
      if (SUPPORTED.indexOf(ext) === -1) {
        addMessage('system', 'Unsupported file type: ' + file.name);
        continue;
      }

      var reader = new FileReader();
      reader.onload = (function (f) {
        return function (ev) {
          var content = ev.target.result;
          var isImage = /^\.(jpg|jpeg|png|gif|webp|bmp|svg|ico)$/i.test(
            '.' + f.name.split('.').pop().toLowerCase()
          );

          uploadedFiles.push({
            name: f.name,
            content: content,
            isImage: isImage
          });

          renderUploadChips();
        };
      })(file);

      if (/^\.(jpg|jpeg|png|gif|webp|bmp|svg|ico)$/i.test(ext)) {
        reader.readAsDataURL(file);
      } else {
        reader.readAsText(file, 'UTF-8');
      }
    }
  }

  function renderUploadChips() {
    var existing = document.getElementById('upload-chips');
    if (existing) existing.remove();

    if (!uploadedFiles.length) return;

    var bar = document.createElement('div');
    bar.id = 'upload-chips';
    bar.className = 'upload-preview-bar';

    for (var i = 0; i < uploadedFiles.length; i++) {
      var f = uploadedFiles[i];
      var chip = document.createElement('span');
      chip.className = 'upload-chip';
      chip.innerHTML = escapeHtml(f.name) + ' <span class="chip-remove" data-idx="' + i + '">&times;</span>';
      bar.appendChild(chip);
    }

    // Insert before input area
    var inputArea = document.getElementById('input-area');
    inputArea.parentNode.insertBefore(bar, inputArea);

    // Remove handlers
    var removes = bar.querySelectorAll('.chip-remove');
    for (var j = 0; j < removes.length; j++) {
      removes[j].addEventListener('click', function (e) {
        e.stopPropagation();
        var idx = parseInt(this.getAttribute('data-idx'), 10);
        uploadedFiles.splice(idx, 1);
        renderUploadChips();
      });
    }
  }

  // ═══════════════ Chat / SSE ═══════════════

  function sendMessage() {
    if (isStreaming) return;

    var text = inputEl.value.trim();
    var hasFiles = uploadedFiles.length > 0;

    if (!text && !hasFiles) return;

    // Clear welcome
    var welcome = messagesEl.querySelector('.welcome');
    if (welcome) welcome.remove();

    // Build full message content
    var fullContent = '';

    // Add file content first
    for (var i = 0; i < uploadedFiles.length; i++) {
      var f = uploadedFiles[i];
      if (f.isImage) {
        fullContent += '[Uploaded image: ' + f.name + ']\n';
      } else {
        fullContent += '[Uploaded file: ' + f.name + ']\n```\n' +
          (typeof f.content === 'string' ? f.content.slice(0, 8000) : '[binary]') +
          '\n```\n\n';
      }
    }

    // Add user text
    if (text) {
      if (fullContent) {
        fullContent += '---\n' + text;
        // Show user message with the actual text, files shown as preview in UI
        addMessage('user', text);
        if (uploadedFiles.length) {
          addMessage('system', 'Attached ' + uploadedFiles.length + ' file(s)');
        }
      } else {
        addMessage('user', text);
        fullContent = text;
      }
    } else {
      addMessage('user', 'Sent ' + uploadedFiles.length + ' file(s) for analysis');
      fullContent = fullContent || 'Analyze the attached files.';
    }

    // Clear state
    inputEl.value = '';
    inputEl.style.height = 'auto';
    uploadedFiles = [];
    var chips = document.getElementById('upload-chips');
    if (chips) chips.remove();

    setStreaming(true);

    // Create agent message element
    currentAgentMsg = addMessage('agent', '');
    currentAgentMsg.classList.add('streaming-cursor');

    abortController = new AbortController();

    fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: fullContent }),
      signal: abortController.signal,
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error('HTTP ' + response.status);
        }
        return readSSE(response);
      })
      .catch(function (err) {
        if (err.name === 'AbortError') return;
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
            if (line.indexOf('event: ') === 0) {
              eventType = line.slice(7).trim();
            } else if (line.indexOf('data: ') === 0) {
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
    try { data = JSON.parse(dataStr); } catch (e) { return; }

    switch (event) {
      case 'status':
        var label = data.text || 'Processing...';
        if (data.type === 'tool') {
          addToolBlock('running', data.tool || 'Tool', label);
        }
        // Update status dot for llm call
        if (data.type === 'llm') {
          statusDot.classList.add('active');
          statusDot.title = 'thinking';
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
    statusEl.textContent = status === 'running' ? '...' : status === 'done' ? 'done' : 'failed';

    var chevron = document.createElement('span');
    chevron.className = 'tool-block-chevron';
    chevron.textContent = '>';

    header.appendChild(icon);
    header.appendChild(nameEl);
    header.appendChild(statusEl);
    header.appendChild(chevron);

    var body = document.createElement('div');
    body.className = 'tool-block-body';
    body.textContent = detail;

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
    sendBtn.hidden = active;
    stopBtn.hidden = !active;
    inputEl.disabled = active;

    if (active) {
      statusDot.classList.add('active');
      statusDot.title = 'active';
    } else {
      statusDot.classList.remove('active', 'error');
      statusDot.title = 'idle';
    }
  }

  function stopGeneration() {
    if (!isStreaming) return;
    if (abortController) {
      abortController.abort();
      abortController = null;
    }
    if (currentAgentMsg) {
      currentAgentMsg.classList.remove('streaming-cursor');
      var existing = currentAgentMsg.textContent.trim();
      currentAgentMsg.textContent = existing ? existing + '\n\n[Stopped]' : '[Stopped]';
    }
    finishStreaming();
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
        var welcome = document.createElement('div');
        welcome.className = 'message system welcome';
        welcome.innerHTML = '<div class="welcome-icon">OA</div>' +
          '<div class="welcome-text"><strong>OfflineAgent Ready</strong>' +
          '<span>Enter /help for available commands</span></div>';
        messagesEl.appendChild(welcome);
      })
      .catch(function () {
        addMessage('system', 'Failed to clear history');
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

  // ═══════════════ Utilities ═══════════════

  function escapeHtml(s) {
    var d = document.createElement('div');
    d.textContent = s;
    return d.innerHTML;
  }

  function escapeAttr(s) {
    return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  function formatSize(bytes) {
    if (!bytes || bytes === 0) return '';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }

  function joinPath(base, name) {
    if (!base) return name;
    base = base.replace(/\\/g, '/');
    if (base.endsWith('/')) return base + name;
    return base + '/' + name;
  }

  function fileRowClass(name) {
    var ext = (name.split('.').pop() || '').toLowerCase();
    if (/^(jpg|jpeg|png|gif|webp|bmp|svg|ico)$/i.test(ext)) return 'image';
    if (/^(docx|xlsx|pptx)$/i.test(ext)) return 'office';
    if (/^pdf$/i.test(ext)) return 'pdf';
    if (/^(py|js|ts|java|kt|c|cpp|h|go|rs|swift|sh|bat|ps1|rb|php|sql|html|css|json|xml|yaml|yml|toml|md|r|m|lua)$/i.test(ext)) return 'code';
    return '';
  }

  function driveIcon() {
    return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="4" width="20" height="14" rx="2"/><path d="M6 12h12"/></svg>';
  }

  function folderIcon() {
    return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>';
  }

  function fileIcon(name) {
    return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>';
  }
})();
