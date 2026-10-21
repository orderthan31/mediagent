import { useEffect, useState } from 'react';
import { PageTitle } from './PageTitle';
import { LoadingSkeleton } from './LoadingSkeleton';
import { Pagination, usePagination } from './Pagination';
import { request } from './api';
import { frontendOnly, renewalBackend } from './preview';
import { ServingTabs } from './ProviderConnections';
import { connectionsEndpoint, type ServingConnection } from './serving-connection';
import { jsonPost } from './video-api';
import { Button } from './hangyeol/primitives/button';
import { Input } from './hangyeol/primitives/input';
import {
  type RegisteredModel,
  modelTypeLabels,
  modalityLabels,
  capabilityLabels,
} from './registered-models';
import { ModelProfileFields, emptyModelProfile, type ModelProfile } from './ModelProfileFields';
const modelUseLabels: Record<string, string> = {
  transcription: '전사',
  translation: '번역',
  decision: '판단',
};
import './serving.css';
import './workflow-tickets.css';

const endpoint = '/settings/registered-models';
export const ModelRegistryPage = ({
  form = false,
  identity,
  query = '',
}: {
  form?: boolean;
  identity?: string;
  query?: string;
}) => {
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [connections, setConnections] = useState<ServingConnection[]>([]);
  const [connectionId, setConnectionId] = useState('');
  const [connectionRevision, setConnectionRevision] = useState(0);
  const [providers, setProviders] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<RegisteredModel | null>(null);
  const [name, setName] = useState('');
  const [provider, setProvider] = useState('openai');
  const [model, setModel] = useState('');
  const [uses, setUses] = useState<string[]>([]);
  const [profile, setProfile] = useState<ModelProfile>(emptyModelProfile);
  const typedRegistry = frontendOnly || renewalBackend;
  const [compatible, setCompatible] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [listError, setListError] = useState('');
  const [listConfirmed, setListConfirmed] = useState(false);
  const [status, setStatus] = useState('');
  const load = async () => {
    setLoading(true);
    setListError('');
    try {
      const data = await request<{ models: RegisteredModel[]; providers: Record<string, string> }>(
        endpoint,
      );
      if (frontendOnly || renewalBackend) {
        const linked = await request<{ connections: ServingConnection[] }>(connectionsEndpoint);
        setConnections(linked.connections);
      }
      setModels(data.models);
      setProviders(data.providers);
      setListConfirmed(true);
    } catch (e) {
      setListError(e instanceof Error ? e.message : '등록 모델 조회 실패');
    } finally {
      setLoading(false);
    }
  };
  const reset = () => {
    setEditing(null);
    setName('');
    setModel('');
    setUses([]);
    setProfile(emptyModelProfile());
    setCompatible([]);
    setStatus('');
    setError('');
  };
  const check = async () => {
    setBusy(true);
    setError('');
    setCompatible([]);
    try {
      const data = await jsonPost<{ uses: string[]; reason: string }>(endpoint + '/compatibility', {
        provider,
        model,
        ...(renewalBackend
          ? { connection_id: connectionId, connection_revision: connectionRevision }
          : {}),
      });
      setCompatible(data.uses);
      setUses((previous) => previous.filter((u) => data.uses.includes(u)));
      if (!data.uses.length) {
        setError(data.reason);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '호환 용도 검사 실패');
    } finally {
      setBusy(false);
    }
  };
  const edit = async (row: RegisteredModel) => {
    const version = row.versions[String(row.current_revision)];
    setEditing(row);
    setName(version.name);
    setConnectionId(version.connection_id || '');
    setConnectionRevision(version.connection_revision || 0);
    setProvider(version.provider);
    setModel(version.model);
    setUses(version.uses || []);
    setProfile({
      model_types: version.model_types || [],
      input_modalities: version.input_modalities || [],
      output_modalities: version.output_modalities || [],
      capabilities: version.capabilities || [],
    });
    setCompatible([]);
    setStatus('');
    if (typedRegistry) {
      return;
    }
    setBusy(true);
    try {
      const data = await jsonPost<{ uses: string[] }>(endpoint + '/compatibility', {
        provider: version.provider,
        model: version.model,
        ...(renewalBackend
          ? {
              connection_id: version.connection_id,
              connection_revision: version.connection_revision,
            }
          : {}),
      });
      setCompatible(data.uses);
    } catch (e) {
      setError(e instanceof Error ? e.message : '호환 검사 실패');
    } finally {
      setBusy(false);
    }
  };
  const save = async () => {
    if (busy || loading || (identity && !editing) || listError) {
      return;
    }
    setBusy(true);
    setError('');
    try {
      const identity = editing?.id || crypto.randomUUID().replaceAll('-', '');
      const row = await request<RegisteredModel>(endpoint + '/' + identity, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          revision: editing?.revision || 0,
          name,
          provider,
          model,
          ...(typedRegistry ? profile : { uses }),
          ...(frontendOnly || renewalBackend ? { connection_id: connectionId } : {}),
          ...(renewalBackend ? { connection_revision: connectionRevision } : {}),
        }),
      });
      setEditing(row);
      setStatus('저장됨');
      await load();
      if (typedRegistry) {
        location.hash = '/serving/' + row.id;
      }
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : '저장 실패. 편집은 유지했습니다. 최신 항목을 명시 조회하세요.',
      );
    } finally {
      setBusy(false);
    }
  };
  const changeAvailability = async (row: RegisteredModel) => {
    setBusy(true);
    setError('');
    try {
      await jsonPost(endpoint + '/' + row.id + '/availability', {
        revision: row.revision,
        active: !row.active,
      });
      setStatus(
        row.active
          ? '사용 중지 · 미실행 호출 차단, 기존 결과/이력 보존'
          : '사용 가능 · 기존 티켓을 자동 실행하지 않습니다.',
      );
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : '사용 상태 변경 실패');
    } finally {
      setBusy(false);
    }
  };
  const selectedModel = models.find((row) => row.id === identity);
  const selectedVersion = selectedModel?.versions[String(selectedModel.current_revision)];
  const selectedName = selectedVersion?.name;
  const shown = models.filter(
    (row) =>
      (!identity || row.id === identity) &&
      (identity ||
        row.versions[String(row.current_revision)].name
          .toLocaleLowerCase()
          .includes(query.toLocaleLowerCase())),
  );
  const page = usePagination(shown, query);
  useEffect(() => {
    void load();
  }, []);
  useEffect(() => {
    const row = models.find((item) => item.id === identity);
    if (form && row && editing?.id !== row.id) {
      void edit(row);
    }
  }, [form, identity, models, editing?.id]);
  if (loading && !listConfirmed && form) {
    return (
      <main className="serving-page model-registry">
        <PageTitle>{identity ? '모델 편집' : '모델 추가'}</PageTitle>
        <LoadingSkeleton layout="form" label="모델 설정 불러오는 중" />
      </main>
    );
  }
  return (
    <main className="serving-page workflow-tickets model-registry">
      <PageTitle>
        {identity
          ? selectedName ||
            (listError ? '모델 조회 실패' : loading ? '모델 상세' : '모델을 찾을 수 없음')
          : form
            ? '모델 추가'
            : '서빙'}
      </PageTitle>
      {(frontendOnly || renewalBackend) && !form && !identity && <ServingTabs />}
      {listError && (
        <p role="alert" className="alert list-query-error">
          목록 조회 실패 · {listError}
        </p>
      )}
      {listError && listConfirmed && (
        <p className="list-query-stale">
          이전 조회값 · 최신 미확인. 등록 모델 목록을 다시 읽어 확인하세요.
        </p>
      )}
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {status && <p role="status">{status}</p>}
      {form && (
        <>
          <section className="ticket-panel page-form">
            <fieldset disabled={busy || loading || (!!identity && !editing) || !!listError}>
              <div className="serving-grid">
                <label>
                  등록 이름
                  <Input
                    aria-label="등록 이름"
                    value={name}
                    maxLength={80}
                    onChange={(e) => setName(e.target.value)}
                  />
                </label>
                <label>
                  {frontendOnly || renewalBackend ? '공급자 연결' : '공급자'}
                  {frontendOnly || renewalBackend ? (
                    <select
                      aria-label="공급자 연결"
                      value={connectionId}
                      onChange={(event) => {
                        const selected = connections.find((row) => row.id === event.target.value);
                        setConnectionId(event.target.value);
                        setConnectionRevision(
                          selected?.current_revision || selected?.revision || 0,
                        );
                        if (selected) {
                          setProvider(selected.provider);
                        }
                        setUses([]);
                        setCompatible([]);
                      }}
                    >
                      <option value="">연결 선택</option>
                      {connections.map((row) => (
                        <option key={row.id} value={row.id}>
                          {row.name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <select
                      aria-label="등록 provider"
                      value={provider}
                      onChange={(e) => {
                        setProvider(e.target.value);
                        setUses([]);
                        setCompatible([]);
                      }}
                    >
                      {Object.entries(providers).map(([id, label]) => (
                        <option key={id} value={id}>
                          {label}
                        </option>
                      ))}
                    </select>
                  )}
                </label>
                <label>
                  모델 ID
                  <Input
                    aria-label="등록 model"
                    value={model}
                    maxLength={200}
                    onChange={(e) => {
                      setModel(e.target.value);
                      setUses([]);
                      setCompatible([]);
                    }}
                  />
                </label>
              </div>
              {renewalBackend &&
                connections.some(
                  (row) => row.id === connectionId && row.current_revision !== connectionRevision,
                ) && (
                  <div className="serving-help">
                    공급자 연결 설정이 변경됐습니다. 저장된 연결은 유지됩니다.
                    {connections.some(
                      (row) =>
                        row.id === connectionId && row.current_revision !== connectionRevision,
                    ) && (
                      <Button
                        variant="quiet"
                        onClick={() => {
                          const row = connections.find((row) => row.id === connectionId);
                          if (row?.current_revision) {
                            setConnectionRevision(row.current_revision);
                            setUses([]);
                            setCompatible([]);
                          }
                        }}
                      >
                        변경된 연결 적용
                      </Button>
                    )}
                  </div>
                )}
              {typedRegistry ? (
                <ModelProfileFields value={profile} changed={setProfile} />
              ) : (
                <>
                  <Button
                    variant="secondary"
                    disabled={!model || ((frontendOnly || renewalBackend) && !connectionId)}
                    onClick={() => void check()}
                  >
                    호환 용도 확인
                  </Button>
                  <div>
                    {compatible.map((use) => (
                      <label className="serving-check" key={use}>
                        <input
                          type="checkbox"
                          aria-label={`${modelUseLabels[use]} 용도`}
                          checked={uses.includes(use)}
                          onChange={(e) =>
                            setUses((previous) =>
                              e.target.checked
                                ? [...previous, use]
                                : previous.filter((v) => v !== use),
                            )
                          }
                        />
                        {modelUseLabels[use]} 용도
                      </label>
                    ))}
                  </div>
                </>
              )}
            </fieldset>
            <div className="page-actions">
              <Button
                disabled={
                  busy ||
                  loading ||
                  !!listError ||
                  (!!identity && !editing) ||
                  !name.trim() ||
                  !model.trim() ||
                  (typedRegistry
                    ? !profile.model_types.length ||
                      !profile.input_modalities.length ||
                      !profile.output_modalities.length ||
                      !profile.capabilities.length
                    : !uses.length || !compatible.length) ||
                  ((frontendOnly || renewalBackend) && !connectionId)
                }
                onClick={() => void save()}
              >
                저장
              </Button>
              <Button
                variant="quiet"
                onClick={() => {
                  location.hash = identity ? `/serving/${identity}` : '/serving';
                }}
              >
                취소
              </Button>
            </div>
          </section>
        </>
      )}
      {!form && !identity && (
        <>
          <section className="ui02-list" aria-label="등록 모델">
            {loading && !listConfirmed ? (
              <LoadingSkeleton layout="list" label="모델 목록 불러오는 중" />
            ) : listConfirmed && !listError && !shown.length ? (
              <p>{query ? '검색 결과 없음' : '등록 모델 없음'}</p>
            ) : (
              page.items.map((row) => {
                const current = row.versions[String(row.current_revision)];
                return (
                  <a
                    className="ui02-list-item serving-resource-row"
                    key={row.id}
                    href={'#/serving/' + row.id}
                  >
                    <strong className="ui02-list-title">{current.name}</strong>
                    <span className="ui02-list-meta">
                      {providers[current.provider] || current.provider} / {current.model}
                    </span>
                    <span className="ui02-list-meta">
                      {typedRegistry
                        ? current.model_types
                            ?.map((type) => modelTypeLabels[type] || type)
                            .join(' / ') || '유형 미분류'
                        : current.uses?.map((use) => modelUseLabels[use]).join(' / ')}
                      {!row.active && ' · 사용 중지'}
                    </span>
                  </a>
                );
              })
            )}
          </section>
          {!loading && listConfirmed && <Pagination {...page} disabled={!!listError} />}
        </>
      )}
      {!form &&
        identity &&
        (loading && !listConfirmed ? (
          <LoadingSkeleton layout="form" label="모델 상세 불러오는 중" />
        ) : selectedModel && selectedVersion ? (
          <>
            <dl className="serving-resource-facts">
              <div>
                <dt>공급자</dt>
                <dd>{providers[selectedVersion.provider] || selectedVersion.provider}</dd>
              </div>
              <div>
                <dt>공급자 연결</dt>
                <dd>
                  {connections.find((row) => row.id === selectedVersion.connection_id)?.name ||
                    '미설정'}
                </dd>
              </div>
              <div>
                <dt>모델 ID</dt>
                <dd>{selectedVersion.model}</dd>
              </div>
              <div>
                <dt>모델 유형</dt>
                <dd>
                  {selectedVersion.model_types
                    ?.map((type) => modelTypeLabels[type] || type)
                    .join(' / ') || '유형 미분류'}
                </dd>
              </div>
              <div>
                <dt>입력</dt>
                <dd>
                  {selectedVersion.input_modalities
                    ?.map((type) => modalityLabels[type] || type)
                    .join(' / ') || '미설정'}
                </dd>
              </div>
              <div>
                <dt>출력</dt>
                <dd>
                  {selectedVersion.output_modalities
                    ?.map((type) => modalityLabels[type] || type)
                    .join(' / ') || '미설정'}
                </dd>
              </div>
              <div>
                <dt>지원 기능</dt>
                <dd>
                  {selectedVersion.capabilities
                    ?.map((type) => capabilityLabels[type] || type)
                    .join(' / ') || '미설정'}
                </dd>
              </div>
              <div>
                <dt>사용 상태</dt>
                <dd>{selectedModel.active ? '등록됨' : '사용 중지'}</dd>
              </div>
              <div>
                <dt>연결 확인</dt>
                <dd>미확인</dd>
              </div>
            </dl>
            <div className="page-actions">
              <Button
                variant="quiet"
                disabled={busy || !!listError}
                onClick={() => void changeAvailability(selectedModel)}
              >
                {selectedModel.active ? '사용 중지' : '사용 재개'}
              </Button>
              <Button
                disabled={busy || !!listError}
                onClick={() => {
                  location.hash = '/serving/' + identity + '/edit';
                }}
              >
                수정
              </Button>
            </div>
          </>
        ) : (
          !listError && <p role="status">모델을 찾을 수 없습니다.</p>
        ))}
      {!frontendOnly && !renewalBackend && !form && (
        <a className="ui02-text-action" href="#/serving/roles">
          역할 설정
        </a>
      )}
    </main>
  );
};
