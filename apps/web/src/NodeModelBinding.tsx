import { useEffect, useState } from 'react';
import { request } from './api';
import { type RegisteredModel, type ModelReference, nodeModelRoles } from './registered-models';

export const NodeModelBinding = ({
  type,
  modelRole,
  value,
  changed,
}: {
  type: string;
  modelRole?: string;
  value?: ModelReference;
  changed: (value: ModelReference | undefined) => void;
}) => {
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const role = modelRole || nodeModelRoles[type];
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
    return null;
  }
  return (
    <section className="node-model-binding">
      <h4>에이전트 모델</h4>
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
              등록 모델 미확인
            </option>
          )}
        </select>
      </label>
      {value && (
        <p className="editor-help">
          버전 {value.revision}
          {selected && selected.current_revision > value.revision ? ' · 새 버전 있음' : ''}
          {selected && !selected.active ? ' · 사용 중지' : ''}
        </p>
      )}
    </section>
  );
};
