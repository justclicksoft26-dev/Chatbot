/**
 * JustClick AI — APEX Widget Markdown Renderer
 * =============================================
 * أضف هذا الكود في APEX widget عشان الردود تتعرض بنفس شكل الـ Frontend.
 *
 * الاستخدام:
 *   بدل ما تعرض reply كنص خام:
 *     el.textContent = data.reply;
 *   استخدم:
 *     el.innerHTML = renderMarkdown(data.reply);
 */

// ── CSS (أضفه مرة واحدة في صفحة APEX أو في Inline CSS) ──────────
const JC_MARKDOWN_CSS = `
.jc-md-p { margin: 5px 0; line-height: 1.8; font-size: 14px; }
.jc-md-p strong { font-weight: 700; }

.jc-md-h3 {
  font-size: 15px; font-weight: 700;
  margin: 14px 0 6px;
  padding-bottom: 4px;
  border-bottom: 1px solid #e0e0e0;
}

.jc-md-h4 {
  font-size: 14px; font-weight: 700;
  margin: 10px 0 4px;
}

.jc-md-list {
  margin: 8px 0; padding-right: 6px;
  list-style: none;
}

.jc-md-list li {
  position: relative;
  padding: 4px 18px 4px 0;
  line-height: 1.7; font-size: 13.5px;
}

.jc-md-list li::before {
  content: '';
  position: absolute; right: 0; top: 13px;
  width: 6px; height: 6px;
  border-radius: 50%;
  background: #4a6cf7;
}

.jc-md-olist {
  margin: 8px 0; padding-right: 6px;
  list-style: none; counter-reset: jc-ol;
}

.jc-md-olist li {
  position: relative;
  padding: 4px 28px 4px 0;
  line-height: 1.7; font-size: 13.5px;
  counter-increment: jc-ol;
}

.jc-md-olist li::before {
  content: counter(jc-ol);
  position: absolute; right: 0; top: 5px;
  width: 20px; height: 20px;
  border-radius: 50%;
  background: rgba(74, 108, 247, 0.1);
  color: #4a6cf7;
  font-size: 11px; font-weight: 700;
  display: flex; align-items: center; justify-content: center;
}

.jc-md-card {
  background: #f8f9fa;
  border: 1px solid #e0e0e0;
  border-radius: 10px;
  padding: 6px 18px;
  margin: 10px 0;
}

.jc-md-card-field {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid #f0f0f0;
  gap: 12px;
}

.jc-md-card-field:last-child { border-bottom: none; }

.jc-md-card-label {
  font-size: 13px; font-weight: 600;
  color: #666; flex-shrink: 0;
}

.jc-md-card-value {
  font-size: 14px; font-weight: 700;
  font-variant-numeric: tabular-nums;
  text-align: left; direction: ltr;
}

.jc-md-card-value.text-val {
  direction: rtl; text-align: right; font-weight: 600;
}

.jc-md-table-wrap {
  margin: 10px 0;
  overflow-x: auto;
  border-radius: 8px;
  border: 1px solid #e0e0e0;
}

.jc-md-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}

.jc-md-table th {
  background: #f0f2f5;
  font-weight: 700; font-size: 11.5px;
  color: #666;
  padding: 8px 12px;
  text-align: right;
  white-space: nowrap;
  border-bottom: 1px solid #e0e0e0;
}

.jc-md-table td {
  padding: 7px 12px;
  border-bottom: 1px solid #f0f0f0;
  white-space: nowrap;
}

.jc-md-table tbody tr:nth-child(even) td { background: #fafafa; }
.jc-md-table tr:last-child td { border-bottom: none; }
.jc-md-table tr:hover td { background: #f0f4ff; }

.jc-md-table td.num {
  font-variant-numeric: tabular-nums;
  font-weight: 600;
  direction: ltr;
  text-align: left;
}

.jc-md-hr {
  border: none;
  border-top: 1px solid #e0e0e0;
  margin: 12px 0;
}

.jc-md-summary {
  margin: 4px 0 0;
  padding: 10px 14px;
  background: rgba(74, 108, 247, 0.08);
  border-radius: 10px;
  font-size: 13.5px;
  line-height: 1.75;
}
`;

// ── Inject CSS once ──────────────────────────────────────────────
(function() {
  if (!document.getElementById('jc-md-styles')) {
    var s = document.createElement('style');
    s.id = 'jc-md-styles';
    s.textContent = JC_MARKDOWN_CSS;
    document.head.appendChild(s);
  }
})();


// ── Helper functions ─────────────────────────────────────────────

function jcEscHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function jcInlineFmt(text) {
  return text.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
}

function jcIsKvLine(line) {
  if (!line || line.startsWith('|') || line.startsWith('#') ||
      /^[-*]\s/.test(line) || /^\d+[.)]\s/.test(line)) return false;
  if (/^[-*_]{3,}$/.test(line)) return false;
  var idx = line.indexOf(':');
  if (idx <= 0 || idx >= line.length - 1) return false;
  var label = line.substring(0, idx).trim();
  return label.length > 0 && label.length < 35;
}

