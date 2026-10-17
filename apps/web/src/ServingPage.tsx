import { useEffect, useState, type FormEvent } from 'react';
import { PageTitle } from './PageTitle';
import { request } from './api';
import { resolvePorts } from './workflow-spec';
import { jsonPost } from './video-api';
import { Button } from './hangyeol/primitives/button';
import { Input } from './hangyeol/primitives/input';
import { Badge } from './hangyeol/primitives/badge';
import './serving.css';

type Role = 'transcription' | 'translation';
type Assignment = {
  provider: string;
  model: string;
  fallback_provider: string;
  fallback_model: string;
  credential: { has_api_key: boolean; key_source: string };
  fallback_credential: { has_api_key: boolean; key_source: string };
  credential_provider: string;
  fallback_credential_provider: string;
};
type Serving = {
  revision: number;
  workers: Record<Role, Assignment>;
  fallback_on_error: boolean;
  fallback_on_block: boolean;
  providers: Record<string, string>;
  stt_models: Record<string, string[]>;
  runtime: { notice: string };
  fixed_workers: { id: string; provider: string; reason: string }[];
};
type Node = {
  id: string;
  label: string;
  inputs: Record<string, string>;
  outputs: Record<string, string>;
  optional_inputs: string[];
  worker_role: string;
  options: Record<string, string[]>;
  port_types_from_options?: Partial<Record<'inputs' | 'outputs', Record<string, string>>>;
  embedded_operations: string[];
  entrypoint: string;
};
type Catalog = { version: number; nodes: Node[]; scope: string; notes: string[] };
const roles: [Role, string][] = [
  ['transcription', '전사'],
  ['translation', '번역'],
];
const portTypes = [
  'video',
  'audio',
  'timeline_map',
  'transcript',
  'subtitle',
  'faceswap_session',
  'faceswap_preview',
];

