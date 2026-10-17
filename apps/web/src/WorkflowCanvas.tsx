import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type PointerEvent,
  type ReactNode,
} from 'react';
import { Boxes, FileVideo, GitBranch, Maximize, Minus, Plus, Trash2, X } from 'lucide-react';
import { isControlNode, switchOutputs } from './workflow-controls';
import { resolvePorts, type PortSpec } from './workflow-spec';
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
  }[];
  edges: { id: string; source: Endpoint; target: Endpoint }[];
};
export type CanvasSpec = PortSpec & { id: string; label: string };
type Box = {
  id: string;
  label: string;
  type: string;
  x: number;
  y: number;
  height: number;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
};
const width = 210;
export const WorkflowCanvas = ({
  definition,
  catalog,
  catalogError = '',
  onChange,
  onSelect,
  details,
  disabled = false,
}: {
  definition: CanvasDefinition;
  catalog: CanvasSpec[];
  catalogError?: string;
  onChange?: (next: CanvasDefinition) => void;
  onSelect?: (id: string) => void;
  details?: ReactNode;
  disabled?: boolean;
}) => {
  const viewport = useRef<HTMLDivElement>(null);
  const marker = useId().replaceAll(':', '');
  const [size, setSize] = useState({ width: 900, height: 580 });
  const [view, setView] = useState({ x: 40, y: 40, scale: 1 });
  const [selected, setSelected] = useState('');
  const [edgeId, setEdgeId] = useState('');
  const [adding, setAdding] = useState<'agent' | 'control' | null>(null);
  const [source, setSource] = useState<Endpoint | null>(null);
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const [connectionError, setConnectionError] = useState('');
  const pan = useRef<{ px: number; py: number; x: number; y: number } | null>(null);
  const nodeDrag = useRef<{ id: string; px: number; py: number; x: number; y: number } | null>(
    null,
  );
  const wireDrag = useRef<{ px: number; py: number } | null>(null);
  const suppressPortClick = useRef(false);
  const boxes = useMemo<Box[]>(
    () => [
      {
        id: '$input',
        label: '원본 입력',
        type: '',
        x: 20,
        y: 24,
        inputs: {},
        outputs: definition.inputs || {},
        height: Math.max(94, 52 + Object.keys(definition.inputs || {}).length * 20),
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
        return {
          id: node.id,
          label: spec?.label || node.type,
          type: node.type,
          x: node.position?.x ?? 330 + index * 290,
          y: node.position?.y ?? 100,
          inputs,
          outputs,
          height: Math.max(
            94,
            52 + Math.max(Object.keys(inputs).length, Object.keys(outputs).length) * 20,
          ),
        };
      }),
    ],
    [definition, catalog],
  );
  const bounds = useMemo(
    () => ({
      left: Math.min(...boxes.map((box) => box.x)),
      top: Math.min(...boxes.map((box) => box.y)),
      right: Math.max(...boxes.map((box) => box.x + width)),
      bottom: Math.max(...boxes.map((box) => box.y + box.height)),
    }),
    [boxes],
  );
  const fitted = () => {
    const scale = Math.min(
      1,
      Math.max(
        0.15,
        Math.min(
          (size.width - 80) / (bounds.right - bounds.left),
          (size.height - 100) / (bounds.bottom - bounds.top),
        ),
      ),
    );
    return {
      scale,
      x: (size.width - (bounds.right - bounds.left) * scale) / 2 - bounds.left * scale,
      y: (size.height - (bounds.bottom - bounds.top) * scale) / 2 - bounds.top * scale,
    };
  };
  const select = (id: string) => {
    setSelected(id);
    setEdgeId('');
    onSelect?.(id);
  };
  const zoom = (factor: number) =>
    setView((previous) => {
      const scale = Math.min(1.8, Math.max(0.15, previous.scale * factor));
      const ratio = scale / previous.scale;
      return {
        scale,
        x: size.width / 2 - (size.width / 2 - previous.x) * ratio,
        y: size.height / 2 - (size.height / 2 - previous.y) * ratio,
      };
    });
  const point = (endpoint: Endpoint, output: boolean) => {
    const box = boxes.find((item) => item.id === endpoint.node);
    if (!box) {
      return null;
    }
    const index = Object.keys(output ? box.outputs : box.inputs).indexOf(endpoint.port);
    return { x: box.x + (output ? width : 0), y: box.y + 56 + Math.max(0, index) * 20 };
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
      (event.target as Element).closest(
        'button, a, input, select, .workflow-node-detail, .workflow-agent-picker',
      )
    ) {
      return;
    }
    pan.current = { px: event.clientX, py: event.clientY, x: view.x, y: view.y };
    event.currentTarget.setPointerCapture(event.pointerId);
    setAdding(null);
  };
  const movePointer = (event: PointerEvent<HTMLDivElement>) => {
    if (pan.current) {
      setView((previous) => ({
        ...previous,
        x: pan.current!.x + event.clientX - pan.current!.px,
        y: pan.current!.y + event.clientY - pan.current!.py,
      }));
    }
    if (source && viewport.current) {
      const rect = viewport.current.getBoundingClientRect();
      setCursor({
        x: (event.clientX - rect.left - view.x) / view.scale,
        y: (event.clientY - rect.top - view.y) / view.scale,
      });
    }
  };
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
  const selectedBox = boxes.find((box) => box.id === selected);
  const previewFrom = source ? point(source, true) : null;
  return (
    <section className="workflow-graph" aria-label="워크플로우">
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
        onPointerUp={() => {
          pan.current = null;
        }}
        onPointerCancel={() => {
          pan.current = null;
          nodeDrag.current = null;
          wireDrag.current = null;
          setSource(null);
        }}
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
                  className={active ? 'is-active' : ''}
                  d={curve(from, to)}
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
              style={{ left: box.x, top: box.y, width, height: box.height }}
            >
              <button
                type="button"
                className="workflow-node-heading"
                aria-pressed={selected === box.id}
                onClick={() => select(box.id)}
                onPointerDown={(event) => {
                  if (!onChange || disabled || box.id === '$input' || event.button !== 0) {
                    return;
                  }
                  event.currentTarget.setPointerCapture(event.pointerId);
                  nodeDrag.current = {
                    id: box.id,
                    px: event.clientX,
                    py: event.clientY,
                    x: box.x,
                    y: box.y,
                  };
                }}
                onPointerMove={(event) => {
                  const start = nodeDrag.current;
                  if (start && onChange && !disabled) {
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
                onPointerUp={() => {
                  nodeDrag.current = null;
                }}
                onPointerCancel={() => {
                  nodeDrag.current = null;
                }}
              >
                <span className="workflow-node-symbol">
                  {box.id === '$input' ? (
                    <FileVideo size={20} />
                  ) : isControlNode(box.type) ? (
                    <GitBranch size={20} />
                  ) : (
                    <Boxes size={20} />
                  )}
                </span>
                <span>
                  <strong>{box.label}</strong>
                  <small>
                    {box.id === '$input'
                      ? '입력'
                      : isControlNode(box.type)
                        ? '제어 노드'
                        : '에이전트'}
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
                          if (direction !== 'outputs') {
                            return;
                          }
                          setSource({ node: box.id, port });
                          setConnectionError('');
                          wireDrag.current = { px: event.clientX, py: event.clientY };
                          event.currentTarget.setPointerCapture(event.pointerId);
                        }}
                        onPointerUp={(event) => {
                          if (direction !== 'outputs' || !wireDrag.current) {
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
            {(['agent', 'control'] as const).map((kind) => (
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
                {kind === 'agent' ? '에이전트 추가' : '제어 노드 추가'}
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
                  .filter((spec) => isControlNode(spec.id) === (adding === 'control'))
                  .map((spec) => (
                    <button type="button" key={spec.id} onClick={() => add(spec)}>
                      {adding === 'control' ? <GitBranch size={16} /> : <Boxes size={16} />}
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
        <section className="workflow-node-settings" aria-label="노드 설정">
          <div>
            <strong>{selectedBox.label}</strong>
            <button
              type="button"
              className="ui02-icon"
              aria-label="노드 설정 닫기"
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
