/**
 * The token dictionary: every indexed token, sorted by UTF-16 code units,
 * stored as one flat character array so loading makes no string per token.
 */
export class Dictionary {
  /** Characters of every token, back to back. */
  readonly chars: Uint16Array;
  /** Token id to the start of its characters (length count + 1). */
  readonly offsets: Uint32Array;
  readonly count: number;

  constructor(chars: Uint16Array, offsets: Uint32Array) {
    this.chars = chars;
    this.offsets = offsets;
    this.count = offsets.length - 1;
  }

  /** Builds a dictionary from sorted, distinct token strings (tests, tools). */
  static fromTokens(tokens: readonly string[]): Dictionary {
    const offsets = new Uint32Array(tokens.length + 1);
    let total = 0;
    tokens.forEach((t, i) => {
      total += t.length;
      offsets[i + 1] = total;
    });
    const chars = new Uint16Array(total);
    tokens.forEach((t, i) => {
      const at = offsets[i] ?? 0;
      for (let k = 0; k < t.length; k++) chars[at + k] = t.charCodeAt(k);
    });
    return new Dictionary(chars, offsets);
  }

  length(id: number): number {
    return (this.offsets[id + 1] ?? 0) - (this.offsets[id] ?? 0);
  }

  token(id: number): string {
    return String.fromCharCode(
      ...this.chars.subarray(this.offsets[id] ?? 0, this.offsets[id + 1] ?? 0),
    );
  }
}

/**
 * A trie over the sorted dictionary, stored as flat arrays in preorder.
 *
 * Because the dictionary is sorted, the tokens under any node form one
 * contiguous id range [lo, hi), so "every token starting with x" is a single
 * range, and so are its postings. Children of node n start at n + 1 and each
 * child's next sibling starts where the child's subtree ends.
 */
export class TokenTrie {
  readonly nodeCount: number;
  private readonly dict: Dictionary;
  private readonly ch: Uint16Array;
  private readonly end: Int32Array;
  private readonly lo: Int32Array;
  private readonly hi: Int32Array;
  private readonly maxDepth: number;

  /** The dictionary must be sorted by UTF-16 code units, without repeats. */
  constructor(dict: Dictionary) {
    this.dict = dict;
    const { chars, offsets, count: tokenCount } = dict;
    let nodes = 1;
    let maxDepth = 0;
    const shared = new Uint8Array(tokenCount);
    for (let i = 0; i < tokenCount; i++) {
      const start = offsets[i] ?? 0;
      const len = (offsets[i + 1] ?? 0) - start;
      let l = 0;
      if (i > 0) {
        const prevStart = offsets[i - 1] ?? 0;
        const prevLen = start - prevStart;
        const max = prevLen < len ? prevLen : len;
        while (l < max && chars[prevStart + l] === chars[start + l]) l++;
        if (l === len) throw new Error('Snowlight search: dictionary is not sorted and distinct');
      }
      shared[i] = l;
      nodes += len - l;
      if (len > maxDepth) maxDepth = len;
    }
    this.nodeCount = nodes;
    this.maxDepth = maxDepth;
    const ch = (this.ch = new Uint16Array(nodes));
    const end = (this.end = new Int32Array(nodes));
    const lo = (this.lo = new Int32Array(nodes));
    const hi = (this.hi = new Int32Array(nodes));

    const stack = new Int32Array(maxDepth + 1);
    let top = 0; // stack[0..top] is the path; stack[d] sits at depth d
    let n = 1;
    for (let i = 0; i < tokenCount; i++) {
      const start = offsets[i] ?? 0;
      const len = (offsets[i + 1] ?? 0) - start;
      const l = shared[i] ?? 0;
      while (top > l) {
        const node = stack[top--] ?? 0;
        end[node] = n;
        hi[node] = i;
      }
      for (let d = l; d < len; d++) {
        const node = n++;
        ch[node] = chars[start + d] ?? 0;
        lo[node] = i;
        stack[++top] = node;
      }
    }
    while (top >= 0) {
      const node = stack[top--] ?? 0;
      end[node] = n;
      hi[node] = tokenCount;
    }
  }

  /** The node spelling exactly `s`, or -1. */
  find(s: string): number {
    const { ch, end } = this;
    let node = 0;
    for (let d = 0; d < s.length; d++) {
      const c = s.charCodeAt(d);
      const stop = end[node] ?? 0;
      let child = node + 1;
      let found = -1;
      while (child < stop) {
        const cc = ch[child] ?? 0;
        if (cc === c) {
          found = child;
          break;
        }
        if (cc > c) break;
        child = end[child] ?? stop;
      }
      if (found < 0) return -1;
      node = found;
    }
    return node;
  }

  /** Token id of exactly `s`, or -1. */
  exact(s: string): number {
    const node = this.find(s);
    if (node < 0) return -1;
    const first = this.lo[node] ?? 0;
    return this.dict.length(first) === s.length ? first : -1;
  }

