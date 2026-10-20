'use strict';

const I18N = {
  en: {
    dataBy: 'Data: Poly Tick Tape ↗', range: 'Date range (UTC)', sample: 'Free sample hour (2026-09-20 04:00–05:00)',
    c1: 'Odds', favorite: 'Buy the favorite', underdog: 'Buy the underdog', priceFrom: 'price',
    c2: 'BTC move vs price to beat', with: 'toward my side', against: 'against my side', any: 'either way',
    plainPrice: 'Price', moveHint: 'Max 0 = no limit.', c3: 'Window time (seconds in)',
    stake: 'Stake $', slip: 'Slippage', ticks: 'tick', run: 'Run backtest',
    s1: 'Chainlink data', s2: 'Polymarket odds', s3: 'Backtest', empty: 'Set the three conditions and press Run.',
    trades: 'Trades', csv: 'Download CSV',
    buyTitle: 'Chainlink data needed',
    buyWhy: 'This backtest runs on per-second Chainlink BTC/USD price and TWAP60, the data Polymarket settles these rounds on. Get it from Poly Tick Tape: $2.99 for a month of history, or $5.99/month for a rolling 60 days.',
    missing: 'Missing files', buyBtn: 'Get the data', trySample: 'Try the free sample hour',
    haveKey: 'Already bought? Paste your API key to download into ./data:', download: 'Download',
    found: (n, a, b) => `${n} days in ./data (${a} to ${b})`, none: 'No Chainlink data in ./data yet.',
    getData: 'Get data', loading: 'loading…', rounds: (d, t) => `${d}/${t} rounds`,
    pnl: 'Net P&L', roi: 'ROI per $', nTrades: 'Trades', winRate: 'Win rate', avgCost: 'avg price paid',
    dd: 'Max drawdown', fees: 'Fees', of: (n) => `of ${n} rounds`, staked: (x) => `${x} staked`,
    settle: (a, c) => `TWAP60 settlement matches Polymarket on ${a.toLocaleString()} of ${c.toLocaleString()} rounds.`,
    noTrade: 'No trade:', reasons: { noChainlink: 'no Chainlink', noOdds: 'no odds', time: 'no print in time', odds: 'odds', move: 'BTC move', btcData: 'BTC not yet seen', tooExpensive: '≥ 0.99' },
    cols: ['Round (UTC)', 'Side', 'Price', 'BTC move', 'Sec', 'Fill', 'Result', 'P&L'], won: 'won', lost: 'lost',
    shown: (n, t) => `latest ${n} of ${t}`, downloading: (d, t) => `Downloading ${d}/${t} files…`,
    downloaded: (s, f) => `${s} file(s) downloaded, ${f - s} already here.`, needKey: 'Paste your key first.',
    noTrades: 'No round met all three conditions. Loosen one of them.',
  },
  zh: {
    dataBy: '数据：Poly Tick Tape ↗', range: '回测日期（UTC）', sample: '免费样本 1 小时（2026-09-20 04:00–05:00）',
    c1: '盘口概率', favorite: '买强势方', underdog: '买弱势方', priceFrom: '价格',
    c2: 'BTC 价差（相对初始价）', with: '朝我下注的方向', against: '朝反方向', any: '不限方向',
    plainPrice: '普通价', moveHint: '上限填 0 表示不限。', c3: '窗口时间（开盘后秒数）',
    stake: '每笔 $', slip: '滑点', ticks: 'tick', run: '运行回测',
    s1: 'Chainlink 数据', s2: 'Polymarket 盘口', s3: '回测', empty: '设好三个条件，点「运行回测」。',
    trades: '成交明细', csv: '导出 CSV',
    buyTitle: '需要 Chainlink 数据',
    buyWhy: '这个回测使用逐秒的 Chainlink BTC/USD 价格和 TWAP60，也就是 Polymarket 结算这些盘口所用的数据。请在 Poly Tick Tape 购买：单月历史 ¥22.99 / $2.99，订阅滚动 60 天 ¥45.99 / $5.99 每月。',
    missing: '缺少的文件', buyBtn: '去网站购买数据', trySample: '先用免费样本试试',
    haveKey: '已经买了？填入 API Key，直接下载到 ./data：', download: '下载',
    found: (n, a, b) => `./data 里有 ${n} 天数据（${a} 至 ${b}）`, none: './data 里还没有 Chainlink 数据。',
    getData: '获取数据', loading: '加载中…', rounds: (d, t) => `${d}/${t} 局`,
    pnl: '净盈亏', roi: '每美元收益率', nTrades: '下单笔数', winRate: '胜率', avgCost: '平均买入价（含费）',
    dd: '最大回撤', fees: '手续费', of: (n) => `共 ${n} 局`, staked: (x) => `投入 ${x}`,
    settle: (a, c) => `用 TWAP60 复算结果，与 Polymarket 官方一致 ${a.toLocaleString()} / ${c.toLocaleString()} 局。`,
    noTrade: '未下单：', reasons: { noChainlink: '缺 Chainlink', noOdds: '缺盘口', time: '时间内无成交', odds: '概率', move: 'BTC 价差', btcData: 'BTC 价未到达', tooExpensive: '≥ 0.99' },
    cols: ['盘口（UTC）', '方向', '价格', 'BTC 价差', '秒', '成交价', '结果', '盈亏'], won: '赢', lost: '输',
    shown: (n, t) => `最近 ${n} 笔，共 ${t} 笔`, downloading: (d, t) => `正在下载 ${d}/${t} 个文件…`,
    downloaded: (s, f) => `下载 ${s} 个文件，已有 ${f - s} 个。`, needKey: '请先填入 API Key。',
    noTrades: '没有任何一局同时满足三个条件，放宽其中一个试试。',
  },
};

