export type ConnectionEndpoint = { node: string; port: string };
export type CanvasEdge = { id: string; source: ConnectionEndpoint; target: ConnectionEndpoint };
export type ConnectionBox = {
  id: string;
  type?: string;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
};
export type EdgeChange = { definition_id: string; before: CanvasEdge[]; after: CanvasEdge[] };
const edgeIdentity = (edges: CanvasEdge[]) =>
  JSON.stringify(
    edges.map((edge) => [
      edge.id,
      edge.source.node,
      edge.source.port,
      edge.target.node,
      edge.target.port,
    ]),
  );
export const undoEdgeChange = <T extends { id: string; edges: CanvasEdge[] }>(
  current: T,
  change: EdgeChange,
): T => {
  if (
    current.id !== change.definition_id ||
    edgeIdentity(current.edges) !== edgeIdentity(change.after)
  ) {
    throw new Error('다른 연결 변경이 있어 되돌릴 수 없습니다. 현재 연결을 확인하세요.');
  }
  return {
    ...current,
    edges: change.before.map((edge) => ({
      ...edge,
      source: { ...edge.source },
      target: { ...edge.target },
    })),
  };
};
export const reconnectEdge = (
  edges: CanvasEdge[],
  id: string,
  endpoint: 'source' | 'target',
  next: ConnectionEndpoint,
  boxes: ConnectionBox[],
): CanvasEdge[] => {
  const original = edges.find((edge) => edge.id === id);
  if (!original) {
    throw new Error('선택한 연결을 다시 확인하세요.');
  }
  const changed = { ...original, [endpoint]: { ...next } };
  const source = boxes.find((box) => box.id === changed.source.node);
  const target = boxes.find((box) => box.id === changed.target.node);
  if (
    !source ||
    !target ||
    !Object.hasOwn(source.outputs, changed.source.port) ||
    !Object.hasOwn(target.inputs, changed.target.port)
  ) {
    throw new Error('연결할 포트를 다시 확인하세요.');
  }
  if (source.outputs[changed.source.port] !== target.inputs[changed.target.port]) {
    throw new Error('서로 다른 자료 유형은 연결할 수 없습니다.');
  }
  if (
    edges.some(
      (edge) =>
        edge.id !== id &&
        edge.target.node === changed.target.node &&
        edge.target.port === changed.target.port,
    )
  ) {
    throw new Error('이미 연결된 입력입니다. 원래 연결을 유지합니다.');
  }
  const replacement = edges.map((edge) => (edge.id === id ? changed : edge));
  const adjacency = new Map<string, string[]>();
  for (const edge of replacement) {
    const destination = boxes.find((box) => box.id === edge.target.node);
    if (destination?.type === 'control_loop' && edge.target.port === 'next') {
      continue;
    }
    adjacency.set(edge.source.node, [...(adjacency.get(edge.source.node) || []), edge.target.node]);
  }
  const visited = new Set<string>();
  const active = new Set<string>();
  const visit = (node: string) => {
    if (active.has(node)) {
      throw new Error('명시 Loop.next 외 순환 연결은 만들 수 없습니다.');
    }
    if (visited.has(node)) {
      return;
    }
    active.add(node);
    for (const nextNode of adjacency.get(node) || []) {
      visit(nextNode);
    }
    active.delete(node);
    visited.add(node);
  };
  for (const box of boxes) {
    visit(box.id);
  }
  return replacement;
};
