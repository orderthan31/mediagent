import { Input } from './hangyeol/primitives/input';
import { Button } from './hangyeol/primitives/button';
import { Badge } from './hangyeol/primitives/badge';
import { useEffect, useRef, useState, type ImgHTMLAttributes } from 'react';
import { X } from 'lucide-react';
import { mediaUrl, Job, request } from './api';
import { jsonPost, VideoDetail } from './video-api';
import './faceswap.css';
import { frontendOnly } from './preview';
import { frameAtTime, sameSettings, nextAutomaticOperation } from './faceswap-state';

type Options = {
  reference_frame: number;
  face_position: number;
  source_position: number;
  distance: number;
  preset: string;
  video_codec: string;
  mask_types: string[];
  mask_blur: number;
  mask_padding: number[];
  mask_areas: string[];
  mask_regions: string[];
  detector_angles: number[];
};
type Session = {
  session_id: string;
  revision: number;
  settings: Options;
  source_file: string | null;
  source_sha256: string | null;
};
type Face = { position: number; bbox: number[]; file: string };
type FaceJob = Job & {
  metadata: Job['metadata'] & {
    faceswap: Session & { fingerprint: string };
    faceswap_operation: string;
    faceswap_processing_seconds?: number;
    preview_resolution?: number;
    faceswap_result?: {
      faces?: Face[];
      frame_number?: number;
      matched_faces?: number;
      frame_count?: number;
      fps?: number;
    };
  };
};
type Capability = {
  ready: boolean;
  reason?: string;
  version?: string;
  fingerprint?: string;
  presets: string[];
};
const imageUrl = (job: Job, file: string) => mediaUrl(`/faceswap/jobs/${job.job_id}/files/${file}`);
const ResultImage = ({ src, ...props }: ImgHTMLAttributes<HTMLImageElement>) => {
  const [attempt, setAttempt] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retry = () => {
    if (attempt >= 3 || timer.current) {
      return;
    }
    timer.current = setTimeout(
      () => {
        timer.current = null;
        setAttempt((old) => old + 1);
      },
      500 * 2 ** attempt,
    );
  };
  useEffect(() => {
    setAttempt(0);
    return () => {
      if (timer.current) {
        clearTimeout(timer.current);
        timer.current = null;
      }
    };
  }, [src]);
  return <img {...props} src={src ? `${src}?retry=${attempt}` : undefined} onError={retry} />;
};

