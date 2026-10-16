// patcher/mixer.js against a modelled L6 Editor port and modelled card
// folders (run by verify_patcher.py). The model follows the stock session
// states in tools/device/l6_transfer_mode.py: identity 0 -> 1 with a reply
// and 1 -> 0 silently, editor open 1 -> 2 with a reply whose byte 23 is the
// transfer mode, 31 09 only in state 2, leaving transfer mode only after a
// primed session (heartbeats), then a USB re-enumeration with new ports.
import { Mixer, MixerError, writeFirmware, isL6Card, supported } from '../../patcher/mixer.js';
import { sha256 } from '../../patcher/patcher.js';
import { isZip, unzip } from '../../patcher/zip.js';
import { readFileSync } from 'node:fs';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class Port extends EventTarget {
  constructor(name, l6, kind) { super(); this.name = name; this.manufacturer = 'ZOOM Corporation'; this.state = 'connected'; this.l6 = l6; this.kind = kind; }
  send(msg) {
    if (this.l6.busy) throw Object.assign(new Error('port in use'), { name: 'InvalidStateError' });
    if (this.kind === 'editor') { this.l6.sent.push(Array.from(msg)); setTimeout(() => this.l6.receive(Array.from(msg)), 3); }
    else this.l6.leaked.push(Array.from(msg));
  }
}

class FakeL6 {
  constructor({ names = ['L6 for L6 Editor Port', 'L6 for L6 Editor Port'], extra = ['L6 Mixer Control Port', 'L6 MIDI I/O Port'], access } = {}) {
    this.names = names; this.extra = extra; this.session = 0; this.ftm = 0; this.beats = 0; this.sent = []; this.leaked = []; this.busy = false;
    this.access = access || { inputs: new Map(), outputs: new Map() };
    this.attach();
  }
  attach() {
    this.input = new Port(this.names[0], this, 'editor'); this.output = new Port(this.names[1], this, 'editor');
    const id = Math.random().toString(36).slice(2);
    this.access.inputs.set('in' + id, this.input); this.access.outputs.set('out' + id, this.output);
    for (const name of this.extra) {   // another L6 port that ignores Editor SysEx
      this.access.inputs.set('xi' + id + name, new Port(name, this, 'other'));
      this.access.outputs.set('xo' + id + name, new Port(name, this, 'other'));
    }
  }
  detach() { for (const m of [this.access.inputs, this.access.outputs]) for (const [k, p] of m) if (p.l6 === this) { p.state = 'disconnected'; m.delete(k); } }
  reply(msg) { this.input.dispatchEvent(Object.assign(new Event('midimessage'), { data: Uint8Array.from(msg) })); }
  receive(m) {
    const is = (x) => m.length === x.length && x.every((b, i) => m[i] === b);
    if (is([0xf0, 0x7e, 0x00, 0x06, 0x01, 0xf7])) {
      if (this.session === 1) { this.session = 0; return; }
      this.session = 1; this.reply([0xf0, 0x7e, 0x00, 0x06, 0x02, 0x52, 0x6a, 0, 0, 0, 0x31, 0x2e, 0x31, 0x30, 0xf7]);
    } else if (is([0xf0, 0x52, 0, 0, 0x2b, 0xf7])) {
      if (this.session !== 1) return;
      this.session = 2; this.beats = 0;
      const r = new Array(32).fill(0); r[0] = 0xf0; r[1] = 0x52; r[4] = 0x2a; r[23] = this.ftm; r[31] = 0xf7; this.reply(r);
    } else if (is([0xf0, 0x52, 0, 0, 0x31, 0x0b, 0xf7])) {
      if (this.session === 2) { this.beats++; if (this.beats === 1) this.reply([0xf0, 0x52, 0, 0, 0x31, 0x0b, 0x00, 0xf7]); }
    } else if (m[4] === 0x31 && m[5] === 0x09 && this.session === 2) {
      if (m[6] === 1) { this.reply([0xf0, 0x52, 0, 0, 0x00, 0x09, 0xf7]); this.ftm = 1; }
      else if (this.beats >= 12) {   // leaving needs the primed session
        this.reply([0xf0, 0x52, 0, 0, 0x00, 0x09, 0xf7]);
        setTimeout(() => { this.detach(); this.session = 0; this.ftm = 0; setTimeout(() => this.attach(), 1500); }, 50);
      }
    }
  }
  nav() { return { requestMIDIAccess: async (o) => { if (!o || !o.sysex) throw new Error('sysex'); return this.access; } }; }
}

