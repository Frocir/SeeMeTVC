import type { Edge, Node } from "@xyflow/react";
import type { WfData } from "./types";

/** Same grid as official templates. */
export const LAYOUT_NODE_W = 300;
export const LAYOUT_NODE_H = 320;
export const LAYOUT_GAP_X = 140;
export const LAYOUT_GAP_Y = 120;
export const LAYOUT_ORIGIN_X = 64;
export const LAYOUT_ORIGIN_Y = 64;

const COL = LAYOUT_NODE_W + LAYOUT_GAP_X;
const ROW = LAYOUT_NODE_H + LAYOUT_GAP_Y;
const WRAP = 4;
const COMPONENT_GAP = 80;
const SWEEPS = 8;
const TRANSPOSE_ROUNDS = 16;

type Adj = Map<string, string[]>;

export function applyDagLayout(nodes: Node<WfData>[], edges: Edge[]): Node<WfData>[] {
  if (nodes.length === 0) return nodes;
  const ids = nodes.map((n) => n.id);
  const idSet = new Set(ids);
  const order = new Map(ids.map((id, i) => [id, i]));
  const outgoing: Adj = new Map();
  const incoming: Adj = new Map();
  for (const id of ids) {
    outgoing.set(id, []);
    incoming.set(id, []);
  }
  for (const e of edges) {
    if (!idSet.has(e.source) || !idSet.has(e.target) || e.source === e.target) continue;
    const outs = outgoing.get(e.source)!;
    const ins = incoming.get(e.target)!;
    if (!outs.includes(e.target)) outs.push(e.target);
    if (!ins.includes(e.source)) ins.push(e.source);
  }

  const seen = new Set<string>();
  const components: string[][] = [];
  for (const id of ids) {
    if (seen.has(id)) continue;
    const stack = [id];
    const comp: string[] = [];
    seen.add(id);
    while (stack.length) {
      const cur = stack.pop()!;
      comp.push(cur);
      for (const n of [...(outgoing.get(cur) || []), ...(incoming.get(cur) || [])]) {
        if (!seen.has(n)) {
          seen.add(n);
          stack.push(n);
        }
      }
    }
    comp.sort((a, b) => (order.get(a) || 0) - (order.get(b) || 0));
    components.push(comp);
  }

  const positions = new Map<string, { x: number; y: number }>();
  let offsetY = LAYOUT_ORIGIN_Y;
  for (const comp of components) {
    const local = layoutComponent(comp, outgoing, incoming, order);
    let minY = Infinity;
    let maxY = -Infinity;
    for (const id of comp) {
      const p = local.get(id)!;
      minY = Math.min(minY, p.y);
      maxY = Math.max(maxY, p.y);
    }
    const shift = offsetY - minY;
    for (const id of comp) {
      const p = local.get(id)!;
      positions.set(id, { x: p.x, y: p.y + shift });
    }
    offsetY = maxY + shift + ROW + COMPONENT_GAP;
  }

  return nodes.map((n) => {
    const p = positions.get(n.id);
    return p ? { ...n, position: p } : n;
  });
}

function layoutComponent(
  ids: string[],
  outgoing: Adj,
  incoming: Adj,
  order: Map<string, number>,
): Map<string, { x: number; y: number }> {
  const positions = new Map<string, { x: number; y: number }>();
  const inComp = (id: string, list: string[]) => list.filter((x) => ids.includes(x));
  const hasEdge = ids.some((id) => inComp(id, outgoing.get(id) || []).length > 0);
  if (!hasEdge) {
    ids.forEach((id, i) => {
      positions.set(id, {
        x: LAYOUT_ORIGIN_X + (i % WRAP) * COL,
        y: LAYOUT_ORIGIN_Y + Math.floor(i / WRAP) * ROW,
      });
    });
    return positions;
  }

  const rank = assignRanks(ids, outgoing, incoming);
  pullRootsTowardChildren(ids, outgoing, incoming, rank);
  compressRanks(rank);
  const proper = insertDummies(ids, outgoing, incoming, rank);
  const layers = buildLayers(proper.ids, rank, proper.dummies, order);
  const ranks = [...layers.keys()].sort((a, b) => a - b);
  reduceCrossings(layers, ranks, proper.out, proper.inn);
  const row = assignRows(layers, ranks, proper.out, proper.inn, proper.dummies);
  place(positions, ids, rank, row);
  return positions;
}