function jcRenderMdCard(lines) {
  var h = '<div class="jc-md-card">';
  for (var k = 0; k < lines.length; k++) {
    var idx = lines[k].indexOf(':');
    var label = lines[k].substring(0, idx).trim();
    var value = lines[k].substring(idx + 1).trim();
    var isNum = /^[\d,.\-\s%]+$/.test(value.replace(/[^\d,.\-%\s]/g, ''));
    h += '<div class="jc-md-card-field">' +
      '<span class="jc-md-card-label">' + jcEscHtml(label) + '</span>' +
      '<span class="jc-md-card-value' + (isNum ? '' : ' text-val') + '">' +
        jcInlineFmt(jcEscHtml(value)) + '</span></div>';
  }
  h += '</div>';
  return h;
}

function jcRenderMdTable(tLines) {
  if (tLines.length < 2) {
    return tLines.map(function(l) {
      return '<p class="jc-md-p">' + jcEscHtml(l) + '</p>';
    }).join('');
  }

  var parseCells = function(row) {
    return row.replace(/^\||\|$/g, '').split('|').map(function(c) { return c.trim(); });
  };

  var headers = parseCells(tLines[0]);
  var dataStart = 1;
  if (tLines.length > 1 && /^[\s|:-]+$/.test(tLines[1])) dataStart = 2;

  var rows = [];
  for (var j = dataStart; j < tLines.length; j++) {
    var cells = parseCells(tLines[j]);
    if (cells.length > 0 && cells.some(function(c) { return c; })) rows.push(cells);
  }

  var h = '<div class="jc-md-table-wrap"><table class="jc-md-table"><thead><tr>';
  headers.forEach(function(hdr) { h += '<th>' + jcEscHtml(hdr) + '</th>'; });
  h += '</tr></thead><tbody>';
  rows.forEach(function(row) {
    h += '<tr>';
    row.forEach(function(cell) {
      var isNum = /^[\d,.\-\s]+$/.test(cell) && cell.length > 0;
      h += '<td class="' + (isNum ? 'num' : '') + '">' + jcEscHtml(cell) + '</td>';
    });
    h += '</tr>';
  });
  h += '</tbody></table></div>';
  return h;
}


// ── Main renderer ────────────────────────────────────────────────

function renderMarkdown(text) {
  if (!text) return '';

  var lines = text.split('\n');
  var html = '';
  var i = 0;
  var afterHr = false;

  while (i < lines.length) {
    var raw = lines[i];
    var line = raw.trim();

    if (!line) { i++; continue; }

    // Horizontal rule
    if (/^[-*_]{3,}$/.test(line)) {
      afterHr = true;
      html += '<hr class="jc-md-hr">';
      i++;
      continue;
    }

    // Headers
    if (line.startsWith('### ')) {
      html += '<h4 class="jc-md-h4">' + jcInlineFmt(jcEscHtml(line.slice(4))) + '</h4>';
      i++; afterHr = false; continue;
    }
    if (line.startsWith('## ')) {
      html += '<h3 class="jc-md-h3">' + jcInlineFmt(jcEscHtml(line.slice(3))) + '</h3>';
      i++; afterHr = false; continue;
    }

    // Markdown table
    if (line.startsWith('|')) {
      var tLines = [];
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        tLines.push(lines[i].trim());
        i++;
      }
      html += jcRenderMdTable(tLines);
      afterHr = false;
      continue;
    }

    // Bullet list
    if (/^[-*]\s+/.test(line)) {
      var items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].trim().replace(/^[-*]\s+/, ''));
        i++;
      }
      html += '<ul class="jc-md-list">' +
        items.map(function(it) { return '<li>' + jcInlineFmt(jcEscHtml(it)) + '</li>'; }).join('') +
        '</ul>';
      afterHr = false;
      continue;
    }

    // Numbered list
    if (/^\d+[.)]\s+/.test(line)) {
      var items = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        items.push(lines[i].trim().replace(/^\d+[.)]\s+/, ''));
        i++;
      }
      html += '<ol class="jc-md-olist">' +
        items.map(function(it) { return '<li>' + jcInlineFmt(jcEscHtml(it)) + '</li>'; }).join('') +
        '</ol>';
      afterHr = false;
      continue;
    }

    // Key-value card
    if (jcIsKvLine(line)) {
      var kvLines = [];
      while (i < lines.length && lines[i].trim() && jcIsKvLine(lines[i].trim())) {
        kvLines.push(lines[i].trim());
        i++;
      }
      if (kvLines.length >= 2) {
        html += jcRenderMdCard(kvLines);
        afterHr = false;
        continue;
      }
      // Single kv line → paragraph
      var cls = afterHr ? 'jc-md-summary' : 'jc-md-p';
      html += '<p class="' + cls + '">' + jcInlineFmt(jcEscHtml(kvLines[0])) + '</p>';
      afterHr = false;
      continue;
    }

    // Regular paragraph
    var cls = afterHr ? 'jc-md-summary' : 'jc-md-p';
    html += '<p class="' + cls + '">' + jcInlineFmt(jcEscHtml(line)) + '</p>';
    afterHr = false;
    i++;
  }

  return html;
}
