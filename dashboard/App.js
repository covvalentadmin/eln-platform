/**
 * App.js — Covvalent ELN Intelligence Dashboard v3.1
 * Brand: Inter font, #000B36 navy, #0E2673 blue, #9DD1F1 cyan, #DEEBF7 soft ice
 * SWA built-in Entra ID auth — no MSAL — user info via /.auth/me
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import AIChatPanel from './AIChatPanel';

const API_BASE = process.env.REACT_APP_API_URL ||
  'https://eln-api-covvalent-asfhf0abbvh2bphd.southindia-01.azurewebsites.net';

async function getSWAUser() {
  try {
    const res = await fetch('/.auth/me');
    const data = await res.json();
    return data?.clientPrincipal || null;
  } catch { return null; }
}

async function apiFetch(path, opts = {}) {
  const res = await fetch(`${API_BASE}${path}`, opts);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// ── Covvalent brand tokens ────────────────────────────────────────────────────
const C = {
  navy:     '#000B36',   // dark navy — sidebar bg, headings
  blue:     '#0E2673',   // brand blue — text, buttons, borders
  cyan:     '#9DD1F1',   // accent cyan — highlights, active states
  ice:      '#DEEBF7',   // soft ice — card/row backgrounds
  white:    '#FFFFFF',   // page background, text on dark
  textBody: '#0E2673',   // body text on light
  textDim:  '#4a6194',   // muted text (blue tinted)
  textSub:  '#6b82b8',   // captions
  border:   '#9DD1F1',   // borders use cyan
  borderMid:'#DEEBF7',   // lighter borders
  danger:   '#c0392b',   // errors only
};

const FONT = "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif";

// ── Google Fonts import ───────────────────────────────────────────────────────
const fontStyle = document.createElement('link');
fontStyle.rel = 'stylesheet';
fontStyle.href = 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap';
document.head.appendChild(fontStyle);

// ── Sidebar ───────────────────────────────────────────────────────────────────
function Sidebar({ active, onNav, user }) {
  const items = [
    { key: 'summary',     icon: '◈', label: 'Summary',     sub: 'Efficiency & KPIs' },
    { key: 'projects',    icon: '⬡', label: 'Projects',    sub: 'All campaigns' },
    { key: 'experiments', icon: '⚗', label: 'Experiments', sub: 'Recent ELN entries' },
    { key: 'askai',       icon: '⚗', label: 'Ask AI',        sub: 'Chemistry agent' },
    { key: 'reports',  icon: '⬒', label: 'Reports',         sub: 'Analysis & meeting docs' },
    { key: 'meeting',  icon: '⏺', label: 'Meeting Copilot', sub: 'Voice to report' },
  ];
  return (
    <div style={{ width: '210px', minHeight: '100vh', background: C.navy, display: 'flex', flexDirection: 'column', flexShrink: 0 }}>
      {/* Logo */}
      <div style={{ padding: '22px 18px 18px', borderBottom: `1px solid rgba(157,209,241,0.2)` }}>
        <div style={{ color: C.white, fontFamily: FONT, fontWeight: 800, fontSize: '15px', letterSpacing: '1px' }}>COVVALENT</div>
        <div style={{ color: C.cyan, fontFamily: FONT, fontSize: '10px', letterSpacing: '1.5px', marginTop: '3px', fontWeight: 500 }}>ELN INTELLIGENCE</div>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, padding: '14px 0' }}>
        {items.map(item => {
          const on = active === item.key;
          return (
            <button key={item.key} onClick={() => onNav(item.key)} style={{
              width: '100%', background: on ? 'rgba(157,209,241,0.15)' : 'transparent',
              border: 'none', borderLeft: `3px solid ${on ? C.cyan : 'transparent'}`,
              color: on ? C.white : C.cyan,
              padding: '11px 18px', textAlign: 'left', cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: '12px',
              fontFamily: FONT, transition: 'all 0.15s'
            }}>
              <span style={{ fontSize: '15px', width: '20px', textAlign: 'center', opacity: on ? 1 : 0.7 }}>{item.icon}</span>
              <div>
                <div style={{ fontSize: '13px', fontWeight: on ? 700 : 500 }}>{item.label}</div>
                <div style={{ fontSize: '10px', color: on ? 'rgba(157,209,241,0.8)' : 'rgba(157,209,241,0.5)', marginTop: '1px' }}>{item.sub}</div>
              </div>
            </button>
          );
        })}
      </nav>

      {/* User */}
      {user && (
        <div style={{ padding: '14px 18px', borderTop: `1px solid rgba(157,209,241,0.2)`, fontFamily: FONT }}>
          <div style={{ color: C.white, fontWeight: 600, fontSize: '12px', marginBottom: '2px' }}>{user.userDetails?.split('@')[0] || 'User'}</div>
          <div style={{ color: 'rgba(157,209,241,0.6)', fontSize: '10px', marginBottom: '8px', wordBreak: 'break-all' }}>{user.userDetails}</div>
          <a href="/.auth/logout" style={{ color: C.cyan, textDecoration: 'none', fontSize: '11px', opacity: 0.7 }}>Sign out</a>
        </div>
      )}
    </div>
  );
}

// ── Page header ───────────────────────────────────────────────────────────────
function PageHeader({ title, sub }) {
  return (
    <div style={{ padding: '24px 28px 0', borderBottom: `2px solid ${C.ice}`, paddingBottom: '16px', marginBottom: '24px' }}>
      <h2 style={{ color: C.navy, fontFamily: FONT, fontSize: '22px', fontWeight: 800, margin: 0 }}>{title}</h2>
      {sub && <div style={{ color: C.textDim, fontFamily: FONT, fontSize: '13px', marginTop: '4px', fontWeight: 500 }}>{sub}</div>}
    </div>
  );
}

// ── Stat card ─────────────────────────────────────────────────────────────────
function StatCard({ label, value, sub, highlight }) {
  return (
    <div style={{
      background: highlight ? C.navy : C.white,
      border: `1.5px solid ${highlight ? C.navy : C.border}`,
      borderRadius: '10px', padding: '18px 22px', flex: 1, minWidth: '148px',
      boxShadow: highlight ? '0 2px 12px rgba(0,11,54,0.15)' : '0 1px 4px rgba(14,38,115,0.08)'
    }}>
      <div style={{ color: highlight ? C.cyan : C.textSub, fontFamily: FONT, fontSize: '10px', fontWeight: 600, letterSpacing: '0.8px', marginBottom: '8px', textTransform: 'uppercase' }}>{label}</div>
      <div style={{ color: highlight ? C.white : C.navy, fontFamily: FONT, fontSize: '30px', fontWeight: 800, lineHeight: 1 }}>{value ?? '—'}</div>
      {sub && <div style={{ color: highlight ? 'rgba(157,209,241,0.7)' : C.textSub, fontFamily: FONT, fontSize: '11px', marginTop: '5px', fontWeight: 500 }}>{sub}</div>}
    </div>
  );
}

