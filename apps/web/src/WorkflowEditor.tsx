import { useEffect, useRef, useState, type PointerEvent } from 'react';
import { request } from './api';
import { resolvePorts as resolveSpec } from './workflow-spec';
import { jsonPost } from './video-api';
import { Button } from './hangyeol/primitives/button';
import { Input } from './hangyeol/primitives/input';
import { Badge } from './hangyeol/primitives/badge';
import { NodeModelBinding } from './NodeModelBinding';
import type { ModelReference } from './registered-models';
import { DefinitionHistory } from './DefinitionHistory';
import './workflow-editor.css';

type Port = { node: string; port: string };
type Node = {
  id: string;
  type: string;
  position: { x: number; y: number };
  options: Record<string, string>;
  model_ref?: ModelReference;
};
type Edge = { id: string; source: Port; target: Port };
type Definition = {
  id: string;
  catalog_version: number;
  revision: number;
  name: string;
  inputs: Record<string, string>;
  nodes: Node[];
  edges: Edge[];
};
type Spec = {
  id: string;
  label: string;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
  optional_inputs: string[];
  options: Record<string, string[]>;
  port_types_from_options?: Partial<Record<'inputs' | 'outputs', Record<string, string>>>;
};
type Summary = { id: string; name: string; revision: number };
type Validation = {
  valid: boolean;
  issues: { node_id: string | null; edge_id: string | null; message: string }[];
  notice: string;
};
const endpoint = '/settings/workflow-definitions';
const uid = () => crypto.randomUUID().replaceAll('-', '');
const draft = (): Definition => ({
  id: uid(),
  catalog_version: 1,
  revision: 0,
  name: '새 워크플로우',
  inputs: { video: 'video' },
  nodes: [],
  edges: [],
});
const payload = (d: Definition) => ({
  catalog_version: d.catalog_version,
  revision: d.revision,
  name: d.name,
  inputs: d.inputs,
  nodes: d.nodes,
  edges: d.edges,
});