  /** Token id range [lo, hi) of every token starting with `s`; empty when none. */
  prefix(s: string): readonly [number, number] {
    const node = this.find(s);
    if (node < 0) return [0, 0];
    return [this.lo[node] ?? 0, this.hi[node] ?? 0];
  }

  /**
   * Appends to `out`, as lo, hi pairs, the token id ranges of every token
   * that starts with some string within `k` edits of `q` (optimal string
   * alignment distance: insertions, deletions, substitutions and adjacent
   * transpositions). Ranges may overlap.
   */
  fuzzy(q: string, k: number, out: number[]): void {
    const m = q.length;
    if (m === 0 || k <= 0) return;
    const width = m + 1;
    const rows = new Int32Array((this.maxDepth + 2) * width);
    for (let j = 0; j <= m; j++) rows[j] = j;
    const qc = new Uint16Array(m);
    for (let j = 0; j < m; j++) qc[j] = q.charCodeAt(j);
    const path = new Uint16Array(this.maxDepth + 1);
    const { ch, end, lo, hi } = this;

    const visit = (node: number, d: number): void => {
      const stop = end[node] ?? 0;
      const prevRow = d * width;
      const row = prevRow + width;
      const prevPrevRow = prevRow - width;
      const parentChar = d > 0 ? (path[d - 1] ?? 0) : -1;
      for (let child = node + 1; child < stop; child = end[child] ?? stop) {
        const c = ch[child] ?? 0;
        rows[row] = d + 1;
        let rowMin = d + 1;
        for (let j = 1; j <= m; j++) {
          const qj = qc[j - 1] ?? 0;
          let v = (rows[prevRow + j - 1] ?? 0) + (qj === c ? 0 : 1);
          const del = (rows[prevRow + j] ?? 0) + 1;
          if (del < v) v = del;
          const ins = (rows[row + j - 1] ?? 0) + 1;
          if (ins < v) v = ins;
          if (j > 1 && d > 0 && qj === parentChar && qc[j - 2] === c) {
            const tr = (rows[prevPrevRow + j - 2] ?? 0) + 1;
            if (tr < v) v = tr;
          }
          rows[row + j] = v;
          if (v < rowMin) rowMin = v;
        }
        if ((rows[row + m] ?? 0) <= k) {
          out.push(lo[child] ?? 0, hi[child] ?? 0);
        } else if (rowMin <= k) {
          path[d] = c;
          visit(child, d + 1);
        }
      }
    };
    visit(0, 0);
  }
}

/**
 * Optimal string alignment distance between `q` and the closest prefix of
 * `s`, and that prefix's length (the longest of equally close ones, so
 * "lancastr" highlights all of "Lancaster"). Used to highlight typo matches.
 */
export function prefixDistance(q: string, s: string): { distance: number; length: number } {
  const m = q.length;
  const n = s.length;
  const width = m + 1;
  const rows = new Int32Array((n + 1) * width);
  for (let j = 0; j <= m; j++) rows[j] = j;
  let best = m;
  let bestLen = 0;
  for (let i = 1; i <= n; i++) {
    const c = s.charCodeAt(i - 1);
    const row = i * width;
    rows[row] = i;
    for (let j = 1; j <= m; j++) {
      const qj = q.charCodeAt(j - 1);
      let v = (rows[row - width + j - 1] ?? 0) + (qj === c ? 0 : 1);
      v = Math.min(v, (rows[row - width + j] ?? 0) + 1, (rows[row + j - 1] ?? 0) + 1);
      if (i > 1 && j > 1 && qj === s.charCodeAt(i - 2) && q.charCodeAt(j - 2) === c) {
        v = Math.min(v, (rows[row - 2 * width + j - 2] ?? 0) + 1);
      }
      rows[row + j] = v;
    }
    const d = rows[row + m] ?? m;
    if (d <= best) {
      best = d;
      bestLen = i;
    }
  }
  return { distance: best, length: bestLen };
}

/** Optimal string alignment distance between two whole strings. */
export function editDistance(a: string, b: string): number {
  const m = b.length;
  const n = a.length;
  const width = m + 1;
  const rows = new Int32Array((n + 1) * width);
  for (let j = 0; j <= m; j++) rows[j] = j;
  for (let i = 1; i <= n; i++) {
    const c = a.charCodeAt(i - 1);
    const row = i * width;
    rows[row] = i;
    for (let j = 1; j <= m; j++) {
      const bj = b.charCodeAt(j - 1);
      let v = (rows[row - width + j - 1] ?? 0) + (bj === c ? 0 : 1);
      v = Math.min(v, (rows[row - width + j] ?? 0) + 1, (rows[row + j - 1] ?? 0) + 1);
      if (i > 1 && j > 1 && bj === a.charCodeAt(i - 2) && b.charCodeAt(j - 2) === c) {
        v = Math.min(v, (rows[row - 2 * width + j - 2] ?? 0) + 1);
      }
      rows[row + j] = v;
    }
  }
  return rows[n * width + m] ?? 0;
}
