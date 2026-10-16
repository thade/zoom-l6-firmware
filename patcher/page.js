// The patcher page: make the file, then send it to the mixer or copy it to
// the card. Loaded as a module from index.html (no inline script, so the
// page's Content Security Policy allows only this site's own code).
import { build, sha256, PatchError } from './patcher.js';
import { Mixer, MixerError, supported, writeFirmware } from './mixer.js';
import { isZip, unzip } from './zip.js';

const $ = (id) => document.getElementById(id);
const short = (h) => h.slice(0, 8) + '…' + h.slice(-7);
const params = new URLSearchParams(location.search);
let recipe = null;
let url = null;
let made = null;   // the built image and its hash

// Section 3 shows one route: send to the mixer where the browser can, else
// (or on request) download and copy the file to the card yourself.
const canSend = supported();
let current = canSend ? 'send' : 'copy';
function route(r) {
  current = r;
  const send = r === 'send';
  $('send').hidden = !send || !made;
  $('sendWait').hidden = !send || Boolean(made);
  $('guide').hidden = send;
  $('downloadBox').hidden = !made;
  $('sendNo').hidden = canSend;
  $('toSend').hidden = !canSend;
}
route(current);

async function loadRecipe() {
  const index = await (await fetch('recipes/index.json', { cache: 'no-cache' })).json();
  const version = index.versions.includes(params.get('version')) ? params.get('version') : index.current;
  recipe = await (await fetch(`recipes/${version}.json`, { cache: 'no-cache' })).json();
  $('version').textContent = recipe.version;
  $('footHash').textContent = short(recipe.image_sha256);
  chooserState();
}

// The current step's numeral is red.
function setStep(n) {
  for (let i = 1; i <= 4; i++) $('n' + i).classList.toggle('now', i === n);
}

function show(which) {
  for (const id of ['done', 'wrong', 'mismatch']) $(id).hidden = id !== which;
}

// The L6.BIN inside Zoom's zip (any folder, any case), or the file itself.
async function stockFrom(file) {
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (isZip(bytes)) {
    const entries = await unzip(bytes, (name) => /(^|\/)l6\.bin$/i.test(name));
    const names = Object.keys(entries);
    for (const name of names) if (await sha256(entries[name]) === recipe.stock_sha256) return { bytes: entries[name], label: `${file.name} → ${name}` };
    return { bytes: names.length ? entries[names[0]] : bytes, label: names.length ? `${file.name} → ${names[0]}` : file.name };
  }
  return { bytes, label: file.name };
}

async function handle(file) {
  if (!$('accept').checked || !recipe) return;
  $('status').textContent = 'Making the file…';
  show(null);
  made = null;
  route(current);
  let input;
  try { input = await stockFrom(file); } catch (e) {
    $('wrongDetail').textContent = `${file.name}: ${e.message}`;
    show('wrong');
    $('status').textContent = '';
    return;
  }
  const { bytes, label } = input;
  try {
    const result = await build(bytes, recipe);
    if (url) URL.revokeObjectURL(url);
    url = URL.createObjectURL(new Blob([result.image], { type: 'application/octet-stream' }));
    $('download').href = url;
    $('stockHash').textContent = `${label} · ${bytes.length.toLocaleString()} bytes · SHA-256 ${short(result.stockHash)}`;
    $('sameLine').textContent = `Identical to ${recipe.version}`;
    $('imageHash').textContent = 'SHA-256 ' + result.hash;
    made = result;
    route(current);
    show('done');
    setStep(3);
    $('status').textContent = `Made the ${recipe.version} firmware file.`;
    $('install').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) {
    if (e instanceof PatchError && e.kind === 'stock') {
      $('wrongDetail').textContent = `You dropped: ${label} · ${bytes.length.toLocaleString()} bytes · SHA-256 ${short(e.detail)} (expected ${short(recipe.stock_sha256)})`;
      show('wrong');
    } else {
      $('mismatchDetail').textContent = e instanceof PatchError ? `${e.kind}: ${e.detail}` : String(e && e.message || e);
      show('mismatch');
    }
    $('status').textContent = '';
  }
}

