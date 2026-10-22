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
  fallbacks = [],
  fallbackChanged,
}: {
  type: string;
  modelRole?: string;
  value?: ModelReference;
  changed: (value: ModelReference | undefined) => void;
  fallbacks?: ModelReference[];
  fallbackChanged?: (value: ModelReference[]) => void;
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
              <option
                key={row.id}
                value={`${row.id}@${current.revision}`}
                disabled={
                  !row.active || (role === 'translation' && current.translation_supported === false)
                }
              >
                {current.name} · {current.provider}/{current.model}
                {row.active ? '' : ' · 사용 중지'}
                {role === 'translation' && current.translation_supported === false
                  ? ' · 번역 실행 미지원'
                  : ''}
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
      {type === 'translate' && fallbackChanged && (
        <section aria-label="번역 폴백">
          <h4>번역 폴백</h4>
          <p>
            선택 사항입니다. 없으면 기본 모델만 한 번 시도합니다. 최대 3개를 순서대로 시도합니다.
          </p>
          <p>
            사용 불가·429·서버 오류·잘못된 응답만 다음 후보로 전환합니다. 인증·요청 거부·전송 결과
            불명·취소는 중단합니다.
          </p>
          {!fallbacks.length && <p>폴백 없음</p>}
          <ol>
            {fallbacks.map((ref, index) => (
              <li key={index}>
                <label>
                  폴백 {index + 1} 모델
                  <select
                    aria-label={`폴백 ${index + 1} 모델`}
                    disabled={loading || !!error}
                    value={`${ref.model_id}@${ref.revision}`}
                    onChange={(event) => {
                      const [model_id, revision] = event.target.value.split('@');
                      fallbackChanged(
                        fallbacks.map((item, i) =>
                          i === index ? { model_id, revision: Number(revision) } : item,
                        ),
                      );
                    }}
                  >
                    {models.map((row) => {
                      const current = row.versions[String(row.current_revision)];
                      if (!current || !supportsModelRole(current, 'translation')) {
                        return null;
                      }
                      const duplicate =
                        value?.model_id === row.id ||
                        fallbacks.some((item, i) => i !== index && item.model_id === row.id);
                      return (
                        <option
                          key={row.id}
                          value={`${row.id}@${current.revision}`}
                          disabled={
                            !row.active || current.translation_supported === false || duplicate
                          }
                        >
                          {current.name} · {current.provider}/{current.model}
                          {!row.active
                            ? ' · 사용 중지'
                            : current.translation_supported === false
                              ? ' · 번역 실행 미지원'
                              : ''}
                        </option>
                      );
                    })}
                    {!models.some(
                      (row) => row.id === ref.model_id && row.current_revision === ref.revision,
                    ) && (
                      <option value={`${ref.model_id}@${ref.revision}`}>
                        저장된 모델 · 개정 {ref.revision}
                      </option>
                    )}
                  </select>
                </label>
                <button
                  type="button"
                  aria-label={`폴백 ${index + 1} 위로`}
                  disabled={index === 0}
                  onClick={() => {
                    const next = [...fallbacks];
                    [next[index - 1], next[index]] = [next[index], next[index - 1]];
                    fallbackChanged(next);
                  }}
                >
                  위로
                </button>
                <button
                  type="button"
                  aria-label={`폴백 ${index + 1} 아래로`}
                  disabled={index === fallbacks.length - 1}
                  onClick={() => {
                    const next = [...fallbacks];
                    [next[index + 1], next[index]] = [next[index], next[index + 1]];
                    fallbackChanged(next);
                  }}
                >
                  아래로
                </button>
                <button
                  type="button"
                  aria-label={`폴백 ${index + 1} 삭제`}
                  onClick={() => fallbackChanged(fallbacks.filter((_, i) => i !== index))}
                >
                  삭제
                </button>
              </li>
            ))}
          </ol>
          <button
            type="button"
            disabled={
              !value ||
              loading ||
              !!error ||
              fallbacks.length >= 3 ||
              !models.some((row) => {
                const current = row.versions[String(row.current_revision)];
                return (
                  row.active &&
                  current &&
                  current.translation_supported !== false &&
                  supportsModelRole(current, 'translation') &&
                  row.id !== value.model_id &&
                  !fallbacks.some((ref) => ref.model_id === row.id)
                );
              })
            }
            onClick={() => {
              const row = models.find((row) => {
                const current = row.versions[String(row.current_revision)];
                return (
                  row.active &&
                  current &&
                  current.translation_supported !== false &&
                  supportsModelRole(current, 'translation') &&
                  row.id !== value?.model_id &&
                  !fallbacks.some((ref) => ref.model_id === row.id)
                );
              });
              if (row) {
                fallbackChanged([
                  ...fallbacks,
                  { model_id: row.id, revision: row.current_revision },
                ]);
              }
            }}
          >
            폴백 추가
          </button>
        </section>
      )}
      {value && selected && selected.current_revision !== value.revision && (
        <p className="editor-help">
          등록 연결 설정이 변경됐습니다. 이 워크플로우의 기존 선택은 유지됩니다.
        </p>
      )}
      {selected && !selected.active && <p className="editor-help">사용 중지된 모델입니다.</p>}
    </section>
  );
};