export const ServingPage = () => {
  const [config, setConfig] = useState<Serving | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [stale, setStale] = useState(false);
  const [notice, setNotice] = useState('');
  const [selected, setSelected] = useState('analyze');
  const [inputs, setInputs] = useState<Record<string, string>>({ video: 'video' });
  const [options, setOptions] = useState<Record<string, string>>({});
  const [validation, setValidation] = useState('');
  const node = resolvePorts(
    catalog?.nodes.find((n) => n.id === selected),
    options,
  );

  const load = async () => {
    setBusy('load');
    setError('');
    setNotice('');
    try {
      const [saved, nodes] = await Promise.all([
        request<Serving>('/settings/serving'),
        request<Catalog>('/settings/node-catalog'),
      ]);
      setConfig(saved);
      setCatalog(nodes);
      setStale(false);
    } catch (e) {
      setStale(true);
      setError(e instanceof Error ? e.message : '서빙 정보를 불러오지 못했습니다.');
    } finally {
      setBusy('');
    }
  };
  const change = (
    role: Role,
    field: 'provider' | 'model' | 'fallback_provider' | 'fallback_model',
    value: string,
  ) => {
    if (!config) {
      return;
    }
    const next = { ...config.workers[role], [field]: value };
    if (field === 'provider') {
      next.model = '';
    }
    if (field === 'fallback_provider') {
      next.fallback_model = '';
    }
    setConfig({ ...config, workers: { ...config.workers, [role]: next } });
    setNotice('');
  };
  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!config || stale || busy) {
      return;
    }
    setBusy('save');
    setError('');
    setNotice('');
    try {
      const workers = Object.fromEntries(
        roles.map(([role]) => {
          const w = config.workers[role];
          return [
            role,
            {
              provider: w.provider,
              model: w.model,
              fallback_provider: w.fallback_provider,
              fallback_model: w.fallback_model,
            },
          ];
        }),
      );
      const saved = await request<Serving>('/settings/serving', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          revision: config.revision,
          workers,
          fallback_on_error: config.fallback_on_error,
          fallback_on_block: config.fallback_on_block,
        }),
      });
      setConfig(saved);
      setNotice(
        '서빙 설정을 저장했습니다. 다음 작업·재시도부터 적용되며 추론 성공을 뜻하지 않습니다.',
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : '저장 실패. 입력은 유지됩니다.');
    } finally {
      setBusy('');
    }
  };
  const selectNode = (id: string) => {
    const n = catalog?.nodes.find((x) => x.id === id);
    if (!n) {
      return;
    }
    setSelected(id);
    setValidation('');
    setInputs(
      Object.fromEntries(
        Object.entries(n.inputs).filter(([key]) => !n.optional_inputs.includes(key)),
      ),
    );
    setOptions(
      Object.fromEntries(
        Object.entries(n.options).map(([key, values]) => [
          key,
          key === 'subtitle_mode' ? 'none' : values[0],
        ]),
      ),
    );
  };
  const validate = async () => {
    setBusy('validate');
    setValidation('');
    try {
      const result = await jsonPost<{ notice: string }>('/settings/node-validation', {
        node: selected,
        inputs: Object.fromEntries(Object.entries(inputs).filter(([, value]) => !!value)),
        options,
      });
      setValidation('유형 검증 통과 · ' + result.notice);
    } catch (e) {
      setValidation('유형 검증 실패 · ' + (e instanceof Error ? e.message : '입력을 확인하세요.'));
    } finally {
      setBusy('');
    }
  };
  const renderModel = (role: Role, fallback: boolean, label: string) => {
    if (!config) {
      return null;
    }
    const w = config.workers[role],
      provider = fallback ? w.fallback_provider : w.provider,
      field = fallback ? 'fallback_model' : 'model',
      value = w[field];
    const models = config.stt_models[provider] || [];
    return (
      <label>
        {label}
        {role === 'transcription' && provider !== 'gemini' ? (
          <select
            aria-label={label}
            value={value}
            required={!fallback}
            onChange={(e) => change(role, field, e.target.value)}
          >
            <option value="">{fallback ? '사용 안 함' : '지원 모델 선택'}</option>
            {value && !models.includes(value) && (
              <option value={value} disabled>
                미지원 저장 모델: {value}
              </option>
            )}
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        ) : (
          <Input
            aria-label={label}
            value={value}
            maxLength={200}
            required={!fallback}
            placeholder={fallback ? '사용 안 함' : '모델 ID'}
            onChange={(e) => change(role, field, e.target.value)}
          />
        )}
      </label>
    );
  };
  useEffect(() => {
    void load();
  }, []);

  return (
    <main className="serving-page">
      <header className="serving-heading">
        <div>
          <PageTitle>역할 설정</PageTitle>
        </div>
        <Button variant="secondary" disabled={!!busy} onClick={() => void load()}>
          새로고침
        </Button>
      </header>
      {error && (
        <p role="alert" className="alert">
          {error} 저장 실패 뒤 입력은 유지됩니다. 충돌은 새로 불러온 뒤 다시 선택하세요.
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {stale && (
        <p role="status">
          서버 조회 실패 · 이전 값은 최신 설정이 아닐 수 있습니다. 다시 불러오기 전에는 저장할 수
          없습니다.
        </p>
      )}
      {!config ? (
        <p>{error ? '서빙 설정 미확인' : '서빙 설정을 불러오는 중입니다.'}</p>
      ) : (
        <form onSubmit={(e) => void save(e)} aria-busy={!!busy}>
          <div className="serving-heading">
            <h2>역할별 서빙 설정</h2>
            <Badge tone="neutral">설정 revision {config.revision}</Badge>
          </div>
          <div className="serving-roles">
            {roles.map(([role, label]) => (
              <fieldset key={role} disabled={!!busy || stale}>
                <legend>{label} 에이전트 역할</legend>
                <Badge tone="neutral">연결·추론 미확인</Badge>
                <div className="serving-grid">
                  <label>
                    {label} 공급자
                    <select
                      aria-label={`서빙 ${label} 공급자`}
                      value={config.workers[role].provider}
                      onChange={(e) => change(role, 'provider', e.target.value)}
                    >
                      {Object.entries(config.providers)
                        .filter(([p]) => role !== 'transcription' || p in config.stt_models)
                        .map(([p, name]) => (
                          <option key={p} value={p}>
                            {name}
                          </option>
                        ))}
                    </select>
                  </label>
                  {renderModel(role, false, `서빙 ${label} 모델`)}
                  <label>
                    {label} 폴백 공급자
                    <select
                      aria-label={`서빙 ${label} 폴백 공급자`}
                      value={config.workers[role].fallback_provider}
                      onChange={(e) => change(role, 'fallback_provider', e.target.value)}
                    >
                      {Object.entries(config.providers)
                        .filter(([p]) => role !== 'transcription' || p in config.stt_models)
                        .map(([p, name]) => (
                          <option key={p} value={p}>
                            {name}
                          </option>
                        ))}
                    </select>
                  </label>
                  {renderModel(role, true, `서빙 ${label} 폴백 모델`)}
                </div>
                <p className="serving-help">
                  마지막 조회한 {config.providers[config.workers[role].credential_provider]} 기본
                  키:{' '}
                  {config.workers[role].credential.has_api_key
                    ? config.workers[role].credential.key_source
                    : '없음'}{' '}
                  · 저장된 폴백 키:{' '}
                  {config.workers[role].fallback_credential.has_api_key
                    ? config.workers[role].fallback_credential.key_source
                    : '없음'}
                  . 선택 변경 뒤 키 상태는 저장/재조회 후 반영됩니다.
                </p>
                {role === 'transcription' && (
                  <p className="serving-help">
                    Anthropic 전사는 지원하지 않습니다. Gemini 외 전사는 서버 허용 모델만 선택할 수
                    있습니다.
                  </p>
                )}
              </fieldset>
            ))}
          </div>
          <fieldset disabled={!!busy || stale}>
            <legend>전사·번역 공유 폴백 정책</legend>
            <label className="serving-check">
              <input
                type="checkbox"
                checked={config.fallback_on_error}
                onChange={(e) => {
                  setConfig({ ...config, fallback_on_error: e.target.checked });
                  setNotice('');
                }}
              />
              오류 때 설정된 폴백 사용
            </label>
            <label className="serving-check">
              <input
                type="checkbox"
                checked={config.fallback_on_block}
                onChange={(e) => {
                  setConfig({ ...config, fallback_on_block: e.target.checked });
                  setNotice('');
                }}
              />
              차단 때 설정된 폴백 사용
            </label>
            <p>
              폴백 모델이 비어 있으면 미사용입니다. 기본과 같은 공급자·모델의 폴백은 저장할 수
              없습니다.
            </p>
          </fieldset>
          <Button type="submit" disabled={!!busy || stale}>
            {busy === 'save' ? '저장 중' : '서빙 설정 저장'}
          </Button>
        </form>
      )}
      {config && (
        <section aria-label="고정 실행기">
          <h2>환경에서 지정하는 실행기</h2>
          {config.fixed_workers.map((w) => (
            <article key={w.id}>
              <h3>{w.provider}</h3>
              <p>{w.reason}</p>
            </article>
          ))}
        </section>
      )}
      {catalog && (
        <section aria-label="에이전트 입출력 검증">
          <h2>현재 처리 단계·입출력</h2>
          <p>{catalog.scope}</p>
          {catalog.notes.map((t) => (
            <p className="serving-help" key={t}>
              {t}
            </p>
          ))}
          <div className="serving-node-list">
            {catalog.nodes.map((n) => (
              <Button
                key={n.id}
                variant={selected === n.id ? 'primary' : 'secondary'}
                onClick={() => selectNode(n.id)}
              >
                {n.label}
              </Button>
            ))}
          </div>
          {node && (
            <article className="serving-node">
              <h3>{node.label}</h3>
              <p>
                역할 {node.worker_role} · 기존 실행 경로 <code>{node.entrypoint}</code>
              </p>
              <p>
                출력:{' '}
                {Object.entries(node.outputs)
                  .map(([key, type]) => `${key}: ${type}`)
                  .join(' · ')}
              </p>
              {node.embedded_operations.length > 0 && (
                <p>포함 동작: {node.embedded_operations.join(' · ')} (독립 실행 API 아님)</p>
              )}
              <div className="serving-grid">
                {Object.entries(node.inputs).map(([key, type]) => (
                  <label key={key}>
                    입력 {key} · {type}
                    {node.optional_inputs.includes(key) ? ' (선택)' : ' (필수)'}
                    <select
                      aria-label={`에이전트 입력 ${key}`}
                      value={inputs[key] || ''}
                      onChange={(e) => {
                        setInputs({ ...inputs, [key]: e.target.value });
                        setValidation('');
                      }}
                    >
                      <option value="">연결 없음</option>
                      {portTypes.map((t) => (
                        <option key={t}>{t}</option>
                      ))}
                    </select>
                  </label>
                ))}
                {Object.entries(node.options).map(([key, values]) => (
                  <label key={key}>
                    검증용 {key}
                    <select
                      aria-label={`에이전트 옵션 ${key}`}
                      value={options[key] || values[0]}
                      onChange={(e) => {
                        setOptions({ ...options, [key]: e.target.value });
                        setValidation('');
                      }}
                    >
                      {values.map((v) => (
                        <option key={v}>{v}</option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
              <Button type="button" disabled={!!busy} onClick={() => void validate()}>
                호환성 확인
              </Button>
              {validation && <p role="status">{validation}</p>}
            </article>
          )}
        </section>
      )}
    </main>
  );
};
