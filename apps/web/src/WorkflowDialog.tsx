import { useEffect, useRef, useState } from 'react';
import { Play, X } from 'lucide-react';
import { Job, request } from './api';
import { executionRequest } from './execution-request';
import {
  AudioInput,
  jsonPost,
  stageLabels,
  SubtitleInput,
  templates,
  VideoDetail,
} from './video-api';
import { Button } from './hangyeol/primitives/button';
import { Badge } from './hangyeol/primitives/badge';
import { Textarea } from './hangyeol/primitives/textarea';
import './workflow.css';
type Plan = {
  stages: string[];
  reused: string[];
  paid_stages: string[];
};
type Planned = { inputKey: string; generation: number; value: Plan };
const isPlan = (value: unknown): value is Plan => {
  if (!value || typeof value !== 'object') {
    return false;
  }
  const record = value as Record<string, unknown>;
  const list = (v: unknown): v is string[] =>
    Array.isArray(v) && v.every((s) => typeof s === 'string' && s.trim().length > 0);
  return (
    list(record.stages) &&
    record.stages.length > 0 &&
    list(record.reused) &&
    list(record.paid_stages) &&
    record.paid_stages.every((s) => (record.stages as string[]).includes(s))
  );
};
export const WorkflowDialog = ({
  detail,
  onClose,
  onCreated,
}: {
  detail: VideoDetail;
  onClose: () => void;
  onCreated: (job: Job) => void;
}) => {
  const modal = useRef<HTMLDialogElement>(null);
  const [template, setTemplate] = useState('full'),
    [subtitles, setSubtitles] = useState<SubtitleInput[]>([]),
    [audios, setAudios] = useState<AudioInput[]>([]);
  const [subtitle, setSubtitle] = useState(''),
    [audio, setAudio] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [busyAction, setBusyAction] = useState(''),
    [planned, setPlanned] = useState<Planned | null>(null),
    [planError, setPlanError] = useState(''),
    [planRefresh, setPlanRefresh] = useState(0),
    [confirmed, setConfirmed] = useState('');
  const activePlan = useRef<Planned | null>(null),
    approval = useRef(''),
    sequence = useRef(0),
    inFlight = useRef(false);
  const [options, setOptions] = useState({
    source_language: 'auto',
    target_language: 'ko',
    quality_profile: 'balanced',
    video_codec: 'hevc',
    subtitle_mode: 'burn',
    resolution: 'original',
    audio_filter: 'silence3',
    vad_mode: 'off',
    video_description: '',
  });
  const key = useRef(crypto.randomUUID()),
    lastPayload = useRef('');
  const base = `/videos/${detail.video.asset_id}`;
  const acceptsSubtitle = ['translate', 'encode', 'full'].includes(template),
    needsTranscription =
      ['transcribe', 'transcribe_translate', 'full'].includes(template) && !subtitle;
  const hasTranslation = ['translate', 'transcribe_translate', 'full'].includes(template),
    hasEncoding = ['encode', 'full'].includes(template);
  const validInput =
    !(template === 'translate' && !subtitle) &&
    !(template === 'encode' && options.subtitle_mode !== 'none' && !subtitle);
  const payload = {
    template,
    subtitle_artifact_id: subtitle || null,
    audio_job_id: audio || null,
    options,
  };
  const inputKey = JSON.stringify({ base, payload });
  const currentPlan = planned?.inputKey === inputKey ? planned : null;
  const plan = currentPlan?.value;
  const confirmationKey = currentPlan ? JSON.stringify(currentPlan) : '';
  const selectedSubtitle = subtitles.find((s) => s.artifact_id === subtitle);
  const canCreate =
    validInput &&
    !busy &&
    !!currentPlan &&
    (!plan?.paid_stages.length || confirmed === confirmationKey);
  const invalidatePlan = () => {
    sequence.current += 1;
    activePlan.current = null;
    approval.current = '';
    setConfirmed('');
    setPlanned(null);
    setPlanError('');
    setPlanRefresh((n) => n + 1);
  };
  const option = (name: keyof typeof options, value: string) => {
    invalidatePlan();
    setOptions((o) => ({ ...o, [name]: value }));
    setError('');
  };
  const changeTemplate = (value: string) => {
    invalidatePlan();
    setTemplate(value);
    setSubtitle('');
    setAudio('');
    setError('');
  };
  const importTrack = async (value: string) => {
    if (inFlight.current) {
      return;
    }
    invalidatePlan();
    if (!value.startsWith('job:')) {
      setSubtitle(value);
      setAudio('');
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setBusyAction('자막 가져오는 중');
    setError('');
    const [, id, track, revision] = value.split(':');
    try {
      const added = await jsonPost<SubtitleInput>(base + '/subtitle-inputs', {
        job_id: id,
        track,
        revision: Number(revision),
      });
      setSubtitles((v) => [added, ...v]);
      setSubtitle(added.artifact_id);
      setAudio('');
    } catch (e) {
      setError(e instanceof Error ? e.message : '자막을 가져오지 못했습니다.');
    } finally {
      inFlight.current = false;
      setBusy(false);
      setBusyAction('');
      setPlanRefresh((n) => n + 1);
    }
  };
  const submit = async () => {
    if (
      !validInput ||
      !currentPlan ||
      inFlight.current ||
      activePlan.current !== currentPlan ||
      sequence.current !== currentPlan.generation ||
      (currentPlan.value.paid_stages.length > 0 && approval.current !== confirmationKey)
    ) {
      return;
    }
    inFlight.current = true;
    setBusy(true);
    setBusyAction('서버 실행 확인 대기');
    setError('');
    const serialized = JSON.stringify(payload);
    if (lastPayload.current && lastPayload.current !== serialized) {
      key.current = crypto.randomUUID();
    }
    lastPayload.current = serialized;
    try {
      onCreated(await executionRequest<Job>(base + '/jobs', { ...payload, request_id: key.current }));
    } catch (e) {
      setError(e instanceof Error ? e.message : '작업 생성 실패');
    } finally {
      inFlight.current = false;
      setBusy(false);
      setBusyAction('');
    }
  };
  useEffect(() => {
    modal.current?.showModal();
    return () => modal.current?.close();
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    request<{
      subtitles: SubtitleInput[];
    }>(base + '/subtitles', { signal: controller.signal })
      .then((v) => setSubtitles(v.subtitles))
      .catch((e) => {
        if (!controller.signal.aborted) {
          setError(e.message);
        }
      });
    request<{
      audio_inputs: AudioInput[];
    }>(base + '/audio-inputs', { signal: controller.signal })
      .then((v) => setAudios(v.audio_inputs))
      .catch((e) => {
        if (!controller.signal.aborted) {
          setError(e.message);
        }
      });
    return () => controller.abort();
  }, [base]);
  useEffect(() => {
    const generation = ++sequence.current;
    activePlan.current = null;
    approval.current = '';
    setConfirmed('');
    setPlanned(null);
    setPlanError('');
    if (!validInput) {
      return;
    }
    const controller = new AbortController();
    request<unknown>(base + '/workflow-plan', {
      method: 'POST',
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        template,
        subtitle_artifact_id: subtitle || null,
        audio_job_id: audio || null,
        subtitle_mode: options.subtitle_mode,
      }),
    })
      .then((value) => {
        if (!controller.signal.aborted && generation === sequence.current) {
          if (!isPlan(value)) {
            throw new Error(
              '실행 계획의 유료 단계 정보를 확인할 수 없습니다. 계획을 다시 확인해 주세요.',
            );
          }
          const next = { inputKey, generation, value };
          activePlan.current = next;
          setPlanned(next);
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted && generation === sequence.current) {
          setPlanError(e instanceof Error ? e.message : '실행 계획 확인 실패');
        }
      });
    return () => controller.abort();
  }, [base, template, subtitle, audio, options.subtitle_mode, validInput, inputKey, planRefresh]);
  return (
    <dialog
      ref={modal}
      className="workflow-modal workflow-renewal"
      onCancel={(e) => {
        e.preventDefault();
        if (!inFlight.current) {
          onClose();
        }
      }}
      aria-labelledby="workflow-title"
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <div className="dialog-heading">
          <div>
            <h2 id="workflow-title">워크플로우 설정</h2>
            <p>입력과 실행 계획을 확인한 뒤 티켓을 생성하세요.</p>
          </div>
          <Button
            variant="quiet"
            type="button"
            title="닫기"
            aria-label="워크플로우 닫기"
            disabled={busy}
            onClick={onClose}
          >
            <X size={20} />
          </Button>
        </div>
        {error && (
          <p role="alert" className="alert">
            {error}
          </p>
        )}
        <section className="workflow-source" aria-label="적용 원본">
          <Badge>적용 원본</Badge>
          <p>{detail.video.original_filename}</p>
          <span>이 원본의 입력·설정에 대한 실행 계획입니다.</span>
        </section>
        <fieldset disabled={busy}>
          <legend>입력과 처리 설정</legend>
          <label>
            작업 종류
            <select value={template} onChange={(e) => changeTemplate(e.target.value)}>
              {Object.entries(templates)
                .filter(([id]) => id !== 'faceswap')
                .map(([id, name]) => (
                  <option key={id} value={id}>
                    {name}
                  </option>
                ))}
            </select>
          </label>
          {acceptsSubtitle && (
            <label>
              자막 입력
              <select
                aria-label="자막 입력"
                required={
                  template === 'translate' ||
                  (template === 'encode' && options.subtitle_mode !== 'none')
                }
                value={subtitle}
                onChange={(e) => void importTrack(e.target.value)}
              >
                <option value="">{template === 'full' ? '새로 전사' : '선택 안 함'}</option>
                {subtitles.map((s) => (
                  <option key={s.artifact_id} value={s.artifact_id}>
                    {s.filename} · {s.language} · {s.cue_count}개
                  </option>
                ))}
                {detail.jobs
                  .filter((j) => j.status === 'COMPLETED')
                  .flatMap((j) =>
                    (j.metadata.result_files || [])
                      .filter((f) => f.endsWith('.srt'))
                      .map((f) => (
                        <option
                          key={j.job_id + f}
                          value={`job:${j.job_id}:${f.replace('.srt', '')}:${j.metadata.subtitle_revision || 0}`}
                        >
                          {f} · {new Date(j.created_at).toLocaleString('ko-KR')} · v
                          {j.metadata.subtitle_revision || 0}
                        </option>
                      )),
                  )}
              </select>
              {(template === 'translate' ||
                (template === 'encode' && options.subtitle_mode !== 'none')) && (
                <span className="workflow-input-hint">
                  필수 · 첨부 자막이나 완료된 결과 자막을 선택하세요.
                </span>
              )}
              {selectedSubtitle && (
                <span className="workflow-selected-input">
                  선택한 자막: {selectedSubtitle.filename} · {selectedSubtitle.language} ·{' '}
                  {selectedSubtitle.cue_count}개
                  {selectedSubtitle.provenance.revision !== undefined
                    ? ` · v${selectedSubtitle.provenance.revision}`
                    : ''}
                </span>
              )}
            </label>
          )}
          {needsTranscription && (
            <label>
              음성 입력
              <select
                value={audio}
                onChange={(e) => {
                  invalidatePlan();
                  setAudio(e.target.value);
                }}
              >
                <option value="">원본에서 추출</option>
                {audios.map((a) => (
                  <option key={a.job_id} value={a.job_id}>
                    추출 음성 · {new Date(a.created_at).toLocaleString('ko-KR')}
                  </option>
                ))}
              </select>
            </label>
          )}
          <div className="workflow-fields">
            {needsTranscription && (
              <>
                <label>
                  원본 언어
                  <select
                    value={options.source_language}
                    onChange={(e) => option('source_language', e.target.value)}
                  >
                    {Object.entries({
                      auto: '자동',
                      ko: '한국어',
                      en: '영어',
                      ja: '일본어',
                      zh: '중국어',
                      es: '스페인어',
                    }).map(([id, name]) => (
                      <option key={id} value={id}>
                        {name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  무음 필터
                  <select
                    value={options.audio_filter}
                    onChange={(e) => option('audio_filter', e.target.value)}
                  >
                    <option value="silence3">3초 이상 무음</option>
                    <option value="off">사용 안 함</option>
                    <option value="conservative">보수적</option>
                    <option value="strong">강하게</option>
                  </select>
                </label>
                <label className="check-field">
                  <input
                    type="checkbox"
                    checked={options.vad_mode === 'nvidia'}
                    onChange={(e) => option('vad_mode', e.target.checked ? 'nvidia' : 'off')}
                  />
                  NVIDIA 음성 감지
                </label>
              </>
            )}
            {hasTranslation && (
              <label>
                번역 언어
                <select
                  value={options.target_language}
                  onChange={(e) => option('target_language', e.target.value)}
                >
                  {Object.entries({
                    ko: '한국어',
                    en: '영어',
                    ja: '일본어',
                    zh: '중국어',
                    es: '스페인어',
                  }).map(([id, name]) => (
                    <option key={id} value={id}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            {hasEncoding && (
              <>
                <label>
                  코덱
                  <select
                    value={options.video_codec}
                    onChange={(e) => option('video_codec', e.target.value)}
                  >
                    <option value="hevc">HEVC</option>
                    <option value="h264">H.264</option>
                  </select>
                </label>
                <label>
                  화질
                  <select
                    value={options.quality_profile}
                    onChange={(e) => option('quality_profile', e.target.value)}
                  >
                    <option value="balanced">균형</option>
                    <option value="high">고화질</option>
                    <option value="compact">용량 우선</option>
                  </select>
                </label>
                <label>
                  해상도
                  <select
                    value={options.resolution}
                    onChange={(e) => option('resolution', e.target.value)}
                  >
                    <option value="original">원본</option>
                    <option value="1080p">1080p</option>
                    <option value="720p">720p</option>
                  </select>
                </label>
                <label>
                  자막 출력
                  <select
                    value={options.subtitle_mode}
                    onChange={(e) => {
                      option('subtitle_mode', e.target.value);
                      if (template === 'encode' && e.target.value === 'none') {
                        setSubtitle('');
                      }
                    }}
                  >
                    <option value="burn">영상에 삽입</option>
                    <option value="soft">선택형 자막</option>
                    <option value="none">자막 없음</option>
                  </select>
                </label>
              </>
            )}
          </div>
          {hasTranslation && (
            <label>
              영상 설명
              <Textarea
                rows={3}
                maxLength={2000}
                value={options.video_description}
                onChange={(e) => option('video_description', e.target.value)}
              />
            </label>
          )}
        </fieldset>
        <div
          className="workflow-plan"
          aria-live="polite"
          aria-busy={validInput && !plan && !planError}
        >
          <h3>실행 단계</h3>
          {plan ? (
            <ol>
              {plan.stages.map((s) => (
                <li key={s}>{stageLabels[s] || s}</li>
              ))}
            </ol>
          ) : planError ? (
            <p role="alert">{planError}</p>
          ) : (
            <p>
              {validInput
                ? '실행 계획 확인 중 · 아직 시작할 수 없어요.'
                : '필수 자막 입력을 선택하세요.'}
            </p>
          )}
          {plan && plan.reused.length > 0 && (
            <p>
              재사용:{' '}
              {plan.reused
                .map((s) => (s === 'audio' ? '추출 음성' : s === 'subtitle' ? '선택한 자막' : s))
                .join(', ')}
            </p>
          )}
          <Button variant="secondary" type="button" disabled={busy} onClick={invalidatePlan}>
            계획 다시 확인
          </Button>
        </div>
        {plan && plan.paid_stages.length > 0 && (
          <section className="workflow-paid" aria-labelledby="workflow-paid-title">
            <h3 id="workflow-paid-title">유료 단계 확인</h3>
            <p>현재 계획에서 유료로 분류된 단계입니다. 표시된 단계를 확인한 뒤 시작하세요.</p>
            <ul>
              {plan.paid_stages.map((s) => (
                <li key={s}>
                  <Badge>{stageLabels[s] || s}</Badge>
                </li>
              ))}
            </ul>
            <label className="workflow-consent">
              <input
                type="checkbox"
                required
                disabled={busy}
                checked={confirmed === confirmationKey}
                onChange={(e) => {
                  if (inFlight.current || activePlan.current !== currentPlan) {
                    return;
                  }
                  const value = e.target.checked ? confirmationKey : '';
                  approval.current = value;
                  setConfirmed(value);
                }}
              />
              표시된 유료 단계의 실행을 확인했습니다.
            </label>
            <p>
              원본·입력·옵션이나 계획을 바꾸면 다시 확인해야 해요. 가격과 청구 금액은 이 계획에서
              제공하지 않아요.
            </p>
          </section>
        )}
        {plan && plan.paid_stages.length === 0 && (
          <p className="workflow-no-paid">
            현재 계획에 유료로 표시된 단계가 없습니다. 비용이 없다는 보장은 아닙니다.
          </p>
        )}
        <div className="workflow-footer">
          <Button variant="secondary" type="button" onClick={onClose} disabled={busy}>
            취소
          </Button>
          <Button variant="primary" type="submit" disabled={!canCreate}>
            <Play size={17} />
            {busy ? busyAction : '작업 시작'}
          </Button>
        </div>
      </form>
    </dialog>
  );
};