// ── Summary view ──────────────────────────────────────────────────────────────
function SummaryView() {
  const [liveStats, setLiveStats]   = useState(null);
  const [efficiency, setEfficiency] = useState(null);
  const [period, setPeriod]         = useState('last_full_year');
  const [liveError, setLiveError]   = useState(null);
  const [effError, setEffError]     = useState(null);
  const [loading, setLoading]       = useState(true);

  useEffect(() => {
    Promise.all([
      apiFetch('/api/dashboard/summary').catch(e => { setLiveError(e.message); return null; }),
      apiFetch('/api/dashboard/efficiency').catch(e => { setEffError(e.message); return null; }),
    ]).then(([live, eff]) => { setLiveStats(live); setEfficiency(eff); setLoading(false); });
  }, []);

  const periods = [
    { key: 'last_full_year', label: 'Last Full Year' },
    { key: 'last_quarter',   label: 'Last Quarter'   },
    { key: 'last_month',     label: 'Last Month'     },
  ];

  const eff = efficiency?.[period];

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '0 28px 28px', background: C.white }}>
      <PageHeader title="Summary" sub="Live metrics · R&D efficiency analysis" />

      {/* Live stats */}
      <div style={{ color: C.blue, fontFamily: FONT, fontSize: '10px', fontWeight: 700, letterSpacing: '1.5px', marginBottom: '12px' }}>LIVE — ELNANALYTICS</div>
      {loading ? (
        <div style={{ color: C.textDim, fontFamily: FONT, fontSize: '13px', marginBottom: '28px' }}>Loading…</div>
      ) : liveError ? (
        <div style={{ color: C.danger, fontFamily: FONT, fontSize: '13px', marginBottom: '28px' }}>Live stats unavailable: {liveError}</div>
      ) : (
        <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap', marginBottom: '32px' }}>
          <StatCard label="Total Projects"     value={liveStats?.total_projects}     sub="All campaigns" />
          <StatCard label="Total Experiments"  value={liveStats?.total_experiments}  sub="All ELN entries" />
          <StatCard label="New in Last 7 Days" value={liveStats?.new_last_7_days}    sub="Recent activity" highlight />
          <StatCard label="Active Projects"    value={liveStats?.active_last_7_days} sub="Last 7 days" />
        </div>
      )}

      {/* Period toggle */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
        <div style={{ color: C.blue, fontFamily: FONT, fontSize: '10px', fontWeight: 700, letterSpacing: '1.5px' }}>EFFICIENCY ANALYSIS</div>
        <div style={{ display: 'flex', gap: '6px' }}>
          {periods.map(p => (
            <button key={p.key} onClick={() => setPeriod(p.key)} style={{
              background: period === p.key ? C.navy : C.white,
              border: `1.5px solid ${period === p.key ? C.navy : C.border}`,
              color: period === p.key ? C.white : C.blue,
              borderRadius: '6px', padding: '5px 14px',
              fontFamily: FONT, fontSize: '12px', cursor: 'pointer',
              fontWeight: period === p.key ? 700 : 500,
              transition: 'all 0.15s'
            }}>{p.label}</button>
          ))}
        </div>
        {eff && <div style={{ color: C.textSub, fontFamily: FONT, fontSize: '12px' }}>{eff.period}</div>}
      </div>

      {effError ? (
        <div style={{ color: C.danger, fontFamily: FONT, fontSize: '13px', marginBottom: '24px' }}>Efficiency data unavailable: {effError}</div>
      ) : !eff && !loading ? (
        <div style={{ color: C.textDim, fontFamily: FONT, fontSize: '13px', marginBottom: '24px' }}>Loading efficiency data…</div>
      ) : eff ? (
        <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap', marginBottom: '32px' }}>
          <StatCard label="Experiments"       value={eff.experiment_count}         sub="ELN entries logged" />
          <StatCard label="Active Scientists" value={eff.active_scientists}        sub="Distinct authors" />
          <StatCard label="Active Projects"   value={eff.active_projects}          sub="With activity" />
          <StatCard label="Avg Exp/Sci/Week"  value={eff.avg_exp_per_sci_per_week} sub="Trimmed mean" />
        </div>
      ) : null}

      <div style={{ background: C.ice, border: `1.5px solid ${C.border}`, borderLeft: `4px solid ${C.blue}`, borderRadius: '8px', padding: '14px 18px', fontFamily: FONT, fontSize: '13px', color: C.blue, lineHeight: '1.7', maxWidth: '700px' }}>
        <strong style={{ color: C.navy }}>Note:</strong> Efficiency metrics calculated live from ELNAnalytics
        using <code style={{ color: C.navy, background: 'rgba(0,11,54,0.06)', padding: '1px 5px', borderRadius: '3px' }}>created_date</code> on{' '}
        <code style={{ color: C.navy, background: 'rgba(0,11,54,0.06)', padding: '1px 5px', borderRadius: '3px' }}>eln_experiments</code>.
        Author attribution via <code style={{ color: C.navy, background: 'rgba(0,11,54,0.06)', padding: '1px 5px', borderRadius: '3px' }}>author</code> field — backfilled nightly at 02:15 IST by ELN_Patch_Author task.
      </div>
    </div>
  );
}

// ── Table header cell with sort ───────────────────────────────────────────────
function SortTh({ field, label, sortField, sortAsc, onSort }) {
  const active = sortField === field;
  return (
    <th onClick={() => onSort(field)} style={{
      padding: '10px 14px', textAlign: 'left', background: C.navy,
      color: active ? C.cyan : C.white,
      fontFamily: FONT, fontSize: '11px', fontWeight: 700,
      letterSpacing: '0.6px', cursor: 'pointer', userSelect: 'none',
      whiteSpace: 'nowrap', position: 'sticky', top: 0
    }}>
      {label}{active ? (sortAsc ? ' ↑' : ' ↓') : ''}
    </th>
  );
}

