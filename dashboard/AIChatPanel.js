/**
 * AIChatPanel.js — ELN Intelligence Agent chat panel
 * Covvalent brand: navy #000B36, blue #0E2673, cyan #9DD1F1, ice #DEEBF7
 */

import React, { useState, useEffect, useRef, useCallback } from 'react';

const API_BASE = process.env.REACT_APP_API_URL ||
  'https://eln-api-covvalent-asfhf0abbvh2bphd.southindia-01.azurewebsites.net';

const FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";
const C = {
  navy: '#000B36', blue: '#0E2673', cyan: '#9DD1F1', ice: '#DEEBF7',
  white: '#FFFFFF', textDim: '#4a6194', textSub: '#6b82b8', border: '#9DD1F1', border: '#9DD1F1',
};

// ── CSV export ────────────────────────────────────────────────────────────────
function markdownTableToCSV(markdown) {
  const lines = markdown.split('\n').filter(l => l.trim().startsWith('|'));
  if (lines.length < 2) return null;
  const rows = lines
    .filter(l => !l.match(/^\|[-| ]+\|$/))
    .map(l => l.split('|').slice(1,-1).map(c => `"${c.trim().replace(/"/g,'""')}"`).join(','));
  return rows.join('\n');
}

function downloadCSV(content, filename) {
  const blob = new Blob([content], { type: 'text/csv;charset=utf-8;' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

function extractCSVFromCodeBlock(text) {
  const match = text.match(/```csv\n([\s\S]+?)```/);
  return match ? match[1].trim() : null;
}

function hasDownloadableContent(text) {
  return /\|.+\|.+\|\n\|[-| ]+\|/.test(text) || /```csv/.test(text);
}

function getCSVContent(text) {
  // Try CSV code block first
  const codeBlock = extractCSVFromCodeBlock(text);
  if (codeBlock) return codeBlock;
  // Fall back to markdown table
  return markdownTableToCSV(text);
}

function hasMarkdownTable(text) {
  return /\|.+\|.+\|\n\|[-| ]+\|/.test(text);
}

// ── Markdown renderer ─────────────────────────────────────────────────────────
function renderMarkdown(text) {
  if (!text) return '';
  // Tables
  text = text.replace(/((?:\|.+\|\n?)+)/g, (match) => {
    const lines = match.trim().split('\n').filter(Boolean);
    if (lines.length < 2) return match;
    const headerCells = lines[0].split('|').slice(1,-1).map(c => c.trim());
    const dataLines   = lines.slice(2);
    const header = `<tr style="background:#000B36">${headerCells.map(c => `<th style="padding:7px 10px;text-align:left;color:#FFFFFF;font-size:11px;font-weight:700;letter-spacing:0.5px;white-space:nowrap">${c}</th>`).join('')}</tr>`;
    const rows   = dataLines.map((l,i) => {
      const cells = l.split('|').slice(1,-1).map(c => c.trim());
      return `<tr style="background:${i%2===0?'#FFFFFF':'#DEEBF7'}">${cells.map(c => `<td style="padding:6px 10px;border-bottom:1px solid #DEEBF7;color:#0E2673;font-size:13px">${c}</td>`).join('')}</tr>`;
    }).join('');
    return `<div style="overflow-x:auto;margin:12px 0;border-radius:6px;overflow:hidden;border:1.5px solid #9DD1F1"><table style="border-collapse:collapse;width:100%"><thead>${header}</thead><tbody>${rows}</tbody></table></div>`;
  });
  text = text.replace(/\*\*(.+?)\*\*/g, '<strong style="color:#000B36">$1</strong>');
  text = text.replace(/^### (.+)$/gm, '<div style="color:#000B36;font-weight:700;font-size:14px;margin:12px 0 4px;font-family:Inter,sans-serif">$1</div>');
  text = text.replace(/^## (.+)$/gm,  '<div style="color:#000B36;font-weight:800;font-size:15px;margin:14px 0 6px;font-family:Inter,sans-serif">$1</div>');
  text = text.replace(/\n/g, '<br/>');
  return text;
}

// ── Error classifier ──────────────────────────────────────────────────────────
function classifyError(status, detail) {
  if (!status) return { message: 'No response from server. Check your connection and try again.', retryable: true, icon: '⚡' };
  if (status === 504) return { message: detail || 'This query took too long. Try asking one step at a time — e.g. fetch the experiment list first, then ask about a specific one.', retryable: true, icon: '⏱' };
  if (status === 503) return { message: 'AI service temporarily unavailable. Usually recovers within a minute.', retryable: true, icon: '🔄' };
  if (status === 500) {
    const clean = detail ? detail.replace(/^Agent run (failed|cancelled|expired):\s*/i, '') : '';
    return { message: clean || 'The agent encountered an error. Try rephrasing your question.', retryable: false, icon: '⚠' };
  }
  return { message: detail || 'Something went wrong. Please try again.', retryable: true, icon: '⚠' };
}

function ToolBadge({ tool, args }) {
  const labels = { fetch_experiment: '⚙ Fetched', search_experiments: '⚙ Searched', search_literature: '⚙ Literature' };
  const label  = labels[tool] || `⚙ ${tool}`;
  const detail = args?.project_code || args?.experiment_id || args?.exp_number_full || args?.q || '';
  return (
    <span style={{ display: 'inline-block', background: C.navy, color: C.cyan, fontSize: '11px', fontWeight: 600, padding: '2px 10px', borderRadius: '10px', marginRight: '5px', marginBottom: '4px', fontFamily: FONT, letterSpacing: '0.3px' }}>
      {label}{detail ? ` ${detail}` : ''}
    </span>
  );
}

function TypingIndicator({ stage }) {
  const stages = { thinking: 'Thinking…', fetching: 'Fetching experiment data…', searching: 'Searching experiments…', literature: 'Searching literature…', writing: 'Writing response…' };
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 0' }}>
      <style>{`@keyframes bounce{0%,80%,100%{transform:translateY(0);opacity:.35}40%{transform:translateY(-6px);opacity:1}}`}</style>
      <div style={{ display: 'flex', gap: '4px' }}>
        {[0,1,2].map(i => <div key={i} style={{ width: '7px', height: '7px', borderRadius: '50%', background: C.blue, animation: `bounce 1.2s ease-in-out ${i*0.2}s infinite` }} />)}
      </div>
      <span style={{ color: C.textDim, fontSize: '13px', fontFamily: FONT }}>{stages[stage] || 'Working…'}</span>
    </div>
  );
}

function MessageBubble({ msg, onRetry }) {
  if (msg.role === 'user') {
    return (
      <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '14px' }}>
        <div style={{ background: C.navy, color: C.white, borderRadius: '16px 16px 4px 16px', padding: '10px 15px', maxWidth: '82%', fontSize: '14px', lineHeight: '1.5', fontFamily: FONT }}>
          {msg.content}
        </div>
      </div>
    );
  }

  if (msg.role === 'error') {
    const err = classifyError(msg.status, msg.content);
    return (
      <div style={{ marginBottom: '12px' }}>
        <div style={{ background: '#fef2f2', border: '1.5px solid #fca5a5', borderLeft: '3px solid #c0392b', borderRadius: '6px', padding: '12px 14px', fontSize: '13px', color: '#c0392b', lineHeight: '1.6', fontFamily: FONT }}>
          <span style={{ marginRight: '6px' }}>{err.icon}</span>{err.message}
          {err.retryable && onRetry && (
            <button onClick={onRetry} style={{ display: 'block', marginTop: '8px', background: 'transparent', border: '1.5px solid #c0392b', color: '#c0392b', borderRadius: '4px', padding: '4px 12px', fontSize: '12px', cursor: 'pointer', fontWeight: 600, fontFamily: FONT }}>Retry</button>
          )}
        </div>
      </div>
    );
  }

  const rendered = renderMarkdown(msg.content);
  const hasTable = hasDownloadableContent(msg.content);
  const csvData  = hasTable ? getCSVContent(msg.content) : null;

  return (
    <div style={{ marginBottom: '18px' }}>
      {msg.toolCalls?.length > 0 && (
        <div style={{ marginBottom: '7px' }}>
          {msg.toolCalls.map((tc, i) => <ToolBadge key={i} tool={tc.tool} args={tc.args} />)}
        </div>
      )}
      <div style={{ background: C.ice, border: `1.5px solid ${C.cyan}`, borderRadius: '4px 14px 14px 14px', padding: '12px 16px', fontSize: '14px', color: C.blue, lineHeight: '1.75', fontFamily: FONT, wordBreak: 'break-word' }}
        dangerouslySetInnerHTML={{ __html: rendered }}
      />
      {csvData && (
        <button onClick={() => downloadCSV(csvData, `eln-export-${Date.now()}.csv`)} style={{ marginTop: '6px', background: 'transparent', border: `1.5px solid ${C.border}`, color: C.textDim, borderRadius: '4px', padding: '4px 12px', fontSize: '11px', cursor: 'pointer', fontWeight: 600, fontFamily: FONT, display: 'flex', alignItems: 'center', gap: '5px' }}>
          ↓ Download CSV
        </button>
      )}
    </div>
  );
}

export default function AIChatPanel({ onClose }) {
  const SESSION_KEY = 'eln_chat_messages';
  const THREAD_KEY  = 'eln_chat_thread_id';

  const [messages, setMessages]           = useState(() => { try { return JSON.parse(sessionStorage.getItem(SESSION_KEY)) || []; } catch { return []; } });
  const [threadId, setThreadId]           = useState(() => sessionStorage.getItem(THREAD_KEY) || null);
  const [input, setInput]                 = useState('');
  const [isLoading, setIsLoading]         = useState(false);
  const [loadingStage, setLoadingStage]   = useState('thinking');
  const [lastUserMessage, setLastUserMsg] = useState(null);

  const bottomRef = useRef(null);
  const inputRef  = useRef(null);
  const abortRef  = useRef(null);

  useEffect(() => { sessionStorage.setItem(SESSION_KEY, JSON.stringify(messages)); }, [messages]);
  useEffect(() => { if (threadId) sessionStorage.setItem(THREAD_KEY, threadId); }, [threadId]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages, isLoading]);
  useEffect(() => { inputRef.current?.focus(); }, []);

  const sendMessage = useCallback(async (text) => {
    if (!text?.trim() || isLoading) return;
    const userText = text.trim();
    setLastUserMsg(userText);
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: userText }]);
    setIsLoading(true);
    setLoadingStage('thinking');

    const t1 = setTimeout(() => setLoadingStage('fetching'),  4000);
    const t2 = setTimeout(() => setLoadingStage('searching'), 8000);
    const t3 = setTimeout(() => setLoadingStage('writing'),   15000);

    try {
      const controller = new AbortController();
      abortRef.current = controller;

      const res = await fetch(`${API_BASE}/api/ai/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: userText, thread_id: threadId || null }),
        signal: controller.signal
      });

      clearTimeout(t1); clearTimeout(t2); clearTimeout(t3);

      if (!res.ok) {
        let detail = '';
        try { detail = (await res.json()).detail; } catch {}
        setMessages(prev => [...prev, { role: 'error', content: detail, status: res.status }]);
        return;
      }

      const data = await res.json();
      if (data.thread_id && !threadId) setThreadId(data.thread_id);

      const wantsCSV = /csv|excel|download|export/i.test(userText);
      if (wantsCSV && hasDownloadableContent(data.answer)) {
        const csv = getCSVContent(data.answer);
        if (csv) downloadCSV(csv, `eln-export-${Date.now()}.csv`);
      }

      setMessages(prev => [...prev, { role: 'assistant', content: data.answer, toolCalls: data.tool_calls || [] }]);
    } catch (err) {
      clearTimeout(t1); clearTimeout(t2); clearTimeout(t3);
      if (err.name === 'AbortError') return;
      setMessages(prev => [...prev, { role: 'error', content: err.message, status: null }]);
    } finally {
      setIsLoading(false);
      setLoadingStage('thinking');
      abortRef.current = null;
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isLoading, threadId]);

  // Direct export — bypasses agent, calls /api/ai/export with parsed intent
  const handleDirectExport = useCallback(async () => {
    const text = input.trim() || '';

    // Date regex runs first — prevents day-of-month digits being captured as days=N
    const MONTHS = { jan:1,feb:2,mar:3,apr:4,may:5,jun:6,jul:7,aug:8,sep:9,oct:10,nov:11,dec:12 };
    const MONTH_PAT = 'jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?';
    let fromDate = null;
    const isoMatch = text.match(/\b(\d{4}-\d{2}-\d{2})\b/);
    const dmy = text.match(new RegExp(`\\b(\\d{1,2})(?:st|nd|rd|th)?\\s+(${MONTH_PAT})\\b`, 'i'));
    const mdy = text.match(new RegExp(`\\b(${MONTH_PAT})\\s+(\\d{1,2})(?:st|nd|rd|th)?\\b`, 'i'));
    if (isoMatch) {
      fromDate = isoMatch[1];
    } else if (dmy) {
      const month = MONTHS[dmy[2].slice(0,3).toLowerCase()];
      if (month) fromDate = `${new Date().getFullYear()}-${String(month).padStart(2,'0')}-${String(parseInt(dmy[1])).padStart(2,'0')}`;
    } else if (mdy) {
      const month = MONTHS[mdy[1].slice(0,3).toLowerCase()];
      if (month) fromDate = `${new Date().getFullYear()}-${String(month).padStart(2,'0')}-${String(parseInt(mdy[2])).padStart(2,'0')}`;
    }

    const daysMatch = text.match(/(\d+)\s*day/i);
    const projectMatch = text.match(/\b([A-Z][0-9]{3}[A-Z][0-9]{2})\b/i);
    const authorMatch = text.match(/author[:\s]+([\w_]+)/i);

    const body = {};
    if (fromDate) body.from_date = fromDate;
    else body.days = daysMatch ? parseInt(daysMatch[1]) : 90;
    if (projectMatch) body.project_code = projectMatch[1].toUpperCase();
    if (authorMatch) body.author = authorMatch[1];

    const label = fromDate ? `from-${fromDate}` : `${body.days}d`;
    try {
      const res = await fetch(`${API_BASE}/api/ai/export`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (!res.ok) { alert('Export failed: ' + await res.text()); return; }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `eln-export-${label}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) { alert('Export error: ' + e.message); }
  }, [input]);

  const handleNewSession = () => {
    if (isLoading) { abortRef.current?.abort(); setIsLoading(false); }
    setMessages([]); setThreadId(null); setInput('');
    sessionStorage.removeItem(SESSION_KEY);
    sessionStorage.removeItem(THREAD_KEY);
    setTimeout(() => inputRef.current?.focus(), 100);
  };

  return (
    <div style={{ position: 'fixed', bottom: '28px', right: '28px', width: '430px', height: '610px', background: C.white, border: `2px solid ${C.cyan}`, borderRadius: '12px', boxShadow: '0 24px 64px rgba(0,11,54,0.2)', display: 'flex', flexDirection: 'column', zIndex: 9999, fontFamily: FONT }}>

      {/* Header */}
      <div style={{ padding: '14px 18px', background: C.navy, borderRadius: '10px 10px 0 0', display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0 }}>
        <div>
          <div style={{ color: C.white, fontWeight: 800, fontSize: '14px', letterSpacing: '0.3px' }}>⚗ Ask AI</div>
          <div style={{ color: C.cyan, fontSize: '11px', marginTop: '1px', fontWeight: 500, opacity: 0.8 }}>ELN Intelligence Agent</div>
        </div>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
          <button onClick={handleNewSession} style={{ background: 'rgba(157,209,241,0.15)', border: `1px solid rgba(157,209,241,0.3)`, color: C.cyan, borderRadius: '6px', padding: '5px 12px', fontSize: '12px', cursor: 'pointer', fontWeight: 600, fontFamily: FONT }}>New session</button>
          <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: C.cyan, fontSize: '20px', cursor: 'pointer', lineHeight: 1, padding: '2px 4px' }}>×</button>
        </div>
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 16px 8px', scrollbarWidth: 'thin', scrollbarColor: `${C.cyan} transparent` }}>
        {messages.length === 0 && (
          <div style={{ color: C.textSub, fontSize: '13px', textAlign: 'center', marginTop: '40px', lineHeight: '1.9', fontFamily: FONT }}>
            Ask about experiments, synthesis routes, projects…
            <br /><span style={{ fontSize: '12px', color: C.cyan, fontStyle: 'italic' }}>"What's the best tryptophan synthesis experiment?"</span>
          </div>
        )}
        {messages.map((msg, i) => (
          <MessageBubble key={i} msg={msg} onRetry={
            msg.role === 'error' && lastUserMessage
              ? () => { setMessages(prev => prev.slice(0,-1)); sendMessage(lastUserMessage); }
              : null
          } />
        ))}
        {isLoading && <TypingIndicator stage={loadingStage} />}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div style={{ padding: '12px 16px 14px', borderTop: `1.5px solid ${C.ice}`, flexShrink: 0, background: C.white, borderRadius: '0 0 10px 10px' }}>
        <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-end', background: C.ice, border: `1.5px solid ${C.cyan}`, borderRadius: '8px', padding: '8px 12px' }}>
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(input); } }}
            placeholder="Ask about experiments, synthesis routes, projects…"
            disabled={isLoading}
            rows={1}
            style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', color: C.blue, fontSize: '13px', resize: 'none', lineHeight: '1.5', maxHeight: '80px', overflowY: 'auto', fontFamily: FONT, opacity: isLoading ? 0.5 : 1 }}
          />
          <button
            onClick={handleDirectExport}
            title="Export as CSV (bypasses AI — downloads full dataset)"
            style={{ background: 'transparent', border: `1.5px solid ${C.cyan}`, borderRadius: '6px', color: C.textDim, width: '34px', height: '34px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, fontFamily: FONT }}
          >↓</button>
          <button
            onClick={() => sendMessage(input)}
            disabled={!input.trim() || isLoading}
            style={{ background: input.trim() && !isLoading ? C.navy : C.ice, border: `1.5px solid ${input.trim() && !isLoading ? C.navy : C.cyan}`, borderRadius: '6px', color: input.trim() && !isLoading ? C.white : C.textSub, width: '34px', height: '34px', cursor: input.trim() && !isLoading ? 'pointer' : 'default', fontSize: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, transition: 'all 0.15s', fontFamily: FONT }}
          >↑</button>
        </div>
        <div style={{ color: C.textSub, fontSize: '11px', marginTop: '6px', textAlign: 'center', fontFamily: FONT }}>↑ Ask AI · ↓ CSV downloads full dataset directly</div>
      </div>
    </div>
  );
}
