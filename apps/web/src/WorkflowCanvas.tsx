import { useEffect, useId, useMemo, useRef, useState, type PointerEvent } from 'react';
import { Boxes, FileVideo, Maximize, Minus, Plus, X } from 'lucide-react';
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
  catalogError,
}: {
  definition: CanvasDefinition;
  catalog: CanvasSpec[];
  catalogError: string;
}) => {
  const viewport = useRef<HTMLDivElement>(null);
  const marker = useId().replaceAll(':', '');
  const [size, setSize] = useState({ width: 900, height: 580 });
  const [view, setView] = useState({ x: 40, y: 40, scale: 1 });
  const [selected, setSelected] = useState('');
  const drag = useRef<{ px: number; py: number; x: number; y: number } | null>(null);
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
        // Unknown catalog entries still retain every saved edge endpoint.
        const inputs =
          spec?.inputs ||
          Object.fromEntries(
            definition.edges
              .filter((edge) => edge.target.node === node.id)
              .map((edge) => [edge.target.port, '미확인']),
          );
        const outputs =
          spec?.outputs ||
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
  useEffect(() => {
    if (!viewport.current) return;
    const observer = new ResizeObserver(([entry]) =>
      setSize({ width: entry.contentRect.width, height: entry.contentRect.height }),
    );
    observer.observe(viewport.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    setView(fitted());
  }, [size.width, size.height, bounds]);
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
    if (!box) return null;
    const index = Object.keys(output ? box.outputs : box.inputs).indexOf(endpoint.port);
    return { x: box.x + (output ? width : 0), y: box.y + 56 + Math.max(0, index) * 20 };
  };
  const selectedBox = boxes.find((box) => box.id === selected);
  const selectedNode = definition.nodes.find((node) => node.id === selected);
  const panStart = (event: PointerEvent<HTMLDivElement>) => {
    if (
      event.button !== 0 ||
      (event.target as HTMLElement).closest('button, a, .workflow-node-detail')
    )
      return;
    drag.current = { px: event.clientX, py: event.clientY, x: view.x, y: view.y };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  return (
    <section className="workflow-graph" aria-label="워크플로우 그래프">
      {catalogError && (
        <p role="alert" className="workflow-catalog-error">
          에이전트 정보 미확인 · {catalogError}
        </p>
      )}
      <div
        className="workflow-graph-viewport"
        ref={viewport}
        tabIndex={0}
        aria-label="워크플로우 캔버스"
        onPointerDown={panStart}
        onPointerMove={(event) => {
          if (drag.current)
            setView((previous) => ({
              ...previous,
              x: drag.current!.x + event.clientX - drag.current!.px,
              y: drag.current!.y + event.clientY - drag.current!.py,
            }));
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
        onKeyDown={(event) => {
          if (event.target !== event.currentTarget) return;
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
          if (event.key === 'Escape') setSelected('');
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
              if (!from || !to) return null;
              const bend = Math.max(70, Math.abs(to.x - from.x) * 0.45);
              const active = selected === edge.source.node || selected === edge.target.node;
              return (
                <path
                  key={edge.id}
                  className={active ? 'is-active' : ''}
                  d={`M${from.x},${from.y} C${from.x + bend},${from.y} ${to.x - bend},${to.y} ${to.x},${to.y}`}
                  markerEnd={`url(#${marker})`}
                >
                  <title>{`${edge.source.node}.${edge.source.port} → ${edge.target.node}.${edge.target.port}`}</title>
                </path>
              );
            })}
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
                onClick={() => setSelected((previous) => (previous === box.id ? '' : box.id))}
              >
                <span className="workflow-node-symbol">
                  {box.id === '$input' ? <FileVideo size={20} /> : <Boxes size={20} />}
                </span>
                <span>
                  <strong>{box.label}</strong>
                  <small>{box.id === '$input' ? '입력' : box.id}</small>
                </span>
              </button>
              <div className="workflow-node-ports">
                {(['inputs', 'outputs'] as const).map((direction) => (
                  <div key={direction} className={direction}>
                    {Object.keys(box[direction]).map((port) => (
                      <span key={port} title={`${port} · ${box[direction][port]}`}>
                        <i />
                        {port}
                      </span>
                    ))}
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
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
        {selectedBox && (
          <aside className="workflow-node-detail" aria-label="선택한 에이전트">
            <div>
              <strong>{selectedBox.label}</strong>
              <button
                type="button"
                className="ui02-icon"
                aria-label="에이전트 정보 닫기"
                onClick={() => setSelected('')}
              >
                <X size={16} />
              </button>
            </div>
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
              {selectedNode &&
                Object.entries(selectedNode.options || {}).map(([key, value]) => (
                  <div key={key}>
                    <dt>{key}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              {selectedNode?.model_ref && (
                <div>
                  <dt>모델</dt>
                  <dd>
                    {selectedNode.model_ref.model_id} · r{selectedNode.model_ref.revision}
                  </dd>
                </div>
              )}
            </dl>
            {selectedNode && <a href={`#/workflows/${definition.id}/edit`}>에이전트 설정 편집</a>}
          </aside>
        )}
      </div>
    </section>
  );
};
