import { useEffect, useState } from 'react';
import { request } from './api';
import { type RegisteredModel, type ModelReference, nodeModelRoles } from './registered-models';

export const NodeModelBinding = ({
  type,
  value,
  changed,
}: {
  type: string;
  value?: ModelReference;
  changed: (value: ModelReference | undefined) => void;
}) => {
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const role = nodeModelRoles[type];
  const selected = models.find((row) => row.id === value?.model_id);
  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const data = await request<{ models: RegisteredModel[] }>('/settings/registered-models');
      setModels(data.models);
    } catch (e) {
      setError(e instanceof Error ? e.message : '등록 모델을 읽지 못했습니다.');
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    if (role) {
      void load();
    } else {
      setLoading(false);
    }
  }, [role]);
  if (!role) {
    return <p className="editor-help">이 처리 노드는 모델 없이 아래 처리 옵션을 사용합니다.</p>;
  }
  return (
    <section className="node-model-binding">
      <h4>노드 모델</h4>
      {error && <p role="alert">{error} 현재 참조는 유지합니다.</p>}
      <label>
        호환 등록 모델
        <select
          aria-label="호환 등록 모델"
          disabled={loading || !!error}
          value={value ? `${value.model_id}@${value.revision}` : ''}
          onChange={(e) => {
            const [model_id, revision] = e.target.value.split('@');
            changed(model_id ? { model_id, revision: Number(revision) } : undefined);
          }}
        >
          <option value="">등록 모델 선택 (필수)</option>
          {models.flatMap((row) =>
            Object.values(row.versions)
              .filter((v) => v.uses.includes(role))
              .map((v) => (
                <option
                  key={`${row.id}@${v.revision}`}
                  value={`${row.id}@${v.revision}`}
                  disabled={!row.active}
                >
                  {v.name} · r{v.revision} · {v.provider}/{v.model}
                  {row.active ? '' : ' · 사용 중지'}
                </option>
              )),
          )}
          {value && !selected && (
            <option value={`${value.model_id}@${value.revision}`} disabled>
              등록 항목 미확인 · 기존 pin 유지
            </option>
          )}
        </select>
      </label>
      {value && (
        <p className="editor-help">
          고정 r{value.revision}
          {selected && selected.current_revision > value.revision
            ? ' · 새 revision 있음. 자동 교체하지 않습니다.'
            : ''}
          {selected && !selected.active
            ? ' · 사용 중지: 활성 모델로 명시 교체하고 새 정의/계획/티켓을 만드세요.'
            : ''}
        </p>
      )}
      <p className="editor-help">
        키는 저장하지 않습니다. 등록/형식 호환과 실제 연결/추론은 다릅니다.{' '}
        <a href="#/serving">서빙에서 등록·관리</a>
      </p>
    </section>
  );
};
