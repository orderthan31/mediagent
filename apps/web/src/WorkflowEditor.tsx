import { useEffect, useState } from 'react';
import { request } from './api';
import { PageTitle } from './PageTitle';
import { LoadingSkeleton } from './LoadingSkeleton';
import { jsonPost } from './video-api';
import { resolvePorts } from './workflow-spec';
import { savedGoalOption } from './goal-languages';
import { languageLabel } from './language-label';
import { setWorkflowInput, setAudioSource } from './normal-inputs';
import { WorkflowCanvas, type CanvasDefinition, type CanvasSpec } from './WorkflowCanvas';
import { Button } from './hangyeol/primitives/button';
import { Input } from './hangyeol/primitives/input';
import { NodeModelBinding } from './NodeModelBinding';
import { NodeConfiguration } from './NodeConfiguration';
import { DefinitionHistory } from './DefinitionHistory';
import { frontendOnly } from './preview';
import { isControlNode, controlFieldLabels, controlValueLabels } from './workflow-controls';
import { createAgentWorkflow } from './workflow-templates';
import './workflow-editor.css';

type Definition = CanvasDefinition & { catalog_version: number };
type Validation = {
  valid: boolean;
  issues: { node_id: string | null; edge_id: string | null; message: string }[];
};
const endpoint = '/settings/workflow-definitions';
const draft = (): Definition => ({
  id: crypto.randomUUID().replaceAll('-', ''),
  catalog_version: 2,
  revision: 0,
  name: '새 워크플로우',
  inputs: {},
  nodes: [],
  edges: [],
});
const payload = ({
  catalog_version,
  revision,
  name,
  inputs,
  nodes,
  edges,
  input_profile,
}: Definition) => ({
  catalog_version,
  revision,
  name,
  inputs,
  nodes,
  edges,
  ...(input_profile ? { input_profile } : {}),
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
  const [templateNotice, setTemplateNotice] = useState('');
  const node = doc.nodes.find((item) => item.id === selected);
  const spec = resolvePorts(
    catalog.find((item) => item.id === node?.type),
    node?.options,
    node?.tool_settings,
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
            simple
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
          (() => {
            const internal = new Set([
              'batch_policy',
              'clock_policy',
              'media_budget',
              'processing_profile',
              'translation_profile',
              'model_source',
              'video_budget',
              'max_model_calls',
              'review_policy',
            ]);
            const render = () =>
              Object.entries(spec.options)
                .filter(
                  ([key]) =>
                    !internal.has(key) &&
                    (node.type !== 'transcribe' ||
                      ['source_language', 'llm_options'].includes(key)) &&
                    (node.type !== 'translate' || ['target_language', 'llm_options'].includes(key)),
                )
                .map(([key, values]) => {
                  const selectedValue = savedGoalOption(node, spec, key, values[0]);
                  const update = (value: string) => {
                    if (key === 'audio_source') {
                      try {
                        change(setAudioSource(doc, node.id, value));
                      } catch (reason) {
                        setError(
                          reason instanceof Error ? reason.message : '음성 출처를 확인하세요.',
                        );
                      }
                      return;
                    }
                    change({
                      ...doc,
                      nodes: doc.nodes.map((item) =>
                        item.id === node.id
                          ? { ...item, options: { ...item.options, [key]: value } }
                          : item,
                      ),
                    });
                  };
                  const free =
                    (key === 'target_language' && node.type === 'translation_agent') ||
                    (values.length === 1 && (isControlNode(node.type) || values[0] === ''));
                  return (
                    <label key={key}>
                      {(
                        {
                          batch_policy: '분할 처리 방식',
                          max_model_calls: '최대 모델 호출 수',
                          source_language: '원문 언어',
                          audio_source: '전사 음성 출처',
                          target_language: '대상 언어',
                          transcript_source: '자막에 사용할 전사문',
                          language: '자막 언어',
                          llm_options: '모델 요청 옵션 (JSON)',
                          audio_filter: '음성 처리',
                          vad_mode: '음성 구간 처리',
                          subtitle_mode: '자막 표시',
                          video_codec: '영상 형식',
                          preset: '합성 품질',
                          quality_profile: '화질',
                          resolution: '해상도',
                          format: '자막 형식',
                        } as Record<string, string>
                      )[key] ||
                        controlFieldLabels[key] ||
                        key}
                      {key === 'cases' ? (
                        <textarea
                          aria-label="분기값"
                          value={selectedValue}
                          rows={4}
                          onChange={(event) => update(event.target.value)}
                        />
                      ) : free ? (
                        <Input
                          aria-label={
                            (
                              {
                                batch_policy: '분할 처리 방식',
                                max_model_calls: '최대 모델 호출 수',
                                llm_options: '모델 요청 옵션 (JSON)',
                                audio_filter: '음성 처리',
                                vad_mode: '음성 구간 처리',
                                subtitle_mode: '자막 표시',
                                video_codec: '영상 형식',
                                preset: '합성 품질',
                                quality_profile: '화질',
                                resolution: '해상도',
                                format: '자막 형식',
                                target_language: '대상 언어',
                              } as Record<string, string>
                            )[key] ||
                            controlFieldLabels[key] ||
                            key
                          }
                          type={
                            ['repeat_count', 'max_iterations', 'max_attempts'].includes(key)
                              ? 'number'
                              : 'text'
                          }
                          min={1}
                          value={selectedValue}
                          onChange={(event) => update(event.target.value)}
                        />
                      ) : (
                        <select
                          aria-label={
                            (
                              {
                                batch_policy: '분할 처리 방식',
                                max_model_calls: '최대 모델 호출 수',
                                llm_options: '모델 요청 옵션 (JSON)',
                                audio_filter: '음성 처리',
                                vad_mode: '음성 구간 처리',
                                subtitle_mode: '자막 표시',
                                video_codec: '영상 형식',
                                preset: '합성 품질',
                                quality_profile: '화질',
                                resolution: '해상도',
                                format: '자막 형식',
                                transcript_source: '자막에 사용할 전사문',
                                language: '자막 언어',
                                audio_source: '전사 음성 출처',
                              } as Record<string, string>
                            )[key] ||
                            controlFieldLabels[key] ||
                            key
                          }
                          value={selectedValue}
                          onChange={(event) => update(event.target.value)}
                        >
                          {values.map((value) => (
                            <option value={value} key={value}>
                              {['source_language', 'target_language', 'language'].includes(key) &&
                              !['from_transcript', 'und'].includes(value)
                                ? languageLabel(value)
                                : (
                                    {
                                      streamed_vocalization_v2: '장문 분할 판정 (원본 최대 6시간)',
                                      bounded_vocalization_v1: '기존 단기 판정 (원본 최대 300초)',
                                      current: '연결된 전사·번역 결과',
                                      original: '원문 전사',
                                      translated: '번역 전사',
                                      from_transcript: '선택한 전사문 언어 (자동 감지는 미지정)',
                                      und: '언어 미지정',
                                      burn: '번인',
                                      soft: '소프트 자막',
                                      srt_smi: 'SRT + SAMI',
                                      video: '선택 영상에서 새로 추출',
                                      audio_file_v1: '음성 원본 파일',
                                      selected_audio: '같은 영상의 완료된 추출 WAV 재사용',
                                    } as Record<string, string>
                                  )[value] ||
                                  controlValueLabels[value] ||
                                  value}
                            </option>
                          ))}
                        </select>
                      )}
                    </label>
                  );
                });
            return <>{render()}</>;
          })()}
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
          setCatalog(specs.nodes);
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
        {!initialId && (
          <Button
            variant="secondary"
            disabled={!!busy || !catalog.length}
            onClick={() => {
              if (
                dirty &&
                !window.confirm('저장하지 않은 편집이 있습니다. 기존 전체 작업 초안으로 바꿀까요?')
              ) {
                return;
              }
              change(createAgentWorkflow());
              setSelected('');
              setError('');
              setTemplateNotice(
                '얼굴합성 제외 초안입니다. 전사·번역 모델을 선택하고 저장하세요. 모델과 언어를 선택하고 저장하세요.',
              );
            }}
          >
            기존 전체 작업 만들기
          </Button>
        )}
        {!initialId && (
          <Button
            variant="secondary"
            disabled={!!busy}
            onClick={() => {
              if (
                dirty &&
                !window.confirm('저장하지 않은 편집이 있습니다. 얼굴 합성 초안으로 바꿀까요?')
              ) {
                return;
              }
              change({
                ...createAgentWorkflow(),
                name: '얼굴 합성',
                input_profile: 'face_workflow_v1',
                inputs: { photo: 'image' },
                nodes: [
                  { id: 'face', type: 'faceswap_agent', position: { x: 0, y: 80 }, options: {} },
                ],
                edges: [],
              });
              setSelected('');
              setError('');
              setTemplateNotice(
                '사진·영상의 인물 분석과 미리보기 확인을 거쳐 합성합니다. 단계별 실행기를 선택해야 시작할 수 있습니다.',
              );
            }}
          >
            얼굴 합성 작업 만들기
          </Button>
        )}
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
      {templateNotice && (
        <p className="workflow-template-notice" role="status">
          {templateNotice}
        </p>
      )}
      {doc.catalog_version === 2 && doc.input_profile !== 'face_workflow_v1' && (
        <fieldset disabled={!!busy} aria-label="워크플로우 선택 입력 설정">
          <legend>작업 시작 시 선택할 입력</legend>
          <label>
            <input
              type="checkbox"
              checked={doc.inputs.transcript === 'transcript'}
              onChange={(event) =>
                change(setWorkflowInput(doc, 'transcript', event.target.checked))
              }
            />
            SRT 또는 완료된 전사문 선택
          </label>
          <label>
            <input
              type="checkbox"
              checked={doc.inputs.audio === 'audio'}
              onChange={(event) => change(setWorkflowInput(doc, 'audio', event.target.checked))}
            />
            같은 영상의 추출 WAV 재사용 (전사 목표에서 재추출 생략)
          </label>
        </fieldset>
      )}
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
          onChange={(next) => {
            const face = next.nodes.some((n) => n.type === 'faceswap_agent');
            if (face && (next.nodes.length !== 1 || next.edges.length)) {
              setError('얼굴 합성은 독립된 얼굴 합성 작업으로 만드세요.');
              return;
            }
            const { input_profile: profile, ...base } = doc;
            change({
              ...base,
              ...(face
                ? { input_profile: 'face_workflow_v1' as const, inputs: { photo: 'image' } }
                : profile === 'face_workflow_v1'
                  ? { inputs: {} }
                  : profile
                    ? { input_profile: profile }
                    : {}),
              nodes: next.nodes,
              edges: next.edges,
            });
          }}
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
