// Read named files from a zip archive with the browser's own deflate
// decoder (DecompressionStream, also in Node 18+), so the page loads no
// third-party code. Enough for Zoom's firmware zip: stored or deflated
// entries, no zip64, no encryption.

const u16 = (b, o) => b[o] | (b[o + 1] << 8);
const u32 = (b, o) => (b[o] | (b[o + 1] << 8) | (b[o + 2] << 16) | (b[o + 3] << 24)) >>> 0;

export const isZip = (b) => b.length > 4 && u32(b, 0) === 0x04034b50;

async function inflate(data) {
  const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

// Entries whose name passes want(name), as { name: bytes }.
export async function unzip(bytes, want) {
  let end = -1;
  for (let o = bytes.length - 22; o >= Math.max(0, bytes.length - 22 - 65535); o--) {
    if (u32(bytes, o) === 0x06054b50) { end = o; break; }
  }
  if (end < 0) throw new Error('not a zip file (no central directory)');
  const count = u16(bytes, end + 10);
  let at = u32(bytes, end + 16);
  const out = {};
  for (let n = 0; n < count; n++) {
    if (u32(bytes, at) !== 0x02014b50) throw new Error('damaged zip central directory');
    const method = u16(bytes, at + 10);
    const flags = u16(bytes, at + 8);
    const packed = u32(bytes, at + 20);
    const size = u32(bytes, at + 24);
    const nameLength = u16(bytes, at + 28);
    const extraLength = u16(bytes, at + 30);
    const commentLength = u16(bytes, at + 32);
    const local = u32(bytes, at + 42);
    const name = new TextDecoder().decode(bytes.subarray(at + 46, at + 46 + nameLength));
    at += 46 + nameLength + extraLength + commentLength;
    if (!want(name) || name.endsWith('/')) continue;
    if (flags & 1) throw new Error(`${name} is encrypted`);
    if (u32(bytes, local) !== 0x04034b50) throw new Error('damaged zip entry');
    const start = local + 30 + u16(bytes, local + 26) + u16(bytes, local + 28);
    const data = bytes.subarray(start, start + packed);
    let file;
    if (method === 0) file = Uint8Array.from(data);
    else if (method === 8) file = await inflate(data);
    else throw new Error(`${name} uses an unsupported compression method`);
    if (file.length !== size) throw new Error(`${name} did not unpack to its recorded size`);
    out[name] = file;
  }
  return out;
}