// ── Projects view ─────────────────────────────────────────────────────────────
function ProjectsView({ onSelectProject }) {
  const [projects, setProjects]   = useState([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);
  const [filter, setFilter]       = useState('');
  const [showGantt, setShowGantt] = useState(false);
  const [sortField, setSortField] = useState('project_code');
  const [sortAsc, setSortAsc]     = useState(true);
  const [generateReport, setGenerateReport] = useState({});
  const [toast, setToast]                   = useState(null);

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(null), 4000); };

  const triggerReport = async (e, projectCode) => {
    e.stopPropagation();
    setGenerateReport(s => ({ ...s, [projectCode]: 'generating' }));
    try {
      await apiFetch('/api/ai/report', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_code: projectCode, triggered_by: 'manual' }) });
      setGenerateReport(s => ({ ...s, [projectCode]: 'done' }));
      showToast(`Report generating for ${projectCode}`);
    } catch (err) {
      setGenerateReport(s => { const n = { ...s }; delete n[projectCode]; return n; });
      showToast(`Error: ${err.message}`);
    }
  };

  useEffect(() => {
    apiFetch('/api/projects').then(setProjects).catch(e => setError(e.message)).finally(() => setLoading(false));
  }, []);

  const toggleSort = f => { if (sortField === f) setSortAsc(a => !a); else { setSortField(f); setSortAsc(true); } };

  const filtered = projects
    .filter(p => !filter || [p.project_code, p.project_title, p.cas_number, p.generic_name].some(v => v?.toLowerCase().includes(filter.toLowerCase())))
    .sort((a, b) => { const va = a[sortField] ?? '', vb = b[sortField] ?? ''; return sortAsc ? String(va).localeCompare(String(vb)) : String(vb).localeCompare(String(va)); });

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: C.white }}>
      {toast && (
        <div style={{ position: 'fixed', bottom: '80px', right: '28px', background: C.navy, color: C.white, fontFamily: FONT, fontSize: '13px', fontWeight: 600, padding: '12px 20px', borderRadius: '8px', boxShadow: '0 4px 18px rgba(0,11,54,0.3)', zIndex: 9999, borderLeft: `4px solid ${C.cyan}`, maxWidth: '360px' }}>{toast}</div>
      )}
      <div style={{ padding: '24px 28px 0', borderBottom: `2px solid ${C.ice}`, paddingBottom: '16px' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h2 style={{ color: C.navy, fontFamily: FONT, fontSize: '22px', fontWeight: 800, margin: 0 }}>Projects</h2>
            <div style={{ color: C.textDim, fontFamily: FONT, fontSize: '13px', marginTop: '4px' }}>{projects.length} campaigns · click any row for experiments</div>
          </div>
          <input value={filter} onChange={e => setFilter(e.target.value)} placeholder="Filter by code, name, CAS…" style={{ background: C.ice, border: `1.5px solid ${C.border}`, borderRadius: '6px', padding: '8px 14px', color: C.blue, fontFamily: FONT, fontSize: '13px', width: '260px', outline: 'none' }} />
        </div>

        <button onClick={() => setShowGantt(s => !s)} style={{ marginTop: '14px', background: 'transparent', border: `1.5px solid ${C.border}`, color: C.blue, borderRadius: '6px', padding: '6px 14px', fontFamily: FONT, fontSize: '12px', cursor: 'pointer', fontWeight: 600 }}>
          {showGantt ? '▲' : '▼'} Project Timeline
        </button>
      </div>

      {showGantt && (
        <div style={{ background: C.ice, borderBottom: `1.5px solid ${C.border}`, padding: '16px 28px', maxHeight: '180px', overflowY: 'auto', flexShrink: 0 }}>
          {filtered.map((p, i) => {
            const barW = 20 + ((p.project_code?.charCodeAt(3) || 0) % 60);
            return (
              <div key={p.project_code} style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '6px' }}>
                <div style={{ width: '80px', color: C.navy, flexShrink: 0, fontFamily: FONT, fontSize: '11px', fontWeight: 700 }}>{p.project_code}</div>
                <div style={{ height: '12px', borderRadius: '3px', minWidth: '20px', width: `${barW}%`, background: i % 2 === 0 ? C.navy : C.blue, opacity: 0.8 }} />
                <div style={{ color: C.textDim, fontFamily: FONT, fontSize: '11px' }}>{p.project_title}</div>
              </div>
            );
          })}
        </div>
      )}

      {loading ? <div style={{ padding: '24px 28px', color: C.textDim, fontFamily: FONT }}>Loading projects…</div>
       : error ? <div style={{ padding: '24px 28px', color: C.danger, fontFamily: FONT }}>Error: {error}</div>
       : (
        <div style={{ flex: 1, overflowY: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: FONT, fontSize: '13px' }}>
            <thead>
              <tr>
                <SortTh field="project_code"   label="CODE"         sortField={sortField} sortAsc={sortAsc} onSort={toggleSort} />
                <SortTh field="project_title"  label="COMPOUND"     sortField={sortField} sortAsc={sortAsc} onSort={toggleSort} />
                <SortTh field="cas_number"     label="CAS"          sortField={sortField} sortAsc={sortAsc} onSort={toggleSort} />
                <SortTh field="generic_name"   label="GENERIC NAME" sortField={sortField} sortAsc={sortAsc} onSort={toggleSort} />
                <SortTh field="project_status" label="STATUS"       sortField={sortField} sortAsc={sortAsc} onSort={toggleSort} />
                <th style={{ padding: '10px 14px', background: C.navy, color: C.white, fontSize: '11px', fontWeight: 700, letterSpacing: '0.6px', position: 'sticky', top: 0 }}>REPORT</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p, i) => (
                <tr key={p.project_id || p.project_code}
                  onClick={() => onSelectProject(p)}
                  style={{ borderBottom: `1px solid ${C.ice}`, cursor: 'pointer', background: i % 2 === 0 ? C.white : C.ice }}
                  onMouseEnter={e => e.currentTarget.style.background = '#DEEBF7'}
                  onMouseLeave={e => e.currentTarget.style.background = i % 2 === 0 ? C.white : C.ice}
                >
                  <td style={{ padding: '11px 14px', color: C.navy, fontWeight: 700, fontFamily: 'monospace', fontSize: '12px' }}>{p.project_code}</td>
                  <td style={{ padding: '11px 14px', color: C.blue, fontWeight: 500 }}>{p.project_title || '—'}</td>
                  <td style={{ padding: '11px 14px', color: C.textDim, fontFamily: 'monospace', fontSize: '12px' }}>{p.cas_number || '—'}</td>
                  <td style={{ padding: '11px 14px', color: C.textDim }}>{p.generic_name || '—'}</td>
                  <td style={{ padding: '11px 14px' }}>
                    <span style={{ background: p.project_status === 1 ? C.navy : C.ice, color: p.project_status === 1 ? C.white : C.textDim, borderRadius: '10px', padding: '3px 12px', fontSize: '11px', fontWeight: 700 }}>
                      {p.project_status === 1 ? 'Active' : 'Closed'}
                    </span>
                  </td>
                  <td style={{ padding: '11px 14px' }} onClick={e => e.stopPropagation()}>
                    <button
                      onClick={e => triggerReport(e, p.project_code)}
                      disabled={generateReport[p.project_code] === 'generating'}
                      style={{ background: generateReport[p.project_code] === 'done' ? C.ice : C.navy, color: generateReport[p.project_code] === 'done' ? C.blue : C.white, border: 'none', borderRadius: '6px', padding: '5px 12px', fontSize: '11px', fontWeight: 700, cursor: generateReport[p.project_code] === 'generating' ? 'default' : 'pointer', fontFamily: FONT, whiteSpace: 'nowrap' }}
                    >
                      {generateReport[p.project_code] === 'generating' ? '…' : generateReport[p.project_code] === 'done' ? '✓ Report' : '⬒ Report'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// ── Project experiments view ──────────────────────────────────────────────────
function ProjectExperimentsView({ project, onBack, onSelectExperiment }) {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [filter, setFilter]   = useState('');
  const [page, setPage]       = useState(0);
  const PAGE_SIZE = 50;

  useEffect(() => {
    apiFetch('/api/ai/fetch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ project_code: project.project_code }) })
      .then(setData).catch(e => setError(e.message)).finally(() => setLoading(false));
  }, [project.project_code]);

  const experiments = data?.experiments || [];
  const filtered    = experiments.filter(e => !filter || [e.exp_number_full, e.title, e.author].some(v => v?.toLowerCase().includes(filter.toLowerCase())));
  const paged       = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const totalPages  = Math.ceil(filtered.length / PAGE_SIZE);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: C.white }}>
      <div style={{ padding: '24px 28px 16px', borderBottom: `2px solid ${C.ice}`, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '14px', flexWrap: 'wrap' }}>
          <button onClick={onBack} style={{ background: C.ice, border: `1.5px solid ${C.border}`, color: C.blue, borderRadius: '6px', padding: '6px 14px', fontFamily: FONT, fontSize: '12px', cursor: 'pointer', fontWeight: 600 }}>← Projects</button>
          <div>
            <h2 style={{ color: C.navy, fontFamily: FONT, fontSize: '20px', fontWeight: 800, margin: 0 }}>{project.project_code} — {data?.project?.project_title || project.project_title}</h2>
            <div style={{ color: C.textDim, fontFamily: FONT, fontSize: '12px', marginTop: '3px' }}>
              {data?.project?.cas_number && <span style={{ color: C.navy, fontFamily: 'monospace', fontWeight: 700, marginRight: '14px' }}>{data.project.cas_number}</span>}
              {experiments.length} experiments · click any row for detail
            </div>
          </div>
          <input value={filter} onChange={e => { setFilter(e.target.value); setPage(0); }} placeholder="Filter by exp no., title, author…" style={{ background: C.ice, border: `1.5px solid ${C.border}`, borderRadius: '6px', padding: '8px 14px', color: C.blue, fontFamily: FONT, fontSize: '13px', width: '260px', outline: 'none', marginLeft: 'auto' }} />
        </div>
      </div>

      {loading ? <div style={{ padding: '24px 28px', color: C.textDim, fontFamily: FONT }}>Loading experiments…</div>
       : error ? <div style={{ padding: '24px 28px', color: C.danger, fontFamily: FONT }}>Error: {error}</div>
       : (
        <>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: FONT, fontSize: '13px' }}>
              <thead>
                <tr style={{ background: C.navy }}>
                  {['EXP NUMBER','TITLE','AUTHOR','DATE','STATUS'].map(h => (
                    <th key={h} style={{ padding: '10px 14px', textAlign: 'left', color: C.white, fontSize: '11px', fontWeight: 700, letterSpacing: '0.6px', position: 'sticky', top: 0 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {paged.map((e, i) => (
                  <tr key={e.experiment_id}
                    onClick={() => onSelectExperiment(e)}
                    style={{ borderBottom: `1px solid ${C.ice}`, cursor: 'pointer', background: i % 2 === 0 ? C.white : C.ice }}
                    onMouseEnter={ev => ev.currentTarget.style.background = C.ice}
                    onMouseLeave={ev => ev.currentTarget.style.background = i % 2 === 0 ? C.white : C.ice}
                  >
                    <td style={{ padding: '10px 14px', color: C.navy, fontWeight: 700, fontFamily: 'monospace', fontSize: '12px' }}>{e.exp_number_full}</td>
                    <td style={{ padding: '10px 14px', color: C.blue, maxWidth: '300px' }}><div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.title || '—'}</div></td>
                    <td style={{ padding: '10px 14px', color: C.textDim }}>{e.author || '—'}</td>
                    <td style={{ padding: '10px 14px', color: C.textDim, whiteSpace: 'nowrap' }}>{e.created_date ? e.created_date.slice(0,10) : '—'}</td>
                    <td style={{ padding: '10px 14px' }}>
                      <span style={{ background: e.experiment_status === 2 ? C.navy : C.ice, color: e.experiment_status === 2 ? C.white : C.textDim, borderRadius: '10px', padding: '3px 12px', fontSize: '11px', fontWeight: 700 }}>
                        {e.experiment_status === 2 ? 'DONE' : e.experiment_status === 1 ? 'ACTIVE' : e.experiment_status || '—'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {totalPages > 1 && (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', padding: '12px 28px', borderTop: `1px solid ${C.ice}`, flexShrink: 0, background: C.white }}>
              <button disabled={page===0} onClick={() => setPage(p=>p-1)} style={{ background: C.ice, border: `1.5px solid ${C.border}`, color: C.blue, borderRadius: '6px', padding: '5px 14px', cursor: page===0?'default':'pointer', fontFamily: FONT, fontSize: '12px', fontWeight: 600 }}>← Prev</button>
              <span style={{ color: C.textDim, fontFamily: FONT, fontSize: '12px' }}>Page {page+1} of {totalPages} · {filtered.length} results</span>
              <button disabled={page>=totalPages-1} onClick={() => setPage(p=>p+1)} style={{ background: C.ice, border: `1.5px solid ${C.border}`, color: C.blue, borderRadius: '6px', padding: '5px 14px', cursor: page>=totalPages-1?'default':'pointer', fontFamily: FONT, fontSize: '12px', fontWeight: 600 }}>Next →</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Experiment detail panel ───────────────────────────────────────────────────
function ExperimentDetailPanel({ experiment, onClose }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('materials');

  useEffect(() => {
    apiFetch(`/api/experiments/${experiment.experiment_id}`)
      .then(setDetail).catch(() => setDetail(null)).finally(() => setLoading(false));
  }, [experiment.experiment_id]);

  const tabs = ['materials','products','procedure','tlc'];

  return (
    <div style={{ position: 'fixed', top: 0, right: 0, width: '580px', height: '100vh', background: C.white, borderLeft: `2px solid ${C.border}`, boxShadow: '-8px 0 32px rgba(0,11,54,0.15)', display: 'flex', flexDirection: 'column', zIndex: 1000, fontFamily: FONT }}>
      {/* Header */}
      <div style={{ padding: '18px 22px', borderBottom: `2px solid ${C.ice}`, background: C.navy, flexShrink: 0 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <div style={{ color: C.cyan, fontSize: '10px', letterSpacing: '1.2px', fontWeight: 600, marginBottom: '5px' }}>EXPERIMENT DETAIL</div>
            <div style={{ color: C.white, fontWeight: 800, fontSize: '15px', fontFamily: 'monospace' }}>{experiment.exp_number_full}</div>
            <div style={{ color: 'rgba(157,209,241,0.8)', fontSize: '12px', marginTop: '3px', fontWeight: 500 }}>{experiment.title}</div>
          </div>
          <button onClick={onClose} style={{ background: 'rgba(157,209,241,0.15)', border: `1px solid rgba(157,209,241,0.3)`, color: C.cyan, fontSize: '18px', cursor: 'pointer', lineHeight: 1, padding: '4px 8px', borderRadius: '4px' }}>×</button>
        </div>
        {detail?.objective && (
          <div style={{ marginTop: '12px', background: 'rgba(157,209,241,0.1)', border: `1px solid rgba(157,209,241,0.3)`, borderLeft: `3px solid ${C.cyan}`, borderRadius: '4px', padding: '8px 12px', fontSize: '12px', color: C.cyan, lineHeight: '1.5' }}>
            <strong>Objective:</strong> {detail.objective}
          </div>
        )}
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', borderBottom: `2px solid ${C.ice}`, flexShrink: 0, background: C.white }}>
        {tabs.map(t => (
          <button key={t} onClick={() => setTab(t)} style={{ background: 'transparent', border: 'none', borderBottom: `3px solid ${tab===t?C.navy:'transparent'}`, color: tab===t?C.navy:C.textDim, padding: '11px 18px', fontSize: '12px', cursor: 'pointer', fontWeight: tab===t?700:500, textTransform: 'uppercase', letterSpacing: '0.5px', fontFamily: FONT, transition: 'all 0.15s' }}>{t}</button>
        ))}
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '18px 22px' }}>
        {loading ? <div style={{ color: C.textDim }}>Loading…</div>
         : !detail ? <div style={{ color: C.danger }}>Could not load detail.</div>
         : (
          <>
            {tab === 'materials' && (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                <thead><tr style={{ background: C.navy }}>{['NAME','CAS','QTY','MOLES','RATIO','KSM'].map(h=><th key={h} style={{padding:'7px 10px',color:C.white,textAlign:'left',fontSize:'10px',fontWeight:700,letterSpacing:'0.5px'}}>{h}</th>)}</tr></thead>
                <tbody>{(detail.materials||[]).map((m,i)=>(
                  <tr key={i} style={{borderBottom:`1px solid ${C.ice}`,background:i%2===0?C.white:C.ice}}>
                    <td style={{padding:'8px 10px',color:C.blue,fontWeight:500}}>{m.raw_material_name}</td>
                    <td style={{padding:'8px 10px',color:C.textDim,fontFamily:'monospace',fontSize:'11px'}}>{m.cas_number||'—'}</td>
                    <td style={{padding:'8px 10px',color:C.textDim}}>{m.quantity||'—'}</td>
                    <td style={{padding:'8px 10px',color:C.textDim}}>{m.moles||'—'}</td>
                    <td style={{padding:'8px 10px',color:C.textDim}}>{m.ratio||'—'}</td>
                    <td style={{padding:'8px 10px'}}>{m.is_limiting_agent?<span style={{background:C.navy,color:C.white,borderRadius:'8px',padding:'2px 8px',fontSize:'10px',fontWeight:700}}>KSM</span>:''}</td>
                  </tr>
                ))}</tbody>
              </table>
            )}
            {tab === 'products' && (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
                <thead><tr style={{ background: C.navy }}>{['NAME','DRY WT','CRUDE YIELD','PURITY','E-FACTOR'].map(h=><th key={h} style={{padding:'7px 10px',color:C.white,textAlign:'left',fontSize:'10px',fontWeight:700,letterSpacing:'0.5px'}}>{h}</th>)}</tr></thead>
                <tbody>{(detail.products||[]).map((p,i)=>(
                  <tr key={i} style={{borderBottom:`1px solid ${C.ice}`,background:i%2===0?C.white:C.ice}}>
                    <td style={{padding:'8px 10px',color:C.blue,fontWeight:500}}>{p.product_name}</td>
                    <td style={{padding:'8px 10px',color:C.textDim}}>{p.dry_wt?`${p.dry_wt} g`:'—'}</td>
                    <td style={{padding:'8px 10px',color:C.textDim}}>{p.crude_yield?`${p.crude_yield}%`:'—'}</td>
                    <td style={{padding:'8px 10px',color:C.textDim}}>{p.purity?`${p.purity}%`:'—'}</td>
                    <td style={{padding:'8px 10px',color:C.textDim}}>{p.e_factor_actual||'—'}</td>
                  </tr>
                ))}</tbody>
              </table>
            )}
            {tab === 'procedure' && (
              <div>{(detail.procedure||[]).map((s,i)=>(
                <div key={i} style={{marginBottom:'10px',padding:'12px 14px',background:C.ice,borderRadius:'6px',border:`1px solid ${C.border}`,fontSize:'13px',color:C.blue,lineHeight:'1.6'}}>
                  <div style={{color:C.navy,fontSize:'10px',fontWeight:700,letterSpacing:'0.5px',marginBottom:'5px'}}>STEP {s.step_order||i+1}{s.operation?` — ${s.operation}`:''}</div>
                  {s.observations && <div>{s.observations}</div>}
                  {(s.temperature||s.time_value||s.quantity) && (
                    <div style={{display:'flex',gap:'16px',marginTop:'6px',fontSize:'11px',color:C.textDim}}>
                      {s.temperature && <span>🌡 {s.temperature}</span>}
                      {s.time_value  && <span>⏱ {s.time_value}</span>}
                      {s.quantity    && <span>⚖ {s.quantity}</span>}
                    </div>
                  )}
                </div>
              ))}</div>
            )}
            {tab === 'tlc' && (
              <div>{(detail.tlc||[]).map((t,i)=>(
                <div key={i} style={{marginBottom:'12px',padding:'12px 14px',background:C.ice,borderRadius:'6px',border:`1px solid ${C.border}`}}>
                  <div style={{color:C.navy,fontWeight:700,fontSize:'13px',marginBottom:'6px'}}>{t.plate_title||`Plate ${i+1}`}</div>
                  {t.plate_notes && <div style={{color:C.textDim,fontSize:'12px',marginBottom:'8px'}}>{t.plate_notes}</div>}
                  <div style={{display:'flex',gap:'12px',flexWrap:'wrap'}}>
                    {[['A',t.spot_a_notes,t.rf1],['B',t.spot_b_notes,t.rf2],['C',t.spot_c_notes,t.rf3],['D',t.spot_d_notes,t.rf4]]
                      .filter(([,notes,rf]) => notes || rf)
                      .map(([label,notes,rf]) => (
                        <div key={label} style={{background:C.white,border:`1px solid ${C.border}`,borderRadius:'6px',padding:'8px 12px',minWidth:'80px'}}>
                          <div style={{color:C.navy,fontWeight:700,fontSize:'11px'}}>Spot {label}</div>
                          {rf && <div style={{color:C.blue,fontWeight:600,fontSize:'14px',margin:'3px 0'}}>Rf {rf}</div>}
                          {notes && <div style={{color:C.textDim,fontSize:'11px'}}>{notes}</div>}
                        </div>
                      ))
                    }
                  </div>
                </div>
              ))}</div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

// ── Experiments view ──────────────────────────────────────────────────────────
function ExperimentsView({ onSelectExperiment }) {
  const [experiments, setExperiments] = useState([]);
  const [loading, setLoading]         = useState(true);
  const [filter, setFilter]           = useState('');
  const [page, setPage]               = useState(0);
  const PAGE_SIZE = 50;

  useEffect(() => {
    apiFetch('/api/experiments?limit=500')
      .then(data => setExperiments(Array.isArray(data) ? data : data.experiments || []))
      .catch(() => setExperiments([]))
      .finally(() => setLoading(false));
  }, []);

  const filtered   = experiments.filter(e => !filter || [e.exp_number_full, e.title, e.author].some(v => v?.toLowerCase().includes(filter.toLowerCase())));
  const paged      = filtered.slice(page * PAGE_SIZE, (page+1) * PAGE_SIZE);
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: C.white }}>
      <div style={{ padding: '24px 28px 16px', borderBottom: `2px solid ${C.ice}`, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h2 style={{ color: C.navy, fontFamily: FONT, fontSize: '22px', fontWeight: 800, margin: 0 }}>Experiments</h2>
            <div style={{ color: C.textDim, fontFamily: FONT, fontSize: '13px', marginTop: '4px' }}>Recent ELN entries · click any row for detail</div>
          </div>
          <input value={filter} onChange={e => { setFilter(e.target.value); setPage(0); }} placeholder="Filter by exp no., title, author…" style={{ background: C.ice, border: `1.5px solid ${C.border}`, borderRadius: '6px', padding: '8px 14px', color: C.blue, fontFamily: FONT, fontSize: '13px', width: '260px', outline: 'none' }} />
        </div>
      </div>

      {loading ? <div style={{ padding: '24px 28px', color: C.textDim, fontFamily: FONT }}>Loading…</div> : (
        <>
          <div style={{ flex: 1, overflowY: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: FONT, fontSize: '13px' }}>
              <thead>
                <tr style={{ background: C.navy }}>
                  {['EXP NUMBER','TITLE','AUTHOR','DATE','STATUS'].map(h=>(
                    <th key={h} style={{ padding: '10px 14px', textAlign: 'left', color: C.white, fontSize: '11px', fontWeight: 700, letterSpacing: '0.6px', position: 'sticky', top: 0 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {paged.map((e, i) => (
                  <tr key={e.experiment_id}
                    onClick={() => onSelectExperiment(e)}
                    style={{ borderBottom: `1px solid ${C.ice}`, cursor: 'pointer', background: i%2===0?C.white:C.ice }}
                    onMouseEnter={ev => ev.currentTarget.style.background = C.ice}
                    onMouseLeave={ev => ev.currentTarget.style.background = i%2===0?C.white:C.ice}
                  >
                    <td style={{ padding: '10px 14px', color: C.navy, fontWeight: 700, fontFamily: 'monospace', fontSize: '12px' }}>{e.exp_number_full}</td>
                    <td style={{ padding: '10px 14px', color: C.blue, maxWidth: '320px' }}><div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.title||'—'}</div></td>
                    <td style={{ padding: '10px 14px', color: C.textDim }}>{e.author||'—'}</td>
                    <td style={{ padding: '10px 14px', color: C.textDim, whiteSpace: 'nowrap' }}>{e.created_date?e.created_date.slice(0,10):'—'}</td>
                    <td style={{ padding: '10px 14px' }}>
                      <span style={{ background: e.experiment_status===2?C.navy:C.ice, color: e.experiment_status===2?C.white:C.textDim, borderRadius: '10px', padding: '3px 12px', fontSize: '11px', fontWeight: 700 }}>
                        {e.experiment_status===2?'DONE':e.experiment_status===1?'ACTIVE':e.experiment_status||'—'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {totalPages > 1 && (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', padding: '12px 28px', borderTop: `1px solid ${C.ice}`, flexShrink: 0, background: C.white }}>
              <button disabled={page===0} onClick={() => setPage(p=>p-1)} style={{ background: C.ice, border: `1.5px solid ${C.border}`, color: C.blue, borderRadius: '6px', padding: '5px 14px', cursor: page===0?'default':'pointer', fontFamily: FONT, fontSize: '12px', fontWeight: 600 }}>← Prev</button>
              <span style={{ color: C.textDim, fontFamily: FONT, fontSize: '12px' }}>Page {page+1} of {totalPages} · {filtered.length} results</span>
              <button disabled={page>=totalPages-1} onClick={() => setPage(p=>p+1)} style={{ background: C.ice, border: `1.5px solid ${C.border}`, color: C.blue, borderRadius: '6px', padding: '5px 14px', cursor: page>=totalPages-1?'default':'pointer', fontFamily: FONT, fontSize: '12px', fontWeight: 600 }}>Next →</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ── Reports view ─────────────────────────────────────────────────────────────
function ReportsView() {
  const [reports, setReports]       = useState([]);
  const [loading, setLoading]       = useState(true);
  const [filter, setFilter]         = useState('');
  const [showGenForm, setShowGenForm] = useState(false);
  const [genCode, setGenCode]       = useState('');
  const [genBusy, setGenBusy]       = useState(false);
  const [toast, setToast]           = useState(null);

  const reload = () =>
    apiFetch('/api/ai/reports')
      .then(data => setReports(data.reports || []))
      .catch(() => setReports([]))
      .finally(() => setLoading(false));

  useEffect(() => { reload(); }, []);

  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(null), 4000); };

  const submitGenerate = async () => {
    if (!genCode.trim()) return;
    setGenBusy(true);
    try {
      await apiFetch('/api/ai/report', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_code: genCode.trim().toUpperCase(), triggered_by: 'manual' }),
      });
      showToast(`Generating report for ${genCode.trim().toUpperCase()}…`);
      setShowGenForm(false);
      setGenCode('');
      setTimeout(reload, 3000);
    } catch (e) {
      showToast(`Error: ${e.message}`);
    } finally {
      setGenBusy(false);
    }
  };

  const STATUS_STYLE = {
    complete: { background: C.cyan,    color: C.navy   },
    failed:   { background: C.danger,  color: C.white  },
    pending:  { background: C.ice,     color: C.textDim },
  };

  const filtered = reports.filter(r =>
    !filter ||
    [r.project_code, r.generated_by, r.topic].some(v => v?.toLowerCase().includes(filter.toLowerCase()))
  );

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', background: C.white }}>
      {toast && (
        <div style={{ position: 'fixed', bottom: '80px', right: '28px', background: C.navy, color: C.white, fontFamily: FONT, fontSize: '13px', fontWeight: 600, padding: '12px 20px', borderRadius: '8px', boxShadow: '0 4px 18px rgba(0,11,54,0.3)', zIndex: 9999, borderLeft: `4px solid ${C.cyan}`, maxWidth: '360px' }}>{toast}</div>
      )}
      <div style={{ padding: '24px 28px 16px', borderBottom: `2px solid ${C.ice}`, flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h2 style={{ color: C.navy, fontFamily: FONT, fontSize: '22px', fontWeight: 800, margin: 0 }}>Reports</h2>
            <div style={{ color: C.textDim, fontFamily: FONT, fontSize: '13px', marginTop: '4px' }}>{reports.length} reports · analysis & meeting documents</div>
          </div>
          <div style={{ display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
            <input value={filter} onChange={e => setFilter(e.target.value)} placeholder="Filter by project code" style={{ background: C.ice, border: `1.5px solid ${C.border}`, borderRadius: '6px', padding: '8px 14px', color: C.blue, fontFamily: FONT, fontSize: '13px', width: '200px', outline: 'none' }} />
            {showGenForm ? (
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                <input autoFocus value={genCode} onChange={e => setGenCode(e.target.value.toUpperCase())} onKeyDown={e => e.key === 'Enter' && submitGenerate()} placeholder="Project code…" style={{ background: C.white, border: `1.5px solid ${C.border}`, borderRadius: '6px', padding: '8px 12px', color: C.blue, fontFamily: 'monospace', fontSize: '13px', width: '160px', outline: 'none' }} />
                <button onClick={submitGenerate} disabled={genBusy || !genCode.trim()} style={{ background: C.navy, border: 'none', color: C.white, borderRadius: '6px', padding: '8px 14px', fontFamily: FONT, fontSize: '12px', fontWeight: 700, cursor: genBusy ? 'default' : 'pointer' }}>{genBusy ? '…' : 'Go'}</button>
                <button onClick={() => { setShowGenForm(false); setGenCode(''); }} style={{ background: 'transparent', border: `1.5px solid ${C.border}`, color: C.textDim, borderRadius: '6px', padding: '8px 12px', fontFamily: FONT, fontSize: '12px', cursor: 'pointer' }}>✕</button>
              </div>
            ) : (
              <button onClick={() => setShowGenForm(true)} style={{ background: C.navy, border: 'none', color: C.white, borderRadius: '6px', padding: '8px 16px', fontFamily: FONT, fontSize: '13px', fontWeight: 700, cursor: 'pointer', whiteSpace: 'nowrap' }}>⬒ Generate Report</button>
            )}
          </div>
        </div>
      </div>
      {loading ? <div style={{ padding: '24px 28px', color: C.textDim, fontFamily: FONT }}>Loading reports…</div> : (
        <div style={{ flex: 1, overflowY: 'auto' }}>
          {filtered.length === 0 ? (
            <div style={{ padding: '32px 28px', color: C.textDim, fontFamily: FONT, fontSize: '14px' }}>
              No reports yet. Click <strong>⬒ Generate Report</strong> above or use the <strong>⬒ Report</strong> button on any project row.
            </div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: FONT, fontSize: '13px' }}>
              <thead>
                <tr style={{ background: C.navy }}>
                  {['PROJECT', 'TYPE', 'DATE', 'GENERATED BY', 'STATUS', 'DOWNLOAD'].map(h => (
                    <th key={h} style={{ padding: '10px 14px', textAlign: 'left', color: C.white, fontSize: '11px', fontWeight: 700, letterSpacing: '0.6px', position: 'sticky', top: 0 }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((r, i) => {
                  const st = STATUS_STYLE[r.status] || STATUS_STYLE.pending;
                  return (
                    <tr key={r.report_id} style={{ borderBottom: `1px solid ${C.ice}`, background: i % 2 === 0 ? C.white : C.ice }}>
                      <td style={{ padding: '11px 14px', color: C.navy, fontWeight: 700, fontFamily: 'monospace', fontSize: '12px' }}>{r.project_code || '—'}</td>
                      <td style={{ padding: '11px 14px', color: C.textDim }}>{r.topic ? 'Meeting' : 'Analysis'}</td>
                      <td style={{ padding: '11px 14px', color: C.textDim, whiteSpace: 'nowrap' }}>{r.generated_date ? r.generated_date.slice(0, 10) : '—'}</td>
                      <td style={{ padding: '11px 14px', color: C.textDim }}>{r.generated_by || r.author || '—'}</td>
                      <td style={{ padding: '11px 14px' }}>
                        <span style={{ ...st, borderRadius: '10px', padding: '3px 12px', fontSize: '11px', fontWeight: 700 }}>{r.status || 'pending'}</span>
                      </td>
                      <td style={{ padding: '11px 14px' }}>
                        {r.blob_url && r.status === 'complete'
                          ? <a href={r.blob_url} target="_blank" rel="noreferrer" style={{ color: C.blue, fontWeight: 600, fontSize: '12px', textDecoration: 'none' }}>↓ Download</a>
                          : <span style={{ color: C.textSub, fontSize: '12px' }}>—</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

// ── Meeting Copilot view ──────────────────────────────────────────────────────
function MeetingCopilotView({ user }) {
  const [isRecording, setIsRecording]         = useState(false);
  const [transcript, setTranscript]           = useState('');
  const [interimTranscript, setInterimTranscript] = useState('');
  const [projectCode, setProjectCode]         = useState('');
  const [audioFile, setAudioFile]             = useState(null);
  const [isGenerating, setIsGenerating]       = useState(false);
  const [reportUrl, setReportUrl]             = useState(null);
  const [reportMeta, setReportMeta]           = useState(null);
  const [error, setError]                     = useState(null);
  const recogRef                              = useRef(null);
  const transcriptRef                         = useRef(null);

  // Auto-scroll transcript
  useEffect(() => {
    if (transcriptRef.current) transcriptRef.current.scrollTop = transcriptRef.current.scrollHeight;
  }, [transcript, interimTranscript]);

  const startRecording = () => {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { setError('Speech recognition not supported in this browser. Use Chrome or Edge.'); return; }
    setError(null);
    const recog = new SR();
    recog.lang = 'en-IN';
    recog.continuous = true;
    recog.interimResults = true;
    recog.onresult = (event) => {
      let finalText = '', interimText = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) finalText += event.results[i][0].transcript + ' ';
        else interimText += event.results[i][0].transcript;
      }
      if (finalText) setTranscript(t => t + finalText);
      setInterimTranscript(interimText);
    };
    recog.onerror  = (e) => { setError(`Mic error: ${e.error}`); setIsRecording(false); };
    recog.onend    = () => { setIsRecording(false); setInterimTranscript(''); };
    recog.start();
    recogRef.current = recog;
    setIsRecording(true);
  };

  const stopRecording = () => {
    recogRef.current?.stop();
    setIsRecording(false);
    setInterimTranscript('');
  };

  const clearAll = () => {
    stopRecording();
    setTranscript(''); setInterimTranscript(''); setProjectCode('');
    setAudioFile(null); setReportUrl(null); setReportMeta(null); setError(null);
  };

  const generateReport = async () => {
    if (!transcript.trim() && !audioFile) {
      setError('Record or upload audio, or paste a transcript first.');
      return;
    }
    setIsGenerating(true); setError(null); setReportUrl(null);
    try {
      let finalTranscript = transcript;
      if (audioFile && !transcript.trim()) {
        const fd = new FormData();
        fd.append('audio', audioFile);
        const res = await fetch(`${API_BASE}/api/ai/speech`, { method: 'POST', body: fd });
        if (!res.ok) throw new Error(`Transcription failed (HTTP ${res.status})`);
        const data = await res.json();
        finalTranscript = data.transcript;
        setTranscript(finalTranscript);
      }
      const data = await apiFetch('/api/ai/meeting', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transcript: finalTranscript, project_code: projectCode || null, author: user?.userDetails || '' }),
      });
      setReportUrl(data.blob_url);
      setReportMeta(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div style={{ flex: 1, overflowY: 'auto', padding: '0 28px 28px', background: C.white }}>
      <PageHeader title="Meeting Copilot" sub="Speak your R&D meeting — get a chemistry analysis report" />

      <div style={{ display: 'flex', gap: '28px', flexWrap: 'wrap', maxWidth: '960px' }}>

        {/* LEFT — recording + live transcript */}
        <div style={{ flex: 1, minWidth: '340px' }}>
          {/* Mic button */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px', marginBottom: '22px' }}>
            <button
              onClick={isRecording ? stopRecording : startRecording}
              style={{
                width: '80px', height: '80px', borderRadius: '50%',
                background: isRecording ? '#c0392b' : C.navy,
                border: `3px solid ${isRecording ? '#e74c3c' : C.cyan}`,
                color: C.white,
                fontSize: '28px', cursor: 'pointer',
                boxShadow: isRecording ? '0 0 0 10px rgba(192,57,43,0.2)' : '0 4px 18px rgba(0,11,54,0.25)',
                transition: 'all 0.2s',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
              }}
            >
              {isRecording ? '⏹' : '⏺'}
            </button>
            <div style={{ color: isRecording ? '#c0392b' : C.textDim, fontFamily: FONT, fontSize: '12px', fontWeight: 600 }}>
              {isRecording ? '● Recording — click to stop' : 'Click to record (Chrome/Edge)'}
            </div>
          </div>

          {/* Upload audio */}
          <div style={{ color: C.blue, fontFamily: FONT, fontSize: '11px', fontWeight: 700, letterSpacing: '1px', marginBottom: '6px' }}>OR UPLOAD AUDIO FILE</div>
          <label style={{ display: 'block', background: C.ice, border: `1.5px dashed ${C.border}`, borderRadius: '6px', padding: '10px 14px', cursor: 'pointer', textAlign: 'center', fontFamily: FONT, fontSize: '12px', color: C.textDim, marginBottom: '18px' }}>
            <input type="file" accept=".wav,.webm,.mp4,.m4a,.ogg,audio/*" onChange={e => setAudioFile(e.target.files[0])} style={{ display: 'none' }} />
            {audioFile ? <span style={{ color: C.blue, fontWeight: 600 }}>{audioFile.name}</span> : '📎 .wav  .webm  .mp4  .m4a  .ogg'}
          </label>

          {/* Live transcript */}
          <div style={{ color: C.blue, fontFamily: FONT, fontSize: '11px', fontWeight: 700, letterSpacing: '1px', marginBottom: '6px' }}>TRANSCRIPT <span style={{ fontWeight: 400, color: C.textSub }}>({transcript.length} chars)</span></div>
          <div
            ref={transcriptRef}
            style={{ background: C.ice, border: `1.5px solid ${C.border}`, borderRadius: '8px', padding: '12px 14px', minHeight: '200px', maxHeight: '400px', overflowY: 'auto', fontFamily: FONT, fontSize: '13px', lineHeight: '1.7', color: C.blue }}
          >
            {transcript && <span style={{ color: C.navy }}>{transcript}</span>}
            {interimTranscript && <span style={{ color: C.textDim, fontStyle: 'italic' }}>{interimTranscript}</span>}
            {!transcript && !interimTranscript && (
              <span style={{ color: C.textSub, fontStyle: 'italic' }}>Transcript appears here as you speak, or paste directly…</span>
            )}
          </div>
          {/* Allow manual edit */}
          <textarea
            value={transcript}
            onChange={e => setTranscript(e.target.value)}
            placeholder="Paste or edit transcript here…"
            rows={3}
            style={{ width: '100%', boxSizing: 'border-box', marginTop: '8px', background: C.white, border: `1.5px solid ${C.borderMid}`, borderRadius: '6px', padding: '10px 14px', color: C.blue, fontFamily: FONT, fontSize: '12px', lineHeight: '1.5', resize: 'vertical', outline: 'none' }}
          />
        </div>

        {/* RIGHT — config + generate */}
        <div style={{ width: '240px', flexShrink: 0 }}>
          <div style={{ color: C.blue, fontFamily: FONT, fontSize: '11px', fontWeight: 700, letterSpacing: '1px', marginBottom: '6px' }}>PROJECT CODE (optional)</div>
          <input
            value={projectCode}
            onChange={e => setProjectCode(e.target.value.toUpperCase())}
            placeholder="e.g. P013E00"
            style={{ width: '100%', boxSizing: 'border-box', background: C.ice, border: `1.5px solid ${C.border}`, borderRadius: '6px', padding: '8px 14px', color: C.blue, fontFamily: 'monospace', fontSize: '13px', outline: 'none', marginBottom: '20px' }}
          />

          <button
            onClick={generateReport}
            disabled={isGenerating || (!transcript.trim() && !audioFile)}
            style={{
              width: '100%', background: isGenerating ? C.ice : C.navy,
              border: 'none', color: isGenerating ? C.textDim : C.white,
              borderRadius: '8px', padding: '13px', fontFamily: FONT, fontSize: '14px',
              fontWeight: 700, cursor: isGenerating || (!transcript.trim() && !audioFile) ? 'default' : 'pointer',
              boxShadow: isGenerating ? 'none' : '0 3px 12px rgba(0,11,54,0.2)',
              transition: 'all 0.15s', marginBottom: '10px',
            }}
          >
            {isGenerating ? '⏳ Generating…' : '⚗ Generate Report'}
          </button>

          <button
            onClick={clearAll}
            style={{ width: '100%', background: 'transparent', border: `1.5px solid ${C.border}`, color: C.textDim, borderRadius: '8px', padding: '10px', fontFamily: FONT, fontSize: '13px', fontWeight: 600, cursor: 'pointer', marginBottom: '20px' }}
          >
            Clear
          </button>

          {error && (
            <div style={{ background: '#fdf2f2', border: `1.5px solid #e57373`, borderRadius: '6px', padding: '10px 14px', color: C.danger, fontFamily: FONT, fontSize: '12px', marginBottom: '14px' }}>{error}</div>
          )}

          {reportUrl && reportMeta && (
            <div style={{ background: C.ice, border: `1.5px solid ${C.border}`, borderLeft: `4px solid ${C.navy}`, borderRadius: '8px', padding: '14px 16px', fontFamily: FONT, marginBottom: '20px' }}>
              <div style={{ color: C.navy, fontSize: '12px', fontWeight: 700, marginBottom: '8px' }}>Report ready</div>
              <div style={{ color: C.textDim, fontSize: '11px', marginBottom: '4px' }}>{reportMeta.topic}</div>
              <div style={{ color: C.textSub, fontSize: '11px', marginBottom: '12px' }}>{reportMeta.generated_date}</div>
              <a href={reportUrl} target="_blank" rel="noreferrer" style={{ display: 'inline-block', background: C.navy, color: C.white, borderRadius: '6px', padding: '8px 16px', fontSize: '12px', fontWeight: 700, textDecoration: 'none', marginRight: '8px' }}>
                ↓ Download
              </a>
              <a href={reportUrl} target="_blank" rel="noreferrer" style={{ display: 'inline-block', background: 'transparent', border: `1.5px solid ${C.border}`, color: C.blue, borderRadius: '6px', padding: '8px 14px', fontSize: '12px', fontWeight: 600, textDecoration: 'none' }}>
                View Report
              </a>
            </div>
          )}

          {/* Instructions */}
          <div style={{ background: C.ice, border: `1.5px solid ${C.border}`, borderRadius: '8px', padding: '14px 16px', fontFamily: FONT, fontSize: '12px', color: C.blue, lineHeight: '1.7' }}>
            <div style={{ color: C.navy, fontWeight: 700, marginBottom: '6px', fontSize: '11px', letterSpacing: '0.5px' }}>HOW TO USE</div>
            Start recording and speak naturally. English, Hindi, or Hinglish all work. Describe the problem, hypotheses, and what experiments you want to run. Stop recording when done, then click Generate Report.
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Root App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [user, setUser]               = useState(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [view, setView]               = useState('summary');
  const [selectedProject, setSelectedProject]       = useState(null);
  const [selectedExperiment, setSelectedExperiment] = useState(null);
  const [showChat, setShowChat]       = useState(false);

  useEffect(() => { getSWAUser().then(u => { setUser(u); setAuthChecked(true); }); }, []);
  useEffect(() => { if (authChecked && !user) window.location.href = '/.auth/login/aad'; }, [authChecked, user]);

  const handleNav = useCallback((key) => {
    if (key === 'askai') { setShowChat(prev => !prev); return; }
    setShowChat(false);
    setView(key);
    if (key !== 'project_experiments') { setSelectedProject(null); }
    setSelectedExperiment(null);
  }, []);

  if (!authChecked) return <div style={{ background: C.white, minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.blue, fontFamily: FONT, fontSize: '14px' }}>Authenticating…</div>;
  if (!user) return null;

  const activeNavKey = showChat ? 'askai' : (view === 'project_experiments' ? 'projects' : view);


  return (
    <div style={{ display: 'flex', minHeight: '100vh', background: C.white, fontFamily: FONT }}>
      <Sidebar active={activeNavKey} onNav={handleNav} user={user} />

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', position: 'relative' }}>
        {view === 'summary'             && <SummaryView />}
        {view === 'projects'            && <ProjectsView onSelectProject={p => { setSelectedProject(p); setView('project_experiments'); }} />}
        {view === 'project_experiments' && selectedProject && <ProjectExperimentsView project={selectedProject} onBack={() => { setView('projects'); setSelectedProject(null); }} onSelectExperiment={setSelectedExperiment} />}
        {view === 'experiments'         && <ExperimentsView onSelectExperiment={setSelectedExperiment} />}
        {view === 'reports'             && <ReportsView />}
        {view === 'meeting'             && <MeetingCopilotView user={user} />}
        {selectedExperiment && <ExperimentDetailPanel experiment={selectedExperiment} onClose={() => setSelectedExperiment(null)} />}
      </div>

      {/* Ask AI button */}
      {!showChat && (
        <button onClick={() => setShowChat(true)} style={{ position: 'fixed', bottom: '28px', right: '28px', background: C.navy, border: `2px solid ${C.cyan}`, color: C.white, borderRadius: '28px', padding: '13px 22px', fontFamily: FONT, fontSize: '14px', fontWeight: 700, cursor: 'pointer', boxShadow: '0 4px 20px rgba(0,11,54,0.3)', display: 'flex', alignItems: 'center', gap: '8px', zIndex: 999, letterSpacing: '0.3px' }}>
          ⚗ Ask AI
        </button>
      )}

      {showChat && <AIChatPanel onClose={() => setShowChat(false)} />}
    </div>
  );
}
