/**
 * OfflineAgent Web UI - Application Logic
 * v7: Five-tab sidebar + Token stats + Skills panel + Search
 */
(function () {
  'use strict';

  // === DOM Refs ===
  var messagesEl    = document.getElementById('messages');
  var inputEl       = document.getElementById('user-input');
  var sendBtn       = document.getElementById('btn-send');
  var stopBtn       = document.getElementById('btn-stop');
  var clearBtn      = document.getElementById('btn-clear');
  var newChatBtn    = document.getElementById('btn-new-chat');
  var filesBtn      = document.getElementById('btn-files');
  var attachBtn     = document.getElementById('btn-attach');
  var fileInput     = document.getElementById('file-input');
  var statusDot     = document.getElementById('status-dot');
  var modelNameEl   = document.getElementById('model-name');
  var chatEl        = document.getElementById('chat');
  var sidebar       = document.getElementById('sidebar');
  var sidebarClose  = document.getElementById('btn-sidebar-close');
  var sidebarList   = document.getElementById('sidebar-list');
  var breadcrumb    = document.getElementById('sidebar-breadcrumb');

  // Five panels
  var panelFiles    = document.getElementById('panel-files');
  var panelHistory  = document.getElementById('panel-history');
  var panelTokens   = document.getElementById('panel-tokens');
  var panelSkills   = document.getElementById('panel-skills');
  var panelSearch   = document.getElementById('panel-search');

  // History (in sidebar)
  var historyList   = document.getElementById('history-list');

  // Tokens
  var tokenBackend  = document.getElementById('token-backend');
  var tokenModel    = document.getElementById('token-model');
  var tokenRange    = document.getElementById('token-range');
  var tcTotal       = document.getElementById('tc-total');
  var tcPrompt      = document.getElementById('tc-prompt');
  var tcCompletion  = document.getElementById('tc-completion');
  var tcCalls       = document.getElementById('tc-calls');

  // Skills
  var skillsCount   = document.getElementById('skills-count');
  var skillsList    = document.getElementById('skills-list');

  // Search
  var searchInput   = document.getElementById('search-input');
  var searchResults = document.getElementById('search-results');

  // State
  var isStreaming      = false;
  var sseDoneReceived  = false;
  var newChatPending   = false;
  var currentAgentMsg  = null;
  var abortController  = null;
  var sseReader        = null;
  var sidebarOpen      = true;
  var activeTab        = 'files';
  var currentDir       = '';
  var uploadedFiles    = [];
  var selectedFileRow  = null;
  var chartBar         = null;
  var chartLine        = null;
  var searchTimeout    = null;
  var skillsCache      = null;

  // === Init ===
  fetchStatus();
  fetchSkills();
  inputEl.focus();
  navigateTo('/');
  switchTab('files');

  // === Event Listeners ===
  sendBtn.addEventListener('click', sendMessage);
  stopBtn.addEventListener('click', stopGeneration);
  clearBtn.addEventListener('click', clearHistory);
  if (newChatBtn) newChatBtn.addEventListener('click', newConversation);
  filesBtn.addEventListener('click', function () { toggleSidebar('files'); });
  sidebarClose.addEventListener('click', function () { closeSidebar(); });
  attachBtn.addEventListener('click', function () { fileInput.click(); });
  fileInput.addEventListener('change', handleFileSelect);

  // Sidebar tab clicks
  var tabs = sidebar.querySelectorAll('.sidebar-tab');
  for (var i = 0; i < tabs.length; i++) {
    tabs[i].addEventListener('click', function (e) {
      switchTab(this.getAttribute('data-tab'));
    });
  }

  // Token filter changes
  tokenBackend.addEventListener('change', function () {
    loadTokenBackend();
    loadTokenStats();
  });
  tokenModel.addEventListener('change', loadTokenStats);
  tokenRange.addEventListener('change', loadTokenStats);

  // Search input (debounce 300ms)
  searchInput.addEventListener('input', function () {
    clearTimeout(searchTimeout);
    var q = searchInput.value.trim();
    if (!q) {
      searchResults.innerHTML = '<div class="search-empty">Enter a keyword to search</div>';
      return;
    }
    searchTimeout = setTimeout(function () { doSearch(q); }, 300);
  });

  // Drag & drop
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

  inputEl.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 160) + 'px';
  });

  // Paste handler — support pasting images from clipboard
  inputEl.addEventListener('paste', function (e) {
    var items = (e.clipboardData || window.clipboardData).items;
    if (!items) return;
    for (var i = 0; i < items.length; i++) {
      var item = items[i];
      if (item.type.indexOf('image') === 0) {
        e.preventDefault();  // Don't paste the image as text
        var blob = item.getAsFile();
        var reader = new FileReader();
        reader.onload = (function (fname) {
          return function (ev) {
            uploadedFiles.push({ name: fname, content: ev.target.result, isImage: true });
            renderUploadChips();
          };
        })('pasted-image-' + Date.now() + '.png');
        reader.readAsDataURL(blob);
      }
    }
  });

  // Click-outside to close panels
  document.addEventListener('click', function (e) {
    if (sidebarOpen && window.innerWidth <= 900) {
      if (!sidebar.contains(e.target) && e.target !== filesBtn && !filesBtn.contains(e.target)) {
        closeSidebar();
      }
    }
  });

  // === Sidebar Tabs ===
  function switchTab(tabName) {
    activeTab = tabName;
    var panels = sidebar.querySelectorAll('.sidebar-panel');
    for (var i = 0; i < panels.length; i++) { panels[i].classList.remove('active'); }
    var tabBtns = sidebar.querySelectorAll('.sidebar-tab');
    for (var j = 0; j < tabBtns.length; j++) { tabBtns[j].classList.remove('active'); }

    var panel = document.getElementById('panel-' + tabName);
    if (panel) panel.classList.add('active');
    var btn = sidebar.querySelector('[data-tab="' + tabName + '"]');
    if (btn) btn.classList.add('active');

    // Load data for the tab
    if (tabName === 'history') loadHistory();
    if (tabName === 'tokens') { loadTokenBackend(); loadTokenStats(); }
    if (tabName === 'skills') fetchSkills();
  }

  // === History (in sidebar) ===
  function loadHistory() {
    historyList.innerHTML = '<div class="history-empty">Loading...</div>';
    fetch('/api/chat/list')
      .then(function (r) { return r.json(); })
      .then(renderHistoryList)
      .catch(function () {
        historyList.innerHTML = '<div class="history-empty">Failed to load</div>';
      });
  }

  function renderHistoryList(data) {
    var convs = data.conversations || [];
    if (!convs.length) {
      historyList.innerHTML = '<div class="history-empty">No saved conversations yet</div>';
      return;
    }
    var html = '';
    for (var i = 0; i < convs.length; i++) {
      var c = convs[i];
      var dateStr = c.created_at ? c.created_at.slice(0, 16).replace('T', ' ') : '';
      html += '<div class="history-item" data-id="' + escapeAttr(c.id) + '">' +
        '<span class="history-item-title">' + escapeHtml(c.title || '(untitled)') + '</span>' +
        '<span class="history-item-meta">' + dateStr + ' \u00b7 ' + (c.message_count || 0) + ' msgs</span>' +
        '</div>';
    }
    historyList.innerHTML = html;

    var items = historyList.querySelectorAll('.history-item');
    for (var j = 0; j < items.length; j++) {
      items[j].addEventListener('click', function () {
        var id = this.getAttribute('data-id');
        if (id) switchConversation(id);
      });
    }
  }

  function switchConversation(convId) {
    if (isStreaming) return;
    closeSidebar();
    addMessage('system', 'Switching conversation...');
    fetch('/api/chat/switch/' + convId, { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) {
          addMessage('system', 'Error: ' + data.error);
          return;
        }
        messagesEl.innerHTML = '';
        addMessage('system', 'Switched to: ' + escapeHtml(data.title || convId));
        fetchStatus();
        inputEl.focus();
      })
      .catch(function () {
        addMessage('system', 'Failed to switch conversation');
      });
  }

  // === Tokens Tab ===
  function loadTokenBackend() {
    fetch('/api/tokens/backends')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var backends = data.backends || [];
        tokenBackend.innerHTML = '<option value="">All backends</option>';
        for (var i = 0; i < backends.length; i++) {
          tokenBackend.innerHTML += '<option value="' + escapeAttr(backends[i]) + '">' + escapeHtml(backends[i]) + '</option>';
        }
        loadTokenModels(tokenBackend.value || '');
      })
      .catch(function () {});
  }

  function loadTokenModels(backend) {
    var url = '/api/tokens/models' + (backend ? '?backend=' + encodeURIComponent(backend) : '');
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var models = data.models || [];
        tokenModel.innerHTML = '<option value="">All models</option>';
        for (var i = 0; i < models.length; i++) {
          tokenModel.innerHTML += '<option value="' + escapeAttr(models[i]) + '">' + escapeHtml(models[i]) + '</option>';
        }
      })
      .catch(function () {});
  }

  function loadTokenStats() {
    var backend = tokenBackend.value || '';
    var model = tokenModel.value || '';
    var range = tokenRange.value || 'week';
    var params = 'range=' + encodeURIComponent(range);
    if (backend) params += '&backend=' + encodeURIComponent(backend);
    if (model) params += '&model=' + encodeURIComponent(model);

    fetch('/api/tokens/stats?' + params)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var summary = data.summary || {};
        tcTotal.textContent = formatNum(summary.total_tokens || 0);
        tcPrompt.textContent = formatNum(summary.prompt_tokens || 0);
        tcCompletion.textContent = formatNum(summary.completion_tokens || 0);
        tcCalls.textContent = summary.total_calls || 0;

        var chartData = data.data || [];
        renderTokenCharts(chartData);
      })
      .catch(function () {
        tcTotal.textContent = 'N/A';
        tcPrompt.textContent = 'N/A';
        tcCompletion.textContent = 'N/A';
        tcCalls.textContent = 'N/A';
      });
  }

  function renderTokenCharts(data) {
    if (!data || !data.length) return;

    var labels = [];
    var barVals = [];
    var lineVals = [];
    for (var i = 0; i < data.length; i++) {
      var d = data[i];
      labels.push(d.period);
      barVals.push(d.total_tokens || 0);
      lineVals.push(d.total_tokens || 0);
    }

    // Bar chart
    var ctxBar = document.getElementById('chart-bar');
    if (ctxBar) {
      if (chartBar) chartBar.destroy();
      chartBar = new Chart(ctxBar.getContext('2d'), {
        type: 'bar',
        data: {
          labels: labels,
          datasets: [{
            label: 'Total Tokens',
            data: barVals,
            backgroundColor: 'rgba(37,99,235,0.30)',
            borderColor: 'rgba(37,99,235,0.80)',
            borderWidth: 1,
            borderRadius: 3,
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { ticks: { font: { size: 9 }, maxRotation: 45, minRotation: 0 } },
            y: { ticks: { font: { size: 9 }, callback: function(v) { return formatNum(v); } } }
          }
        }
      });
    }

    // Line chart
    var ctxLine = document.getElementById('chart-line');
    if (ctxLine) {
      if (chartLine) chartLine.destroy();
      chartLine = new Chart(ctxLine.getContext('2d'), {
        type: 'line',
        data: {
          labels: labels,
          datasets: [{
            label: 'Total Tokens',
            data: lineVals,
            borderColor: 'rgba(37,99,235,0.80)',
            borderWidth: 2,
            fill: true,
            backgroundColor: 'rgba(37,99,235,0.06)',
            tension: 0.3,
            pointRadius: 2,
            pointBackgroundColor: 'rgba(37,99,235,0.80)',
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: { ticks: { font: { size: 9 }, maxRotation: 45, minRotation: 0 } },
            y: { ticks: { font: { size: 9 }, callback: function(v) { return formatNum(v); } } }
          }
        }
      });
    }
  }

  // === Skills Tab ===
  function fetchSkills() {
    if (skillsCache) { renderSkills(skillsCache); return; }
    fetch('/api/skills')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        skillsCache = data;
        renderSkills(data);
      })
      .catch(function () {
        skillsCount.textContent = 'Failed to load skills';
      });
  }

  function renderSkills(data) {
    skillsCache = data;
    var skills = data.skills || [];
    skillsCount.textContent = skills.length + ' skills loaded';
    if (!skills.length) {
      skillsList.innerHTML = '<div class="skill-item" style="color:var(--text-tertiary)">No skills available</div>';
      return;
    }
    var html = '';
    for (var i = 0; i < skills.length; i++) {
      var s = skills[i];
      html += '<div class="skill-item">' +
        '<span class="skill-item-name">' + escapeHtml(s.name) + '</span>' +
        '<span class="skill-item-source">' + escapeHtml(s.source || 'local') + '</span>' +
        '<div class="skill-item-desc">' + escapeHtml(s.description || 'No description') + '</div>' +
        '</div>';
    }
    skillsList.innerHTML = html;
  }

  // === Search Tab ===
  function doSearch(query) {
    searchResults.innerHTML = '<div class="search-empty">Searching...</div>';
    fetch('/api/chat/search?q=' + encodeURIComponent(query))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var results = data.results || [];
        if (!results.length) {
          searchResults.innerHTML = '<div class="search-empty">No results for "' + escapeHtml(query) + '"</div>';
          return;
        }
        var html = '';
        for (var i = 0; i < results.length; i++) {
          var r = results[i];
          var dateStr = r.created_at ? r.created_at.slice(0, 16).replace('T', ' ') : '';
          html += '<div class="search-result" data-id="' + escapeAttr(r.id) + '">' +
            '<div class="search-result-title">' + highlightText(r.title || '(untitled)', query) + '</div>';
          var snippets = r.snippets || [];
          for (var j = 0; j < Math.min(snippets.length, 2); j++) {
            html += '<div class="search-result-snippet">' + highlightText(snippets[j].substring(0, 160), query) + '</div>';
          }
          html += '<div class="search-result-meta">' + dateStr + ' \u00b7 ' + (r.message_count || 0) + ' msgs</div>' +
            '</div>';
        }
        searchResults.innerHTML = html;

        var items = searchResults.querySelectorAll('.search-result');
        for (var k = 0; k < items.length; k++) {
          items[k].addEventListener('click', function () {
            var id = this.getAttribute('data-id');
            if (id) switchConversation(id);
          });
        }
      })
      .catch(function () {
        searchResults.innerHTML = '<div class="search-empty">Search failed</div>';
      });
  }

  function highlightText(text, keyword) {
    if (!keyword) return escapeHtml(text);
    var escaped = escapeHtml(text);
    var kwEscaped = escapeHtml(keyword);
    var regex = new RegExp('(' + kwEscaped.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi');
    return escaped.replace(regex, '<mark class="highlight">$1</mark>');
  }

  // === Sidebar Toggle ===
  function toggleSidebar(tab) {
    if (sidebarOpen) { closeSidebar(); }
    else { openSidebar(); if (tab) switchTab(tab); if (tab === 'files' && !currentDir) navigateTo('/'); }
  }

  function openSidebar() {
    sidebar.classList.remove('hidden');
    sidebarOpen = true;
    if (!activeTab) switchTab('files');
    // Auto-navigate to files root if not yet loaded
    if (activeTab === 'files' && !currentDir) {
      navigateTo('/');
    }
    if (window.innerWidth <= 900) {
      var overlay = document.querySelector('.sidebar-overlay');
      if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'sidebar-overlay visible';
        overlay.addEventListener('click', closeSidebar);
        document.body.appendChild(overlay);
      } else { overlay.classList.add('visible'); }
    }
  }

  function closeSidebar() {
    sidebar.classList.add('hidden');
    sidebarOpen = false;
    var overlay = document.querySelector('.sidebar-overlay');
    if (overlay) overlay.classList.remove('visible');
  }

  // === File Panel ===
  function navigateTo(path) {
    currentDir = path || currentDir;
    fetch('/api/files?path=' + encodeURIComponent(currentDir))
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
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
    updateBreadcrumb(data.path);
    var html = '';
    if (data.parent !== null && data.parent !== undefined) {
      html += '<div class="file-row dir" data-path="' + escapeAttr(data.parent) + '">' +
        '<span class="file-icon">&#8617;</span><span class="file-name">..</span></div>';
    }
    if (data.drives && data.drives.length) {
      for (var i = 0; i < data.drives.length; i++) {
        var d = data.drives[i];
        html += '<div class="file-row dir" data-path="' + escapeAttr(d.name + '\\') + '">' +
          '<span class="file-icon">' + driveIcon() + '</span>' +
          '<span class="file-name">' + escapeHtml(d.name) + '</span></div>';
      }
    }
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
    var rows = sidebarList.querySelectorAll('.file-row');
    for (var k = 0; k < rows.length; k++) {
      rows[k].addEventListener('click', handleFileRowClick);
    }
  }

  function handleFileRowClick(e) {
    var row = e.currentTarget;
    var path = row.getAttribute('data-path');
    if (!path) return;
    if (selectedFileRow) selectedFileRow.classList.remove('selected');
    row.classList.add('selected');
    selectedFileRow = row;
    if (row.classList.contains('dir')) { navigateTo(path); hidePreview(); }
    else { readAndPreviewFile(path); }
  }

  function readAndPreviewFile(path) {
    fetch('/api/files?read=' + encodeURIComponent(path))
      .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
      .then(showPreview)
      .catch(function (err) { showPreview({ type: 'error', content: 'Error: ' + err.message }); });
  }

  function showPreview(data) {
    var panel = document.getElementById('sidebar-preview');
    if (!panel) return;
    var titleEl = document.getElementById('preview-title');
    var contentEl = document.getElementById('preview-content');

    if (data.type === 'error') {
      contentEl.innerHTML = '<div class="preview-error">' + escapeHtml(data.content) + '</div>';
      titleEl.textContent = 'Error';
    } else {
      titleEl.textContent = data.path || 'Preview';
      if (data.type === 'image') {
        contentEl.innerHTML = '<img src="' + data.content + '" alt="preview" style="max-width:100%;height:auto">';
      } else {
        contentEl.innerHTML = '<pre class="preview-code">' + escapeHtml((data.content || '').substring(0, 20000)) + '</pre>';
      }
    }
    panel.classList.add('visible');
    var closeBtn = document.getElementById('btn-preview-close');
    if (closeBtn) {
      var newBtn = closeBtn.cloneNode(true);
      closeBtn.parentNode.replaceChild(newBtn, closeBtn);
      newBtn.addEventListener('click', hidePreview);
    }
  }

  function hidePreview() {
    var panel = document.getElementById('sidebar-preview');
    if (panel) panel.classList.remove('visible');
  }

  function updateBreadcrumb(path) {
    breadcrumb.textContent = path || '/';
  }

  // === File Upload ===
  function handleFileSelect(e) {
    if (e.target.files && e.target.files.length) {
      processFiles(e.target.files);
      e.target.value = '';
    }
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
          var isImage = /^\.(jpg|jpeg|png|gif|webp|bmp|svg|ico)$/i.test('.' + f.name.split('.').pop().toLowerCase());
          uploadedFiles.push({ name: f.name, content: content, isImage: isImage });
          renderUploadChips();
        };
      })(file);
      if (/^\.(jpg|jpeg|png|gif|webp|bmp|svg|ico)$/i.test(ext)) {
        reader.readAsDataURL(file);
      } else {
        var isBinary = /^\.(docx|xlsx|pptx|pdf)$/i.test(ext);
        if (isBinary) {
          uploadAndParse(file);
        } else {
          reader.readAsText(file, 'UTF-8');
        }
      }
    }
  }

  function uploadAndParse(file) {
    var formData = new FormData();
    formData.append('file', file);
    fetch('/api/upload', { method: 'POST', body: formData })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) {
          addMessage('system', 'Upload error: ' + data.error);
          return;
        }
        uploadedFiles.push({
          name: data.filename || file.name,
          content: data.content || '[Parsed: ' + (data.type || 'unknown') + ']',
          isImage: false,
        });
        renderUploadChips();
      })
      .catch(function (err) {
        addMessage('system', 'Upload failed: ' + err.message);
      });
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
    var inputArea = document.getElementById('input-area');
    inputArea.parentNode.insertBefore(bar, inputArea);
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

  // === Chat / SSE ===
  function sendMessage() {
    if (isStreaming) return;
    var text = inputEl.value.trim();
    var hasFiles = uploadedFiles.length > 0;
    if (!text && !hasFiles) return;

    var welcome = messagesEl.querySelector('.welcome');
    if (welcome) welcome.remove();

    var fullContent = '';
    for (var i = 0; i < uploadedFiles.length; i++) {
      var f = uploadedFiles[i];
      if (f.isImage) {
        fullContent += '[Uploaded image: ' + f.name + ']\n' + f.content + '\n';
      } else {
        fullContent += '[Uploaded file: ' + f.name + ']\n```\n' +
          (typeof f.content === 'string' ? f.content.slice(0, 8000) : '[binary]') + '\n```\n\n';
      }
    }
    if (text) {
      if (fullContent) {
        fullContent += '---\n' + text;
        addMessage('user', text);
        if (uploadedFiles.length) addMessage('system', 'Attached ' + uploadedFiles.length + ' file(s)');
      } else {
        addMessage('user', text);
        fullContent = text;
      }
    } else {
      addMessage('user', 'Sent ' + uploadedFiles.length + ' file(s) for analysis');
      fullContent = fullContent || 'Analyze the attached files.';
    }

    inputEl.value = '';
    inputEl.style.height = 'auto';
    uploadedFiles = [];
    var chips = document.getElementById('upload-chips');
    if (chips) chips.remove();

    setStreaming(true);
    sseDoneReceived = false;

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
        if (!response.ok) throw new Error('HTTP ' + response.status);
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
    sseReader = reader;
    var decoder = new TextDecoder();
    var buffer = '';

    function pump() {
      if (sseDoneReceived) {
        reader.cancel().catch(function () {});
        sseReader = null;
        return Promise.resolve();
      }
      return reader.read().then(function (result) {
        if (result.done) { finishStreaming(); sseReader = null; return; }
        if (sseDoneReceived) { reader.cancel().catch(function () {}); sseReader = null; return; }
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
            if (line.indexOf('event: ') === 0) eventType = line.slice(7).trim();
            else if (line.indexOf('data: ') === 0) dataStr += line.slice(6);
          }
          if (eventType && dataStr) handleSSEEvent(eventType, dataStr);
        }
        if (sseDoneReceived) { reader.cancel().catch(function () {}); sseReader = null; return; }
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
        if (data.type === 'tool') addToolBlock('running', data.tool || 'Tool', label);
        if (data.type === 'llm') { statusDot.classList.add('active'); statusDot.title = 'thinking'; }
        break;
      case 'message':
        sseDoneReceived = true;
        finishStreaming();
        if (currentAgentMsg) { currentAgentMsg.textContent = data.text || ''; }
        else { currentAgentMsg = addMessage('agent', data.text || ''); }
        // Detect LLM Error responses and style them as connection errors
        if (data.text && data.text.indexOf('[LLM Error]') === 0) {
          currentAgentMsg.classList.add('llm-error');
        }
        scrollToBottom();
        break;
      case 'done':
        sseDoneReceived = true;
        finishStreaming();
        break;
      case 'error':
        sseDoneReceived = true;
        finishStreaming();
        if (currentAgentMsg) { currentAgentMsg.textContent = ''; currentAgentMsg.classList.remove('streaming-cursor'); }
        addToolBlock('error', 'Error', data.text || 'Unknown error', true);
        break;
    }
  }

  function finishStreaming() {
    setStreaming(false);
    var running = messagesEl.querySelectorAll('.tool-block-icon.running');
    for (var i = 0; i < running.length; i++) { running[i].classList.remove('running'); running[i].classList.add('done'); }
    if (currentAgentMsg) currentAgentMsg.classList.remove('streaming-cursor');
    if (sseReader) { sseReader.cancel().catch(function () {}); sseReader = null; }
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
    header.appendChild(icon); header.appendChild(nameEl);
    header.appendChild(statusEl); header.appendChild(chevron);
    var body = document.createElement('div');
    body.className = 'tool-block-body';
    body.textContent = detail;
    header.addEventListener('click', function () { block.classList.toggle('expanded'); });
    block.appendChild(header); block.appendChild(body);
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

  function scrollToBottom() { chatEl.scrollTop = chatEl.scrollHeight; }

  function setStreaming(active) {
    isStreaming = active;
    sendBtn.hidden = active;
    stopBtn.hidden = !active;
    inputEl.readOnly = active;
    if (active) { statusDot.classList.add('active'); statusDot.title = 'active'; }
    else { statusDot.classList.remove('active', 'error'); statusDot.title = 'idle'; }
  }

  function stopGeneration() {
    if (!isStreaming) return;
    sseDoneReceived = true;
    if (sseReader) { sseReader.cancel().catch(function () {}); sseReader = null; }
    if (abortController) { abortController.abort(); abortController = null; }
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
      .then(function () { showWelcome('OfflineAgent Ready'); })
      .catch(function () { addMessage('system', 'Failed to clear history'); });
  }

  function newConversation() {
    if (isStreaming || newChatPending) return;
    newChatPending = true;
    fetch('/api/chat/new', { method: 'POST' })
      .then(function (r) { return r.json(); })
      .then(function (d) {
        showWelcome('New Conversation');
        if (d.saved_id) {
          addMessage('system', 'Previous conversation saved (ID: ' + d.saved_id.slice(0, 8) + '...)');
        }
        // Reset skills cache since conversations changed
        skillsCache = null;
      })
      .catch(function () { addMessage('system', 'Failed to create new conversation'); })
      .finally(function () { newChatPending = false; });
  }

  function showWelcome(title) {
    messagesEl.innerHTML = '';
    var welcome = document.createElement('div');
    welcome.className = 'message system welcome';
    welcome.innerHTML = '<div class="welcome-icon"><svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/></svg></div>' +
      '<div class="welcome-text"><strong>' + escapeHtml(title) + '</strong>' +
      '<span>Type /help for commands</span></div>';
    messagesEl.appendChild(welcome);
    inputEl.focus();
  }

  function fetchStatus() {
    fetch('/api/status')
      .then(function (r) { return r.json(); })
      .then(function (status) {
        modelNameEl.textContent = status.model || '--';
        statusDot.title = 'connected: ' + (status.model || '--');
        // Show echo mode warning if not connected to real LLM
        var banner = document.getElementById('echo-banner');
        if (banner) {
          banner.style.display = status.is_echo_mode ? 'flex' : 'none';
        }
      })
      .catch(function () {
        modelNameEl.textContent = '--';
        statusDot.classList.add('error');
        statusDot.title = 'disconnected';
        // Also show echo banner on connection failure
        var banner = document.getElementById('echo-banner');
        if (banner) { banner.style.display = 'flex'; }
      });
  }

  // === Utilities ===
  function escapeHtml(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
  function escapeAttr(s) { return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
  function formatSize(bytes) {
    if (!bytes || bytes === 0) return '';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1048576).toFixed(1) + ' MB';
  }
  function formatNum(n) {
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return String(n);
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
  function driveIcon() { return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="2" y="4" width="20" height="14" rx="2"/><path d="M6 12h12"/></svg>'; }
  function folderIcon() { return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>'; }
  function fileIcon(name) { return '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>'; }
})();
