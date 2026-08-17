"use client";

// ─── HierarchyTree ─────────────────────────────────────────────────────────
// Hierarchies & Mind Maps family + compare-hierarchy. Covers "Hierarchy (Mind
// Map)" / hierarchy-structure / "Hierarchy Tree" / compare-hierarchy as one
// component with a `variant` switch. All share one nested-node data shape;
// only the layout differs. Depth is intentionally shallow (chat-card sized —
// not a full graph editor), so mindmap only radially positions the first
// level; deeper children render as a nested list under their parent.

import { EmptyState } from "@/components/ui/EmptyState";
import { categoricalColor, sequentialStep } from "./_palette";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface HierarchyNode {
  label: string;
  value?: string | number;
  children?: HierarchyNode[];
}

export interface HierarchyTreeProps {
  title?: string;
  variant?: "mindmap" | "structure" | "tree" | "compare";
  root?: HierarchyNode;
  /** "compare" only — two trees rendered side by side. */
  roots?: [HierarchyNode, HierarchyNode];
  canAct?: boolean;
}

const CARD = "bg-lf-surface-container-lowest rounded-xl border border-lf-outline-variant/20 p-4";

export function HierarchyTree({ title, variant = "tree", root, roots }: HierarchyTreeProps) {
  if (variant === "compare") {
    if (!roots) {
      return <EmptyState title="Nothing to compare" message="Supply two root nodes to render this comparison." />;
    }
    return (
      <div className={CARD}>
        {title && <p className="text-sm font-semibold text-lf-on-surface mb-3">{title}</p>}
        <div className="flex gap-3">
          <div className="flex-1 min-w-0">
            <TreeList node={roots[0]} depth={0} />
          </div>
          <div className="w-px bg-lf-outline-variant/20 shrink-0" />
          <div className="flex-1 min-w-0">
            <TreeList node={roots[1]} depth={0} />
          </div>
        </div>
      </div>
    );
  }

  if (!root) {
    return <EmptyState title="Nothing to show" message="Supply a root node to render this hierarchy." />;
  }

  return (
    <div className={CARD}>
      {title && <p className="text-sm font-semibold text-lf-on-surface mb-3">{title}</p>}
      {variant === "mindmap" && <MindmapView root={root} />}
      {variant === "structure" && <StructureView root={root} />}
      {variant === "tree" && <TreeList node={root} depth={0} />}
    </div>
  );
}

// ── tree: recursive indented list with guide lines ────────────────────────────

function TreeList({ node, depth }: { node: HierarchyNode; depth: number }) {
  const color = sequentialStep(depth, 4);
  return (
    <div className={depth > 0 ? "pl-4 border-l border-lf-outline-variant/25 ml-1.5" : ""}>
      <div className="flex items-center gap-1.5 py-1">
        <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: color }} />
        <span className="text-xs font-medium text-lf-on-surface truncate">{node.label}</span>
        {node.value !== undefined && <span className="text-[10px] text-lf-on-surface-variant shrink-0">{node.value}</span>}
      </div>
      {node.children?.map((c) => <TreeList key={c.label} node={c} depth={depth + 1} />)}
    </div>
  );
}

// ── structure: top-down org-chart boxes ───────────────────────────────────────

function StructureView({ root }: { root: HierarchyNode }) {
  const children = root.children ?? [];
  return (
    <div className="flex flex-col items-center">
      <NodeBox node={root} color={categoricalColor(0)} />
      {children.length > 0 && (
        <>
          <div className="w-px h-4 bg-lf-outline-variant/40" />
          <div className="relative flex gap-4">
            {children.length > 1 && (
              <div
                className="absolute top-0 h-px bg-lf-outline-variant/40"
                style={{ left: "10%", right: "10%" }}
              />
            )}
            {children.map((c, i) => (
              <div key={c.label} className="flex flex-col items-center">
                <div className="w-px h-4 bg-lf-outline-variant/40" />
                <NodeBox node={c} color={categoricalColor(i + 1)} />
                {c.children && c.children.length > 0 && (
                  <div className="mt-2 text-left space-y-0.5">
                    {c.children.map((gc) => (
                      <TreeList key={gc.label} node={gc} depth={1} />
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function NodeBox({ node, color }: { node: HierarchyNode; color: string }) {
  return (
    <div
      className="rounded-lg px-3 py-1.5 text-center min-w-[88px]"
      style={{ backgroundColor: `${color}14`, border: `1px solid ${color}40` }}
    >
      <p className="text-xs font-semibold text-lf-on-surface truncate">{node.label}</p>
      {node.value !== undefined && <p className="text-[10px] text-lf-on-surface-variant">{node.value}</p>}
    </div>
  );
}

// ── mindmap: central root, children radiating left / right ───────────────────

function MindmapView({ root }: { root: HierarchyNode }) {
  const children = root.children ?? [];
  const right = children.filter((_, i) => i % 2 === 0);
  const left = children.filter((_, i) => i % 2 === 1);
  const rows = Math.max(right.length, left.length, 1);
  const rowH = 40;
  const H = rows * rowH + 20;
  const W = 320;
  const CX = W / 2;
  const CY = H / 2;
  const SIDE_X = 110;

  const yFor = (i: number, count: number) => CY - ((count - 1) * rowH) / 2 + i * rowH;

  return (
    <div className="relative mx-auto" style={{ width: W, height: H, maxWidth: "100%" }}>
      <svg viewBox={`0 0 ${W} ${H}`} className="absolute inset-0 w-full h-full">
        {right.map((_, i) => {
          const y = yFor(i, right.length);
          const midX = (CX + (CX + SIDE_X)) / 2;
          return <path key={`r${i}`} d={`M ${CX} ${CY} Q ${midX} ${CY} ${CX + SIDE_X} ${y}`} fill="none" stroke="#cbc3d7" strokeWidth={1.5} />;
        })}
        {left.map((_, i) => {
          const y = yFor(i, left.length);
          const midX = (CX + (CX - SIDE_X)) / 2;
          return <path key={`l${i}`} d={`M ${CX} ${CY} Q ${midX} ${CY} ${CX - SIDE_X} ${y}`} fill="none" stroke="#cbc3d7" strokeWidth={1.5} />;
        })}
      </svg>

      <div className="absolute -translate-x-1/2 -translate-y-1/2" style={{ left: CX, top: CY }}>
        <NodeBox node={root} color={categoricalColor(0)} />
      </div>
      {right.map((c, i) => (
        <div key={c.label} className="absolute -translate-y-1/2 w-24" style={{ left: CX + SIDE_X - 12, top: yFor(i, right.length) }}>
          <NodeBox node={c} color={categoricalColor(1)} />
        </div>
      ))}
      {left.map((c, i) => (
        <div
          key={c.label}
          className="absolute -translate-y-1/2 -translate-x-full w-24"
          style={{ left: CX - SIDE_X + 12, top: yFor(i, left.length) }}
        >
          <NodeBox node={c} color={categoricalColor(2)} />
        </div>
      ))}
    </div>
  );
}
