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
      setStatus(
        '선택 이력을 새 revision ' +
          next.revision +
          '으로 복원했습니다. 정의 저장이며 티켓 재개/실행이 아닙니다.',
      );
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
      <h2>저장 이력 · 새 revision 복원</h2>
      <p>
        도입 뒤 실제 저장한 이력만 표시합니다. 없는 과거본은 합성하지 않습니다. 복원해도 기존
        티켓/모델 pin은 바뀌지 않습니다.
      </p>
      <Button variant="secondary" disabled={busy || revision === 0} onClick={() => void load()}>
        저장 이력 읽기
      </Button>
      {error && <p role="alert">{error}</p>}
      {versions && versions.length === 0 && <p>이 기능으로 저장된 과거 이력이 없습니다.</p>}
      {versions && versions.length > 0 && (
        <>
          <label>
            복원할 저장 revision
            <select
              aria-label="복원할 저장 revision"
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
            선택 이력을 새 revision으로 복원
          </Button>
        </>
      )}
      {dirty && (
        <p>
          미저장 편집을 보존합니다. 먼저 저장하거나 명시적으로 서버값을 열어 확인한 뒤 복원하세요.
        </p>
      )}
      {status && <p role="status">{status}</p>}
    </section>
  );
};
