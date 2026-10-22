export type LayoutPoint = { x: number; y: number };
export type LayoutBox = LayoutPoint & {
  id: string;
  width: number;
  height: number;
  sourcePorts?: Record<string, number>;
};
export type LayoutEdge = {
  id: string;
  source: { node: string; port: string };
  target: { node: string; port: string };
};
export type Positions = Record<string, LayoutPoint>;

export const applyLayout = <T extends { nodes: { id: string; position: LayoutPoint }[] }>(
  definition: T,
  positions: Positions,
): T => {
  return {
    ...definition,
    nodes: definition.nodes.map((node) =>
      Object.hasOwn(positions, node.id) ? { ...node, position: { ...positions[node.id] } } : node,
    ),
  };
};

export const autoArrange = (boxes: LayoutBox[], edges: LayoutEdge[]): Positions => {
  const byId = new Map(boxes.map((box) => [box.id, box]));
  if (
    byId.size !== boxes.length ||
    boxes.some(
      (box) =>
        ![box.x, box.y, box.width, box.height].every(Number.isFinite) ||
        box.width <= 0 ||
        box.height <= 0,
    )
  ) {
    throw new Error('노드 크기를 확인한 뒤 다시 정렬해 주세요.');
  }
  const input = byId.get('$input');
  const nodes = boxes.filter((box) => box.id !== '$input');
  const incoming = new Map(boxes.map((box) => [box.id, [] as string[]]));
  const outgoing = new Map(boxes.map((box) => [box.id, [] as string[]]));
  for (const edge of edges) {
    if (byId.has(edge.source.node) && byId.has(edge.target.node)) {
      incoming.get(edge.target.node)!.push(edge.source.node);
      outgoing.get(edge.source.node)!.push(edge.target.node);
    }
  }
  const degree = new Map([...incoming].map(([id, parents]) => [id, parents.length]));
  const ranks = new Map(boxes.map((box) => [box.id, 0]));
  const queue = boxes.filter((box) => degree.get(box.id) === 0).map((box) => box.id);
  const order: string[] = [];
  for (let i = 0; i < queue.length; i++) {
    const id = queue[i];
    order.push(id);
    for (const child of outgoing.get(id)!) {
      ranks.set(child, Math.max(ranks.get(child)!, ranks.get(id)! + 1));
      degree.set(child, degree.get(child)! - 1);
      if (degree.get(child) === 0) {
        queue.push(child);
      }
    }
  }
  const groups = new Map<number, LayoutBox[]>();
  for (const node of nodes) {
    const rank = Math.max(1, ranks.get(node.id)!);
    groups.set(rank, [...(groups.get(rank) || []), node]);
  }
  const positions: Positions = Object.create(null);
  if (input) {
    positions[input.id] = { x: input.x, y: input.y };
  }
  let x = input ? input.x + input.width + 120 : 24;
  for (const [, group] of [...groups].sort(([a], [b]) => a - b)) {
    const parentY = (box: LayoutBox) => {
      const parents = edges.filter(
        (edge) => edge.target.node === box.id && byId.has(edge.source.node),
      );
      return parents.length
        ? parents.reduce((sum, edge) => {
            const parent = byId.get(edge.source.node)!;
            const offset =
              parent.sourcePorts && Object.hasOwn(parent.sourcePorts, edge.source.port)
                ? parent.sourcePorts[edge.source.port]
                : parent.height / 2;
            return sum + (positions[parent.id]?.y ?? 24) + offset;
          }, 0) / parents.length
        : 24;
    };
    group.sort((a, b) => parentY(a) - parentY(b));
    let y = 24;
    for (const node of group) {
      positions[node.id] = { x: Math.round(x), y: Math.round(y) };
      y += node.height + 80;
    }
    x += Math.max(...group.map((node) => node.width)) + 120;
  }
  const bounded = () =>
    nodes.every((node) => positions[node.id].x <= 4000 && positions[node.id].y <= 3000);
  if (order.length !== boxes.length || !bounded()) {
    // Preserve server coordinate bounds for long chains/large or cyclic drafts.
    const ordered = [...nodes].sort((a, b) => order.indexOf(a.id) - order.indexOf(b.id));
    x = input ? input.x + input.width + 120 : 24;
    let y = 24,
      columnWidth = 0;
    for (const node of ordered) {
      if (y > 3000) {
        x += columnWidth + 80;
        y = 24;
        columnWidth = 0;
      }
      positions[node.id] = { x: Math.round(x), y: Math.round(y) };
      y += node.height + 64;
      columnWidth = Math.max(columnWidth, node.width);
    }
    if (!bounded()) {
      throw new Error('노드 크기가 자동 정렬 범위를 넘었습니다. 배치를 나눠 조정해 주세요.');
    }
  }
  delete positions.$input;
  return positions;
};
