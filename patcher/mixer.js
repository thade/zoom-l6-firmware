// Send the firmware file to the mixer from the browser: File Transfer Mode
// over USB MIDI (Web MIDI with SysEx), then L6.BIN written to the card
// (File System Access API). Chrome and Edge on desktop computers. The
// mixer still updates itself only from the card, at power-on with PLAY/STOP
// held, so the page cannot do that last step.
//
// The MIDI side sends only the fixed messages tools/device/l6_transfer_mode.py
// sends on hardware (identity, editor open, heartbeat, 31 09 01/00), in the
// same order and with the same timing; its docstring explains the stock
// session states. Byte 23 of the editor-open reply is 1 in File Transfer
// Mode and 0 otherwise.

export const IDENTITY = [0xf0, 0x7e, 0x00, 0x06, 0x01, 0xf7];
export const EDITOR_OPEN = [0xf0, 0x52, 0, 0, 0x2b, 0xf7];
export const HEARTBEAT = [0xf0, 0x52, 0, 0, 0x31, 0x0b, 0xf7];
export const TRANSFER_ON = [0xf0, 0x52, 0, 0, 0x31, 0x09, 0x01, 0xf7];
export const TRANSFER_OFF = [0xf0, 0x52, 0, 0, 0x31, 0x09, 0x00, 0xf7];
const ALLOWED = [IDENTITY, EDITOR_OPEN, HEARTBEAT, TRANSFER_ON, TRANSFER_OFF].map(String);
const EDITOR_REPLY = [0xf0, 0x52, 0, 0, 0x2a];
const ACK_TRANSFER = [0xf0, 0x52, 0, 0, 0x00, 0x09, 0xf7];
const MODE_BYTE = 23;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const starts = (msg, prefix) => prefix.every((b, i) => msg[i] === b);
const same = (msg, other) => msg.length === other.length && starts(msg, other);

export function supported(nav = globalThis.navigator, win = globalThis) {
  return Boolean(nav && nav.requestMIDIAccess && win.showDirectoryPicker && win.isSecureContext !== false);
}

export class MixerError extends Error {
  constructor(kind, message) { super(message); this.kind = kind; }
}

// One input and output pair on the mixer's Editor port.
class Link {
  constructor(input, output) {
    this.input = input; this.output = output; this.queue = []; this.waiters = [];
    this.handler = (e) => {
      const msg = Array.from(e.data);
      if (msg[0] !== 0xf0) return;
      const w = this.waiters.find((x) => x.match(msg));
      if (w) { this.waiters.splice(this.waiters.indexOf(w), 1); w.resolve(msg); } else this.queue.push(msg);
    };
    input.addEventListener('midimessage', this.handler);
  }
  close() { this.input.removeEventListener('midimessage', this.handler); }
  send(msg) {
    if (!ALLOWED.includes(String(msg))) throw new MixerError('internal', 'only fixed transfer-mode messages may be sent');
    this.output.send(msg);
  }
  // The first message matching within ms (queued ones first), or null.
  expect(match, ms) {
    const i = this.queue.findIndex(match);
    if (i >= 0) return Promise.resolve(this.queue.splice(i, 1)[0]);
    return new Promise((resolve) => {
      const w = { match, resolve };
      this.waiters.push(w);
      setTimeout(() => { const k = this.waiters.indexOf(w); if (k >= 0) { this.waiters.splice(k, 1); resolve(null); } }, ms);
    });
  }
  drain() { this.queue.length = 0; }
  // Session state 2; the editor-open reply, or null.
  async openSession() {
    this.drain();
    for (let k = 0; k < 2; k++) {
      this.send(IDENTITY);
      if (await this.expect(() => true, 2000)) break;
    }
    this.send(EDITOR_OPEN);
    return this.expect((m) => starts(m, EDITOR_REPLY) && m.length > MODE_BYTE, 2000);
  }
  async heartbeats(count = 12) {
    await sleep(320);
    for (let i = 0; i < count; i++) {
      this.send(HEARTBEAT);
      if (i === 0) await this.expect(() => true, 450); else await sleep(100);
    }
    await sleep(260);
  }
}

export class Mixer {
  constructor(access) { this.access = access; }

