// Koli Ölçüm arayüzü: 3 kaynak (kamera ya da dosya) -> /capture -> /result -> /measure?cargo=1
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const API = location.origin;                 // arayüz servisin kendisinden sunulur (aynı köken)
const SLOTS = 3;
const MAX_W = 1280;                          // Studio bloğu gibi: 1280 px üstü küçültülür
const JPEG_Q = 0.92;
const MAX_CLOUD = 2000000;                   // ölçüm tam bulutla (Studio bloğu varsayılanı)
const VIEW_POINTS = 300000;                  // 3D görünümde en fazla nokta
const MIN_H = 8;                             // /measure varsayılanı (mm)
const SID = 'web-' + (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2));

const $ = (s, el = document) => el.querySelector(s);
const fmt1 = v => Number(v).toLocaleString('tr-TR', { minimumFractionDigits: 1, maximumFractionDigits: 1 });

// ---------- kalıcı küçük ayarlar (yalnızca bu tarayıcı) ----------
const store = {
  get(k, d) { try { const v = localStorage.getItem('koli.' + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem('koli.' + k, JSON.stringify(v)); } catch { /* yok say */ } },
};

const markerIn = $('#marker'), savePly = $('#saveply');
markerIn.value = store.get('marker', 100);
savePly.checked = store.get('saveply', false);
markerIn.addEventListener('change', () => store.set('marker', Number(markerIn.value)));
savePly.addEventListener('change', () => store.set('saveply', savePly.checked));

// ---------- kaynak yuvaları ----------
let cameras = [];                             // [{deviceId, label}]
const slots = [];

function makeSlot(i) {
  const el = $('#slotTpl').content.firstElementChild.cloneNode(true);
  const s = {
    i, el, mode: 'none', stream: null, bitmap: null, url: null, name: '',
    sel: $('.src', el), video: $('video', el), img: $('img', el), ph: $('.ph', el),
    meta: $('.meta', el), file: $('.file', el),
  };
  $('.badge', el).textContent = i + 1;
  $('.pick', el).addEventListener('click', () => s.file.click());
  s.file.addEventListener('change', () => { if (s.file.files[0]) setFile(s, s.file.files[0]); s.file.value = ''; });
  s.sel.addEventListener('change', () => onSelect(s));
  const pv = $('.preview', el);
  pv.addEventListener('dragover', e => { e.preventDefault(); el.classList.add('drag'); });
  pv.addEventListener('dragleave', () => el.classList.remove('drag'));
  pv.addEventListener('drop', e => {
    e.preventDefault(); el.classList.remove('drag');
    const f = [...(e.dataTransfer?.files || [])].find(f => f.type.startsWith('image/'));
    if (f) setFile(s, f);
  });
  $('#cams').appendChild(el);
  return s;
}

function fillSelect(s) {
  const cur = s.mode === 'camera' ? 'cam:' + s.deviceId : s.mode === 'file' ? 'file' : 'none';
  s.sel.innerHTML = '';
  const add = (v, t, dis = false) => { const o = new Option(t, v); o.disabled = dis; s.sel.add(o); };
  add('none', 'Kaynak yok');
  add('file', s.mode === 'file' ? 'Dosya: ' + s.name : 'Görüntü dosyası…');
  if (cameras.length) {
    cameras.forEach((c, k) => add('cam:' + c.deviceId, c.label || 'Kamera ' + (k + 1)));
  } else {
    add('', '— Kamera için "Kameraları bul" —', true);
  }
  s.sel.value = [...s.sel.options].some(o => o.value === cur) ? cur : 'none';
}

function stopSlot(s) {
  if (s.stream) s.stream.getTracks().forEach(t => t.stop());
  s.stream = null;
  if (s.url) URL.revokeObjectURL(s.url);
  s.url = null; s.bitmap = null;
  s.video.srcObject = null; s.video.hidden = true; s.img.hidden = true;
  s.ph.hidden = false; s.meta.textContent = '';
  s.mode = 'none'; s.el.classList.remove('ready');
}

async function onSelect(s) {
  const v = s.sel.value;
  if (v === 'file') { s.file.click(); fillSelect(s); return; }
  if (v === 'none') { stopSlot(s); fillSelect(s); store.set('cam' + s.i, null); return; }
  if (v.startsWith('cam:')) await startCamera(s, v.slice(4));
}

async function startCamera(s, deviceId) {
  stopSlot(s);
  s.ph.textContent = 'Kamera açılıyor…';
  try {
    s.stream = await navigator.mediaDevices.getUserMedia({
      video: { deviceId: { exact: deviceId }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false,
    });
    s.video.srcObject = s.stream;
    s.video.hidden = false; s.ph.hidden = true;
    s.mode = 'camera'; s.deviceId = deviceId; s.el.classList.add('ready');
    s.video.onloadedmetadata = () => {
      const lbl = cameras.find(c => c.deviceId === deviceId)?.label || 'Kamera';
      s.meta.textContent = `${lbl} · ${s.video.videoWidth}×${s.video.videoHeight}`;
    };
    store.set('cam' + s.i, deviceId);
    const dup = slots.filter(o => o !== s && o.mode === 'camera' && o.deviceId === deviceId);
    if (dup.length) setStep(`Uyarı: Kaynak ${s.i + 1} ile Kaynak ${dup[0].i + 1} aynı kamera.`, 'warn');
  } catch (e) {
    stopSlot(s);
    s.ph.textContent = camError(e);
  }
  fillSelect(s);
}

function camError(e) {
  const n = e?.name || '';
  if (n === 'NotAllowedError') return 'Kamera izni verilmedi.';
  if (n === 'NotReadableError') return 'Kamera açılamadı (başka bir uygulama kullanıyor olabilir).';
  if (n === 'OverconstrainedError' || n === 'NotFoundError') return 'Kamera bulunamadı.';
  return 'Kamera açılamadı: ' + (e?.message || n);
}

async function setFile(s, file) {
  stopSlot(s);
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' });
    s.bitmap = bmp; s.name = file.name; s.url = URL.createObjectURL(file);
    s.img.src = s.url; s.img.hidden = false; s.ph.hidden = true;
    s.mode = 'file'; s.el.classList.add('ready');
    s.meta.textContent = `${file.name} · ${bmp.width}×${bmp.height}`;
  } catch {
    s.ph.textContent = 'Görüntü okunamadı: ' + file.name;
  }
  fillSelect(s);
}

async function listCameras(askPermission) {
  if (!navigator.mediaDevices?.enumerateDevices) {
    setStep('Bu tarayıcı kamera erişimini desteklemiyor (localhost ya da https gerekli).', 'warn');
    return;
  }
  try {
    if (askPermission) {
      const tmp = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      tmp.getTracks().forEach(t => t.stop());
    }
    const devs = await navigator.mediaDevices.enumerateDevices();
    cameras = devs.filter(d => d.kind === 'videoinput' && d.deviceId).map(d => ({ deviceId: d.deviceId, label: d.label }));
    if (askPermission) setStep(cameras.length ? `${cameras.length} kamera bulundu.` : 'Kamera bulunamadı.', cameras.length ? '' : 'warn');
  } catch (e) {
    if (askPermission) setStep(camError(e), 'err');
  }
  slots.forEach(fillSelect);
}

for (let i = 0; i < SLOTS; i++) slots.push(makeSlot(i));
slots.forEach(fillSelect);
$('#scanCams').addEventListener('click', () => listCameras(true));
// izin daha önce verildiyse kameraları listele ve son seçimleri geri aç
listCameras(false).then(async () => {
  for (const s of slots) {
    const id = store.get('cam' + s.i, null);
    if (id && cameras.some(c => c.deviceId === id && c.label)) await startCamera(s, id);
  }
});
navigator.mediaDevices?.addEventListener?.('devicechange', () => listCameras(false));

// ---------- kare yakalama ----------
function grabCanvas(s) {
  const src = s.mode === 'camera' ? s.video : s.bitmap;
  const w0 = s.mode === 'camera' ? s.video.videoWidth : s.bitmap.width;
  const h0 = s.mode === 'camera' ? s.video.videoHeight : s.bitmap.height;
  if (!w0 || !h0) return null;
  const k = Math.min(1, MAX_W / w0);
  const c = document.createElement('canvas');
  c.width = Math.round(w0 * k); c.height = Math.round(h0 * k);
  c.getContext('2d').drawImage(src, 0, 0, c.width, c.height);
  return c;
}
const toJpeg = c => new Promise((res, rej) => c.toBlob(b => b ? res(b) : rej(new Error('JPEG oluşturulamadı')), 'image/jpeg', JPEG_Q));

// ---------- servis ----------
async function api(path, opt = {}, kind = 'json') {
  let r;
  try { r = await fetch(API + path, opt); } catch { throw new Error('Servise ulaşılamadı: ' + API); }
  if (!r.ok) {
    let msg = r.status + ' ' + r.statusText;
    try { const j = await r.json(); if (j.error) msg = j.error; } catch { /* düz metin */ }
    throw new Error('Servis hatası: ' + msg);
  }
  return kind === 'json' ? r.json() : kind === 'buf' ? r.arrayBuffer() : r.blob();
}

const svc = $('#svc');
let running = false;
async function pollStatus() {
  try {
    await api('/status');
    svc.className = 'pill ' + (running ? 'pill-busy' : 'pill-ok');
    svc.querySelector('b').textContent = running ? 'Servis: hesaplıyor' : 'Servis bağlı';
  } catch {
    svc.className = 'pill pill-err';
    svc.querySelector('b').textContent = 'Servise ulaşılamadı';
  }
}
pollStatus();
setInterval(pollStatus, 3000);

// ---------- ölçüm akışı ----------
const btn = $('#measure'), stepEl = $('#step'), svcMsg = $('#svcmsg');
function setStep(t, cls = '') { stepEl.innerHTML = t; stepEl.className = 'step ' + cls; }
function setBusy(b) {
  running = b;
  btn.disabled = b; btn.classList.toggle('busy', b);
  $('.lbl', btn).textContent = b ? 'Ölçülüyor' : 'Ölç';
  pollStatus();
}

btn.addEventListener('click', measure);
async function measure() {
  const ready = slots.filter(s => s.mode !== 'none');
  if (ready.length < 2) { setStep('En az 2 kaynak gerekli (kamera ya da görüntü dosyası).', 'warn'); return; }
  const marker = Number(markerIn.value);
  if (!(marker > 0)) { setStep('Kart boyu 0\'dan büyük olmalı.', 'warn'); return; }
  setBusy(true); svcMsg.textContent = '';
  const t0 = performance.now();
  const secs = () => ((performance.now() - t0) / 1000).toFixed(1).replace('.', ',') + ' sn';
  try {
    // 1) tüm kaynaklardan aynı anda birer kare
    setStep('Kareler alınıyor…');
    const canvases = ready.map(grabCanvas);
    ready.forEach(s => {
      s.el.classList.remove('flash'); void s.el.offsetWidth; s.el.classList.add('flash');
      setTimeout(() => s.el.classList.remove('flash'), 400);
    });
    if (canvases.some(c => !c)) throw new Error('Bir kamera henüz görüntü vermiyor; birkaç saniye sonra tekrar deneyin.');
    const blobs = await Promise.all(canvases.map(toJpeg));

    // 2) /capture: art arda JPEG'ler + X-Sizes (Studio "Çok Kameralı 3D" bloğuyla aynı)
    setStep(`3D oluşturuluyor (${ready.length} kamera)…`);
    const q = new URLSearchParams({ sid: SID, marker: String(marker), save: savePly.checked ? '1' : '0' });
    const cap = await api('/capture?' + q, {
      method: 'POST', body: new Blob(blobs, { type: 'application/octet-stream' }),
      headers: { 'X-Sizes': blobs.map(b => b.size).join(',') },
    });
    if (cap.error) throw new Error('Servis hatası: ' + cap.error);
    svcMsg.textContent = 'Servis: ' + (cap.status || '');
    if (!cap.points) throw new Error(cap.status || 'Servis nokta bulutu üretmedi.');
    const noCard = /kart bulunamadı/i.test(cap.status || '');

    // 3) bulut + gönderilen kareler
    setStep('Nokta bulutu alınıyor…');
    const [buf, sheet] = await Promise.all([
      api(`/result?sid=${encodeURIComponent(SID)}&max=${MAX_CLOUD}`, {}, 'buf'),
      api(`/result_preview?sid=${encodeURIComponent(SID)}`, {}, 'blob').catch(() => null),
    ]);
    if (buf.byteLength < 15) throw new Error('Bulut boş geldi.');

    // 4) /measure?cargo=1
    setStep('Koliler ölçülüyor…');
    const m = await api(`/measure?cargo=1&min_h=${MIN_H}`, { method: 'POST', body: buf });

    showResults(m, buf, cap, sheet, marker);
    const n = m.objects.length;
    if (noCard) setStep(`ArUco kart bulunamadı: ölçek mm değil, sonuçlar geçersiz (${secs()}).`, 'err');
    else if (!n) setStep(`Masa üstünde koli bulunamadı (${secs()}).`, 'warn');
    else setStep(`<b>${n} koli</b> ölçüldü · toplam <b>${fmt1(m.objects.reduce((a, o) => a + o.desi, 0))} desi</b> · ${secs()}`);
  } catch (e) {
    setStep(e.message || String(e), 'err');
  } finally {
    setBusy(false);
  }
}

$('#clear').addEventListener('click', () => {
  clearResults();
  svcMsg.textContent = '';
  setStep('Hazır. En az 2 kaynak seçip <b>Ölç</b>\'e basın.');
});

// ---------- sonuç tablosu ve görüntüler ----------
const tbody = $('#tbl tbody');
function clearResults() {
  tbody.innerHTML = '<tr class="placeholder"><td colspan="3">Ölçüm bekleniyor</td></tr>';
  $('#tfootDesi').textContent = '–'; $('#totalDesi').textContent = '–'; $('#count').textContent = '–';
  $('#topImg').hidden = true; $('#emptyTop').hidden = false;
  $('#sheetImg').removeAttribute('src'); $('#plyPath').textContent = '';
  viewer.clear();
}

function showResults(m, buf, cap, sheet, marker) {
  const objs = m.objects || [];
  const total = objs.reduce((a, o) => a + o.desi, 0);
  tbody.innerHTML = objs.length ? '' : '<tr class="placeholder"><td colspan="3">Koli bulunamadı</td></tr>';
  for (const o of objs) {
    const tr = document.createElement('tr');
    tr.dataset.id = o.id;
    tr.innerHTML = `<td><b>${o.id}</b></td><td>${fmt1(o.L / 10)} × ${fmt1(o.W / 10)} × ${fmt1(o.H / 10)}</td><td class="num">${fmt1(o.desi)}</td>`;
    tr.addEventListener('mouseenter', () => viewer.highlight(o.id));
    tr.addEventListener('mouseleave', () => viewer.highlight(null));
    tbody.appendChild(tr);
  }
  $('#tfootDesi').textContent = objs.length ? fmt1(total) : '–';
  $('#totalDesi').textContent = objs.length ? fmt1(total) : '–';
  $('#count').textContent = String(objs.length);
  const img = $('#topImg');
  img.src = 'data:image/jpeg;base64,' + m.image; img.hidden = false; $('#emptyTop').hidden = true;
  if (sheet && sheet.size) {
    const old = $('#sheetImg').src; if (old.startsWith('blob:')) URL.revokeObjectURL(old);
    $('#sheetImg').src = URL.createObjectURL(sheet);
  }
  $('#plyPath').textContent = cap.ply ? 'PLY: ' + cap.ply : '';
  viewer.show(buf, objs, marker);
}

// ---------- 3D görünüm ----------
const viewer = (() => {
  const stage = $('#stage');
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.setClearColor(0x000000, 0);
  stage.prepend(renderer.domElement);
  const scene = new THREE.Scene();
  const cam = new THREE.PerspectiveCamera(45, 1, 5, 50000);
  const controls = new OrbitControls(cam, renderer.domElement);
  controls.enableDamping = true; controls.dampingFactor = 0.12;
  controls.maxPolarAngle = Math.PI * 0.495;
  let root = null, boxes = [], home = null, dirty = true;

  const resize = () => {
    const w = stage.clientWidth, h = stage.clientHeight;
    renderer.setSize(w, h, false); cam.aspect = w / Math.max(h, 1); cam.updateProjectionMatrix(); dirty = true;
  };
  new ResizeObserver(resize).observe(stage); resize();
  controls.addEventListener('change', () => { dirty = true; });
  (function loop() {
    requestAnimationFrame(loop);
    if (controls.update() || dirty) { renderer.render(scene, cam); dirty = false; }
  })();

  function dispose(o) {
    o.traverse(c => {
      c.geometry?.dispose();
      [].concat(c.material || []).forEach(mt => { mt.map?.dispose(); mt.dispose(); });
    });
  }

  function clear() {
    if (root) { scene.remove(root); dispose(root); }
    root = null; boxes = []; home = null;
    $('#empty3d').hidden = false; $('#cloudinfo').textContent = ''; dirty = true;
  }

  // ikili bulut: N x (3 float32 xyz + 3 uint8 rgb), y yukarı, mm
  function parse(buf) {
    const n = Math.floor(buf.byteLength / 15), dv = new DataView(buf);
    return {
      n,
      x: i => dv.getFloat32(i * 15, true), y: i => dv.getFloat32(i * 15 + 4, true), z: i => dv.getFloat32(i * 15 + 8, true),
      rgb: i => [dv.getUint8(i * 15 + 12), dv.getUint8(i * 15 + 13), dv.getUint8(i * 15 + 14)],
    };
  }

  // servis kutu açısını döndürmüyor: üst yüzey noktalarından en küçük alanlı dikdörtgenin açısı
  function orientation(cl, o) {
    const r = 0.5 * Math.hypot(o.L, o.W) + 10, r2 = r * r;
    const pts = [];
    for (let i = 0; i < cl.n; i++) {
      const h = cl.y(i);
      if (h < 0.9 * o.H || h > 1.08 * o.H) continue;
      const dx = cl.x(i) - o.x, dy = -cl.z(i) - o.y;
      if (dx * dx + dy * dy <= r2) pts.push(dx, dy);
    }
    let m = pts.length / 2;
    if (m < 20) return 0;
    const step = Math.max(1, Math.floor(m / 3000));
    const px = [], py = [];
    for (let k = 0; k < m; k += step) { px.push(pts[2 * k]); py.push(pts[2 * k + 1]); }
    m = px.length;
    const pct = (a, p) => a[Math.min(a.length - 1, Math.max(0, Math.round(p * (a.length - 1))))];
    let best = { area: Infinity, a: 0 };
    const u = new Float64Array(m), v = new Float64Array(m);
    for (let deg = 0; deg < 90; deg += 1) {
      const a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
      for (let k = 0; k < m; k++) { u[k] = px[k] * c + py[k] * s; v[k] = -px[k] * s + py[k] * c; }
      u.sort(); v.sort();
      const eu = pct(u, 0.97) - pct(u, 0.03), ev = pct(v, 0.97) - pct(v, 0.03);
      if (eu * ev < best.area) best = { area: eu * ev, a, eu, ev };
    }
    // uzun kenar (L) u yönündeyse açı aynen, değilse 90° döndür
    return best.eu >= best.ev ? best.a : best.a + Math.PI / 2;
  }

  function label(text) {
    const c = document.createElement('canvas'); c.width = 128; c.height = 128;
    const g = c.getContext('2d');
    g.fillStyle = '#f5b83d'; g.beginPath(); g.roundRect(14, 14, 100, 100, 24); g.fill();
    g.fillStyle = '#1a1305'; g.font = 'bold 68px Segoe UI, sans-serif'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText(text, 64, 70);
    const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: new THREE.CanvasTexture(c), depthTest: false }));
    sp.renderOrder = 10;
    return sp;
  }

  function show(buf, objs, marker) {
    clear();
    const cl = parse(buf);
    root = new THREE.Group(); scene.add(root);

    // görünüm için seyreltme (~300k)
    const m = Math.min(cl.n, VIEW_POINTS), stride = cl.n / m;
    const pos = new Float32Array(m * 3), col = new Uint8Array(m * 3);
    const bb = new THREE.Box3();
    for (let k = 0; k < m; k++) {
      const i = Math.floor(k * stride);
      pos[3 * k] = cl.x(i); pos[3 * k + 1] = cl.y(i); pos[3 * k + 2] = cl.z(i);
      const [r, g, b] = cl.rgb(i); col[3 * k] = r; col[3 * k + 1] = g; col[3 * k + 2] = b;
    }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(col, 3, true));
    geo.computeBoundingBox(); bb.copy(geo.boundingBox);

    // odak: kolilerin kapladığı alan (yoksa bulutun kendisi)
    const focus = new THREE.Box3();
    if (objs.length) {
      for (const o of objs) {
        const rr = 0.5 * Math.hypot(o.L, o.W);
        focus.expandByPoint(new THREE.Vector3(o.x - rr, 0, -o.y - rr));
        focus.expandByPoint(new THREE.Vector3(o.x + rr, o.H, -o.y + rr));
      }
    } else focus.copy(bb);
    const size = focus.getSize(new THREE.Vector3()), center = focus.getCenter(new THREE.Vector3());
    const span = Math.max(size.x, size.z, size.y, 200);

    const pmat = new THREE.PointsMaterial({ size: Math.max(1.5, span / 420), vertexColors: true, sizeAttenuation: true });
    root.add(new THREE.Points(geo, pmat));

    // zemin ızgarası (kart düzlemi y = 0) ve kart
    const gsize = Math.ceil(span * 1.8 / 100) * 100;
    const grid = new THREE.GridHelper(gsize, gsize / 50, 0x3a4554, 0x222a33);
    grid.position.set(Math.round(center.x / 50) * 50, -0.5, Math.round(center.z / 50) * 50);
    grid.material.transparent = true; grid.material.opacity = 0.6;
    root.add(grid);
    const s = marker;
    const card = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(0, 0.5, 0), new THREE.Vector3(s, 0.5, 0), new THREE.Vector3(s, 0.5, -s), new THREE.Vector3(0, 0.5, -s)]),
      new THREE.LineBasicMaterial({ color: 0x5ab0ff }));
    root.add(card);

    // koli kutuları: merkez (x, y) ölçüm düzleminde, y_ölçüm = -z
    for (const o of objs) {
      const ang = orientation(cl, o);
      const g = new THREE.Group();
      g.position.set(o.x, 0, -o.y); g.rotation.y = ang;
      const bg = new THREE.BoxGeometry(o.L, o.H, o.W); bg.translate(0, o.H / 2, 0);
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(bg), new THREE.LineBasicMaterial({ color: 0xf5b83d }));
      const fill = new THREE.Mesh(bg, new THREE.MeshBasicMaterial({ color: 0xf5b83d, transparent: true, opacity: 0.06, depthWrite: false }));
      const lb = label(String(o.id));
      lb.position.set(0, o.H + span * 0.04, 0);
      lb.scale.setScalar(span * 0.05);
      g.add(fill, edges, lb);
      g.userData = { id: o.id, edges, fill };
      boxes.push(g); root.add(g);
    }
    root.children.filter(c => boxes.includes(c)).forEach(c => { c.visible = $('#showBoxes').checked; });

    // kamera: önden-yukarıdan
    const dist = span * 1.35;
    home = { target: new THREE.Vector3(center.x, size.y * 0.3, center.z),
             pos: new THREE.Vector3(center.x + dist * 0.55, dist * 0.75, center.z + dist * 0.85) };
    resetView();
    $('#empty3d').hidden = true;
    $('#cloudinfo').textContent = `${m.toLocaleString('tr-TR')} / ${cl.n.toLocaleString('tr-TR')} nokta gösteriliyor`;
    dirty = true;
  }

  function resetView() {
    if (!home) return;
    controls.target.copy(home.target); cam.position.copy(home.pos); controls.update(); dirty = true;
  }

  function highlight(id) {
    for (const b of boxes) {
      const on = b.userData.id === id;
      b.userData.edges.material.color.set(on ? 0xffffff : 0xf5b83d);
      b.userData.fill.material.opacity = on ? 0.22 : 0.06;
    }
    tbody.querySelectorAll('tr').forEach(tr => tr.classList.toggle('hl', Number(tr.dataset.id) === id));
    dirty = true;
  }

  $('#showBoxes').addEventListener('change', e => { boxes.forEach(b => { b.visible = e.target.checked; }); dirty = true; });
  $('#resetView').addEventListener('click', resetView);
  return { show, clear, highlight };
})();

clearResults();
