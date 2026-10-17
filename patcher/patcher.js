// Builds a release image from Zoom's own L6 v1.10 L6.BIN and a release
// recipe (tools/firmware/recipe.py writes recipes; its rebuild() is the
// reference for build() below). Runs in the browser and in Node; nothing is
// uploaded. The input must hash to the recipe's stock hash and the result to
// its published image hash, or nothing is returned.

export class PatchError extends Error {
  constructor(kind, detail) {
    super(kind);
    this.kind = kind;       // 'recipe' | 'stock' | 'result'
    this.detail = detail;   // the hash that did not match
  }
}

export async function sha256(bytes) {
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  return Array.from(digest, (b) => b.toString(16).padStart(2, '0')).join('');
}

function unbase64(text) {
  const raw = atob(text);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

// The compressed DSP stream: the skeleton's token headers with the literal
// bytes taken, in order, from the user's own stock DSP record (with the
// recipe's few DSP edits, if any, applied to it first).
export function clothe(skeleton, plain) {
  const out = [];
  let c = 0;
  let p = 0;
  while (p < plain.length) {
    const flags = skeleton[c++];
    out.push(flags);
    let literals = flags & 7;
    if (!literals) { literals = skeleton[c++]; out.push(literals); }
    literals -= 1;
    let run = flags >> 4;
    if (!run) { run = skeleton[c++]; out.push(run); }
    for (let k = 0; k < literals; k++) out.push(plain[p + k]);
    p += literals;
    if (flags & 8) { out.push(skeleton[c++]); run += 2; }
    p += run;
  }
  if (c !== skeleton.length) throw new PatchError('recipe', 'skeleton');
  return Uint8Array.from(out);
}

export async function build(stock, recipe) {
  if (recipe.format !== 1 && recipe.format !== 2) throw new PatchError('recipe', String(recipe.format));
  const stockHash = await sha256(stock);
  if (stockHash !== recipe.stock_sha256) throw new PatchError('stock', stockHash);
  const image = Uint8Array.from(stock);
  const s = recipe.span;
  const span = new Uint8Array(s.length).fill(s.fill);
  const plain = Uint8Array.from(stock.subarray(s.literals_from, s.literals_from + s.length));
  for (const [offset, data] of s.dsp_edits || []) plain.set(unbase64(data), offset);
  span.set(clothe(unbase64(s.skeleton), plain), 0);
  span.set(unbase64(s.code), s.code_at);
  image.set(span, s.offset);
  for (const op of recipe.ops) {
    if (op[0] === 'put') image.set(unbase64(op[2]), op[1]);
    else if (op[0] === 'copy') image.set(stock.subarray(op[2], op[2] + op[3]), op[1]);
    else throw new PatchError('recipe', op[0]);
  }
  let sum = 0;
  for (let i = recipe.checksum.sum_from; i < image.length; i++) sum = (sum + image[i]) >>> 0;
  new DataView(image.buffer).setUint32(recipe.checksum.offset, sum, false);
  const hash = await sha256(image);
  if (hash !== recipe.image_sha256) throw new PatchError('result', hash);
  return { image, hash, stockHash };
}