export const FaceSwapDialog = ({
  detail,
  onClose,
  onCreated,
}: {
  detail: VideoDetail;
  onClose: () => void;
  onCreated: (job: Job) => void;
}) => {
  const dialog = useRef<HTMLDialogElement>(null);
  const player = useRef<HTMLVideoElement>(null);
  const locked = useRef(false);
  const attempts = useRef(new Set<string>());
  const mounted = useRef(true);
  const requestGeneration = useRef(0);
  const [playing, setPlaying] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [options, setOptions] = useState<Options | null>(null);
  const [jobs, setJobs] = useState<FaceJob[]>([]);
  const [capability, setCapability] = useState<Capability | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [previewFrame, setPreviewFrame] = useState(1);
  const [previewResolution, setPreviewResolution] = useState(1024);
  const [compare, setCompare] = useState(50);
  const createKey = useRef(crypto.randomUUID());
  const pending = useRef<{ key: string; signature: string } | null>(null);
  const sessionBase = `/faceswap/sessions/${session?.session_id}`;
  const active = jobs.filter((j) => !['COMPLETED', 'FAILED', 'CANCELLED'].includes(j.status));
  const latestFailure = jobs[0]?.status === 'FAILED' ? jobs[0].error : null;
  const sourceJob = jobs.find(
    (j) =>
      j.status === 'COMPLETED' &&
      !j.metadata.results_expired_at &&
      j.metadata.faceswap_operation === 'analyze_source' &&
      j.metadata.faceswap.fingerprint === capability?.fingerprint &&
      JSON.stringify(j.metadata.faceswap.settings.detector_angles) ===
        JSON.stringify(options?.detector_angles) &&
      j.metadata.faceswap.source_sha256 === session?.source_sha256,
  );
  const referenceJob = jobs.find(
    (j) =>
      j.status === 'COMPLETED' &&
      !j.metadata.results_expired_at &&
      ['analyze_reference', 'preview'].includes(j.metadata.faceswap_operation) &&
      j.metadata.faceswap.fingerprint === capability?.fingerprint &&
      JSON.stringify(j.metadata.faceswap.settings.detector_angles) ===
        JSON.stringify(options?.detector_angles) &&
      j.metadata.faceswap_result?.frame_number === previewFrame,
  );
  const previews = jobs.filter(
    (j) =>
      j.status === 'COMPLETED' &&
      !j.metadata.results_expired_at &&
      j.metadata.faceswap_operation === 'preview',
  );
  const currentPreview = previews.find(
    (j) =>
      j.metadata.faceswap.revision === session?.revision &&
      j.metadata.faceswap.fingerprint === capability?.fingerprint &&
      j.metadata.faceswap_result?.frame_number === previewFrame &&
      (j.metadata.preview_resolution || 1024) === previewResolution &&
      sameSettings(j.metadata.faceswap.settings, options),
  );
  const frameCount = jobs.find((j) => j.metadata.faceswap_result?.frame_count)?.metadata
    .faceswap_result?.frame_count;
  const rateParts = (detail.video.media?.frame_rate || '').split('/').map(Number);
  const measuredFps = jobs.find((j) => j.metadata.faceswap_result?.fps)?.metadata.faceswap_result
    ?.fps;
  const fps = measuredFps || rateParts[0] / (rateParts[1] || 1) || 25;
  const shownPreview = currentPreview || previews[0];
  const operation = nextAutomaticOperation({
    blocked: busy || playing || !capability?.ready || !session || !options || active.length > 0,
    source: !!session?.source_file,
    sourceAnalyzed: !!sourceJob,
    referenceAnalyzed: !!referenceJob,
    selected: !!options && options.source_position >= 0 && options.face_position >= 0,
    previewReady: !!currentPreview,
  });
  const automaticKey = JSON.stringify([
    session?.session_id,
    capability?.fingerprint,
    operation,
    operation === 'analyze_source' ? session?.source_sha256 : previewFrame,
    operation === 'preview' ? options : options?.detector_angles,
    previewResolution,
  ]);
  const loadSession = (value: Session) => {
    setSession(value);
    setOptions(value.settings);
    setJobs([]);
    setPreviewFrame(value.settings.reference_frame);
    attempts.current.clear();
  };
  const guarded = async (action: () => Promise<void>) => {
    if (locked.current) {
      return;
    }
    locked.current = true;
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : '요청 실패');
    } finally {
      locked.current = false;
      setBusy(false);
    }
  };
  const newSession = async () => {
    const created = await jsonPost<Session>(`/videos/${detail.video.asset_id}/faceswap-sessions`, {
      request_id: createKey.current,
    });
    createKey.current = crypto.randomUUID();
    setSessions((old) => [created, ...old.filter((s) => s.session_id !== created.session_id)]);
    loadSession(created);
  };
  const save = async () => {
    if (!session || !options) {
      throw new Error('설정을 불러오는 중입니다.');
    }
    if (sameSettings(options, session.settings)) {
      return session;
    }
    const updated = await request<Session>(sessionBase, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ revision: session.revision, settings: options }),
    });
    setSession(updated);
    return updated;
  };
  const submit = async (operation: string) => {
    requestGeneration.current += 1;
    const saved = await save();
    const payload = {
      operation,
      revision: saved.revision,
      preview_frame: previewFrame,
      preview_resolution: previewResolution,
      analysis_frame: operation === 'analyze_reference' ? previewFrame : null,
      preview_job_id: operation === 'render' ? currentPreview?.job_id : null,
    };
    const signature = saved.session_id + JSON.stringify(payload);
    if (pending.current?.signature !== signature) {
      pending.current = { signature, key: crypto.randomUUID() };
    }
    const job = await jsonPost<FaceJob>(`/faceswap/sessions/${saved.session_id}/requests`, {
      ...payload,
      request_id: pending.current.key,
    });
    pending.current = null;
    setJobs((old) => [job, ...old.filter((j) => j.job_id !== job.job_id)]);
    if (operation === 'render') {
      onCreated(job);
    }
  };
  const upload = async (file: File) => {
    if (!session) {
      return;
    }
    if (file.size > 10 * 1024 ** 2) {
      throw new Error('최대 10MB 이미지를 선택하세요.');
    }
    const saved = await save();
    const updated = await request<Session>(sessionBase + `/source?revision=${saved.revision}`, {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file,
    });
    setSession(updated);
    setOptions(updated.settings);
    attempts.current.clear();
  };
  const change = <K extends keyof Options>(key: K, value: Options[K]) => {
    attempts.current.clear();
    setOptions((old) =>
      old
        ? {
            ...old,
            [key]: value,
            ...(key === 'detector_angles' ? { face_position: -1, source_position: -1 } : {}),
          }
        : old,
    );
  };
  const seekFrame = (frame: number) => {
    attempts.current.clear();
    const next = Math.max(
      1,
      Math.min(frameCount || Number.MAX_SAFE_INTEGER, Math.round(frame) || 1),
    );
    setPreviewFrame(next);
    if (player.current) {
      player.current.currentTime = (next - 1) / fps;
    }
  };
  const syncCursor = () => {
    if (player.current) {
      const frame = frameAtTime(player.current.currentTime, fps, frameCount);
      if (frame !== previewFrame) {
        attempts.current.clear();
      }
      setPreviewFrame(frame);
    }
  };
  const checks = (
    key: 'mask_types' | 'mask_areas' | 'mask_regions',
    choices: [string, string][],
  ) => (
    <div className="faceswap-checks">
      {choices.map(([value, label]) => (
        <label key={value}>
          <input
            type="checkbox"
            checked={options?.[key].includes(value) || false}
            onChange={(e) => {
              if (!options) {
                return;
              }
              const values = e.target.checked
                ? [...options[key], value]
                : options[key].filter((v) => v !== value);
              if (values.length) {
                change(
                  key,
                  choices.map(([v]) => v).filter((v) => values.includes(v)),
                );
              }
            }}
          />
          {label}
        </label>
      ))}
    </div>
  );
  const deleteSession = async () => {
    await request(sessionBase, { method: 'DELETE' });
    const remaining = sessions.filter((s) => s.session_id !== session?.session_id);
    setSessions(remaining);
    setSession(null);
    setOptions(null);
    setJobs([]);
    if (remaining.length) {
      loadSession(await request<Session>(`/faceswap/sessions/${remaining[0].session_id}`));
    }
  };
  const facePicker = (job: FaceJob | undefined, source: boolean) => {
    if (!job) {
      return null;
    }
    const faces = job.metadata.faceswap_result?.faces || [];
    const selected = source
      ? options?.source_position
      : options?.reference_frame === previewFrame
        ? options.face_position
        : -1;
    const choose = (position: number) => {
      attempts.current.clear();
      setOptions((old) =>
        old
          ? {
              ...old,
              ...(source
                ? { source_position: position }
                : { face_position: position, reference_frame: previewFrame }),
            }
          : old,
      );
    };
    return (
      <div>
        <div className="faceswap-frame">
          <ResultImage
            src={imageUrl(job, 'original.png')}
            alt={source ? 'Source 얼굴 선택' : '교체 대상 얼굴 선택'}
          />
          {faces.map((face) => (
            <Button
              variant="secondary"
              type="button"
              key={face.position}
              className={selected === face.position ? 'selected' : ''}
              aria-label={`${source ? 'Source' : '대상'} 얼굴 ${face.position + 1} 선택`}
              onClick={() => choose(face.position)}
              style={{
                left: `${face.bbox[0] * 100}%`,
                top: `${face.bbox[1] * 100}%`,
                width: `${(face.bbox[2] - face.bbox[0]) * 100}%`,
                height: `${(face.bbox[3] - face.bbox[1]) * 100}%`,
              }}
            >
              {face.position + 1}
            </Button>
          ))}
        </div>
        <div className="faceswap-faces">
          {faces.map((face) => (
            <Button
              variant="secondary"
              key={face.position}
              type="button"
              aria-pressed={selected === face.position}
              aria-label={`${source ? 'Source' : '대상'} 얼굴 ${face.position + 1} 썸네일`}
              onClick={() => choose(face.position)}
            >
              <ResultImage src={imageUrl(job, face.file)} alt={`얼굴 ${face.position + 1}`} />
              {face.position + 1}
            </Button>
          ))}
        </div>
        {!faces.length && <p>얼굴이 검출되지 않았습니다. 다른 이미지나 프레임을 선택하세요.</p>}
      </div>
    );
  };
  useEffect(() => {
    mounted.current = true;
    dialog.current?.showModal();
    return () => {
      mounted.current = false;
      dialog.current?.close();
    };
  }, []);
  useEffect(() => {
    let alive = true;
    void request<{ sessions: Session[] }>(`/videos/${detail.video.asset_id}/faceswap-sessions`)
      .then((value) => {
        if (alive) {
          setSessions(value.sessions);
          if (value.sessions[0]) {
            loadSession(value.sessions[0]);
          } else {
            void guarded(newSession);
          }
        }
      })
      .catch((e) => {
        if (alive) {
          setError(e.message);
        }
      });
    return () => {
      alive = false;
    };
  }, [detail.video.asset_id]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      const generation = requestGeneration.current;
      try {
        const cap = await request<Capability>('/faceswap/capabilities', {
          signal: controller.signal,
        });
        if (!controller.signal.aborted) {
          setCapability(cap);
        }
        if (session) {
          const value = await request<{ jobs: FaceJob[] }>(
            `/faceswap/sessions/${session.session_id}/requests`,
            { signal: controller.signal },
          );
          if (
            !controller.signal.aborted &&
            generation === requestGeneration.current &&
            !locked.current
          ) {
            setJobs(value.jobs);
          }
        }
      } catch (e) {
        if (!controller.signal.aborted) {
          setError(e instanceof Error ? e.message : '상태 조회 실패');
        }
      } finally {
        if (!controller.signal.aborted) {
          timer = setTimeout(poll, 500);
        }
      }
    };
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [session?.session_id]);
  useEffect(() => {
    syncCursor();
  }, [fps]);
  useEffect(() => {
    if (!options || busy || active.length > 0) {
      return;
    }
    const sourceFaces = sourceJob?.metadata.faceswap_result?.faces || [];
    const targetFaces = referenceJob?.metadata.faceswap_result?.faces || [];
    if (
      (options.source_position < 0 && sourceFaces.length === 1) ||
      (options.face_position < 0 && targetFaces.length === 1)
    ) {
      setOptions({
        ...options,
        ...(options.source_position < 0 && sourceFaces.length === 1
          ? { source_position: sourceFaces[0].position }
          : {}),
        ...(options.face_position < 0 && targetFaces.length === 1
          ? { face_position: targetFaces[0].position, reference_frame: previewFrame }
          : {}),
      });
    }
  }, [sourceJob, referenceJob, options, busy, active.length, previewFrame]);
  useEffect(() => {
    if (!operation || attempts.current.has(automaticKey)) {
      return;
    }
    const timer = setTimeout(() => {
      if (!mounted.current || locked.current) {
        return;
      }
      attempts.current.add(automaticKey);
      void guarded(() => submit(operation));
    }, 200);
    return () => clearTimeout(timer);
  });
  return (
    <dialog
      className="faceswap-dialog"
      ref={dialog}
      onCancel={onClose}
      aria-labelledby="faceswap-title"
    >
      <header>
        <div>
          <p className="feature-eyebrow">영상 도구 · 인물 선택과 결과 확인</p>
          <h2 id="faceswap-title">얼굴 합성</h2>
          <p>{detail.video.original_filename}</p>
        </div>
        <Button variant="secondary" className="icon" title="닫기" onClick={onClose}>
          <X />
        </Button>
      </header>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {!error && latestFailure && (
        <p className="alert" role="alert">
          {latestFailure} 사진·장면·설정을 확인한 뒤 다시 생성하세요.
        </p>
      )}
      <div className="faceswap-guide" role="status">
        <Badge tone={capability?.ready ? 'info' : 'neutral'}>
          {frontendOnly ? '목업' : capability?.ready ? '엔진 준비됨' : '엔진 확인 필요'}
        </Badge>
        <strong>
          {frontendOnly ? '합성 화면 미리보기 · 실제 엔진 미연결' : capability?.ready
            ? `얼굴 합성 준비 완료 · FaceFusion ${capability.version || ''}`
            : '얼굴 합성 엔진 연결 대기'}
        </strong>
        {!capability?.ready && (
          <p>
            {capability?.reason || '에이전트 연결 확인 중…'} 엔진이 준비되면 아래 기능이 자동으로
            활성화됩니다.
          </p>
        )}
        <p className="feature-steps">사진 선택 → 대상 인물 선택 → 미리보기 확인 → 전체 합성</p>
        <p>
          사진을 등록하고 영상에서 원하는 장면으로 이동하세요. 멈춘 위치에서 얼굴을 자동 분석하고,
          얼굴 선택·마스크 설정을 바꾸면 미리보기도 자동 갱신됩니다.
        </p>
        {capability?.ready && !session && <p>작업 설정을 준비하고 있습니다.</p>}
        {capability?.ready && session && !session.source_file && (
          <p>
            새 얼굴의 JPEG/PNG 사진을 등록하세요. 얼굴이 하나면 자동 선택되며, 여러 명이면 원하는
            얼굴을 눌러주세요.
          </p>
        )}
        {active.length > 0 && (
          <p>얼굴 분석·미리보기 작업이 진행 중입니다. 완료되면 결과가 자동으로 표시됩니다.</p>
        )}
      </div>
      <div className="faceswap-session">
        <select
          aria-label="저장된 얼굴 합성 설정"
          value={session?.session_id || ''}
          disabled={busy}
          onChange={(e) =>
            void guarded(async () =>
              loadSession(await request<Session>(`/faceswap/sessions/${e.target.value}`)),
            )
          }
        >
          <option value="" disabled>
            저장된 설정 선택
          </option>
          {sessions.map((s, i) => (
            <option key={s.session_id} value={s.session_id}>
              설정 {i + 1} · {s.session_id.slice(0, 6)}
            </option>
          ))}
        </select>
        <Button variant="secondary" disabled={busy} onClick={() => void guarded(newSession)}>
          새 설정
        </Button>
        {session && (
          <Button
            variant="secondary"
            disabled={busy || active.length > 0}
            onClick={() => void guarded(deleteSession)}
          >
            설정 삭제
          </Button>
        )}
      </div>
      {session && options && (
        <>
          <fieldset disabled={busy || !capability?.ready} className="faceswap-grid">
            <section className="faceswap-source">
              <h3>새 얼굴 사진</h3>
              <Input
                aria-label="Source 이미지"
                type="file"
                accept="image/jpeg,image/png"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) {
                    void guarded(() => upload(file));
                  }
                  e.target.value = '';
                }}
              />
              <Button
                variant="secondary"
                disabled={!session.source_file}
                onClick={() => void guarded(() => submit('analyze_source'))}
              >
                사진 다시 분석
              </Button>
              {facePicker(sourceJob, true)}
            </section>
            <section className="faceswap-target">
              <h3>대상 영상 · 커서 탐색</h3>
              <video
                ref={player}
                controls
                preload="metadata"
                onPlay={() => setPlaying(true)}
                onPause={() => {
                  setPlaying(false);
                  syncCursor();
                }}
                onSeeked={syncCursor}
                onLoadedMetadata={syncCursor}
                src={mediaUrl(`/videos/${detail.video.asset_id}/stream`)}
              />
              <label>
                현재 커서 · 프레임 번호
                <Input
                  type="number"
                  min="1"
                  max={frameCount}
                  value={previewFrame}
                  onChange={(e) => seekFrame(Number(e.target.value))}
                />
              </label>
              {frameCount && (
                <label>
                  프레임 탐색 · 총 {frameCount} 프레임
                  <input
                    type="range"
                    min="1"
                    max={frameCount}
                    value={previewFrame}
                    onChange={(e) => seekFrame(Number(e.target.value))}
                  />
                </label>
              )}
              <p className="muted">
                {playing
                  ? '일시정지하면 해당 장면을 자동 분석합니다.'
                  : `프레임 ${previewFrame} · ${((previewFrame - 1) / fps).toFixed(2)}초`}
              </p>
              <p>
                얼굴이 여러 명이면 교체할 얼굴을 누르세요. 선택한 인물은 커서를 옮겨도 유지됩니다.
              </p>
              {options.face_position >= 0 && (
                <p>
                  선택한 대상: 기준 프레임 {options.reference_frame}의 얼굴{' '}
                  {options.face_position + 1}
                </p>
              )}
              <Button
                variant="secondary"
                onClick={() => void guarded(() => submit('analyze_reference'))}
              >
                현재 장면 다시 분석
              </Button>
              {facePicker(referenceJob, false)}
            </section>
            <section className="faceswap-settings">
              <h3>합성 설정</h3>
              <label>
                품질
                <select value={options.preset} onChange={(e) => change('preset', e.target.value)}>
                  {(capability?.presets || []).map((p) => (
                    <option key={p} value={p}>
                      {
                        (
                          { fast: '빠르게', balanced: '균형', quality: '고품질' } as Record<
                            string,
                            string
                          >
                        )[p]
                      }
                    </option>
                  ))}
                </select>
              </label>
              <label>
                인물 매칭 범위
                <input
                  type="range"
                  min=".05"
                  max="1"
                  step=".05"
                  value={options.distance}
                  onChange={(e) => change('distance', Number(e.target.value))}
                />
              </label>
              <p>엄격함 ← {options.distance.toFixed(2)} → 느슨함</p>
              <h4>합성 마스크</h4>
              {checks('mask_types', [
                ['box', '박스'],
                ['occlusion', '가림 처리'],
                ['area', '얼굴 윤곽 영역'],
                ['region', '얼굴 부위'],
              ])}
              <p className="muted">
                마스크는 겹치는 영역에 적용됩니다. 가림 처리는 손·물체를 보존하고, 얼굴 윤곽 영역은
                검출된 랜드마크로 다각형을 만듭니다.
              </p>
              {options.mask_types.includes('box') && (
                <>
                  <label>
                    경계 부드러움 · {options.mask_blur.toFixed(2)}
                    <input
                      type="range"
                      min="0"
                      max="1"
                      step=".05"
                      value={options.mask_blur}
                      onChange={(e) => change('mask_blur', Number(e.target.value))}
                    />
                  </label>
                  <div className="faceswap-padding">
                    {['위', '오른쪽', '아래', '왼쪽'].map((label, i) => (
                      <label key={label}>
                        {label} 여백 (%)
                        <Input
                          type="number"
                          min="0"
                          max="100"
                          value={options.mask_padding[i]}
                          onChange={(e) =>
                            change(
                              'mask_padding',
                              options.mask_padding.map((v, n) =>
                                n === i
                                  ? Math.max(0, Math.min(100, Math.round(Number(e.target.value))))
                                  : v,
                              ),
                            )
                          }
                        />
                      </label>
                    ))}
                  </div>
                </>
              )}
              {options.mask_types.includes('area') &&
                checks('mask_areas', [
                  ['upper-face', '얼굴 위쪽'],
                  ['lower-face', '얼굴 아래쪽'],
                  ['mouth', '입 주변'],
                ])}
              {options.mask_types.includes('region') &&
                checks('mask_regions', [
                  ['skin', '피부'],
                  ['left-eyebrow', '왼쪽 눈썹'],
                  ['right-eyebrow', '오른쪽 눈썹'],
                  ['left-eye', '왼쪽 눈'],
                  ['right-eye', '오른쪽 눈'],
                  ['glasses', '안경'],
                  ['nose', '코'],
                  ['mouth', '입'],
                  ['upper-lip', '윗입술'],
                  ['lower-lip', '아랫입술'],
                ])}
              <details>
                <summary>얼굴 검출 방향</summary>
                <p>
                  기울거나 돌아간 영상의 얼굴을 찾는 회전각입니다. 정면·측면 필터는 FaceFusion
                  3.5.4에서 제공하지 않습니다. 변경하면 얼굴을 다시 분석·선택합니다.
                </p>
                <div className="faceswap-checks">
                  {[0, 90, 180, 270].map((angle) => (
                    <label key={angle}>
                      <input
                        type="checkbox"
                        checked={options.detector_angles.includes(angle)}
                        onChange={(e) => {
                          const values = e.target.checked
                            ? [...options.detector_angles, angle].sort((a, b) => a - b)
                            : options.detector_angles.filter((a) => a !== angle);
                          if (values.length) {
                            change('detector_angles', values);
                          }
                        }}
                      />
                      {angle}°
                    </label>
                  ))}
                </div>
              </details>
              <label>
                출력 형식
                <select
                  value={options.video_codec}
                  onChange={(e) => change('video_codec', e.target.value)}
                >
                  <option value="h264">H.264</option>
                  <option value="hevc">HEVC</option>
                </select>
              </label>
              <Button
                variant="secondary"
                onClick={() =>
                  void guarded(async () => {
                    await save();
                  })
                }
              >
                설정 저장
              </Button>
            </section>
            <section className="faceswap-preview">
              <h3>자동 미리보기</h3>
              <label>
                미리보기 해상도
                <select
                  value={previewResolution}
                  onChange={(e) => {
                    attempts.current.clear();
                    setPreviewResolution(Number(e.target.value));
                  }}
                >
                  <option value={512}>512px · 빠르게</option>
                  <option value={768}>768px</option>
                  <option value={1024}>1024px · Gradio 기본값</option>
                </select>
              </label>
              <p className="muted">미리보기만 축소합니다. 전체 영상 처리 해상도는 유지됩니다.</p>
              <label>
                확인할 프레임 번호
                <Input
                  type="number"
                  min="1"
                  value={previewFrame}
                  max={frameCount}
                  onChange={(e) => seekFrame(Number(e.target.value))}
                />
              </label>
              <Button
                variant="secondary"
                disabled={
                  !sourceJob ||
                  !referenceJob ||
                  options.source_position < 0 ||
                  options.face_position < 0
                }
                onClick={() => void guarded(() => submit('preview'))}
              >
                미리보기 다시 생성
              </Button>
              <p role="status">
                {playing
                  ? '재생을 멈추면 미리보기를 갱신합니다.'
                  : currentPreview
                    ? '현재 장면·설정의 미리보기입니다.'
                    : active.length
                      ? '분석·미리보기 처리 중… 이동한 마지막 장면을 이어서 처리합니다.'
                      : options.source_position < 0 || options.face_position < 0
                        ? '사진과 교체할 얼굴이 선택되면 미리보기가 자동 생성됩니다.'
                        : '자동 미리보기 대기 중입니다. 실패 시 다시 생성 버튼으로 재시도하세요.'}
              </p>
              {shownPreview && (
                <>
                  {shownPreview.metadata.faceswap_result?.matched_faces === 0 && (
                    <p className="muted">
                      이 장면에는 선택한 인물이 없습니다. 다른 장면으로 이동하거나 검출된 얼굴에서
                      대상을 다시 선택하세요.
                    </p>
                  )}
                  {shownPreview !== currentPreview && (
                    <p className="muted">
                      이전 결과입니다. 현재 커서·설정의 미리보기로 갱신 중입니다.
                    </p>
                  )}
                  <div className="faceswap-compare">
                    <ResultImage src={imageUrl(shownPreview, 'original.png')} alt="합성 전" />
                    <ResultImage
                      src={imageUrl(shownPreview, 'preview.png')}
                      alt="합성 후"
                      style={{ clipPath: `inset(0 0 0 ${compare}%)` }}
                    />
                  </div>
                  <label>
                    원본 / 합성 비교
                    <input
                      type="range"
                      min="0"
                      max="100"
                      value={compare}
                      onChange={(e) => setCompare(Number(e.target.value))}
                    />
                  </label>
                  <p>
                    프레임 {shownPreview.metadata.faceswap_result?.frame_number} · 설정 버전{' '}
                    {shownPreview.metadata.faceswap.revision}
                    {shownPreview.metadata.faceswap_processing_seconds !== undefined &&
                      ` · 처리 ${shownPreview.metadata.faceswap_processing_seconds.toFixed(2)}초`}
                  </p>
                </>
              )}
            </section>
          </fieldset>
          <Button
            variant="primary"
            className="primary"
            disabled={
              busy ||
              !capability?.ready ||
              !currentPreview ||
              currentPreview.metadata.faceswap_result?.matched_faces === 0
            }
            onClick={() => void guarded(() => submit('render'))}
          >
            현재 설정으로 전체 영상 처리
          </Button>
          <p>
            최대 10분씩 순차 합성 후 하나의 영상으로 연결하고 인코딩합니다. 실패한 경우 완료된
            구간부터 이어서 처리합니다.
          </p>
          {!currentPreview && (
            <p>현재 장면·설정의 자동 미리보기가 완료되면 전체 처리가 활성화됩니다.</p>
          )}
        </>
      )}
    </dialog>
  );
};
