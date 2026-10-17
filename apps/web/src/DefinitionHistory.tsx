import { useState } from 'react';
import { request } from './api';
import { jsonPost } from './video-api';
import { Button } from './hangyeol/primitives/button';

type Version = { revision: number; sha256: string; source: { kind: string } };
export const DefinitionHistory = ({
  identity,
  revision,
  dirty,
  onRestored,
}: {
  identity: string;
  revision: number;
  dirty: boolean;
  onRestored: () => Promise<void>;
}) => {
  const [versions, setVersions] = useState<Version[] | null>(null),
    [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [status, setStatus] = useState('');
  const load = async () => {
    setBusy(true);
    setError('');
    try {
      const response = await request<{ versions: Version[] }>(
        '/settings/workflow-definitions/' + identity + '/versions',
      );
      setVersions(response.versions);
      setSelected('');
    } catch (e) {
      setVersions(null);
      setError(e instanceof Error ? e.message : '저장 이력 조회 실패');
    } finally {
      setBusy(false);
    }
  };
  const restore = async () => {
    setBusy(true);
    setError('');
    try {
      const next = await jsonPost<{ revision: number }>(
        '/settings/workflow-definitions/' + identity + '/restore',
        { revision, source: { kind: 'definition_revision', revision: Number(selected) } },
      );
      await onRestored();
      setStatus('버전 ' + next.revision + '으로 복원했습니다.');
      setVersions(null);
      setSelected('');
    } catch (e) {
      setError(e instanceof Error ? e.message : '복원 충돌. 편집은 보존됩니다.');
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="definition-history ticket-panel">
      <h2>저장 이력</h2>
      <Button variant="secondary" disabled={busy || revision === 0} onClick={() => void load()}>
        불러오기
      </Button>
      {error && <p role="alert">{error}</p>}
      {versions && versions.length === 0 && <p>이 기능으로 저장된 과거 이력이 없습니다.</p>}
      {versions && versions.length > 0 && (
        <>
          <label>
            버전
            <select
              aria-label="버전"
              value={selected}
              disabled={busy}
              onChange={(e) => setSelected(e.target.value)}
            >
              <option value="">이력 선택</option>
              {versions.map((v) => (
                <option key={v.revision} value={v.revision}>
                  r{v.revision} · {v.source.kind} · {v.sha256.slice(0, 12)}
                </option>
              ))}
            </select>
          </label>
          <Button disabled={busy || dirty || !selected} onClick={() => void restore()}>
            복원
          </Button>
        </>
      )}
      {dirty && <p>변경 내용을 저장한 뒤 복원할 수 있습니다.</p>}
      {status && <p role="status">{status}</p>}
    </section>
  );
};