const $ = (s) => document.querySelector(s);
const form = $('#form');
const PARAMS = ['side', 'prob_min', 'prob_max', 'move_mode', 'move_min', 'move_max', 'btc_source',
  'elapsed_min', 'elapsed_max', 'stake', 'slippage_ticks'];
let lang = localStorage.getItem('lang') || (navigator.language.startsWith('zh') ? 'zh' : 'en');
let status = null;
let last = null;

const T = (k, ...a) => { const v = I18N[lang][k]; return typeof v === 'function' ? v(...a) : v; };
const money = (x) => (x < 0 ? '−$' : '$') + Math.abs(x).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const signed = (x) => (x > 0 ? '+' : '') + money(x);
const pct = (x) => (x == null ? '–' : (x * 100).toFixed(2) + '%');
const utc = (s) => new Date(s * 1000).toISOString().slice(0, 16).replace('T', ' ');

function applyLang() {
  document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
  document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = T(el.dataset.i18n); });
  $('#lang').textContent = lang === 'zh' ? 'EN' : '中文';
  const zh = lang === 'zh' ? 'zh/' : '';
  $('#buyBtn').href = `https://polyticktape.com/${zh}pricing/?ref=bt`;
  $('#dataLink').href = `https://polyticktape.com/${zh}?ref=bt`;
  showDataInfo();
  if (last) render(last);
}

function showDataInfo() {
  if (!status) return;
  const d = status.days;
  $('#dataInfo').innerHTML = d.length
    ? T('found', d.length, d[0], d[d.length - 1])
    : `${T('none')} <a href="#" id="getData">${T('getData')}</a>`;
  const g = $('#getData');
  if (g) g.onclick = (e) => { e.preventDefault(); openBuy({ message: '' }); };
}

function syncSample() {
  const on = form.sample.checked;
  form.from.disabled = form.to.disabled = on;
}

async function init() {
  status = await (await fetch('/api/status')).json();
  const q = new URLSearchParams(location.search);
  if (I18N[q.get('lang')]) lang = q.get('lang');
  for (const k of PARAMS) form[k].value = q.get(k) ?? status.defaults[k];
  const d = status.days;
  if (d.length) {
    const lastDay = d[d.length - 1];
    const first = new Date(Date.parse(lastDay) - 29 * 864e5).toISOString().slice(0, 10);
    form.from.value = q.get('from') || (first < d[0] ? d[0] : first);
    form.to.value = q.get('to') || lastDay;
  }
  form.sample.checked = q.get('sample') === '1' || (!d.length && !q.get('from'));
  syncSample();
  applyLang();
  // Step 1 comes first: without Chainlink data there is nothing to backtest, so say where to get it.
  if (!d.length && q.get('sample') !== '1') openBuy({ message: T('none') });
  if (q.get('autorun') === '1') run();
}

function params() {
  const p = {};
  for (const k of PARAMS) p[k] = form[k].value;
  return p;
}