class FakeFile {
  constructor() { this.data = new Uint8Array(0); }
  async createWritable() { const f = this; let parts = []; return { write: async (d) => { parts.push(Uint8Array.from(d)); }, close: async () => { const n = parts.reduce((a, p) => a + p.length, 0); f.data = new Uint8Array(n); let o = 0; for (const p of parts) { f.data.set(p, o); o += p.length; } }, abort: async () => { parts = []; } }; }
  async getFile() { const d = this.data; return { arrayBuffer: async () => d.buffer.slice(d.byteOffset, d.byteOffset + d.length) }; }
}
class FakeDir {
  constructor(name, dirs = {}) { this.name = name; this.dirs = dirs; this.files = {}; }
  async getDirectoryHandle(n) { if (!this.dirs[n]) throw Object.assign(new Error('not found'), { name: 'NotFoundError' }); return this.dirs[n]; }
  async getFileHandle(n, o = {}) { if (!this.files[n]) { if (!o.create) throw new Error('not found'); this.files[n] = new FakeFile(); } return this.files[n]; }
}
const card = () => new FakeDir('L6_SD', { SOUND_PAD: new FakeDir('SOUND_PAD', { PAD1: new FakeDir('PAD1'), PAD2: new FakeDir('PAD2'), PAD3: new FakeDir('PAD3'), PAD4: new FakeDir('PAD4') }), RECORDER: new FakeDir('RECORDER') });

const out = {};
const image = new Uint8Array(3756544).map((_, i) => (i * 31) & 255);
const imageHash = await sha256(image);

// The whole route: connect, enter, write and check, leave.
{
  const l6 = new FakeL6(); const mixer = await Mixer.connect(l6.nav());
  out.before = await mixer.state(); out.enter = await mixer.enter(); out.during = await mixer.state();
  const c = card(); const back = await writeFirmware(c, image, sha256);
  out.written = back.hash === imageHash && back.bytes === image.length;
  out.exit = await mixer.exit(); out.after = await mixer.state();
  out.only_fixed = l6.sent.every((m) => [6, 7, 8].includes(m.length) && m[0] === 0xf0 && m.at(-1) === 0xf7);
  out.other_ports_untouched = l6.leaked.length === 0;
  out.first_state = mixer.firstState;
}
// Two L6s: refused, nothing sent.
{
  const a = new FakeL6(); const b = new FakeL6({ access: a.access });
  try { await Mixer.connect(a.nav()); out.two = 'connected'; } catch (e) { out.two = e instanceof MixerError && e.kind; }
  out.two_silent = a.sent.length === 0 && b.sent.length === 0;
}
// The port held by another program (Windows, the Editor open).
{ const l6 = new FakeL6(); l6.busy = true; try { await Mixer.connect(l6.nav()); out.busy = 'connected'; } catch (e) { out.busy = e instanceof MixerError && e.kind; } }
// Zoom's zip read by zip.js (deflated and stored), as the page does.
for (const [key, path] of [['zip_deflated', process.argv[2]], ['zip_stored', process.argv[3]]]) {
  if (!path) continue;
  const bytes = new Uint8Array(readFileSync(path));
  const entries = await unzip(bytes, (n) => /(^|\/)l6\.bin$/i.test(n));
  out[key] = isZip(bytes) && Object.keys(entries).length === 1 ? await sha256(Object.values(entries)[0]) : null;
}
// Already in transfer mode; already out of it.
{ const l6 = new FakeL6(); l6.ftm = 1; const mixer = await Mixer.connect(l6.nav()); out.enter_again = await mixer.enter(); }
{ const l6 = new FakeL6(); const mixer = await Mixer.connect(l6.nav()); out.exit_when_out = await mixer.exit(); }
// Windows-style names: the Editor port beside another L6 port.
{ const l6 = new FakeL6({ names: ['MIDIIN2 (L6)', 'MIDIOUT2 (L6)'], extra: ['L6', 'MIDIIN3 (L6)'] }); const mixer = await Mixer.connect(l6.nav()); out.windows_names = await mixer.state(); out.windows_key = mixer.key; }
// Refusals: no permission, no L6, a folder that is not an L6 card.
try { await Mixer.connect({ requestMIDIAccess: async () => { throw new Error('denied'); } }); } catch (e) { out.denied = e instanceof MixerError && e.kind; }
try { await Mixer.connect({ requestMIDIAccess: async () => ({ inputs: new Map(), outputs: new Map() }) }); } catch (e) { out.absent = e instanceof MixerError && e.kind; }
try { await writeFirmware(new FakeDir('Desktop'), image, sha256); } catch (e) { out.not_card = e instanceof MixerError && e.kind; }
out.card_check = (await isL6Card(card())) && !(await isL6Card(new FakeDir('x')));
out.supported = [supported({ requestMIDIAccess() {} }, { showDirectoryPicker() {} }), supported({}, { showDirectoryPicker() {} }), supported({ requestMIDIAccess() {} }, {})];
console.log(JSON.stringify(out));