  static async connect(nav = globalThis.navigator) {
    let access;
    try { access = await nav.requestMIDIAccess({ sysex: true }); } catch (e) {
      throw new MixerError('permission', 'MIDI access was not allowed');
    }
    const mixer = new Mixer(access);
    const state = await mixer.state();
    if (state === null) throw new MixerError('absent', 'No L6 found on USB');
    return mixer;
  }

  // Candidate Editor port pairs: an L6 port named for the Editor first, then
  // any other L6 port (Windows names ports differently).
  pairs() {
    const l6 = (p) => /\bL6\b/i.test(`${p.name} ${p.manufacturer}`) && p.state !== 'disconnected';
    const ins = [...this.access.inputs.values()].filter(l6);
    const outs = [...this.access.outputs.values()].filter(l6);
    const rank = (p) => (/editor/i.test(p.name) ? 0 : 1);
    const out = [];
    for (const i of ins) for (const o of outs) out.push([i, o]);
    return out.sort((a, b) => rank(a[0]) + rank(a[1]) - rank(b[0]) - rank(b[1]));
  }

  // Run fn on a link over the first pair that answers the editor open.
  async withLink(fn) {
    for (const [input, output] of this.pairs()) {
      const link = new Link(input, output);
      try {
        const reply = await link.openSession();
        if (reply) return await fn(link, reply);
      } finally { link.close(); }
    }
    return undefined;
  }

  // 1 in File Transfer Mode, 0 not, null when no L6 answers.
  async state() {
    const mode = await this.withLink(async (link, reply) => reply[MODE_BYTE]);
    return mode === undefined ? null : mode ? 1 : 0;
  }

  async enter() {
    const result = await this.withLink(async (link, reply) => {
      if (reply[MODE_BYTE]) return 'already';
      link.send(TRANSFER_ON);
      return (await link.expect((m) => same(m, ACK_TRANSFER), 1000)) ? 'acknowledged' : 'sent';
    });
    if (result === undefined) throw new MixerError('absent', 'No L6 answered');
    return result;
  }

  // The card must be ejected first. The mixer re-enumerates on USB when it
  // leaves File Transfer Mode, so the result is read from a new session.
  async exit({ attempts = 2, settle = 40000 } = {}) {
    for (let attempt = 1; attempt <= attempts; attempt++) {
      const sent = await this.withLink(async (link) => {
        await link.heartbeats(); await sleep(1000);          // the prime pass
        const reply = await link.openSession();
        if (reply && !reply[MODE_BYTE]) return 'already';
        await link.heartbeats();
        if (!reply) return 'no-session';
        link.send(TRANSFER_OFF);
        return (await link.expect((m) => same(m, ACK_TRANSFER), 1000)) ? 'acknowledged' : 'sent';
      });
      if (sent === 'already') return { attempt, state: 0 };
      if (sent === undefined) throw new MixerError('absent', 'No L6 answered');
      await sleep(3000);
      let state = null;
      const deadline = Date.now() + settle;
      while (state === null && Date.now() < deadline) {
        state = await this.state();
        if (state === null) await sleep(2000);
      }
      if (state !== 1) return { attempt, state };
    }
    return { attempt: attempts, state: 1 };
  }
}

// The card in File Transfer Mode (or a card reader): an L6 card has
// SOUND_PAD/PAD1..PAD4 at its top.
export async function isL6Card(dir) {
  try {
    const pads = await dir.getDirectoryHandle('SOUND_PAD');
    for (let n = 1; n <= 4; n++) await pads.getDirectoryHandle(`PAD${n}`);
    return true;
  } catch { return false; }
}

// Write L6.BIN at the card's top and read it back. Returns the read-back
// hash (the caller compares it with the image's).
export async function writeFirmware(dir, image, sha256) {
  if (!(await isL6Card(dir))) throw new MixerError('not-card', 'That folder is not an L6 card (no SOUND_PAD/PAD1–PAD4)');
  const handle = await dir.getFileHandle('L6.BIN', { create: true });
  const out = await handle.createWritable();
  try { await out.write(image); await out.close(); } catch (e) {
    try { await out.abort(); } catch {}
    throw new MixerError('write', `Writing L6.BIN failed: ${e.message}`);
  }
  const back = new Uint8Array(await (await handle.getFile()).arrayBuffer());
  return { bytes: back.length, hash: await sha256(back) };
}
