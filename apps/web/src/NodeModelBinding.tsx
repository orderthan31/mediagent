import { useEffect, useState } from 'react';
import { request } from './api';
import {
  type RegisteredModel,
  type RegisteredVersion,
  type ModelReference,
  nodeModelRoles,
  supportsModelRole,
} from './registered-models';
import { frontendOnly, renewalBackend } from './preview';
import { createPortal } from 'react-dom';
import { ModelRegistryPage } from './ModelRegistryPage';

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
  const [selectionNotice, setSelectionNotice] = useState('');
  const [search, setSearch] = useState('');
  const [registering, setRegistering] = useState(false);
  const [models, setModels] = useState<RegisteredModel[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const role = modelRole || nodeModelRoles[type];
  const roleLabel =
    role === 'vocalization' ? '보컬 판정' : role === 'transcription' ? '전사' : '번역';
  const wireSupported = (model: RegisteredVersion) =>
    !(frontendOnly || renewalBackend) ||
    (role === 'vocalization'
      ? model.vocalization_supported === true
      : role === 'transcription'
        ? model.transcription_supported === true
        : role !== 'translation' || model.translation_supported !== false);
  const selected = models.find((row) => row.id === value?.model_id);
  const pinned = selected?.versions[String(value?.revision)];
  const pinnedAvailable =
    pinned &&
    (frontendOnly || renewalBackend
      ? supportsModelRole(pinned, role) && wireSupported(pinned)
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
  const closeRegistration = () => {
    setRegistering(false);
    if (window.history.state?.modelRegistration) {
      window.history.back();
    }
    void load();
  };
  useEffect(() => {
    if (role) {
      void load();
    } else {
      setLoading(false);
    }
  }, [role]);
  useEffect(() => {
    if (!registering) {
      return;
    }
    const prior = document.activeElement as HTMLElement | null;
    document
      .querySelector<HTMLElement>('.registration-overlay button')
      ?.focus({ preventScroll: true });
    const trap = (event: KeyboardEvent) => {
      if (event.key !== 'Tab') {
        return;
      }
      const panes = document.querySelectorAll<HTMLElement>('.registration-overlay');
      const pane = panes[panes.length - 1];
      const items = [
        ...(pane?.querySelectorAll<HTMLElement>(
          'button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]',
        ) || []),
      ].filter((e) => e.getClientRects().length);
      const first = items[0],
        last = items[items.length - 1];
      if (!first) {
        return;
      }
      if (
        !pane.contains(document.activeElement) ||
        (!event.shiftKey && document.activeElement === last) ||
        (event.shiftKey && document.activeElement === first)
      ) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus({ preventScroll: true });
      }
    };
    document.addEventListener('keydown', trap);
    const back = () => {
      if (!window.history.state?.modelRegistration) {
        setRegistering(false);
      }
    };
    window.addEventListener('popstate', back);
    return () => {
      window.removeEventListener('popstate', back);
      document.removeEventListener('keydown', trap);
      prior?.focus({ preventScroll: true });
    };
  }, [registering]);

  if (!role) {
    return null;
  }
  return (
    <section className="node-model-binding">
      <h4>{roleLabel} 모델</h4>
      <label>
        모델 검색
        <input
          type="search"
          aria-label="모델 검색"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="이름 또는 모델 ID"
        />
      </label>
      <button
        type="button"
        onClick={() => {
          window.history.pushState(
            { ...window.history.state, modelRegistration: true },
            '',
            location.href,
          );
          setRegistering(true);
        }}
      >
        모델·공급자 추가
      </button>
      {registering &&
        createPortal(
          <div
            className="registration-backdrop"
            data-hangyeol=""
            data-theme={
              document.querySelector('[data-hangyeol]')?.getAttribute('data-theme') || 'light'
            }
          >
            <section
              className="registration-overlay"
              role="dialog"
              aria-modal="true"
              aria-label={`${roleLabel} 모델 추가`}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  e.stopPropagation();
                  closeRegistration();
                }
              }}
            >
              <div className="registration-top">
                <strong>{roleLabel} 모델 추가</strong>
                <button type="button" onClick={closeRegistration}>
                  노드로 돌아가기
                </button>
              </div>
              <div className="registration-body">
                <ModelRegistryPage
                  form
                  onCancel={closeRegistration}
                  onRegistered={(row) => {
                    const current = row.versions[String(row.current_revision)];
                    if (
                      current &&
                      row.active &&
                      supportsModelRole(current, role) &&
                      wireSupported(current)
                    ) {
                      changed({ model_id: row.id, revision: row.current_revision });
                      closeRegistration();
                    } else {
                      setSelectionNotice(
                        '등록한 모델은 이 노드의 용도를 지원하지 않습니다. 모델 선택은 그대로 유지했습니다.',
                      );
                      closeRegistration();
                    }
                  }}
                />
              </div>
            </section>
          </div>,
          document.body,
        )}
      {selectionNotice && <p role="status">{selectionNotice}</p>}
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
              (row.id !== value?.model_id &&
                search &&
                !`${current?.name || ''} ${current?.model || ''} ${current?.provider || ''}`
                  .toLocaleLowerCase()
                  .includes(search.toLocaleLowerCase())) ||
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
                disabled={!row.active || !wireSupported(current)}
              >
                {current.name}
                {row.active ? '' : ' · 사용 중지'}
                {!wireSupported(current) ? ` · ${roleLabel} 실행 미지원` : ''}
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
      {['translate', 'transcribe', 'vocalize'].includes(type) && fallbackChanged && (
        <details>
          <summary>대체 모델 (선택)</summary>
          <section aria-label={`${roleLabel} 폴백`}>
            <h4>{roleLabel} 폴백</h4>
            {role === 'transcription' && (
              <p>
                Gemini 음성 포함 네이티브 요청 / OpenAI 계열 whisper-1 verbose_json 구간 시각만
                지원합니다. PCM16·mono·16kHz WAV, 60초/2MiB 이내. 등록 정보상 규격 지원이며 실제
                인식 정확도·인증 성공은 미확인입니다.
              </p>
            )}
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
                        if (!current || !supportsModelRole(current, role)) {
                          return null;
                        }
                        const duplicate =
                          value?.model_id === row.id ||
                          fallbacks.some((item, i) => i !== index && item.model_id === row.id);
                        return (
                          <option
                            key={row.id}
                            value={`${row.id}@${current.revision}`}
                            disabled={!row.active || !wireSupported(current) || duplicate}
                          >
                            {current.name}
                            {!row.active
                              ? ' · 사용 중지'
                              : !wireSupported(current)
                                ? ` · ${roleLabel} 실행 미지원`
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
                    wireSupported(current) &&
                    supportsModelRole(current, role) &&
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
                    wireSupported(current) &&
                    supportsModelRole(current, role) &&
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
        </details>
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