function emptyAdj(ids: string[]): Adj {
  const m: Adj = new Map();
  for (const id of ids) m.set(id, []);
  return m;
}

function link(out: Adj, inn: Adj, src: string, tgt: string) {
  const outs = out.get(src) || [];
  const ins = inn.get(tgt) || [];
  if (!outs.includes(tgt)) outs.push(tgt);
  if (!ins.includes(src)) ins.push(src);
  out.set(src, outs);
  inn.set(tgt, ins);
}

function unlink(out: Adj, inn: Adj, src: string, tgt: string) {
  out.set(src, (out.get(src) || []).filter((x) => x !== tgt));
  inn.set(tgt, (inn.get(tgt) || []).filter((x) => x !== src));
}

/** Split long edges so every edge spans exactly one rank (Sugiyama). */
function insertDummies(
  ids: string[],
  outgoing: Adj,
  incoming: Adj,
  rank: Map<string, number>,
): { ids: string[]; out: Adj; inn: Adj; dummies: Set<string> } {
  const out = emptyAdj(ids);
  const inn = emptyAdj(ids);
  for (const src of ids) {
    for (const tgt of outgoing.get(src) || []) {
      if (ids.includes(tgt)) link(out, inn, src, tgt);
    }
  }
  const dummies = new Set<string>();
  const longs: [string, string][] = [];
  for (const src of ids) {
    for (const tgt of [...(out.get(src) || [])]) {
      if ((rank.get(tgt) || 0) - (rank.get(src) || 0) > 1) longs.push([src, tgt]);
    }
  }
  let n = 0;
  for (const [src, tgt] of longs) {
    unlink(out, inn, src, tgt);
    let prev = src;
    for (let r = (rank.get(src) || 0) + 1; r < (rank.get(tgt) || 0); r += 1) {
      const dummy = `__d${n++}`;
      dummies.add(dummy);
      rank.set(dummy, r);
      out.set(dummy, []);
      inn.set(dummy, []);
      link(out, inn, prev, dummy);
      prev = dummy;
    }
    link(out, inn, prev, tgt);
  }
  return { ids: [...ids, ...dummies], out, inn, dummies };
}

function buildLayers(
  ids: string[],
  rank: Map<string, number>,
  dummies: Set<string>,
  order: Map<string, number>,
): Map<number, string[]> {
  const layers = new Map<number, string[]>();
  for (const id of ids) {
    const r = rank.get(id) || 0;
    const list = layers.get(r) || [];
    list.push(id);
    layers.set(r, list);
  }
  for (const list of layers.values()) {
    list.sort((a, b) => {
      const da = dummies.has(a) ? 1 : 0;
      const db = dummies.has(b) ? 1 : 0;
      if (da !== db) return da - db;
      return (order.get(a) || 0) - (order.get(b) || 0);
    });
  }
  return layers;
}

function cloneLayers(layers: Map<number, string[]>): Map<number, string[]> {
  return new Map([...layers.entries()].map(([k, v]) => [k, [...v]]));
}

function posMap(layer: string[]): Map<string, number> {
  return new Map(layer.map((id, i) => [id, i]));
}

function barycenter(id: string, neighbors: string[], pos: Map<string, number>, fallback: number): number {
  const vals = neighbors.map((n) => pos.get(n)).filter((v): v is number => v !== undefined);
  if (!vals.length) return fallback;
  return vals.reduce((a, b) => a + b, 0) / vals.length;
}

function countPairCrossings(left: string[], right: string[], out: Adj): number {
  const rightPos = posMap(right);
  const edges: [number, number][] = [];
  left.forEach((src, i) => {
    for (const tgt of out.get(src) || []) {
      const j = rightPos.get(tgt);
      if (j !== undefined) edges.push([i, j]);
    }
  });
  let crosses = 0;
  for (let i = 0; i < edges.length; i += 1) {
    for (let j = i + 1; j < edges.length; j += 1) {
      if ((edges[i][0] - edges[j][0]) * (edges[i][1] - edges[j][1]) < 0) crosses += 1;
    }
  }
  return crosses;
}