// The chooser works once the risks are accepted and the recipe is loaded.
function chooserState() {
  const on = $('accept').checked && Boolean(recipe);
  $('choose').disabled = !on;
  $('drop').classList.toggle('off', !on);
  $('dropNote').textContent = !$('accept').checked ? 'Tick the box above first. The file stays on your computer.'
    : recipe ? 'The file stays on your computer.' : 'Loading…';
}
$('accept').addEventListener('change', () => {
  chooserState();
  setStep(made ? 3 : $('accept').checked ? 2 : 1);
});
$('choose').addEventListener('click', () => $('file').click());
$('file').addEventListener('change', (e) => { if (e.target.files[0]) handle(e.target.files[0]); e.target.value = ''; });
const drop = $('drop');
drop.addEventListener('dragover', (e) => { e.preventDefault(); if (!$('choose').disabled) drop.classList.add('over'); });
drop.addEventListener('dragleave', () => drop.classList.remove('over'));
drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('over'); if (e.dataTransfer.files[0]) handle(e.dataTransfer.files[0]); });
$('download').addEventListener('click', () => setStep(4));
$('toCopy').addEventListener('click', () => route('copy'));
$('toSendLink').addEventListener('click', () => route('send'));

// Send to the mixer: each task unlocks the next.
let mixer = null;
let card = null;          // the folder written in task c
let warnedMounted = false;
function task(n, text, kind) {
  const t = $('t' + n);
  if (text !== undefined) t.textContent = text;
  t.classList.toggle('err', kind === 'err');
  const li = $('m' + n);
  li.classList.toggle('ok', kind === 'ok');
  li.classList.toggle('wait', kind === 'wait');
  li.classList.toggle('now', kind === 'now' || kind === 'err');
}
function unlock(n) { $('b' + n).disabled = false; task(n, undefined, 'now'); }
function failText(e) {
  if (e instanceof MixerError) {
    if (e.kind === 'permission') return 'MIDI access was not allowed. Allow it in the browser (the icon in the address bar) and try again.';
    if (e.kind === 'absent') return 'No L6 answered. Check the USB cable, that the L6 is on, and that ZOOM L6 Editor is closed.';
    return e.message;
  }
  if (e && e.name === 'AbortError') return 'No folder chosen.';
  return (e && e.message) || String(e);
}
async function step(n, fn) {
  const b = $('b' + n);
  b.disabled = true;
  try { await fn(); } catch (e) { task(n, failText(e), 'err'); b.disabled = false; }
}
// Still able to list the card's folders: probably not ejected yet.
async function stillMounted(dir) {
  try { await dir.getDirectoryHandle('SOUND_PAD'); return true; } catch { return false; }
}
$('b1').addEventListener('click', () => step(1, async () => {
  task(1, 'Connecting…', 'now');
  mixer = await Mixer.connect();
  task(1, 'Connected.', 'ok');
  if (mixer.firstState === 1) { task(2, 'Already in File Transfer Mode.', 'ok'); unlock(3); } else unlock(2);
}));
$('b2').addEventListener('click', () => step(2, async () => {
  task(2, 'Asking the L6…', 'now');
  await mixer.enter();
  task(2, 'In File Transfer Mode: wait until the card shows up as a drive (a few seconds).', 'ok');
  unlock(3);
}));
$('b3').addEventListener('click', () => step(3, async () => {
  const dir = await window.showDirectoryPicker({ id: 'l6-card', mode: 'readwrite' });
  task(3, 'Writing L6.BIN…', 'now');
  const back = await writeFirmware(dir, made.image, sha256);
  if (back.hash !== made.hash || back.bytes !== made.image.length) throw new MixerError('verify', 'L6.BIN on the card does not match: write it again.');
  card = dir;
  task(3, `L6.BIN written to the card${dir.name ? ` “${dir.name}”` : ''} and checked.`, 'ok');
  $('ejected').disabled = false;
  task(4, undefined, 'now');
}));
$('ejected').addEventListener('change', () => { $('b4').disabled = !$('ejected').checked; });
$('b4').addEventListener('click', () => step(4, async () => {
  if (card && !warnedMounted && await stillMounted(card)) {
    warnedMounted = true;
    throw new MixerError('mounted', 'The card still seems to be on this computer. Eject it first; if you already have, press Leave again.');
  }
  task(4, 'Leaving File Transfer Mode (up to a minute: the L6 reconnects)…', 'now');
  const r = await mixer.exit();
  if (r.state === 0) {
    task(4, 'Done: the L6 is out of File Transfer Mode.', 'ok');
    $('sendNext').hidden = false;
    setStep(4);
  } else if (r.state === 1) {
    throw new MixerError('exit', 'The L6 is still in File Transfer Mode. Check the card is ejected, then try again.');
  } else {
    throw new MixerError('exit', 'The L6 has not reconnected yet. Wait a few seconds, then press the button again to check.');
  }
}));

loadRecipe().catch(() => { $('status').textContent = 'Could not load the release recipe. Reload the page to try again.'; });