export const WorkflowEditor = () => {
  const [doc, setDoc] = useState<Definition>(draft);
  const [catalog, setCatalog] = useState<Spec[]>([]);
  const [saved, setSaved] = useState<Summary[]>([]);
  const [openId, setOpenId] = useState('');
  const [selected, setSelected] = useState('');
  const [source, setSource] = useState<Port | null>(null);
  const [selectedEdge, setSelectedEdge] = useState('');
  const [validation, setValidation] = useState<Validation | null>(null);
  const [busy, setBusy] = useState('load');
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [dirty, setDirty] = useState(false);
  const [inputName, setInputName] = useState('');
  const [inputType, setInputType] = useState('video');
  const viewport = useRef<HTMLDivElement>(null);
  const drag = useRef<{
    id: string;
    x: number;
    y: number;
    px: number;
    py: number;
    sx: number;
    sy: number;
  } | null>(null);
  const node = doc.nodes.find((n) => n.id === selected),
    spec = resolveSpec(
      catalog.find((n) => n.id === node?.type),
      node?.options,
    );
  const inputTypes = [...new Set(catalog.flatMap((n) => Object.values(n.inputs)))];
  const nodeLabel = (identity: string) =>
    identity === '$input'
      ? '외부 입력'
      : catalog.find((s) => s.id === doc.nodes.find((n) => n.id === identity)?.type)?.label ||
        '없는 노드';
  const change = (next: Definition) => {
    setDoc(next);
    setDirty(true);
    setValidation(null);
    setStatus('');
  };
  const list = async () => {
    const r = await request<{ definitions: Summary[] }>(endpoint);
    setSaved(r.definitions);
  };
  const load = async (identity: string) => {
    if (!identity) {
      return;
    }
    setBusy('load');
    setError('');
    setStatus('');
    try {
      const next = await request<Definition>(endpoint + '/' + identity);
      setDoc(next);
      setOpenId(next.id);
      setSelected('');
      setSource(null);
      setSelectedEdge('');
      setValidation(null);
      setDirty(false);
      setStatus('서버값을 불러왔습니다. 이전 편집은 교체되었습니다.');
    } catch (e) {
      setError(e instanceof Error ? e.message : '서버 조회 실패. 현재 편집은 유지됩니다.');
    } finally {
      setBusy('');
    }
  };
  const check = async () => {
    const result = await jsonPost<Validation>(endpoint + '/validate', payload(doc));
    setValidation(result);
    return result;
  };
  const validate = async () => {
    setBusy('validate');
    setError('');
    try {
      await check();
    } catch (e) {
      setError(e instanceof Error ? e.message : '검증 서버에 접근하지 못했습니다.');
    } finally {
      setBusy('');
    }
  };
  const save = async () => {
    setBusy('save');
    setError('');
    setStatus('');
    try {
      const result = await check();
      if (!result.valid) {
        setError('노드·연결 문제를 해결한 뒤 저장하세요. 현재 편집은 유지됩니다.');
        return;
      }
      const next = await request<Definition>(endpoint + '/' + doc.id, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload(doc)),
      });
      setDoc(next);
      setDirty(false);
      setOpenId(next.id);
      setStatus('서버 저장 완료 · 실행이나 기존 티켓 변경은 하지 않았습니다.');
      await list();
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패. 현재 편집은 유지됩니다.');
    } finally {
      setBusy('');
    }
  };
  const add = (item: Spec) => {
    const n: Node = {
      id: uid(),
      type: item.id,
      position: {
        x: 340 + (doc.nodes.length % 8) * 270,
        y: 140 + Math.floor(doc.nodes.length / 8) * 220,
      },
      options: Object.fromEntries(
        Object.entries(item.options).map(([k, v]) => [k, k === 'subtitle_mode' ? 'none' : v[0]]),
      ),
    };
    change({ ...doc, nodes: [...doc.nodes, n] });
    setSelected(n.id);
  };
  const move = (identity: string, x: number, y: number) => {
    if (busy || !Number.isFinite(x) || !Number.isFinite(y)) {
      return;
    }
    setDoc((prev) => ({
      ...prev,
      nodes: prev.nodes.map((n) =>
        n.id === identity
          ? {
              ...n,
              position: {
                x: Math.round(Math.max(0, Math.min(4000, x))),
                y: Math.round(Math.max(0, Math.min(3000, y))),
              },
            }
          : n,
      ),
    }));
    setDirty(true);
    setValidation(null);
    setStatus('');
  };
  const startDrag = (e: PointerEvent<HTMLButtonElement>, n: Node) => {
    if (e.button !== 0 || busy) {
      return;
    }
    setSelected(n.id);
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = {
      id: n.id,
      x: n.position.x,
      y: n.position.y,
      px: e.clientX,
      py: e.clientY,
      sx: viewport.current?.scrollLeft || 0,
      sy: viewport.current?.scrollTop || 0,
    };
  };
  const moveDrag = (e: PointerEvent<HTMLButtonElement>) => {
    const d = drag.current;
    if (d) {
      move(
        d.id,
        d.x + e.clientX - d.px + (viewport.current?.scrollLeft || 0) - d.sx,
        d.y + e.clientY - d.py + (viewport.current?.scrollTop || 0) - d.sy,
      );
    }
  };
  const connect = (identity: string, port: string) => {
    if (!source) {
      setError('먼저 외부 입력이나 노드의 출력 포트를 선택하세요.');
      return;
    }
    change({
      ...doc,
      edges: [...doc.edges, { id: uid(), source, target: { node: identity, port } }],
    });
    setSource(null);
  };
  const removeEdge = (identity: string) => {
    change({ ...doc, edges: doc.edges.filter((e) => e.id !== identity) });
    setSelectedEdge('');
  };
  const removeNode = () => {
    change({
      ...doc,
      nodes: doc.nodes.filter((n) => n.id !== selected),
      edges: doc.edges.filter((e) => e.source.node !== selected && e.target.node !== selected),
    });
    setSelected('');
    setSource(null);
  };
  const point = (p: Port, output: boolean) => {
    if (p.node === '$input') {
      return { x: 260, y: 100 + Object.keys(doc.inputs).indexOf(p.port) * 36 };
    }
    const n = doc.nodes.find((x) => x.id === p.node),
      s = catalog.find((x) => x.id === n?.type);
    if (!n || !s) {
      return null;
    }
    const index = Object.keys(output ? s.outputs : s.inputs).indexOf(p.port);
    return { x: n.position.x + (output ? 248 : 0), y: n.position.y + 80 + index * 36 };
  };
  useEffect(() => {
    void (async () => {
      try {
        const c = await request<{ nodes: Spec[] }>('/settings/node-catalog');
        setCatalog(c.nodes);
        await list();
      } catch (e) {
        setError(e instanceof Error ? e.message : '정의를 읽지 못했습니다.');
      } finally {
        setBusy('');
      }
    })();
  }, []);

  return (
    <main className="workflow-editor">
      <div className="editor-heading">
        <div>
          <p className="workspace-eyebrow">편집 정의 · 실행과 분리</p>
          <h1>워크플로우 편집기</h1>
        </div>
        <Badge tone="neutral">
          편집 revision {doc.revision} · {dirty ? '미저장 편집' : '서버 반영 또는 새 정의'}
        </Badge>
      </div>
      <p>
        노드를 배치하고 포트를 연결해 저장합니다.{' '}
        <strong>실제 티켓·개별 노드 실행은 하지 않습니다.</strong> 기존 고정 template·영상·설정에
        소급 적용되지 않습니다.
      </p>
      <p className="editor-help">
        초기·변경된 정의는 서버 검증 후 저장합니다. 문제가 있는 정의는 편집을 유지하되 저장하지
        않습니다. ‘열기/다시 불러오기’는 현재 편집을 서버값으로 교체합니다. 편집 revision은 실행
        버전정책이 아닙니다.
      </p>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {status && <p role="status">{status}</p>}
      <fieldset disabled={!!busy} className="editor-toolbar">
        <label>
          이름
          <Input
            aria-label="워크플로우 이름"
            value={doc.name}
            maxLength={80}
            onChange={(e) => change({ ...doc, name: e.target.value })}
          />
        </label>
        <Button onClick={() => void validate()}>서버에서 그래프 검증</Button>
        <Button onClick={() => void save()}>
          {busy === 'save' ? '저장 중' : '편집 정의 저장'}
        </Button>
        <Button
          variant="secondary"
          onClick={() => {
            setDoc(draft());
            setSelected('');
            setSource(null);
            setValidation(null);
            setDirty(false);
            setStatus('새 정의입니다. 이전 편집은 교체되었습니다.');
            setError('');
          }}
        >
          새 정의
        </Button>
      </fieldset>
      <fieldset disabled={!!busy} className="editor-toolbar">
        <label>
          저장된 정의
          <select
            aria-label="저장된 정의"
            value={openId}
            onChange={(e) => setOpenId(e.target.value)}
          >
            <option value="">저장된 정의 선택</option>
            {saved.map((s) => (
              <option value={s.id} key={s.id}>
                {s.name} · r{s.revision}
              </option>
            ))}
          </select>
        </label>
        <DefinitionHistory
          key={doc.id}
          identity={doc.id}
          revision={doc.revision}
          dirty={dirty}
          onRestored={async () => {
            await load(doc.id);
            await list();
          }}
        />
        <Button variant="secondary" disabled={!openId} onClick={() => void load(openId)}>
          선택 정의 서버값 열기
        </Button>
        <Button variant="secondary" disabled={doc.revision === 0} onClick={() => void load(doc.id)}>
          현재 정의 서버값 다시 불러오기
        </Button>
      </fieldset>
      {!catalog.length ? (
        <p>서버 catalog 미확인 · 편집은 catalog 로드 후 가능합니다.</p>
      ) : (
        <>
          <div className="editor-layout">
            <aside className="editor-panel" aria-label="노드 선택">
              <h2>처리 단계</h2>
              <p className="editor-help">
                현재 실행 경로가 있는 정의만 표시합니다. 아직 독립 executor가 아닙니다.
              </p>
              {catalog.map((c) => (
                <Button
                  key={c.id}
                  variant="secondary"
                  disabled={!!busy || doc.nodes.length >= 100}
                  onClick={() => add(c)}
                >
                  {c.label} 추가
                </Button>
              ))}
            </aside>
            <section className="editor-center">
              <div className="editor-heading">
                <h2>캔버스</h2>
                <span className="editor-help">
                  제목 끌기/방향키 이동 · 출력→입력 선택 · 영역 내부 스크롤
                </span>
              </div>
              <p className="editor-help">
                {source
                  ? `${nodeLabel(source.node)} 출력 ${source.port} 선택됨 · 연결할 입력을 누르세요.`
                  : '출력을 누른 뒤 입력을 눌러 연결하세요.'}
              </p>
              <div
                className="editor-canvas"
                ref={viewport}
                tabIndex={0}
                aria-label="워크플로우 캔버스"
                onKeyDown={(e) => {
                  if (e.key === 'Escape') {
                    setSource(null);
                  }
                }}
              >
                <div
                  className="editor-world"
                  style={{
                    width: Math.max(1250, ...doc.nodes.map((n) => n.position.x + 320)),
                    height: Math.max(700, ...doc.nodes.map((n) => n.position.y + 240)),
                  }}
                >
                  <svg className="editor-wires" width="100%" height="100%" aria-label="연결선">
                    <defs>
                      <marker
                        id="editor-arrow"
                        viewBox="0 0 10 10"
                        refX="10"
                        refY="5"
                        markerWidth="7"
                        markerHeight="7"
                        orient="auto-start-reverse"
                      >
                        <path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor" />
                      </marker>
                    </defs>
                    {doc.edges.map((e) => {
                      const a = point(e.source, true),
                        b = point(e.target, false);
                      return a && b ? (
                        <path
                          key={e.id}
                          d={`M${a.x},${a.y} C${a.x + 70},${a.y} ${b.x - 70},${b.y} ${b.x},${b.y}`}
                          markerEnd="url(#editor-arrow)"
                          className={
                            validation?.issues.some((i) => i.edge_id === e.id)
                              ? 'bad'
                              : selectedEdge === e.id
                                ? 'selected'
                                : ''
                          }
                          onClick={() => setSelectedEdge(e.id)}
                        />
                      ) : null;
                    })}
                  </svg>
                  <article className="canvas-input">
                    <h3>외부 입력 · 파일 선언만</h3>
                    {Object.entries(doc.inputs).map(([key, type]) => (
                      <button
                        type="button"
                        key={key}
                        disabled={!!busy}
                        className="editor-port"
                        aria-label={`외부 출력 ${key}`}
                        onClick={() => setSource({ node: '$input', port: key })}
                      >
                        {key} <small>{type} →</small>
                      </button>
                    ))}
                  </article>
                  {doc.nodes.map((n) => {
                    const s = resolveSpec(
                      catalog.find((x) => x.id === n.type),
                      n.options,
                    );
                    if (!s) {
                      return null;
                    }
                    const invalid = validation?.issues.some((i) => i.node_id === n.id);
                    return (
                      <article
                        className={`canvas-node ${selected === n.id ? 'selected' : ''} ${invalid ? 'invalid' : ''}`}
                        data-id={n.id}
                        data-node-type={n.type}
                        key={n.id}
                        style={{ left: n.position.x, top: n.position.y }}
                      >
                        <button
                          type="button"
                          disabled={!!busy}
                          className="canvas-drag"
                          onPointerDown={(e) => startDrag(e, n)}
                          onPointerMove={moveDrag}
                          onPointerUp={() => {
                            drag.current = null;
                          }}
                          onPointerCancel={() => {
                            drag.current = null;
                          }}
                          onClick={() => setSelected(n.id)}
                          onKeyDown={(e) => {
                            const vectors: Record<string, [number, number]> = {
                              ArrowLeft: [-20, 0],
                              ArrowRight: [20, 0],
                              ArrowUp: [0, -20],
                              ArrowDown: [0, 20],
                            };
                            if (vectors[e.key]) {
                              e.preventDefault();
                              move(
                                n.id,
                                n.position.x + vectors[e.key][0],
                                n.position.y + vectors[e.key][1],
                              );
                            }
                          }}
                        >
                          {s.label}
                          <small>{invalid ? '입력/연결 문제' : n.id.slice(0, 6)}</small>
                        </button>
                        <div className="canvas-ports">
                          <div>
                            {Object.entries(s.inputs).map(([key, type]) => (
                              <button
                                type="button"
                                key={key}
                                className="editor-port in"
                                disabled={!!busy}
                                aria-label={`입력 ${key}`}
                                onClick={() => connect(n.id, key)}
                              >
                                <span>● {key}</span>
                                <small>
                                  {type}
                                  {s.optional_inputs.includes(key) ? ' · 선택' : ''}
                                </small>
                              </button>
                            ))}
                          </div>
                          <div>
                            {Object.entries(s.outputs).map(([key, type]) => (
                              <button
                                type="button"
                                key={key}
                                disabled={!!busy}
                                className="editor-port out"
                                aria-label={`출력 ${key}`}
                                onClick={() => setSource({ node: n.id, port: key })}
                              >
                                <span>{key} ●</span>
                                <small>{type}</small>
                              </button>
                            ))}
                          </div>
                        </div>
                      </article>
                    );
                  })}
                </div>
              </div>
            </section>
            <aside className="editor-panel" aria-label="노드 속성">
              <h2>노드 속성</h2>
              {node && spec ? (
                <fieldset disabled={!!busy}>
                  <h3>{spec.label}</h3>
                  <NodeModelBinding
                    key={node.id}
                    type={node.type}
                    value={node.model_ref}
                    changed={(reference) =>
                      change({
                        ...doc,
                        nodes: doc.nodes.map((n) =>
                          n.id === node.id ? { ...n, model_ref: reference } : n,
                        ),
                      })
                    }
                  />
                  {node.type === 'preprocess_audio' && (
                    <p className="editor-help">
                      전처리 옵션은 이 노드에 저장합니다. 현재 새 실행 경로의 GPU VAD/NVIDIA 무음
                      제거는 미지원이며 서버가 거절합니다.
                    </p>
                  )}
                  <label>
                    배치 X
                    <Input
                      type="number"
                      min={0}
                      max={4000}
                      aria-label="노드 X"
                      value={node.position.x}
                      onChange={(e) => move(node.id, Number(e.target.value), node.position.y)}
                    />
                  </label>
                  <label>
                    배치 Y
                    <Input
                      type="number"
                      min={0}
                      max={3000}
                      aria-label="노드 Y"
                      value={node.position.y}
                      onChange={(e) => move(node.id, node.position.x, Number(e.target.value))}
                    />
                  </label>
                  {Object.entries(spec.options).map(([key, values]) => (
                    <label key={key}>
                      {key}
                      <select
                        aria-label={`노드 옵션 ${key}`}
                        value={node.options[key] || values[0]}
                        onChange={(e) =>
                          change({
                            ...doc,
                            nodes: doc.nodes.map((n) =>
                              n.id === node.id
                                ? { ...n, options: { ...n.options, [key]: e.target.value } }
                                : n,
                            ),
                          })
                        }
                      >
                        {values.map((v) => (
                          <option key={v}>{v}</option>
                        ))}
                      </select>
                    </label>
                  ))}
                  <Button variant="secondary" onClick={removeNode}>
                    선택 노드 삭제
                  </Button>
                </fieldset>
              ) : (
                <p>노드 제목을 선택하세요. 작은 화면에서는 배치 X/Y로도 이동할 수 있습니다.</p>
              )}
              <h3>외부 입력 선언</h3>
              <p className="editor-help">
                실제 파일·세션은 여기서 연결하지 않습니다. 입력 포트당 소스 하나를 연결하세요. 수동
                분기·결과 목록 합류는 <a href="#/graph-tickets">분기·병렬 티켓</a>에서 계획 확인 후
                실행 요청합니다. AI 조건 판단은 <a href="#/decision-tickets">AI 판단 티켓</a>에서
                구조화 결과·서버 조건을 고정하고 선택 후행을 새로 확인합니다.
              </p>
              <fieldset disabled={!!busy}>
                <label>
                  입력 이름
                  <Input
                    aria-label="외부 입력 이름"
                    value={inputName}
                    maxLength={40}
                    onChange={(e) => setInputName(e.target.value)}
                  />
                </label>
                <label>
                  유형
                  <select
                    aria-label="외부 입력 유형"
                    value={inputType}
                    onChange={(e) => setInputType(e.target.value)}
                  >
                    {inputTypes.map((t) => (
                      <option key={t}>{t}</option>
                    ))}
                  </select>
                </label>
                <Button
                  variant="secondary"
                  onClick={() => {
                    if (
                      !/^[A-Za-z][A-Za-z0-9_-]{0,39}$/.test(inputName) ||
                      inputName in doc.inputs
                    ) {
                      setError(
                        '입력 이름은 영문으로 시작하는 고유한 영문/숫자/_/- 40자 이하여야 합니다.',
                      );
                      return;
                    }
                    change({ ...doc, inputs: { ...doc.inputs, [inputName]: inputType } });
                    setInputName('');
                  }}
                >
                  외부 입력 추가
                </Button>
                {Object.keys(doc.inputs).map((k) => (
                  <Button
                    key={k}
                    variant="secondary"
                    onClick={() => {
                      const next = { ...doc.inputs };
                      delete next[k];
                      change({ ...doc, inputs: next });
                    }}
                  >
                    {k} 선언 제거
                  </Button>
                ))}
              </fieldset>
            </aside>
          </div>
          <section className="editor-panel">
            <h2>연결 목록</h2>
            <Button
              variant="secondary"
              disabled={!!busy || !selectedEdge}
              onClick={() => removeEdge(selectedEdge)}
            >
              선택 연결 해제
            </Button>
            {doc.edges.map((e) => (
              <div
                key={e.id}
                className={`graph-edge-row ${validation?.issues.some((i) => i.edge_id === e.id) ? 'invalid' : ''}`}
              >
                <span>
                  {nodeLabel(e.source.node)}.{e.source.port} → {nodeLabel(e.target.node)}.
                  {e.target.port}
                </span>
                <Button variant="secondary" disabled={!!busy} onClick={() => removeEdge(e.id)}>
                  연결 해제
                </Button>
              </div>
            ))}
          </section>
          {validation && (
            <section className="editor-panel graph-issues" aria-live="polite">
              <h2>{validation.valid ? '정의 유형·연결 검증 통과' : '정의에 문제가 있습니다'}</h2>
              <p>{validation.notice}</p>
              {validation.issues.map((i, index) => (
                <p key={index}>
                  {i.node_id
                    ? `${nodeLabel(i.node_id)} (${i.node_id.slice(0, 6)}) · `
                    : i.edge_id
                      ? '연결 · '
                      : ''}
                  {i.message}
                </p>
              ))}
            </section>
          )}
        </>
      )}
      <p className="editor-help">
        노드 설정과 고정 모델 revision을 저장한 뒤 작업 시작에서 계획을 확인하세요. 저장은 모델
        실행/키 변경/큐 소비가 아닙니다.
      </p>
    </main>
  );
};
