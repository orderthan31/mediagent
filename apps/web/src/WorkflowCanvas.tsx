import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type PointerEvent,
  type ReactNode,
} from 'react';
import {
  GitBranch,
  LayoutGrid,
  LogIn,
  LogOut,
  Maximize,
  Minus,
  Plus,
  Trash2,
  Undo2,
  X,
} from 'lucide-react';
import { autoArrange, applyLayout, type LayoutPoint, type Positions } from './workflow-layout';
import { routeConnections, type Wire, type WireRoute } from './workflow-routing';
import { switchOutputs } from './workflow-controls';
import { NodeSymbol, nodeKind, nodeKindLabel } from './NodeSymbol';
import { resolvePorts, type PortSpec } from './workflow-spec';
import type { NodeFormContract } from './form-contract';
import './workflow-canvas.css';
type Endpoint = { node: string; port: string };
export type CanvasDefinition = {
  id: string;
  name: string;
  revision: number;
  inputs: Record<string, string>;
  nodes: {
    id: string;
    type: string;
    position: { x: number; y: number };
    options: Record<string, string>;
    model_ref?: { model_id: string; revision: number };
    fallback_refs?: { model_id: string; revision: number }[];
  }[];
  edges: { id: string; source: Endpoint; target: Endpoint }[];
};
export type CanvasSpec = PortSpec & { id: string; label: string } & NodeFormContract;
type Box = {
  review?: boolean;
  id: string;
  label: string;
  type: string;
  x: number;
  y: number;
  width: number;
  height: number;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
};
type NodeMetrics = { height: number; ports: Record<string, LayoutPoint> };
const width = 210;
export const WorkflowCanvas = ({
  definition,
  catalog,
  catalogError = '',
  onChange,
  onSelect,
  details,
  disabled = false,
  nodeStates = {},
  detailsLabel = '노드 설정',
  inputLabel = '입력 트리거',
  inputThumbnail,
}: {
  definition: CanvasDefinition;
  catalog: CanvasSpec[];
  catalogError?: string;
  onChange?: (next: CanvasDefinition) => void;
  onSelect?: (id: string) => void;
  details?: ReactNode;
  disabled?: boolean;
  nodeStates?: Record<string, { label: string; state: string }>;
  detailsLabel?: string;
  inputLabel?: string;
  inputThumbnail?: string;
}) => {
  const viewport = useRef<HTMLDivElement>(null);
  const detailsPanel = useRef<HTMLElement>(null);
  const marker = useId().replaceAll(':', '');
  const [size, setSize] = useState({ width: 900, height: 580 });
  const [view, setView] = useState({ x: 40, y: 40, scale: 1 });
  const [selected, setSelected] = useState('');
  const [edgeId, setEdgeId] = useState('');
  const [adding, setAdding] = useState<'agent' | 'control' | 'review' | null>(null);
  const [source, setSource] = useState<Endpoint | null>(null);
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const [connectionError, setConnectionError] = useState('');
  const [measurements, setMeasurements] = useState<Record<string, NodeMetrics>>({});
  const [previewLayout, setPreviewLayout] = useState<{ key: string; positions: Positions } | null>(
    null,
  );
  const [layoutHistory, setLayoutHistory] = useState<{ key: string; values: Positions[] }>({
    key: definition.id,
    values: [],
  });
  const [layoutNotice, setLayoutNotice] = useState('');
  const [cleanupRequested, setCleanupRequested] = useState(false);
  const [routingPass, setRoutingPass] = useState(0);
  const pendingFit = useRef(false);
  const viewKey = definition.id + ':' + definition.revision;
  const previewPositions = previewLayout?.key === viewKey ? previewLayout.positions : null;
  const history = layoutHistory.key === definition.id ? layoutHistory.values : [];
  const pan = useRef<{ pointerId: number; px: number; py: number; x: number; y: number } | null>(
    null,
  );
  const nodeDrag = useRef<{
    pointerId: number;
    id: string;
    px: number;
    py: number;
    x: number;
    y: number;
  } | null>(null);
  const wireDrag = useRef<{ pointerId: number; px: number; py: number } | null>(null);
  const suppressPortClick = useRef(false);
  const boxes = useMemo<Box[]>(
    () => [
      {
        id: '$input',
        label: inputLabel,
        type: '',
        x: 20,
        y: 24,
        width,
        inputs: {},
        outputs: definition.inputs || {},
        height:
          measurements.$input?.height ??
          Math.max(94, 52 + Object.keys(definition.inputs || {}).length * 20),
      },
      ...definition.nodes.map((node, index) => {
        const spec = resolvePorts(
          catalog.find((item) => item.id === node.type),
          node.options,
        );
        const inputs =
          spec?.inputs ||
          Object.fromEntries(
            definition.edges
              .filter((edge) => edge.target.node === node.id)
              .map((edge) => [edge.target.port, '미확인']),
          );
        const outputs =
          node.type === 'control_switch'
            ? switchOutputs(node.options)
            : spec?.outputs ||
              Object.fromEntries(
                definition.edges
                  .filter((edge) => edge.source.node === node.id)
                  .map((edge) => [edge.source.port, '미확인']),
              );
        const position =
          !onChange && previewPositions && Object.hasOwn(previewPositions, node.id)
            ? previewPositions[node.id]
            : node.position;
        return {
          id: node.id,
          label: spec?.label || node.type,
          review: !!node.options.review_mode && node.options.review_mode !== 'none',
          type: node.type,
          x: position?.x ?? 330 + index * 290,
          y: position?.y ?? 100,
          width,
          inputs,
          outputs,
          height:
            measurements[node.id]?.height ??
            Math.max(
              94,
              52 + Math.max(Object.keys(inputs).length, Object.keys(outputs).length) * 20,
            ),
        };
      }),
    ],
    [definition, catalog, inputLabel, measurements, previewPositions, onChange],
  );
  const readMeasurements = useCallback(() => {
    const measured: Record<string, NodeMetrics> = Object.create(null);
    for (const node of viewport.current?.querySelectorAll<HTMLElement>('.workflow-graph-node') ||
      []) {
      const rect = node.getBoundingClientRect();
      const scale = rect.width / node.offsetWidth;
      if (!scale) {
        continue;
      }
      const ports: Record<string, LayoutPoint> = Object.create(null);
      for (const port of node.querySelectorAll<HTMLElement>('button[data-port-direction]')) {
        const circle = port.querySelector('i')!.getBoundingClientRect();
        ports[(port.dataset.portDirection === 'outputs' ? 'out:' : 'in:') + port.dataset.port] = {
          x: Math.round(((circle.left + circle.width / 2 - rect.left) / scale) * 100) / 100,
          y: Math.round(((circle.top + circle.height / 2 - rect.top) / scale) * 100) / 100,
        };
      }
      measured[node.dataset.nodeId!] = { height: node.offsetHeight, ports };
    }
    return measured;
  }, []);
  const measurementKey = boxes
    .map((box) =>
      [
        box.id,
        box.label,
        Object.keys(box.inputs).join(','),
        Object.keys(box.outputs).join(','),
      ].join('|'),
    )
    .join(';');
  const point = useCallback(
    (endpoint: Endpoint, output: boolean) => {
      const box = boxes.find((item) => item.id === endpoint.node);
      if (!box) {
        return null;
      }
      const index = Object.keys(output ? box.outputs : box.inputs).indexOf(endpoint.port);
      if (index < 0) {
        return null;
      }
      const actual =
        measurements[endpoint.node]?.ports?.[(output ? 'out:' : 'in:') + endpoint.port];
      return actual
        ? { x: box.x + actual.x, y: box.y + actual.y }
        : { x: box.x + (output ? width : 0), y: box.y + 56 + index * 20 };
    },
    [boxes, measurements],
  );
  const routing = useMemo(() => {
    // Recompute paths, never edge endpoints or immutable ticket data.
    void routingPass;
    try {
      const wires: Wire[] = [];
      for (const edge of definition.edges) {
        const from = point(edge.source, true),
          to = point(edge.target, false);
        if (!from || !to) {
          throw new Error('연결 포트의 위치를 확인할 수 없습니다.');
        }
        wires.push({ ...edge, from, to });
      }
      return { routes: routeConnections(boxes, wires), error: '' };
    } catch (error) {
      return {
        routes: new Map<string, WireRoute>(),
        error: error instanceof Error ? error.message : '연결선을 정리하지 못했습니다.',
      };
    }
  }, [boxes, definition.edges, point, routingPass]);
  const bounds = useMemo(() => {
    const points = [...routing.routes.values()].flatMap((route) => route.points);
    return {
      left: Math.min(...boxes.map((box) => box.x), ...points.map((p) => p.x)),
      top: Math.min(...boxes.map((box) => box.y), ...points.map((p) => p.y)),
      right: Math.max(...boxes.map((box) => box.x + width), ...points.map((p) => p.x)),
      bottom: Math.max(...boxes.map((box) => box.y + box.height), ...points.map((p) => p.y)),
    };
  }, [boxes, routing.routes]);
  const fitted = () => {
    // Fit inside the unobstructed canvas, not underneath touch-sized controls.
    const topInset = matchMedia('(max-width: 700px)').matches ? 72 : 0;
    const bottomInset = onChange || topInset === 0 ? 72 : 0;
    const contentHeight = Math.max(1, size.height - topInset - bottomInset);
    const scale = Math.min(
      1,
      Math.max(
        0.02,
        Math.min(
          (size.width - 80) / (bounds.right - bounds.left),
          (contentHeight - 48) / (bounds.bottom - bounds.top),
        ),
      ),
    );
    return {
      scale,
      x: (size.width - (bounds.right - bounds.left) * scale) / 2 - bounds.left * scale,
      y: topInset + (contentHeight - (bounds.bottom - bounds.top) * scale) / 2 - bounds.top * scale,
    };
  };
  const select = (id: string) => {
    setSelected(id);
    setEdgeId('');
    onSelect?.(id);
  };
  const zoom = (factor: number) =>
    setView((previous) => {
      const scale = Math.min(1.8, Math.max(0.02, previous.scale * factor));
      const ratio = scale / previous.scale;
      return {
        scale,
        x: size.width / 2 - (size.width / 2 - previous.x) * ratio,
        y: size.height / 2 - (size.height / 2 - previous.y) * ratio,
      };
    });
  const arrange = () => {
    if (onChange && disabled) {
      return;
    }
    try {
      const nextMetrics = readMeasurements();
      setMeasurements(nextMetrics);
      const next = autoArrange(
        boxes.map((box) => ({
          ...box,
          height: nextMetrics[box.id]?.height ?? box.height,
          sourcePorts: Object.fromEntries(
            Object.entries(nextMetrics[box.id]?.ports || {})
              .filter(([key]) => key.startsWith('out:'))
              .map(([key, value]) => [key.slice(4), value.y]),
          ),
        })),
        definition.edges,
      );
      pendingFit.current = true;
      if (onChange) {
        const previous = Object.fromEntries(
          definition.nodes.map((node) => [node.id, { ...node.position }]),
        );
        setLayoutHistory({ key: definition.id, values: [...history, previous].slice(-20) });
        onChange(applyLayout(definition, next));
      } else {
        setPreviewLayout({ key: viewKey, positions: next });
      }
      setCleanupRequested(true);
      setLayoutNotice(
        onChange
          ? '노드를 자동 정렬했습니다. 저장하면 배치가 반영됩니다.'
          : '화면 배치만 정렬했습니다. 고정 티켓은 바뀌지 않습니다.',
      );
    } catch (error) {
      setLayoutNotice(error instanceof Error ? error.message : '자동 정렬을 완료하지 못했습니다.');
    }
  };
  const undoLayout = () => {
    pendingFit.current = true;
    if (onChange && history.length && !disabled) {
      onChange(applyLayout(definition, history[history.length - 1]));
      setLayoutHistory({ key: definition.id, values: history.slice(0, -1) });
    } else if (!onChange) {
      setPreviewLayout(null);
    }
    setLayoutNotice(
      onChange ? '이전 배치로 되돌렸습니다.' : '고정 티켓의 원래 배치로 돌아왔습니다.',
    );
  };
  const cleanupWires = () => {
    setMeasurements(readMeasurements());
    setRoutingPass((previous) => previous + 1);
    setCleanupRequested(true);
    setLayoutNotice('포트와 연결 관계를 유지하고 연결선 경로를 정리했습니다.');
    pendingFit.current = true;
  };
  const curve = (from: { x: number; y: number }, to: { x: number; y: number }) => {
    const bend = Math.max(70, Math.abs(to.x - from.x) * 0.45);
    return `M${from.x},${from.y} C${from.x + bend},${from.y} ${to.x - bend},${to.y} ${to.x},${to.y}`;
  };
  const connect = (target: Endpoint) => {
    if (!source || !onChange || disabled) {
      return;
    }
    if (source.node === target.node) {
      setConnectionError('같은 에이전트에는 연결할 수 없습니다.');
      return;
    }
    if (
      definition.edges.some(
        (edge) => edge.target.node === target.node && edge.target.port === target.port,
      )
    ) {
      setConnectionError('이미 연결된 입력입니다.');
      return;
    }
    onChange({
      ...definition,
      edges: [...definition.edges, { id: crypto.randomUUID().replaceAll('-', ''), source, target }],
    });
    setSource(null);
    setCursor(null);
    setConnectionError('');
  };
  const add = (spec: CanvasSpec) => {
    if (!onChange || disabled) {
      return;
    }
    const id = crypto.randomUUID().replaceAll('-', '');
    onChange({
      ...definition,
      nodes: [
        ...definition.nodes,
        {
          id,
          type: spec.id,
          position: {
            x: Math.round(Math.max(0, (size.width * 0.45 - view.x) / view.scale)),
            y: Math.round(Math.max(0, (size.height * 0.4 - view.y) / view.scale)),
          },
          options: Object.fromEntries(
            Object.entries(spec.options).map(([key, values]) => [
              key,
              key === 'subtitle_mode' && values.includes('none') ? 'none' : values[0],
            ]),
          ),
        },
      ],
    });
    select(id);
    setAdding(null);
  };
  const panStart = (event: PointerEvent<HTMLDivElement>) => {
    if (
      event.button !== 0 ||
      event.isPrimary === false ||
      pan.current ||
      nodeDrag.current ||
      wireDrag.current ||
      (event.target as Element).closest(
        'button, a, input, select, .workflow-node-detail, .workflow-agent-picker',
      )
    ) {
      return;
    }
    pan.current = {
      pointerId: event.pointerId,
      px: event.clientX,
      py: event.clientY,
      x: view.x,
      y: view.y,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
    setAdding(null);
  };
  const movePointer = (event: PointerEvent<HTMLDivElement>) => {
    const start = pan.current;
    const clientX = event.clientX;
    const clientY = event.clientY;
    if (start && start.pointerId === event.pointerId) {
      const x = start.x + clientX - start.px;
      const y = start.y + clientY - start.py;
      setView((previous) => ({ ...previous, x, y }));
    }
    if (source && viewport.current) {
      const rect = viewport.current.getBoundingClientRect();
      setCursor({
        x: (event.clientX - rect.left - view.x) / view.scale,
        y: (event.clientY - rect.top - view.y) / view.scale,
      });
    }
  };
  const endPointer = (event: PointerEvent<HTMLElement>) => {
    const id = event.pointerId;
    if (pan.current?.pointerId === id) {
      pan.current = null;
    }
    if (nodeDrag.current?.pointerId === id) {
      nodeDrag.current = null;
    }
    if (wireDrag.current?.pointerId === id) {
      wireDrag.current = null;
      if (event.type !== 'pointerup') {
        setSource(null);
      }
    }
    if (event.currentTarget.hasPointerCapture(id)) {
      event.currentTarget.releasePointerCapture(id);
    }
  };
  const selectedBox = boxes.find((box) => box.id === selected);
  const previewFrom = source ? point(source, true) : null;
  useEffect(() => {
    let disposed = false;
    const refresh = () => {
      if (disposed) {
        return;
      }
      const next = readMeasurements();
      setMeasurements((previous) =>
        JSON.stringify(previous) === JSON.stringify(next) ? previous : next,
      );
    };
    const observer = new ResizeObserver(refresh);
    viewport.current
      ?.querySelectorAll('.workflow-graph-node')
      .forEach((node) => observer.observe(node));
    refresh();
    void document.fonts.ready.then(refresh);
    return () => {
      disposed = true;
      observer.disconnect();
    };
  }, [measurementKey, readMeasurements]);
  useEffect(() => {
    if (pendingFit.current) {
      pendingFit.current = false;
      setView(fitted());
    }
  }, [bounds, size, routingPass]);
  useEffect(() => {
    if (!viewport.current) {
      return;
    }
    const observer = new ResizeObserver(([entry]) =>
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height }),
    );
    observer.observe(viewport.current);
    return () => observer.disconnect();
  }, []);
  // Editing must not reset the current viewport on every pointer movement.
  useEffect(() => {
    setView(fitted());
  }, [size.width, size.height, definition.id]);
  useEffect(() => {
    if (selected) {
      const panel = detailsPanel.current;
      if (panel) {
        panel.scrollTop = 0;
        panel.scrollIntoView({ block: 'nearest' });
      }
    }
  }, [selected]);
  return (
    <section className="workflow-graph" aria-label="워크플로우">
      <div className="workflow-layout-actions" role="toolbar" aria-label="캔버스 배치">
        <button
          type="button"
          onClick={arrange}
          disabled={(!!onChange && disabled) || !definition.nodes.length}
        >
          <LayoutGrid size={16} /> 자동 정렬
        </button>
        <button type="button" onClick={cleanupWires}>
          <GitBranch size={16} /> 연결선 정리
        </button>
        <button type="button" onClick={() => setView(fitted())}>
          <Maximize size={16} /> 전체 보기
        </button>
        <button
          type="button"
          onClick={undoLayout}
          disabled={onChange ? disabled || !history.length : !previewPositions}
        >
          <Undo2 size={16} /> {onChange ? '정렬 되돌리기' : '배치 초기화'}
        </button>
      </div>
      <p className="workflow-layout-notice" aria-live="polite">
        {cleanupRequested && routing.error
          ? routing.error
          : layoutNotice ||
            (onChange ? '배치 변경은 저장 후 반영됩니다.' : '읽기 전용 · 화면 배치만 변경')}
        {!onChange && layoutNotice && <span>읽기 전용 · 화면 배치만 변경</span>}
      </p>
      {catalogError && (
        <p role="alert" className="workflow-catalog-error">
          {catalogError}
        </p>
      )}
      <div
        className="workflow-graph-viewport"
        ref={viewport}
        tabIndex={0}
        aria-label="워크플로우 캔버스"
        onPointerDown={panStart}
        onPointerMove={movePointer}
        onPointerUp={endPointer}
        onPointerCancel={endPointer}
        onLostPointerCapture={endPointer}
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            setSource(null);
            setAdding(null);
            select('');
          }
          if (event.target !== event.currentTarget) {
            return;
          }
          const delta: Record<string, [number, number]> = {
            ArrowLeft: [40, 0],
            ArrowRight: [-40, 0],
            ArrowUp: [0, 40],
            ArrowDown: [0, -40],
          };
          if (delta[event.key]) {
            event.preventDefault();
            const [x, y] = delta[event.key];
            setView((previous) => ({ ...previous, x: previous.x + x, y: previous.y + y }));
          }
          if (
            (event.key === 'Delete' || event.key === 'Backspace') &&
            edgeId &&
            onChange &&
            !disabled
          ) {
            event.preventDefault();
            onChange({
              ...definition,
              edges: definition.edges.filter((edge) => edge.id !== edgeId),
            });
            setEdgeId('');
          }
        }}
      >
        <div
          className="workflow-graph-world"
          style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}
        >
          <svg
            className="workflow-graph-wires"
            width={Math.max(1, bounds.right + 160)}
            height={Math.max(1, bounds.bottom + 100)}
            aria-label="에이전트 연결선"
          >
            <defs>
              <marker
                id={marker}
                viewBox="0 0 10 10"
                refX="9"
                refY="5"
                markerWidth="5"
                markerHeight="5"
                orient="auto"
              >
                <path d="M0 0 10 5 0 10z" fill="currentColor" />
              </marker>
            </defs>
            {definition.edges.map((edge) => {
              const from = point(edge.source, true),
                to = point(edge.target, false);
              if (!from || !to) {
                return null;
              }
              const active =
                edgeId === edge.id ||
                selected === edge.source.node ||
                selected === edge.target.node;
              return (
                <path
                  key={edge.id}
                  data-edge-id={edge.id}
                  className={'workflow-wire ' + (active ? 'is-active' : '')}
                  d={routing.routes.get(edge.id)?.path || curve(from, to)}
                  markerEnd={`url(#${marker})`}
                  onPointerDown={(event) => event.stopPropagation()}
                  onClick={() => {
                    if (onChange) {
                      setEdgeId(edge.id);
                      setSelected('');
                      onSelect?.('');
                    }
                  }}
                >
                  <title>{`${edge.source.port} → ${edge.target.port}`}</title>
                </path>
              );
            })}
            {previewFrom && cursor && (
              <path className="is-preview" d={curve(previewFrom, cursor)} />
            )}
          </svg>
          {boxes.map((box) => (
            <article
              key={box.id}
              className={`workflow-graph-node ${selected === box.id ? 'is-selected' : ''}`}
              data-node-id={box.id}
              data-node-kind={box.id === '$input' ? 'input' : nodeKind(box.type)}
              data-state={nodeStates[box.id]?.state}
              style={{ left: box.x, top: box.y, width }}
            >
              <button
                type="button"
                className="workflow-node-heading"
                aria-pressed={selected === box.id}
                onClick={() => select(box.id)}
                onPointerDown={(event) => {
                  if (
                    !onChange ||
                    disabled ||
                    box.id === '$input' ||
                    event.button !== 0 ||
                    event.isPrimary === false ||
                    pan.current ||
                    nodeDrag.current ||
                    wireDrag.current
                  ) {
                    return;
                  }
                  event.currentTarget.setPointerCapture(event.pointerId);
                  nodeDrag.current = {
                    pointerId: event.pointerId,
                    id: box.id,
                    px: event.clientX,
                    py: event.clientY,
                    x: box.x,
                    y: box.y,
                  };
                }}
                onPointerMove={(event) => {
                  const start = nodeDrag.current;
                  if (start && start.pointerId === event.pointerId && onChange && !disabled) {
                    onChange({
                      ...definition,
                      nodes: definition.nodes.map((node) =>
                        node.id === start.id
                          ? {
                              ...node,
                              position: {
                                x: Math.round(
                                  Math.max(0, start.x + (event.clientX - start.px) / view.scale),
                                ),
                                y: Math.round(
                                  Math.max(0, start.y + (event.clientY - start.py) / view.scale),
                                ),
                              },
                            }
                          : node,
                      ),
                    });
                  }
                }}
                onPointerUp={endPointer}
                onPointerCancel={endPointer}
              >
                <span className="workflow-node-symbol">
                  {box.id === '$input' && inputThumbnail ? (
                    <img src={inputThumbnail} alt="" />
                  ) : box.id === '$input' ? (
                    <LogIn size={20} />
                  ) : box.type === '$output' ? (
                    <LogOut size={20} />
                  ) : (
                    <NodeSymbol type={box.type} />
                  )}
                </span>
                <span>
                  <strong title={box.label}>{box.label}</strong>
                  <small>
                    {box.id === '$input'
                      ? '트리거'
                      : box.type === '$output'
                        ? '종료'
                        : nodeKindLabel(box.type)}
                    {box.review && ' · 검토'}
                    {nodeStates[box.id] && ` · ${nodeStates[box.id].label}`}
                  </small>
                </span>
              </button>
              <div className="workflow-node-ports">
                {(['inputs', 'outputs'] as const).map((direction) => (
                  <div key={direction} className={direction}>
                    {Object.keys(box[direction]).map((port) => (
                      <button
                        type="button"
                        key={port}
                        className={
                          source?.node === box.id && source.port === port ? 'is-source' : ''
                        }
                        disabled={!onChange || disabled}
                        data-port-direction={direction}
                        data-node={box.id}
                        data-port={port}
                        aria-label={`${box.label} ${direction === 'inputs' ? '입력' : '출력'} ${port}`}
                        title={`${port} · ${box[direction][port]}`}
                        onPointerDown={(event) => {
                          if (
                            direction !== 'outputs' ||
                            event.button !== 0 ||
                            event.isPrimary === false ||
                            pan.current ||
                            nodeDrag.current ||
                            wireDrag.current
                          ) {
                            return;
                          }
                          setSource({ node: box.id, port });
                          setConnectionError('');
                          wireDrag.current = {
                            pointerId: event.pointerId,
                            px: event.clientX,
                            py: event.clientY,
                          };
                          event.currentTarget.setPointerCapture(event.pointerId);
                        }}
                        onPointerUp={(event) => {
                          if (
                            direction !== 'outputs' ||
                            wireDrag.current?.pointerId !== event.pointerId
                          ) {
                            return;
                          }
                          const start = wireDrag.current;
                          wireDrag.current = null;
                          if (
                            Math.abs(event.clientX - start.px) +
                              Math.abs(event.clientY - start.py) <
                            5
                          ) {
                            return;
                          }
                          suppressPortClick.current = true;
                          const target = document
                            .elementFromPoint(event.clientX, event.clientY)
                            ?.closest<HTMLElement>('[data-port-direction="inputs"]');
                          if (target?.dataset.node && target.dataset.port) {
                            connect({ node: target.dataset.node, port: target.dataset.port });
                          }
                        }}
                        onClick={() => {
                          if (suppressPortClick.current) {
                            suppressPortClick.current = false;
                            return;
                          }
                          if (direction === 'outputs') {
                            setSource({ node: box.id, port });
                            setConnectionError('');
                          } else {
                            connect({ node: box.id, port });
                          }
                        }}
                      >
                        <i />
                        {port}
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
        {onChange && (
          <div className="workflow-agent-picker">
            {(['agent', 'control', 'review'] as const).map((kind) => (
              <button
                type="button"
                className={kind === 'agent' ? 'ui02-primary' : 'workflow-control-add'}
                key={kind}
                disabled={disabled || definition.nodes.length >= 100}
                aria-expanded={adding === kind}
                aria-controls={`${marker}-nodes`}
                onClick={() => setAdding((previous) => (previous === kind ? null : kind))}
              >
                <Plus size={17} />
                {
                  { agent: '에이전트 추가', control: '제어 노드 추가', review: '사람 검수 추가' }[
                    kind
                  ]
                }
              </button>
            ))}
            {adding && (
              <div
                id={`${marker}-nodes`}
                className="workflow-agent-menu"
                role="group"
                aria-label="추가할 노드"
              >
                {catalog
                  .filter((spec) => nodeKind(spec.id) === adding)
                  .map((spec) => (
                    <button type="button" key={spec.id} onClick={() => add(spec)}>
                      <NodeSymbol type={spec.id} size={16} />
                      {spec.label}
                    </button>
                  ))}
              </div>
            )}
          </div>
        )}
        <div className="workflow-graph-controls">
          <button
            type="button"
            className="ui02-icon"
            aria-label="캔버스 축소"
            onClick={() => zoom(1 / 1.2)}
          >
            <Minus size={16} />
          </button>
          <span>{Math.round(view.scale * 100)}%</span>
          <button
            type="button"
            className="ui02-icon"
            aria-label="캔버스 확대"
            onClick={() => zoom(1.2)}
          >
            <Plus size={16} />
          </button>
          <button
            type="button"
            className="ui02-icon"
            aria-label="전체 노드 보기"
            onClick={() => setView(fitted())}
          >
            <Maximize size={16} />
          </button>
        </div>
        {connectionError && (
          <p role="alert" className="workflow-connection-error">
            {connectionError}
          </p>
        )}
        {edgeId && onChange && (
          <div className="workflow-edge-action">
            <button
              type="button"
              className="ui02-icon"
              disabled={disabled}
              aria-label="선택한 연결 삭제"
              title="연결 삭제"
              onClick={() => {
                onChange({
                  ...definition,
                  edges: definition.edges.filter((edge) => edge.id !== edgeId),
                });
                setEdgeId('');
              }}
            >
              <Trash2 size={17} />
            </button>
          </div>
        )}
      </div>
      {selectedBox && (
        <section
          className="workflow-node-settings"
          aria-label={detailsLabel}
          ref={detailsPanel}
          tabIndex={0}
        >
          <div>
            <strong>{selectedBox.label}</strong>
            <button
              type="button"
              className="ui02-icon"
              aria-label={`${detailsLabel} 닫기`}
              onClick={() => select('')}
            >
              <X size={16} />
            </button>
          </div>
          {details ?? (
            <dl>
              {(['inputs', 'outputs'] as const).map((direction) => (
                <div key={direction}>
                  <dt>{direction === 'inputs' ? '입력' : '출력'}</dt>
                  <dd>
                    {Object.entries(selectedBox[direction]).map(([port, type]) => (
                      <span key={port}>
                        {port}
                        <small>{type}</small>
                      </span>
                    ))}
                    {!Object.keys(selectedBox[direction]).length && '—'}
                  </dd>
                </div>
              ))}
            </dl>
          )}
        </section>
      )}
    </section>
  );
};
