"use client";

// ─── RelationGraph ─────────────────────────────────────────────────────────
// Relations family. Covers relation-circle / relation-dagre / relation-network
// as one component with a `variant` switch — all three share one nodes+edges
// data shape and differ only in layout algorithm. Deliberately deterministic,
// dependency-free layouts (no d3-force / dagre) sized for a handful of nodes
// in a chat card, not a full graph editor.

import { EmptyState } from "@/components/ui/EmptyState";
import { categoricalColor } from "./_palette";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface RelationNode {
  id: string;
  label: string;
  group?: number;
}

export interface RelationEdge {
  source: string;
  target: string;
  label?: string;
}

export interface RelationGraphProps {
  title?: string;
  variant?: "circle" | "dagre" | "network";
  nodes?: RelationNode[];
  edges?: RelationEdge[];
  canAct?: boolean;
}

type Point = { x: number; y: number };

const CARD = "bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 p-4";
const NODE_R = 8;

export function RelationGraph({ title, variant = "network", nodes = [], edges = [] }: RelationGraphProps) {
  if (nodes.length === 0) {
    return <EmptyState title="No nodes to graph" message="Supply at least one node to render this relation graph." />;
  }

  return (
    <div className={CARD}>
      {title && <p className="text-sm font-semibold text-lf-on-surface mb-3">{title}</p>}
      {variant === "circle" && <CircleLayout nodes={nodes} edges={edges} />}
      {variant === "dagre" && <DagreLayout nodes={nodes} edges={edges} />}
      {variant === "network" && <NetworkLayout nodes={nodes} edges={edges} />}
    </div>
  );
}

function Arrowhead({ id }: { id: string }) {
  return (
    <marker id={id} markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
      <path d="M0,0 L6,3 L0,6 Z" fill="#cbc3d7" />
    </marker>
  );
}

