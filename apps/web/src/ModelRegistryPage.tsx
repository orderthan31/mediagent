import { useEffect, useState } from 'react';
import { request } from './api';
import { jsonPost } from './video-api';
import { Button } from './hangyeol/primitives/button';
import { Input } from './hangyeol/primitives/input';
import { type RegisteredModel, modelUseLabels } from './registered-models';
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
  const [providers, setProviders] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<RegisteredModel | null>(null);
  const [name, setName] = useState('');
  const [provider, setProvider] = useState('openai');
  const [model, setModel] = useState('');
  const [uses, setUses] = useState<string[]>([]);
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
    setProvider(version.provider);
    setModel(version.model);
    setUses(version.uses);
    setCompatible([]);
    setStatus('');
    setBusy(true);
    try {
      const data = await jsonPost<{ uses: string[] }>(endpoint + '/compatibility', {
        provider: version.provider,
        model: version.model,
      });
      setCompatible(data.uses);
    } catch (e) {
      setError(e instanceof Error ? e.message : '호환 검사 실패');
    } finally {
      setBusy(false);
    }
  };
  const save = async () => {
    setBusy(true);
    setError('');
    try {
      const identity = editing?.id || crypto.randomUUID().replaceAll('-', '');
      const row = await request<RegisteredModel>(endpoint + '/' + identity, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ revision: editing?.revision || 0, name, provider, model, uses }),
      });
      setEditing(row);
      setStatus('저장됨');
      await load();
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
  useEffect(() => {
    void load();
  }, []);
  useEffect(() => {
    const row = models.find((item) => item.id === identity);
    if (form && row && editing?.id !== row.id) void edit(row);
  }, [form, identity, models, editing?.id]);
  return (
    <main className="serving-page workflow-tickets model-registry">
      <div className="serving-heading">
        <div>
          <h1>{form ? (identity ? '모델 편집' : '모델 추가') : '서빙'}</h1>
        </div>
        <Button variant="secondary" disabled={busy || loading} onClick={() => void load()}>
          새로고침
        </Button>
      </div>
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
          <section className="ticket-panel">
            <h2>{editing ? '모델 편집' : '모델 등록'}</h2>
            <fieldset disabled={busy || loading}>
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
                  Provider
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
                </label>
                <label>
                  Model ID
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
              <Button variant="secondary" disabled={!model} onClick={() => void check()}>
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
                          e.target.checked ? [...previous, use] : previous.filter((v) => v !== use),
                        )
                      }
                    />
                    {modelUseLabels[use]} 용도
                  </label>
                ))}
              </div>
              <div className="ticket-actions">
                <Button
                  disabled={!name.trim() || !uses.length || !compatible.length}
                  onClick={() => void save()}
                >
                  모델 등록 저장
                </Button>
                <Button variant="secondary" onClick={reset}>
                  새 등록 입력
                </Button>
              </div>
            </fieldset>
            {editing && <p className="serving-help">새 버전으로 저장</p>}
          </section>
        </>
      )}
      {!form && (
        <>
          <section className="ui02-list" aria-label="등록 모델">
            {loading ? (
              <p>등록 목록 읽는 중</p>
            ) : listConfirmed && !listError && models.length === 0 ? (
              <p>등록 모델 없음</p>
            ) : (
              models
                .filter(
                  (row) =>
                    (!identity || row.id === identity) &&
                    row.versions[String(row.current_revision)].name
                      .toLocaleLowerCase()
                      .includes(query.toLocaleLowerCase()),
                )
                .map((row) => {
                  const current = row.versions[String(row.current_revision)];
                  return (
                    <article className="ui02-list-item" key={row.id}>
                      <div className="ui02-list-copy">
                        <h3 className="ui02-list-title">
                          <a href={'#/serving/' + row.id}>{current.name}</a> · r
                          {row.current_revision}
                        </h3>
                        <p>
                          {current.provider} / {current.model} ·{' '}
                          {row.active ? '사용 가능' : '사용 중지'} · 연결 미확인
                        </p>
                        <p className="ui02-list-meta">
                          {current.uses.map((u) => modelUseLabels[u]).join(' / ')}
                        </p>
                      </div>
                      <div className="ticket-actions ui02-list-actions">
                        <Button
                          variant="secondary"
                          disabled={busy}
                          onClick={() => {
                            location.hash = '/serving/' + row.id + '/edit';
                          }}
                        >
                          수정 {current.name}
                        </Button>
                        <Button
                          variant="secondary"
                          disabled={busy}
                          onClick={() => void changeAvailability(row)}
                        >
                          {row.active ? '사용 중지' : '사용 가능으로 변경'}
                        </Button>
                      </div>
                      {identity && (
                        <details className="ui02-list-extra">
                          <summary>revision 이력</summary>
                          {Object.values(row.versions).map((v) => (
                            <p key={v.revision}>
                              r{v.revision} · {v.name} · {v.provider}/{v.model}
                            </p>
                          ))}
                        </details>
                      )}
                    </article>
                  );
                })
            )}
          </section>
        </>
      )}
      {!form && (
        <a className="ui02-text-action" href="#/serving/roles">
          역할 설정
        </a>
      )}
    </main>
  );
};