async function run(e) {
  if (e) e.preventDefault();
  const body = { params: params(), from: form.from.value, to: form.to.value, sample: form.sample.checked };
  const r = await post('/api/run', body);
  if (!r) return;
  $('#run').disabled = true;
  resetSteps();
  poll();
}

async function post(url, body) {
  const r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (r.ok) return r.json();
  const j = await r.json().catch(() => ({}));
  alert(j.error || r.statusText);
  return null;
}

function resetSteps() {
  document.querySelectorAll('#steps li').forEach((li) => { li.className = ''; li.querySelector('em').textContent = ''; });
}

function setStep(step, cls, text) {
  const order = ['chainlink', 'odds', 'engine'];
  const i = order.indexOf(step);
  document.querySelectorAll('#steps li').forEach((li, j) => {
    if (j < i) { li.className = 'ok'; if (!li.querySelector('em').textContent) li.querySelector('em').textContent = '✓'; }
    if (j === i) { li.className = cls; li.querySelector('em').textContent = text; }
  });
}

async function poll() {
  const j = await (await fetch('/api/job')).json();
  if (j.state === 'running') {
    if (j.kind === 'run' && j.step) {
      setStep(j.step, 'busy', j.step === 'odds' && j.total ? T('rounds', j.done, j.total) : T('loading'));
    }
    if (j.kind === 'download') $('#dlMsg').textContent = T('downloading', j.done, j.total);
    return setTimeout(poll, 400);
  }
  $('#run').disabled = false;
  if (j.kind === 'download') return downloadDone(j);
  if (j.state === 'error') {
    const step = j.step || 'chainlink';
    setStep(step, 'bad', '✕');
    if (step === 'chainlink') openBuy(j.error);
    else alert(j.error.message);
    return;
  }
  ['chainlink', 'odds', 'engine'].forEach((s) => setStep(s, 'ok', '✓'));
  last = j.result;
  render(last);
}

function openBuy(err) {
  $('#buyMsg').textContent = [err.message, err.hint].filter(Boolean).join(' ');
  const m = err.missing || [];
  $('#missingBox').hidden = !m.length;
  $('#missingList').textContent = m.join('\n');
  $('#dlMsg').textContent = '';
  const dlg = $('#buy');
  if (!dlg.open) dlg.showModal();
}

async function startDownload() {
  const key = $('#key').value.trim();
  if (!key && !status.hasKey) { $('#dlMsg').textContent = T('needKey'); return; }
  const from = form.from.value || '2026-08-14';
  const to = form.to.value || new Date(Date.now() - 864e5).toISOString().slice(0, 10);
  if (await post('/api/download', { key, from, to })) poll();
}

async function downloadDone(j) {
  if (j.state === 'error') {
    $('#dlMsg').textContent = [j.error.message, j.error.hint].filter(Boolean).join(' ');
    return;
  }
  $('#dlMsg').textContent = T('downloaded', j.result.saved, j.result.files);
  status = await (await fetch('/api/status')).json();
  showDataInfo();
  if (status.days.length) {
    form.sample.checked = false;
    syncSample();
    setTimeout(() => { $('#buy').close(); run(); }, 800);
  }
}

function render(res) {
  $('#empty').hidden = true;
  $('#result').hidden = false;
  const s = res.summary;
  const cards = [
    [T('pnl'), signed(s.pnl), s.pnl >= 0 ? 'pos' : 'neg', T('staked', money(s.staked))],
    [T('roi'), pct(s.roi), s.roi >= 0 ? 'pos' : 'neg', ''],
    [T('nTrades'), s.trades.toLocaleString(), '', T('of', s.rounds.toLocaleString())],
    [T('winRate'), pct(s.winRate), '', s.avgCost == null ? '' : `${T('avgCost')} ${s.avgCost.toFixed(3)}`],
    [T('dd'), money(-s.maxDrawdown), '', ''],
    [T('fees'), money(s.fees), '', ''],
  ];
  $('#cards').innerHTML = cards.map(([k, v, c, sub]) =>
    `<div class="card"><div class="k">${k}</div><div class="v ${c}">${v}</div><div class="sub">${sub}</div></div>`).join('');
  drawEquity(res.trades);
  const st = res.settlement;
  const why = Object.entries(res.skipped).filter(([, v]) => v).map(([k, v]) => `${T('reasons')[k]} ${v.toLocaleString()}`).join(' · ');
  $('#meta').textContent = [st.checked ? T('settle', st.agree, st.checked) : '', why ? `${T('noTrade')} ${why}` : ''].filter(Boolean).join('  ');
  renderTable(res.trades);
}