function EdgeLines({ nodes, edges, positions, markerId }: { nodes: RelationNode[]; edges: RelationEdge[]; positions: Map<string, Point>; markerId: string }) {
  const idSet = new Set(nodes.map((n) => n.id));
  return (
    <>
      {edges
        .filter((e) => idSet.has(e.source) && idSet.has(e.target))
        .map((e, i) => {
          const a = positions.get(e.source);
          const b = positions.get(e.target);
          if (!a || !b) return null;
          return <line key={`${e.source}-${e.target}-${i}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke="#cbc3d7" strokeWidth={1.5} markerEnd={`url(#${markerId})`} />;
        })}
    </>
  );
}

function NodeLabel({ node, p, color }: { node: RelationNode; p: Point; color: string }) {
  return (
    <div className="absolute flex flex-col items-center -translate-x-1/2 -translate-y-1/2 w-16" style={{ left: p.x, top: p.y }}>
      <span
        className="rounded-full flex items-center justify-center text-[9px] font-bold text-white shrink-0"
        style={{ width: NODE_R * 2 + 8, height: NODE_R * 2 + 8, backgroundColor: color }}
      >
        {node.label.slice(0, 2).toUpperCase()}
      </span>
      <span className="text-[9px] text-lf-on-surface-variant text-center truncate w-full mt-0.5">{node.label}</span>
    </div>
  );
}

// ── circle: nodes evenly ringed, all edges drawn as chords ───────────────────

function CircleLayout({ nodes, edges }: { nodes: RelationNode[]; edges: RelationEdge[] }) {
  const SIZE = 260;
  const CX = SIZE / 2;
  const CY = SIZE / 2;
  const R = SIZE / 2 - 44;
  const n = nodes.length;

  const positions = new Map<string, Point>(
    nodes.map((node, i): [string, Point] => {
      const angle = (i / n) * Math.PI * 2 - Math.PI / 2;
      return [node.id, { x: CX + R * Math.cos(angle), y: CY + R * Math.sin(angle) }];
    }),
  );

  return (
    <div className="relative mx-auto" style={{ width: SIZE, height: SIZE, maxWidth: "100%" }}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="absolute inset-0 w-full h-full">
        <defs>
          <Arrowhead id="relation-arrow-circle" />
        </defs>
        <EdgeLines nodes={nodes} edges={edges} positions={positions} markerId="relation-arrow-circle" />
      </svg>
      {nodes.map((node, i) => (
        <NodeLabel key={node.id} node={node} p={positions.get(node.id)!} color={categoricalColor(node.group ?? i)} />
      ))}
    </div>
  );
}

// ── network: deterministic phyllotaxis scatter (no physics engine) ───────────

function NetworkLayout({ nodes, edges }: { nodes: RelationNode[]; edges: RelationEdge[] }) {
  const SIZE = 260;
  const CX = SIZE / 2;
  const CY = SIZE / 2;
  const GOLDEN_ANGLE = 2.399963; // radians
  const n = nodes.length;
  const scale = Math.min(SIZE / 2 - 30, 18 * Math.sqrt(n || 1));

  const positions = new Map<string, Point>(
    nodes.map((node, i): [string, Point] => {
      if (n === 1) return [node.id, { x: CX, y: CY }];
      const r = (scale * Math.sqrt(i + 1)) / Math.sqrt(n);
      const angle = i * GOLDEN_ANGLE;
      return [node.id, { x: CX + r * Math.cos(angle), y: CY + r * Math.sin(angle) }];
    }),
  );

  return (
    <div className="relative mx-auto" style={{ width: SIZE, height: SIZE, maxWidth: "100%" }}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="absolute inset-0 w-full h-full">
        <defs>
          <Arrowhead id="relation-arrow-network" />
        </defs>
        <EdgeLines nodes={nodes} edges={edges} positions={positions} markerId="relation-arrow-network" />
      </svg>
      {nodes.map((node, i) => (
        <NodeLabel key={node.id} node={node} p={positions.get(node.id)!} color={categoricalColor(node.group ?? i)} />
      ))}
    </div>
  );
}

// ── dagre: layered top-to-bottom DAG (BFS depth from roots) ──────────────────

function DagreLayout({ nodes, edges }: { nodes: RelationNode[]; edges: RelationEdge[] }) {
  const idSet = new Set(nodes.map((n) => n.id));
  const validEdges = edges.filter((e) => idSet.has(e.source) && idSet.has(e.target));
  const hasIncoming = new Set(validEdges.map((e) => e.target));
  const outgoing = new Map<string, string[]>();
  validEdges.forEach((e) => outgoing.set(e.source, [...(outgoing.get(e.source) ?? []), e.target]));

  // BFS layering from every root (no incoming edge); falls back to node order if fully cyclic.
  const depth = new Map<string, number>();
  const roots = nodes.filter((n) => !hasIncoming.has(n.id));
  const queue: { id: string; d: number }[] = (roots.length > 0 ? roots : [nodes[0]]).map((n) => ({ id: n.id, d: 0 }));
  while (queue.length > 0) {
    const { id, d } = queue.shift()!;
    if (depth.has(id) && depth.get(id)! <= d) continue;
    depth.set(id, d);
    for (const next of outgoing.get(id) ?? []) queue.push({ id: next, d: d + 1 });
  }
  nodes.forEach((n) => {
    if (!depth.has(n.id)) depth.set(n.id, 0);
  });

  const maxDepth = Math.max(...Array.from(depth.values()), 0);
  const layers: RelationNode[][] = Array.from({ length: maxDepth + 1 }, () => []);
  nodes.forEach((n) => layers[depth.get(n.id)!].push(n));

  const ROW_H = 64;
  const W = 300;
  const H = layers.length * ROW_H;

  const positions = new Map<string, Point>();
  layers.forEach((layer, li) => {
    const y = li * ROW_H + ROW_H / 2;
    layer.forEach((n, ni) => {
      const x = ((ni + 1) / (layer.length + 1)) * W;
      positions.set(n.id, { x, y });
    });
  });

  return (
    <div className="relative mx-auto" style={{ width: W, height: H, maxWidth: "100%" }}>
      <svg viewBox={`0 0 ${W} ${H}`} className="absolute inset-0 w-full h-full">
        <defs>
          <Arrowhead id="relation-arrow-dagre" />
        </defs>
        <EdgeLines nodes={nodes} edges={validEdges} positions={positions} markerId="relation-arrow-dagre" />
      </svg>
      {nodes.map((node, i) => (
        <NodeLabel key={node.id} node={node} p={positions.get(node.id)!} color={categoricalColor(node.group ?? i)} />
      ))}
    </div>
  );
}
