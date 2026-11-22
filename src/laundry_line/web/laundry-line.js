/* 晾衣绳 laundry-line · 小组件
 * 一行挂到你的聊天页上：
 *   <script src="http://127.0.0.1:8790/widget/laundry-line.js" defer></script>
 * 可选（写在同一个 <script> 标签上）：
 *   data-api="http://127.0.0.1:8790"   数据从哪儿取（默认＝这个脚本的来源）
 *   data-token="..."                    服务设了 token 时带上
 *   data-rope=".chat-header"            绳子挂在哪个元素的下沿（不写＝贴在屏幕左上角）
 *   data-basket="#input-bar"            满篮子坐在哪个元素的右上角（不写＝贴在屏幕右下角）
 *   data-poll="300"                     多少秒取一次（默认 300）
 * 颜色、尺寸全是 CSS 变量（.ll-wrap / .ll-bwrap 上的 --ll-*），在你自己的样式里盖掉就行。
 * 夜间：<html data-theme="dark"> 时自动暗一档。
 */
(function () {
  'use strict';
  const me = document.currentScript || document.querySelector('script[src*="laundry-line.js"]');
  const ds = (me && me.dataset) || {};
  const API = (ds.api || (me && me.src ? new URL(me.src).origin : '')).replace(/\/$/, '') + '/api/state';
  const TOKEN = ds.token || '';
  const POLL = Math.max(30, parseInt(ds.poll || '300', 10)) * 1000;

  const CSS = `
  .ll-wrap { --ll-w: 214px; --ll-sag: 12px; --ll-drop: -20px; --ll-scale: 1.22; --ll-top: 56px; --ll-min: 5; --ll-max: 7;
    --ll-rope: #B79C7B; --ll-rope-hi: #E3D3BC; --ll-pin: #CFA97D; --ll-pin-edge: #8E6A45;
    --ll-c1: #F4ECDD; --ll-c2: #CADBC4; --ll-c3: #C6D5E4; --ll-c4: #EECFC6; --ll-c5: #F1DFAE; --ll-c6: #E6E1F0;
    --ll-stripe: #8FA7BF; --ll-edge: rgba(90,70,50,0.28); --ll-mud: #8A6A4A;
    --ll-tint-pink: #F2C6CF; --ll-tint-grey: #CBC7C3; --ll-tint-blue: #BCC9D7;
    --ll-kitty: #FFFDFB; --ll-kitty-eye: #6B4F4F;
    --ll-cat-stripe: #A9C2D2; --ll-cat-ink: #22262A; --ll-dog-face: #CDAE8E; --ll-dog-curl: #3A2C24; --ll-dog-dot: #BCAAA8;
    --ll-note-bg: #FBF6EA; --ll-note-ink: #5A4A3A; --ll-note-font: Georgia, 'Noto Serif SC', 'Songti SC', serif;
    position: fixed; top: var(--ll-top); left: 0; width: var(--ll-w); height: 0; z-index: 50; pointer-events: none; }
  .ll-wrap.ll-in { position: absolute; top: 100%; left: 0; z-index: 1; }
  [data-theme="dark"] .ll-wrap { --ll-rope: #8C7A64; --ll-rope-hi: #A8977F; --ll-note-bg: #2F2822; --ll-note-ink: #D9CBB8; filter: brightness(.82); }
  .ll-wrap[hidden], .ll-bwrap[hidden] { display: none; }
  .ll-rope { position: absolute; left: 0; top: 0; overflow: visible; }
  .ll-item { position: absolute; top: 0; transform-origin: 50% 0; pointer-events: auto; cursor: pointer; -webkit-tap-highlight-color: transparent; }
  .ll-sway { transform-origin: 50% 0; animation: ll-sway var(--ll-dur, 5s) ease-in-out var(--ll-delay, 0s) infinite alternate; }
  @keyframes ll-sway { from { transform: rotate(calc(var(--ll-tilt, 0deg) - 2.2deg)); } to { transform: rotate(calc(var(--ll-tilt, 0deg) + 2.2deg)); } }
  @media (prefers-reduced-motion: reduce) { .ll-sway { animation: none; transform: rotate(var(--ll-tilt, 0deg)); } .ll-basket { animation: none; } }
  .ll-item svg { display: block; overflow: visible; filter: drop-shadow(0 1.5px 1.5px rgba(80,60,40,0.16)); }
  .ll-drip { position: absolute; left: 50%; width: 3px; height: 4px; margin-left: -1.5px; border-radius: 50% 50% 50% 50% / 60% 60% 40% 40%;
    background: rgba(140,170,200,0.75); opacity: 0; animation: ll-drip 2.6s ease-in var(--ll-ddelay, 0s) infinite; }
  @keyframes ll-drip { 0% { opacity: 0; transform: translateY(0); } 15% { opacity: .9; } 100% { opacity: 0; transform: translateY(14px); } }
  .ll-note { position: absolute; left: 10px; top: 80px; min-width: 150px; max-width: 230px; padding: 8px 11px 9px;
    background: var(--ll-note-bg); color: var(--ll-note-ink); font-family: var(--ll-note-font); font-size: 12.5px; line-height: 1.6; letter-spacing: .3px;
    border-radius: 3px; box-shadow: 0 2px 8px rgba(70,50,30,0.16); transform: rotate(-1.6deg) translateY(-6px); opacity: 0;
    transition: opacity .25s ease, transform .3s ease; pointer-events: none; }
  .ll-note.open { opacity: 1; transform: rotate(-1.6deg); pointer-events: auto; }
  .ll-note::before { content: ''; position: absolute; top: -7px; left: 18px; width: 34px; height: 13px; background: rgba(231,214,170,0.75); transform: rotate(4deg); }
  .ll-note b { font-weight: 600; }
  .ll-bwrap { --ll-b-right: 22px; --ll-b-bottom: 90px; --ll-b-size: 40px; --ll-wicker: #CDAA7D; --ll-wicker-dk: #9B774E;
    position: fixed; right: 0; bottom: var(--ll-b-bottom); width: 0; height: 0; z-index: 50; }
  .ll-bwrap.ll-in { position: relative; right: auto; bottom: auto; width: auto; z-index: 5; }
  [data-theme="dark"] .ll-bwrap { --ll-note-bg: #2F2822; --ll-note-ink: #D9CBB8; filter: brightness(.85); }
  .ll-basket { position: absolute; right: var(--ll-b-right); bottom: -9px; width: var(--ll-b-size); cursor: pointer; transform-origin: 50% 100%;
    animation: ll-wobble 5.5s ease-in-out infinite; -webkit-tap-highlight-color: transparent; }
  .ll-basket svg { display: block; width: 100%; height: auto; overflow: visible; filter: drop-shadow(0 1.5px 1.5px rgba(80,60,40,0.18)); }
  @keyframes ll-wobble { 0%, 74%, 100% { transform: rotate(0); } 78% { transform: rotate(-7deg); } 83% { transform: rotate(6deg); }
    88% { transform: rotate(-3.5deg); } 93% { transform: rotate(2deg); } 97% { transform: rotate(-.6deg); } }
  .ll-bnote { position: absolute; right: calc(var(--ll-b-right) + var(--ll-b-size) + 6px); bottom: 2px; white-space: nowrap; padding: 4px 9px;
    background: var(--ll-note-bg, #FBF6EA); color: var(--ll-note-ink, #5A4A3A); font-family: Georgia, 'Noto Serif SC', 'Songti SC', serif; font-size: 12.5px;
    border-radius: 3px; box-shadow: 0 2px 6px rgba(70,50,30,0.15); opacity: 0; transform: translateX(4px); transition: opacity .25s, transform .25s; pointer-events: none; }
  .ll-bnote.open { opacity: 1; transform: none; }`;

  const NS = 'http://www.w3.org/2000/svg';
  // 每种衣服一个小剪影：上沿 y=0 就是夹在绳子上的地方
  const SHAPES = {
    sheet:   { w: 40, h: 34, d: 'M1 0H39V29q-3.2 3.6-6.4 0t-6.4 0-6.4 0-6.4 0-6.4 0-6.4 0Z', fold: 5, bed: 'sheet' },
    duvet:   { w: 40, h: 34, d: 'M1 0H39V30.5Q20 33 1 30.5Z', fold: 5, bed: 'print' },
    blanket: { w: 36, h: 31, d: 'M1 0H35V27H1Z', fold: 4, blanket: 1, fringe: 1 },
    pillow:  { w: 24, h: 17, d: 'M1 0H23V15.5Q12 17.5 1 15.5Z', inner: 1, bed: 'print' },
    towel:   { w: 20, h: 30, d: 'M1 0H19V29H1Z', bands: 1 },
    sock:    { w: 14, h: 22, d: 'M2.5 0H10.5V12.5Q15 14 14.5 18Q14 21.5 9.5 21.5H5Q2 21.5 2 18.5Z', heel: 1 },
    briefs:  { w: 21, h: 14, d: 'M1 0H20V4.5Q15.5 6 13.5 13.5H7.5Q5.5 6 1 4.5Z', band: 1 },
    bra:     { w: 24, h: 13, d: 'M1 1.5Q6 -.5 11 3.2L12 4 13 3.2Q18 -.5 23 1.5Q22.2 11.5 16 11.8Q12.8 12 12 8.6Q11.2 12 8 11.8Q1.8 11.5 1 1.5Z' },
    tee:     { w: 30, h: 26, d: 'M9.5 0L1 5 4.2 10.5 8 8.6V25.5H22V8.6L25.8 10.5 29 5 20.5 0Q15 4.2 9.5 0Z' },
    pants:   { w: 20, h: 30, d: 'M2 0H18L19.5 29.5H12.5L10 9 7.5 29.5H.5Z', band: 1 },
    skirt:   { w: 24, h: 26, d: 'M7.5 0H16.5L17.5 7 23.5 25.5H.5L6.5 7Z' },
    cloth:   { w: 18, h: 18, d: 'M1 0H17V17H1Z' },
  };
  function kind(n) {
    if (/被套/.test(n)) return 'duvet';
    if (/床单|床罩|床笠/.test(n)) return 'sheet';
    if (/枕/.test(n)) return 'pillow';
    if (/毯|被子/.test(n)) return 'blanket';
    if (/巾/.test(n)) return 'towel';
    if (/袜/.test(n)) return 'sock';
    if (/内裤/.test(n)) return 'briefs';
    if (/内衣|文胸|胸罩/.test(n)) return 'bra';
    if (/裤/.test(n)) return 'pants';
    if (/裙/.test(n)) return 'skirt';
    if (/T恤|衬衫|卫衣|毛衣|衣|背心/.test(n)) return 'tee';
    return 'cloth';
  }
  // 名字里写了颜色就照颜色画；没写才按名字挑六个浅色之一
  const NAMED = [[/牛仔/, '#7189A8'], [/藏青|海军/, '#4A5873'], [/黑/, '#3D3B3E'], [/白/, '#FBFAF6'], [/灰/, '#B9B6B1'],
    [/酒红|红/, '#C46F6C'], [/粉/, '#F2C6CF'], [/蓝/, '#A3BBD3'], [/绿/, '#AFC6A6'], [/黄/, '#F1DFAE'], [/紫/, '#C9B8DC'],
    [/棕|咖啡/, '#A58C7C'], [/米|杏|奶/, '#F4ECDD']];
  let LOOK = { bed_sets: [], blanket: {} };
  function bare(n) { let s = n; for (const b of LOOK.bed_sets || []) for (const k of b.keywords || [b.name]) s = s.split(k).join(''); return s; }
  function hue(n) {
    const b = bare(n);
    for (const [re, c] of NAMED) if (re.test(b)) return c;
    let h = 0; for (const c of n) h = (h * 31 + c.charCodeAt(0)) >>> 0; return 'var(--ll-c' + (1 + h % 6) + ')';
  }
  function mk(tag, attrs) { const e = document.createElementNS(NS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); return e; }
  // 尺寸写死在元素上：挂到别人页面里时，不让页面自己的「svg { width: … }」之类的样式把绳子和衣服压扁
  function fix(el, w, h) { el.style.cssText += ';width:' + w + 'px;height:' + h + 'px;max-width:none;max-height:none;min-width:0;min-height:0;'; return el; }

  function pattern(g, S, p) {
    if (p === 'cats') {   // 浅蓝波浪竖条 + 往上爬的小黑猫
      for (let x = 3; x < S.w; x += 5.5) g.appendChild(mk('path', { d: 'M' + x + ' 0q1.1 ' + (S.h / 4) + ' 0 ' + (S.h / 2) + 't0 ' + (S.h / 2), fill: 'none', stroke: 'var(--ll-cat-stripe)', 'stroke-width': .45 }));
      [6, 15, 24].forEach((y, r) => { for (let x = (r % 2 ? 7 : 2.5); x < S.w - 4 && y < S.h - 2; x += 10) {
        const c = mk('g', { transform: 'translate(' + x + ' ' + y + ') rotate(-28)', fill: 'var(--ll-cat-ink)' });
        c.appendChild(mk('circle', { cx: 1.1, cy: 1.4, r: 1 }));
        c.appendChild(mk('path', { d: 'M.25 .9L.45-.25 1 .55ZM1.2 .55L1.75-.25 1.95 .95Z' }));
        c.appendChild(mk('ellipse', { cx: 2.9, cy: 2, rx: 1.6, ry: .85 }));
        c.appendChild(mk('path', { d: 'M4.3 1.8Q5.2 1.2 4.9 .1', fill: 'none', stroke: 'var(--ll-cat-ink)', 'stroke-width': .5, 'stroke-linecap': 'round' }));
        g.appendChild(c); } });
    } else if (p === 'dogs') {   // 卷毛小狗头 + 点点
      for (let i = 0; i < 14; i++) g.appendChild(mk('circle', { cx: (i * 7.3 + 2) % S.w, cy: (i * 5.1 + 3) % S.h, r: .45, fill: 'var(--ll-dog-dot)' }));
      [7, 18, 28].forEach((y, r) => { for (let x = (r % 2 ? 9 : 4); x < S.w - 2 && y < S.h - 1; x += 11) {
        const c = mk('g', { transform: 'translate(' + x + ' ' + y + ')' });
        c.appendChild(mk('circle', { cx: 0, cy: 0, r: 2.1, fill: 'var(--ll-dog-face)' }));
        c.appendChild(mk('circle', { cx: -1.7, cy: -1.5, r: 1, fill: 'none', stroke: 'var(--ll-dog-curl)', 'stroke-width': .45 }));
        c.appendChild(mk('circle', { cx: -.6, cy: -.2, r: .25, fill: 'var(--ll-dog-curl)' }));
        c.appendChild(mk('circle', { cx: .7, cy: -.2, r: .25, fill: 'var(--ll-dog-curl)' }));
        c.appendChild(mk('ellipse', { cx: .1, cy: .7, rx: .4, ry: .3, fill: 'var(--ll-dog-curl)' }));
        g.appendChild(c); } });
    } else if (p === 'kitty') {   // 一身小猫头
      [7, 14.5, 22].forEach((y, r) => { for (let x = (r % 2 ? 6 : 1.8); x < S.w - 4; x += 8.6) {
        const c = mk('g', { transform: 'translate(' + x.toFixed(1) + ' ' + y + ')' });
        c.appendChild(mk('path', { d: 'M0 1.8L.9 0 2 1.2Q2.7 1 3.4 1.2L4.5 0 5.4 1.8Q5.6 4.6 2.7 4.6Q-.2 4.6 0 1.8Z', fill: 'var(--ll-kitty)', stroke: 'rgba(150,90,100,0.35)', 'stroke-width': .3 }));
        c.appendChild(mk('circle', { cx: 1.75, cy: 2.8, r: .38, fill: 'var(--ll-kitty-eye)' }));
        c.appendChild(mk('circle', { cx: 3.65, cy: 2.8, r: .38, fill: 'var(--ll-kitty-eye)' }));
        g.appendChild(c); } });
    } else if (p === 'dots') {
      for (let y = 4; y < S.h; y += 6) for (let x = (y / 6 % 2 ? 6 : 3); x < S.w; x += 6) g.appendChild(mk('circle', { cx: x, cy: y, r: .9, fill: 'var(--ll-stripe)', opacity: .5 }));
    } else if (p === 'stripes') {
      for (let x = 4; x < S.w; x += 6) g.appendChild(mk('rect', { x, y: 0, width: 1.6, height: S.h, fill: 'var(--ll-stripe)', opacity: .45 }));
    }
  }

  function cloth(name, wet, scale, dirty, tint, set) {
    const S = SHAPES[kind(name)];
    const w = S.w * scale, h = S.h * scale;
    const svg = mk('svg', { width: w, height: h + 6 * scale, viewBox: '0 -6 ' + S.w + ' ' + (S.h + 6) });
    fix(svg, w, h + 6 * scale);
    const id = 'llc' + Math.random().toString(36).slice(2, 8);
    const clip = mk('clipPath', { id }); clip.appendChild(mk('path', { d: S.d })); svg.appendChild(clip);
    const g = mk('g', { 'clip-path': 'url(#' + id + ')' });
    const bk = LOOK.blanket || {};
    let base = hue(name), pat = null;
    if (S.bed && set) { base = S.bed === 'sheet' ? (set.sheet || base) : (set.cover || base); pat = S.bed === 'print' ? set.pattern : null; }
    if (S.blanket) { if (bk.color) base = bk.color; pat = bk.pattern; }
    if (tint) base = 'var(--ll-tint-' + tint + ')';
    g.appendChild(mk('path', { d: S.d, fill: base }));
    if (pat) pattern(g, S, pat);
    if (S.fold) g.appendChild(mk('rect', { x: 0, y: 0, width: S.w, height: S.fold, fill: 'rgba(90,70,50,0.10)' }));
    if (S.bands) for (const y of [S.h * .72, S.h * .8]) g.appendChild(mk('rect', { x: 0, y, width: S.w, height: 1.6, fill: 'var(--ll-stripe)', opacity: .55 }));
    if (S.band) g.appendChild(mk('rect', { x: 0, y: 0, width: S.w, height: 2.4, fill: 'rgba(90,70,50,0.16)' }));
    if (S.heel) g.appendChild(mk('rect', { x: 0, y: 0, width: S.w, height: 3, fill: 'rgba(90,70,50,0.14)' }));
    if (S.inner) g.appendChild(mk('rect', { x: 3, y: 3, width: S.w - 6, height: S.h - 7, fill: 'none', stroke: 'rgba(90,70,50,0.22)', 'stroke-width': .8, 'stroke-dasharray': '1.6 1.4' }));
    g.appendChild(mk('path', { d: S.d, fill: 'rgba(55,65,80,' + (wet * 0.30).toFixed(3) + ')' }));   // 湿＝暗一层，干了就没了
    if (dirty) for (const [fx, fy, fr] of [[.28, .55, 1.6], [.62, .38, 1.2], [.5, .78, 2], [.78, .7, 1.1], [.2, .3, .9]])   // 淋脏了：几个泥点
      g.appendChild(mk('ellipse', { cx: S.w * fx, cy: S.h * fy, rx: fr * 1.3, ry: fr, fill: 'var(--ll-mud)', opacity: .7 }));
    svg.appendChild(g);
    svg.appendChild(mk('path', { d: S.d, fill: 'none', stroke: 'var(--ll-edge)', 'stroke-width': .8 }));
    if (S.fringe) for (let x = 3; x < S.w - 1; x += 3.2) svg.appendChild(mk('line', { x1: x, y1: 27, x2: x + .3, y2: 30.5, stroke: base, 'stroke-width': 1.1 }));
    const pins = S.w >= 30 ? [S.w * .2, S.w * .8] : [S.w / 2];   // 夹子：宽的两头各一个
    for (const px of pins) {
      svg.appendChild(mk('rect', { x: px - 1.8, y: -5.5, width: 3.6, height: 9, rx: 1, fill: 'var(--ll-pin)', stroke: 'var(--ll-pin-edge)', 'stroke-width': .6 }));
      svg.appendChild(mk('line', { x1: px - 1.8, y1: -1.2, x2: px + 1.8, y2: -1.2, stroke: 'var(--ll-pin-edge)', 'stroke-width': .5 }));
    }
    return svg;
  }

  // 这一缸是哪套四件套：名字里有那套的关键词就是那套；都没写就按这一缸的开始时间挑（同一缸一直是同一套）
  function bedSet(ld, n) {
    const sets = LOOK.bed_sets || [];
    if (!sets.length) return null;
    const has = (s, t) => (s.keywords || [s.name]).some(k => t.indexOf(k) >= 0);
    return sets.find(s => has(s, n)) || sets.find(s => has(s, (ld.items || []).join(''))) || sets[Math.floor(ld.start || 0) % sets.length];
  }
  function hm(ts) { const d = new Date(ts * 1000); return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0'); }

  const BASKET_SVG = '<svg viewBox="0 0 40 36" aria-hidden="true">' +
    '<path d="M9 11 Q12 2 20 5 Q25 0 31 6 Q36 5 34 12Z" fill="#F4ECDD" stroke="rgba(90,70,50,.3)" stroke-width=".6"/>' +
    '<path d="M6 12 Q9 4 16 7 L17 12Z" fill="#F3C3CE" stroke="rgba(150,90,100,.35)" stroke-width=".5"/>' +
    '<path d="M28 12 L29 5 L32.5 5 L32 9 Q35 9.5 35 12Z" fill="#C6D5E4" stroke="rgba(90,70,50,.3)" stroke-width=".5"/>' +
    '<path d="M3 11.5 H37 L33.5 34 H6.5Z" fill="var(--ll-wicker)" stroke="var(--ll-wicker-dk)" stroke-width=".8" stroke-linejoin="round"/>' +
    '<g stroke="var(--ll-wicker-dk)" stroke-width=".6" opacity=".55" fill="none"><path d="M4 17.5H36M4.8 23H35.2M5.6 28.5H34.4"/>' +
    '<path d="M10 12V34M15 12V34M20 12V34M25 12V34M30 12V34"/></g>' +
    '<rect x="2" y="10" width="36" height="3.4" rx="1.4" fill="var(--ll-wicker-dk)"/>' +
    '<path d="M24 13 Q24.5 19 22 21 Q20 22.5 21 24" fill="none" stroke="#C6D5E4" stroke-width="2.4" stroke-linecap="round"/></svg>';

  let wrap, note, bwrap, bnote, btimer, data = null, skew = 0;
  function mount(sel) { if (!sel) return null; try { return document.querySelector(sel); } catch (e) { return null; } }
  function ensure() {
    if (wrap) return true;
    if (!document.getElementById('ll-style')) { const st = document.createElement('style'); st.id = 'll-style'; st.textContent = CSS; document.head.appendChild(st); }
    wrap = document.createElement('div'); wrap.className = 'll-wrap'; wrap.hidden = true;
    note = document.createElement('div'); note.className = 'll-note';
    const host = mount(ds.rope);
    if (host) { if (getComputedStyle(host).position === 'static') host.style.position = 'relative'; wrap.classList.add('ll-in'); host.appendChild(wrap); }
    else document.body.appendChild(wrap);
    document.addEventListener('click', e => { if (note.classList.contains('open') && !e.target.closest('.ll-item')) note.classList.remove('open'); });
    return true;
  }
  function renderBasket() {
    const b = data && data.basket;
    const full = !!(b && b.cap && b.n >= b.cap);
    if (!bwrap) {
      if (!full) return;
      bwrap = document.createElement('div'); bwrap.className = 'll-bwrap';
      const bk = document.createElement('div'); bk.className = 'll-basket'; bk.innerHTML = BASKET_SVG;
      bk.firstChild.style.cssText = 'width:100%;height:auto;max-width:none;max-height:none;display:block;';
      bnote = document.createElement('div'); bnote.className = 'll-bnote'; bnote.textContent = '洗衣篮满啦';
      bk.addEventListener('click', () => { bnote.classList.add('open'); clearTimeout(btimer); btimer = setTimeout(() => bnote.classList.remove('open'), 2200); });
      bwrap.appendChild(bnote); bwrap.appendChild(bk);
      const host = mount(ds.basket);
      if (host) { bwrap.classList.add('ll-in'); host.insertBefore(bwrap, host.firstChild); } else document.body.appendChild(bwrap);
    }
    bwrap.hidden = !full;
  }

  function render(d) {
    if (d) { data = d; if (d.now) skew = d.now - Date.now() / 1000; if (d.look) LOOK = d.look; }
    if (!ensure()) return;
    renderBasket();
    const loads = (data && data.loads) || [];
    const items = [];
    for (const ld of loads) { const left = (ld.tint || []).map(t => typeof t === 'string' ? { n: t, c: 'pink' } : t);   // 串色的只算第一件同名的
      (ld.items || []).forEach((n, k) => { const i = left.findIndex(t => t.n === n); let c = null; if (i >= 0) { c = left[i].c || 'pink'; left.splice(i, 1); } items.push({ n, ld, k, tinted: !!c, tint: c }); }); }
    wrap.textContent = '';
    if (!items.length) { wrap.hidden = true; return; }
    wrap.hidden = false;
    const cs = getComputedStyle(wrap);
    const num = (k, dflt) => { const v = parseFloat(cs.getPropertyValue(k)); return isNaN(v) ? dflt : v; };
    const W = num('--ll-w', 214), SAG = num('--ll-sag', 12), DROP = num('--ll-drop', -20), base = num('--ll-scale', 1.22);
    const HI = Math.round(num('--ll-max', 7)), LO = Math.min(HI, Math.round(num('--ll-min', 5)));
    let hs = 7; for (const ld of loads) hs = (hs * 31 + Math.floor(ld.start || 0)) >>> 0;
    const MAX = LO + hs % (HI - LO + 1);   // 挂几件：每缸在 min~max 之间定死
    let shown = items;
    if (items.length > MAX) {   // 挑哪几件也按名字+哪一缸定死；串了色的那件必挑
      const key = it => { if (it.tinted) return -1; let h = 2166136261; for (const c of it.n + '|' + it.ld.start + '|' + it.k) h = Math.imul(h ^ c.charCodeAt(0), 16777619) >>> 0; return h; };
      const pick = new Set(items.slice().sort((a, b) => key(a) - key(b)).slice(0, MAX));
      shown = items.filter(x => pick.has(x));
    }
    const need = shown.reduce((a, x) => a + SHAPES[kind(x.n)].w + 3, 0);
    const scale = Math.min(base, (W - 22) / need);
    // 左头系在屏幕边（从外面拉进来），右头一颗钉子；--ll-drop 负数＝靠屏幕边那头往下斜出去
    const x0 = -6, x1 = W - 8, yL = 2 + Math.max(0, -DROP), yR = 2 + Math.max(0, DROP);
    const yC = (yL + yR) / 2 + 2 * SAG, H = Math.max(yL, yR) + SAG + 10;
    const ropeY = t => (1 - t) * (1 - t) * yL + 2 * t * (1 - t) * yC + t * t * yR;
    const rope = mk('svg', { class: 'll-rope', width: W, height: H, viewBox: '0 0 ' + W + ' ' + H });
    fix(rope, W, H);
    const dpath = 'M' + x0 + ' ' + yL + 'Q' + ((x0 + x1) / 2) + ' ' + yC + ' ' + x1 + ' ' + yR;
    rope.appendChild(mk('path', { d: dpath, fill: 'none', stroke: 'var(--ll-rope)', 'stroke-width': 1.5, 'stroke-linecap': 'round' }));
    rope.appendChild(mk('path', { d: dpath, fill: 'none', stroke: 'var(--ll-rope-hi)', 'stroke-width': .7, 'stroke-dasharray': '1.4 2.2', opacity: .8 }));
    rope.appendChild(mk('circle', { cx: x1, cy: yR, r: 2.3, fill: 'var(--ll-pin-edge)' }));
    wrap.appendChild(rope);
    const now = Date.now() / 1000 + skew;
    const totalW = shown.reduce((a, x) => a + SHAPES[kind(x.n)].w * scale, 0) + 3 * (shown.length - 1);
    let x = Math.max(4, (W - totalW) / 2);
    shown.forEach((it, i) => {
      const S = SHAPES[kind(it.n)], w = S.w * scale;
      const cx = x + w / 2; x += w + 3;
      const t = Math.min(1, Math.max(0, (cx - x0) / (x1 - x0)));
      const ld = it.ld;
      const wet = ld.dirty ? 1 : 1 - (typeof ld.dry === 'number' ? ld.dry : 0);
      const el = document.createElement('div'); el.className = 'll-item';
      el.style.left = (cx - w / 2) + 'px'; el.style.top = (ropeY(t) - 2 * scale) + 'px';
      const sw = document.createElement('div'); sw.className = 'll-sway';
      sw.style.setProperty('--ll-dur', (4.2 + (i % 3) * .9) + 's');
      sw.style.setProperty('--ll-delay', (-i * 1.3) + 's');
      sw.style.setProperty('--ll-tilt', ((t - .5) * -6).toFixed(1) + 'deg');
      sw.appendChild(cloth(it.n, Math.min(1, wet), scale, ld.dirty, it.tint, bedSet(ld, it.n)));
      if (wet > 0.55 && (i % 2 === 0)) {
        const dr = document.createElement('i'); dr.className = 'll-drip';
        dr.style.top = (S.h * scale + 4) + 'px'; dr.style.setProperty('--ll-ddelay', (i * .7) + 's');
        sw.appendChild(dr);
      }
      el.appendChild(sw);
      el.addEventListener('click', e => { e.stopPropagation(); note.classList.toggle('open'); });
      wrap.appendChild(el);
    });
    note.innerHTML = '';
    for (const ld of loads) {
      const p = document.createElement('div');
      const b = document.createElement('b'); b.textContent = (ld.items || []).join('、');
      p.appendChild(b);
      const d = typeof ld.dry === 'number' ? ld.dry : 0;
      const dw = d >= 1 ? '干了' : d < .15 ? '还湿着' : d < .4 ? '干了两三成' : d < .6 ? '半干' : d < .85 ? '干了七八成' : '快干了';
      p.appendChild(document.createTextNode(ld.dirty ? ' · 淋脏了，要重洗' : dw === '干了' ? ' · 干了'
        : ' · ' + dw + (ld.end ? '，大概 ' + hm(ld.end) + ' 干' : '') + (ld.wet ? '（淋过雨）' : '')));
      note.appendChild(p);
    }
    note.style.top = (Math.max(yL, yR) + SAG + 46 * scale) + 'px';
    wrap.appendChild(note);
  }

  async function load() {
    try {
      const r = await fetch(API, { cache: 'no-store', headers: TOKEN ? { Authorization: 'Bearer ' + TOKEN } : {} });
      if (r.ok) render(await r.json());
    } catch (e) {}
  }
  window.laundryLine = { refresh: load, render, openNote: () => note && note.classList.add('open') };
  function start() { load(); setInterval(load, POLL); setInterval(() => render(), 60 * 1000); }
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();