function drawEquity(trades) {
  const svg = $('#equity');
  const W = 800, H = 240, P = 28;
  if (!trades.length) { svg.innerHTML = `<text x="${W / 2}" y="${H / 2}" text-anchor="middle" class="axis">${T('noTrades')}</text>`; return; }
  let eq = 0;
  const pts = [[trades[0].round, 0], ...trades.map((t) => [t.ts, (eq += t.pnl)])];
  const x0 = pts[0][0], x1 = pts[pts.length - 1][0] || x0 + 1;
  const ys = pts.map((p) => p[1]);
  const y0 = Math.min(0, ...ys), y1 = Math.max(0, ...ys);
  const sx = (x) => P + ((x - x0) / Math.max(1, x1 - x0)) * (W - 2 * P);
  const sy = (y) => H - P - ((y - y0) / Math.max(1e-9, y1 - y0)) * (H - 2 * P);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${sx(p[0]).toFixed(1)},${sy(p[1]).toFixed(1)}`).join('');
  const cls = eq >= 0 ? 'pos' : 'neg';
  svg.innerHTML = `
    <line x1="${P}" x2="${W - P}" y1="${sy(0)}" y2="${sy(0)}" class="zero"/>
    <path d="${line}L${sx(x1)},${sy(0)}L${sx(x0)},${sy(0)}Z" class="area ${cls}"/>
    <path d="${line}" class="line ${cls}"/>
    <text x="${P}" y="${H - 8}" class="axis">${utc(x0).slice(0, 10)}</text>
    <text x="${W - P}" y="${H - 8}" class="axis" text-anchor="end">${utc(x1).slice(0, 10)}</text>
    <text x="${P + 4}" y="${sy(y1) - 6 < 12 ? 12 : sy(y1) - 6}" class="axis">${signed(y1)}</text>
    ${y0 < 0 ? `<text x="${P + 4}" y="${Math.min(H - P - 4, sy(y0) + 14)}" class="axis">${signed(y0)}</text>` : ''}`;
}

function renderTable(trades) {
  const rows = trades.slice(-200).reverse();
  const c = T('cols');
  $('#table').innerHTML = `<thead><tr>${c.map((h) => `<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.map((t) => `
    <tr><td><a href="https://polymarket.com/event/btc-updown-5m-${t.round}" target="_blank" rel="noopener">${utc(t.round)}</a></td>
    <td>${t.side}</td><td>${t.prob.toFixed(3)}</td><td>${t.move >= 0 ? '+' : ''}${t.move.toFixed(2)}</td><td>${t.elapsed}</td>
    <td>${t.fill.toFixed(3)}</td><td class="${t.won ? 'pos' : 'neg'}">${T(t.won ? 'won' : 'lost')}</td>
    <td class="${t.pnl >= 0 ? 'pos' : 'neg'}">${signed(t.pnl)}</td></tr>`).join('')}</tbody>
    ${trades.length > rows.length ? `<caption>${T('shown', rows.length, trades.length.toLocaleString())}</caption>` : ''}`;
}

function downloadCsv() {
  if (!last) return;
  const head = 'round_utc,slug,elapsed,side,prob,btc_move,fill,shares,fee,won,pnl';
  const lines = last.trades.map((t) => [utc(t.round), `btc-updown-5m-${t.round}`, t.elapsed, t.side, t.prob, t.move,
    t.fill, t.shares, t.fee, t.won, t.pnl].join(','));
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([[head, ...lines].join('\n')], { type: 'text/csv' }));
  a.download = `backtest-${last.range.from}-${last.range.to}.csv`;
  a.click();
}

form.addEventListener('submit', run);
form.sample.addEventListener('change', syncSample);
$('#lang').onclick = () => { lang = lang === 'zh' ? 'en' : 'zh'; localStorage.setItem('lang', lang); applyLang(); };
$('#csv').onclick = downloadCsv;
$('#dl').onclick = startDownload;
$('#trySample').onclick = () => { form.sample.checked = true; syncSample(); $('#buy').close(); run(); };
init();
