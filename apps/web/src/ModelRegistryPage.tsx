import { useEffect, useState } from 'react';
import { request } from './api';
import { jsonPost } from './video-api';
import { Button } from './hangyeol/primitives/button';
import { Input } from './hangyeol/primitives/input';
import { type RegisteredModel, modelUseLabels } from './registered-models';
import { ServingPage } from './ServingPage';
import './serving.css';
import './workflow-tickets.css';

const endpoint = '/settings/registered-models';
export const ModelRegistryPage = () => {
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
    setStatus('기존 노드 pin은 유지합니다. 수정 저장은 새 revision입니다.');
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
      setStatus('등록 저장 완료 · 기존 pin 보존 · 실연결/추론 미확인');
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
  return (
    <main className="serving-page workflow-tickets model-registry">
      <div className="serving-heading">
        <div>
          <p className="workspace-eyebrow">서빙</p>
          <h1>모델 관리</h1>
        </div>
        <Button variant="secondary" disabled={busy || loading} onClick={() => void load()}>
          등록 목록 새로 읽기
        </Button>
      </div>
      <p>
        모델을 등록한 뒤 워크플로우의 해당 노드에 정확한 revision을 연결하세요. 등록·키 보유·adapter
        호환은 실제 연결/추론 성공이 아닙니다.
      </p>
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
      <section className="ticket-panel">
        <h2>{editing ? '등록 항목 수정 · 새 revision' : '모델 등록'}</h2>
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
        <p className="serving-help">
          키 입력/복사는 하지 않습니다. 기존 키 보관소를 실행 시 해석합니다. 수정은 새 revision이며
          기존 정의/티켓을 자동 교체하지 않습니다.
        </p>
      </section>
      <section className="ticket-panel">
        <h2>등록 모델</h2>
        {loading ? (
          <p>등록 목록 읽는 중</p>
        ) : listConfirmed && !listError && models.length === 0 ? (
          <p>등록 모델 없음. 모델 없는 처리 노드는 등록 없이 사용할 수 있습니다.</p>
        ) : (
          models.map((row) => {
            const current = row.versions[String(row.current_revision)];
            return (
              <article className="ticket-step" key={row.id}>
                <h3>
                  {current.name} · r{row.current_revision}
                </h3>
                <p>
                  {current.provider} / {current.model} · {row.active ? '사용 가능' : '사용 중지'} ·
                  실연결 미확인
                </p>
                <p>{current.uses.map((u) => modelUseLabels[u]).join(' / ')}</p>
                <div className="ticket-actions">
                  <Button variant="secondary" disabled={busy} onClick={() => void edit(row)}>
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
                <details>
                  <summary>불변 revision 이력</summary>
                  {Object.values(row.versions).map((v) => (
                    <p key={v.revision}>
                      r{v.revision} · {v.name} · {v.provider}/{v.model}
                    </p>
                  ))}
                </details>
              </article>
            );
          })
        )}
      </section>
      <details>
        <summary>기존 공유 역할 설정 · 이전 티켓 호환</summary>
        <ServingPage />
      </details>
    </main>
  );
};