function countCrossings(layers: Map<number, string[]>, ranks: number[], out: Adj): number {
  let total = 0;
  for (let i = 0; i < ranks.length - 1; i += 1) {
    total += countPairCrossings(layers.get(ranks[i]) || [], layers.get(ranks[i + 1]) || [], out);
  }
  return total;
}

function sortByBarycenter(layer: string[], neighborPos: Map<string, number>, adj: Adj) {
  const keyed = layer.map((id, i) => ({
    id,
    key: barycenter(id, adj.get(id) || [], neighborPos, i),
    i,
  }));
  keyed.sort((a, b) => a.key - b.key || a.i - b.i);
  layer.splice(0, layer.length, ...keyed.map((x) => x.id));
}

function adjacentCrossings(
  layers: Map<number, string[]>,
  ranks: number[],
  idx: number,
  out: Adj,
): number {
  let n = 0;
  if (idx > 0) n += countPairCrossings(layers.get(ranks[idx - 1]) || [], layers.get(ranks[idx]) || [], out);
  if (idx < ranks.length - 1) {
    n += countPairCrossings(layers.get(ranks[idx]) || [], layers.get(ranks[idx + 1]) || [], out);
  }
  return n;
}

function transpose(layers: Map<number, string[]>, ranks: number[], out: Adj) {
  for (let round = 0; round < TRANSPOSE_ROUNDS; round += 1) {
    let improved = false;
    ranks.forEach((r, idx) => {
      const layer = layers.get(r) || [];
      for (let i = 0; i < layer.length - 1; i += 1) {
        const before = adjacentCrossings(layers, ranks, idx, out);
        const tmp = layer[i];
        layer[i] = layer[i + 1];
        layer[i + 1] = tmp;
        const after = adjacentCrossings(layers, ranks, idx, out);
        if (after < before) {
          improved = true;
        } else {
          layer[i + 1] = layer[i];
          layer[i] = tmp;
        }
      }
    });
    if (!improved) break;
  }
}

/** Barycenter + adjacent transpose; keep the order with fewest crossings. */
function reduceCrossings(layers: Map<number, string[]>, ranks: number[], out: Adj, inn: Adj) {
  let best = cloneLayers(layers);
  let bestX = countCrossings(layers, ranks, out);
  if (bestX === 0) return;
  for (let pass = 0; pass < SWEEPS; pass += 1) {
    if (pass % 2 === 0) {
      for (let i = 1; i < ranks.length; i += 1) {
        sortByBarycenter(layers.get(ranks[i]) || [], posMap(layers.get(ranks[i - 1]) || []), inn);
      }
    } else {
      for (let i = ranks.length - 2; i >= 0; i -= 1) {
        sortByBarycenter(layers.get(ranks[i]) || [], posMap(layers.get(ranks[i + 1]) || []), out);
      }
    }
    transpose(layers, ranks, out);
    const x = countCrossings(layers, ranks, out);
    if (x < bestX) {
      best = cloneLayers(layers);
      bestX = x;
      if (x === 0) break;
    }
  }
  for (const r of ranks) {
    const src = best.get(r) || [];
    const dst = layers.get(r) || [];
    dst.splice(0, dst.length, ...src);
  }
}

function median(vals: number[]): number {
  const s = [...vals].sort((a, b) => a - b);
  const mid = Math.floor((s.length - 1) / 2);
  return s.length % 2 ? s[mid] : (s[mid] + s[mid + 1]) / 2;
}

function realNeighbors(id: string, out: Adj, inn: Adj, dummies: Set<string>, row: Map<string, number>): number[] {
  return [...(inn.get(id) || []), ...(out.get(id) || [])]
    .filter((n) => row.has(n) && !dummies.has(n))
    .map((n) => row.get(n) || 0);
}

/** Tight block: same-layer nodes share a column and sit on consecutive rows. */
function placeCompactColumn(ids: string[], row: Map<string, number>, out: Adj, inn: Adj, dummies: Set<string>) {
  const desired = ids.map((id) => {
    const neigh = realNeighbors(id, out, inn, dummies, row);
    return neigh.length ? median(neigh) : 0;
  });
  const start = Math.round(median(desired) - (ids.length - 1) / 2);
  ids.forEach((id, i) => row.set(id, start + i));
}

