import { useEffect, useState } from 'react';
import { request } from './api';
import { PageTitle } from './PageTitle';
import { LoadingSkeleton } from './LoadingSkeleton';
import { jsonPost } from './video-api';
import { resolvePorts } from './workflow-spec';
import { WorkflowCanvas, type CanvasDefinition, type CanvasSpec } from './WorkflowCanvas';
import { Button } from './hangyeol/primitives/button';
import { Input } from './hangyeol/primitives/input';
import { NodeModelBinding } from './NodeModelBinding';
import { NodeConfiguration } from './NodeConfiguration';
import { DefinitionHistory } from './DefinitionHistory';
import { frontendOnly } from './preview';
import {
  controlSpecs,
  isControlNode,
  controlFieldLabels,
  controlValueLabels,
} from './workflow-controls';
import './workflow-editor.css';

type Definition = CanvasDefinition & { catalog_version: number };
type Validation = {
  valid: boolean;
  issues: { node_id: string | null; edge_id: string | null; message: string }[];
};
const endpoint = '/settings/workflow-definitions';
const draft = (): Definition => ({
  id: crypto.randomUUID().replaceAll('-', ''),
  catalog_version: 1,
  revision: 0,
  name: '새 워크플로우',
  inputs: { video: 'video' },
  nodes: [],
  edges: [],
});
const payload = ({ catalog_version, revision, name, inputs, nodes, edges }: Definition) => ({
  catalog_version,
  revision,
  name,
  inputs,
  nodes,
  edges,
});
export const WorkflowEditor = ({ initialId }: { initialId?: string }) => {
  const [doc, setDoc] = useState<Definition>(draft);
  const [catalog, setCatalog] = useState<CanvasSpec[]>([]);
  const [selected, setSelected] = useState('');
  const [validation, setValidation] = useState<Validation | null>(null);
  const [busy, setBusy] = useState('load');
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const [dirty, setDirty] = useState(false);
  const [history, setHistory] = useState(false);
  const [inputName, setInputName] = useState('');
  const [inputType, setInputType] = useState('video');
  const node = doc.nodes.find((item) => item.id === selected);
  const spec = resolvePorts(
    catalog.find((item) => item.id === node?.type),
    node?.options,
  );
  const inputTypes = [...new Set(catalog.flatMap((item) => Object.values(item.inputs)))];
  const change = (next: Definition) => {
    setDoc(next);
    setDirty(true);
    setValidation(null);
    setStatus('');
  };
  const load = async (identity: string) => {
    setBusy('load');
    setError('');
    try {
      setDoc(await request<Definition>(endpoint + '/' + identity));
      setDirty(false);
      setSelected('');
      setValidation(null);
    } catch (value) {
      setError(value instanceof Error ? value.message : '워크플로우를 불러오지 못했습니다.');
    } finally {
      setBusy('');
    }
  };
  const save = async () => {
    setBusy('save');
    setError('');
    setStatus('');
    try {
      const result = await jsonPost<Validation>(endpoint + '/validate', payload(doc));
      setValidation(result);
      if (!result.valid) {
        setError('연결과 설정을 확인해 주세요.');
        return;
      }
      const next = await request<Definition>(endpoint + '/' + doc.id, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload(doc)),
      });
      setDoc(next);
      setDirty(false);
      setStatus('저장됨');
      if (!initialId) {
        window.location.hash = '#/workflows/' + next.id;
      }
    } catch (value) {
      setError(value instanceof Error ? value.message : '저장하지 못했습니다.');
    } finally {
      setBusy('');
    }
  };
  const removeNode = () => {
    change({
      ...doc,
      nodes: doc.nodes.filter((item) => item.id !== selected),
      edges: doc.edges.filter(
        (edge) => edge.source.node !== selected && edge.target.node !== selected,
      ),
    });
    setSelected('');
  };
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const [specs, saved] = await Promise.all([
          request<{ nodes: CanvasSpec[] }>('/settings/node-catalog', { signal: controller.signal }),
          initialId
            ? request<Definition>(endpoint + '/' + initialId, { signal: controller.signal })
            : Promise.resolve(null),
        ]);
        if (!controller.signal.aborted) {
          setCatalog([...specs.nodes, ...(frontendOnly ? controlSpecs : [])]);
          if (saved) {
            setDoc(saved);
          }
        }
      } catch (value) {
        if (!controller.signal.aborted) {
          setError(value instanceof Error ? value.message : '워크플로우를 불러오지 못했습니다.');
        }
      } finally {
        if (!controller.signal.aborted) {
          setBusy('');
        }
      }
    })();
    return () => controller.abort();
  }, [initialId]);
  const panel =
    selected === '$input' ? (
      <fieldset disabled={!!busy}>
        {Object.entries(doc.inputs).map(([key, type]) => (
          <div className="workflow-input-row" key={key}>
            <span>
              {key}
              <small>{type}</small>
            </span>
            <Button
              variant="quiet"
              size="small"
              aria-label={`${key} 입력 삭제`}
              onClick={() => {
                const inputs = { ...doc.inputs };
                delete inputs[key];
                change({
                  ...doc,
                  inputs,
                  edges: doc.edges.filter(
                    (edge) => edge.source.node !== '$input' || edge.source.port !== key,
                  ),
                });
              }}
            >
              삭제
            </Button>
          </div>
        ))}
        <label>
          이름
          <Input
            aria-label="입력 이름"
            value={inputName}
            maxLength={40}
            onChange={(event) => setInputName(event.target.value)}
          />
        </label>
        <label>
          유형
          <select
            value={inputType}
            aria-label="입력 유형"
            onChange={(event) => setInputType(event.target.value)}
          >
            {inputTypes.map((type) => (
              <option key={type}>{type}</option>
            ))}
          </select>
        </label>
        <Button
          variant="secondary"
          onClick={() => {
            if (!/^[A-Za-z][A-Za-z0-9_-]{0,39}$/.test(inputName) || inputName in doc.inputs) {
              setError(
                '입력 이름은 영문으로 시작하는 고유한 영문·숫자·_·- 40자 이내로 입력해 주세요.',
              );
              return;
            }
            change({ ...doc, inputs: { ...doc.inputs, [inputName]: inputType } });
            setInputName('');
          }}
        >
          입력 추가
        </Button>
      </fieldset>
    ) : node && spec ? (
      <fieldset disabled={!!busy}>
        {!isControlNode(node.type) && (
          <NodeModelBinding
            key={node.id}
            type={node.type}
            modelRole={spec.model_role}
            value={node.model_ref}
            fallbacks={node.fallback_refs}
            fallbackChanged={(refs) =>
              change({
                ...doc,
                nodes: doc.nodes.map((item) =>
                  item.id === node.id ? { ...item, fallback_refs: refs } : item,
                ),
              })
            }
            changed={(reference) =>
              change({
                ...doc,
                nodes: doc.nodes.map((item) =>
                  item.id === node.id
                    ? {
                        ...item,
                        model_ref: reference,
                        fallback_refs: reference
                          ? item.fallback_refs?.filter((ref) => ref.model_id !== reference.model_id)
                          : undefined,
                      }
                    : item,
                ),
              })
            }
          />
        )}
        {!spec.settings_schema &&
          Object.entries(spec.options).map(([key, values]) => {
            const update = (value: string) =>
              change({
                ...doc,
                nodes: doc.nodes.map((item) =>
                  item.id === node.id
                    ? { ...item, options: { ...item.options, [key]: value } }
                    : item,
                ),
              });
            const free = isControlNode(node.type) && values.length === 1;
            return (
              <label key={key}>
                {controlFieldLabels[key] || key}
                {key === 'cases' ? (
                  <textarea
                    aria-label="분기값"
                    value={node.options[key] ?? values[0]}
                    rows={4}
                    onChange={(event) => update(event.target.value)}
                  />
                ) : free ? (
                  <Input
                    aria-label={controlFieldLabels[key] || key}
                    type={
                      ['repeat_count', 'max_iterations', 'max_attempts'].includes(key)
                        ? 'number'
                        : 'text'
                    }
                    min={1}
                    value={node.options[key] ?? values[0]}
                    onChange={(event) => update(event.target.value)}
                  />
                ) : (
                  <select
                    aria-label={controlFieldLabels[key] || key}
                    value={node.options[key] || values[0]}
                    onChange={(event) => update(event.target.value)}
                  >
                    {values.map((value) => (
                      <option value={value} key={value}>
                        {controlValueLabels[value] || value}
                      </option>
                    ))}
                  </select>
                )}
              </label>
            );
          })}
        {frontendOnly && (spec.settings_schema || spec.review_contracts) && (
          <NodeConfiguration
            key={node.id}
            contract={spec}
            options={node.options}
            changed={(options) =>
              change({
                ...doc,
                nodes: doc.nodes.map((item) => (item.id === node.id ? { ...item, options } : item)),
              })
            }
          />
        )}
        <Button variant="quiet" onClick={removeNode}>
          노드 삭제
        </Button>
      </fieldset>
    ) : undefined;
  return (
    <main className="workflow-editor">
      <PageTitle>{doc.name}</PageTitle>
      <div className="workflow-editor-toolbar">
        <Input
          aria-label="워크플로우 이름"
          className="workflow-name"
          value={doc.name}
          maxLength={80}
          disabled={!!busy}
          onChange={(event) => change({ ...doc, name: event.target.value })}
        />
        <span className="workflow-save-state" role="status">
          {dirty ? '미저장' : status}
        </span>
        {doc.revision > 0 && (
          <Button variant="quiet" onClick={() => setHistory((previous) => !previous)}>
            이력
          </Button>
        )}
        <Button
          disabled={!!busy || !catalog.length}
          loading={busy === 'save'}
          onClick={() => void save()}
        >
          저장
        </Button>
      </div>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {validation && !validation.valid && (
        <ul className="workflow-errors" role="alert">
          {validation.issues.map((issue, index) => (
            <li key={index}>{issue.message}</li>
          ))}
        </ul>
      )}
      {busy === 'load' && doc.revision === 0 ? (
        <LoadingSkeleton layout="canvas" label="워크플로우 불러오는 중" />
      ) : (
        <WorkflowCanvas
          key={doc.id}
          definition={doc}
          catalog={catalog}
          disabled={!!busy || !catalog.length}
          onChange={(next) => change({ ...doc, nodes: next.nodes, edges: next.edges })}
          onSelect={setSelected}
          details={panel}
        />
      )}
      {history && doc.revision > 0 && (
        <div className="workflow-history-popover">
          <DefinitionHistory
            key={doc.id}
            identity={doc.id}
            revision={doc.revision}
            dirty={dirty}
            onRestored={() => load(doc.id)}
          />
        </div>
      )}
    </main>
  );
};
