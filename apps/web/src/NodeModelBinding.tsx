import { useEffect, useState } from 'react';
import { request } from './api';
import {
  type RegisteredModel,
  type ModelReference,
  nodeModelRoles,
  supportsModelRole,
} from './registered-models';
import { frontendOnly, renewalBackend } from './preview';

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
  const pinned = selected?.versions[String(value?.revision)];
  const pinnedAvailable =
    pinned &&
    (frontendOnly || renewalBackend
      ? supportsModelRole(pinned, role)
      : pinned.uses?.includes(role));
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
          {models.map((row) => {
            const current = row.versions[String(row.current_revision)];
            if (
              !current ||
              !(frontendOnly || renewalBackend
                ? supportsModelRole(current, role)
                : current.uses?.includes(role))
            ) {
              return null;
            }
            return (
              <option key={row.id} value={`${row.id}@${current.revision}`} disabled={!row.active}>
                {current.name} · {current.provider}/{current.model}
                {row.active ? '' : ' · 사용 중지'}
              </option>
            );
          })}
          {value && (!pinnedAvailable || selected?.current_revision !== value.revision) && (
            <option value={`${value.model_id}@${value.revision}`} disabled>
              {pinned
                ? `${pinned.name} · ${pinnedAvailable ? '이 워크플로우에 저장된 연결' : '유형/능력 재확인 필요'}`
                : '등록 모델 미확인'}
            </option>
          )}
        </select>
      </label>
      {value && selected && selected.current_revision !== value.revision && (
        <p className="editor-help">
          등록 연결 설정이 변경됐습니다. 이 워크플로우의 기존 선택은 유지됩니다.
        </p>
      )}
      {selected && !selected.active && <p className="editor-help">사용 중지된 모델입니다.</p>}
    </section>
  );
};