/**
 * Dummy vertices only decide order. Real nodes: one rank = one column,
 * packed with no skipped rows, then nudged to face neighbors.
 */
function assignRows(
  layers: Map<number, string[]>,
  ranks: number[],
  out: Adj,
  inn: Adj,
  dummies: Set<string>,
): Map<string, number> {
  const real = new Map<number, string[]>();
  for (const r of ranks) {
    const list = (layers.get(r) || []).filter((id) => !dummies.has(id));
    if (list.length) real.set(r, list);
  }
  const cols = [...real.keys()].sort((a, b) => a - b);
  let pivot = cols[0] || 0;
  let pivotSize = -1;
  for (const r of cols) {
    const n = (real.get(r) || []).length;
    if (n > pivotSize) {
      pivot = r;
      pivotSize = n;
    }
  }

  const row = new Map<string, number>();
  (real.get(pivot) || []).forEach((id, i) => row.set(id, i));
  const sweep = [...cols.filter((r) => r > pivot), ...cols.filter((r) => r < pivot).reverse()];
  for (const r of sweep) placeCompactColumn(real.get(r) || [], row, out, inn, dummies);
  for (let pass = 0; pass < 2; pass += 1) {
    for (const r of cols) {
      if (r === pivot) continue;
      placeCompactColumn(real.get(r) || [], row, out, inn, dummies);
    }
  }
  return row;
}

function assignRanks(ids: string[], outgoing: Adj, incoming: Adj): Map<string, number> {
  const remaining = new Map(
    ids.map((id) => [id, (incoming.get(id) || []).filter((p) => ids.includes(p)).length]),
  );
  const rank = new Map(ids.map((id) => [id, 0]));
  const queue = ids.filter((id) => (remaining.get(id) || 0) === 0);
  let seen = 0;
  while (queue.length) {
    const nid = queue.shift()!;
    seen += 1;
    for (const tgt of outgoing.get(nid) || []) {
      if (!ids.includes(tgt)) continue;
      rank.set(tgt, Math.max(rank.get(tgt) || 0, (rank.get(nid) || 0) + 1));
      remaining.set(tgt, (remaining.get(tgt) || 1) - 1);
      if (remaining.get(tgt) === 0) queue.push(tgt);
    }
  }
  if (seen < ids.length) {
    const doneMax = Math.max(
      0,
      ...ids.map((id) => ((remaining.get(id) || 0) <= 0 ? rank.get(id) || 0 : 0)),
    );
    for (const nid of ids) {
      if ((remaining.get(nid) || 0) <= 0) continue;
      const preds = (incoming.get(nid) || []).filter(
        (p) => ids.includes(p) && (remaining.get(p) || 0) <= 0,
      );
      rank.set(nid, preds.length ? Math.max(...preds.map((p) => rank.get(p) || 0)) + 1 : doneMax + 1);
    }
  }
  return rank;
}

function compressRanks(rank: Map<string, number>) {
  const used = [...new Set(rank.values())].sort((a, b) => a - b);
  const remap = new Map(used.map((r, i) => [r, i]));
  for (const [id, r] of rank) rank.set(id, remap.get(r) ?? r);
}

function pullRootsTowardChildren(ids: string[], outgoing: Adj, incoming: Adj, rank: Map<string, number>) {
  for (const id of ids) {
    const preds = (incoming.get(id) || []).filter((p) => ids.includes(p));
    const succs = (outgoing.get(id) || []).filter((s) => ids.includes(s));
    if (preds.length || !succs.length) continue;
    rank.set(id, Math.max(0, Math.min(...succs.map((s) => rank.get(s) || 0)) - 1));
  }
}

function place(
  positions: Map<string, { x: number; y: number }>,
  ids: string[],
  rank: Map<string, number>,
  row: Map<string, number>,
) {
  for (const id of ids) {
    positions.set(id, {
      x: LAYOUT_ORIGIN_X + (rank.get(id) || 0) * COL,
      y: LAYOUT_ORIGIN_Y + (row.get(id) || 0) * ROW,
    });
  }
}
