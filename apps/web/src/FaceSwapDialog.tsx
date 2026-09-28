import { useEffect, useRef, useState } from 'react';
import { X } from 'lucide-react';
import { base, Job, request } from './api';
import { jsonPost, statusLabels, VideoDetail } from './video-api';
import './faceswap.css';

type Options = {
  reference_frame: number;
  face_position: number;
  source_position: number;
  distance: number;
  preset: string;
  video_codec: string;
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
const imageUrl = (job: Job, file: string) => `${base}/faceswap/jobs/${job.job_id}/files/${file}`;

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
  const [session, setSession] = useState<Session | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [options, setOptions] = useState<Options | null>(null);
  const [jobs, setJobs] = useState<FaceJob[]>([]);
  const [capability, setCapability] = useState<Capability | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [previewFrame, setPreviewFrame] = useState(1);
  const [compare, setCompare] = useState(50);
  const [selectedPreview, setSelectedPreview] = useState('');
  const createKey = useRef(crypto.randomUUID());
  const pending = useRef<{ key: string; signature: string } | null>(null);
  const sessionBase = `/faceswap/sessions/${session?.session_id}`;
  const active = jobs.filter((j) => !['COMPLETED', 'FAILED', 'CANCELLED'].includes(j.status));
  const sourceJob = jobs.find(
    (j) =>
      j.status === 'COMPLETED' &&
      j.metadata.faceswap_operation === 'analyze_source' &&
      j.metadata.faceswap.fingerprint === capability?.fingerprint &&
      j.metadata.faceswap.source_sha256 === session?.source_sha256,
  );
  const referenceJob = jobs.find(
    (j) =>
      j.status === 'COMPLETED' &&
      j.metadata.faceswap_operation === 'analyze_reference' &&
      j.metadata.faceswap.fingerprint === capability?.fingerprint &&
      j.metadata.faceswap.settings.reference_frame === options?.reference_frame,
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
      JSON.stringify(j.metadata.faceswap.settings) === JSON.stringify(options),
  );
  const frameCount = jobs.find((j) => j.metadata.faceswap_result?.frame_count)?.metadata
    .faceswap_result?.frame_count;
  const shownPreview =
    previews.find((j) => j.job_id === selectedPreview) || currentPreview || previews[0];
  const loadSession = (value: Session) => {
    setSession(value);
    setOptions(value.settings);
    setJobs([]);
    setSelectedPreview('');
  };
  const guarded = async (action: () => Promise<void>) => {
    setBusy(true);
    setError('');
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : '요청 실패');
    } finally {
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
    if (JSON.stringify(options) === JSON.stringify(session.settings)) {
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
    const saved = await save();
    const payload = {
      operation,
      revision: saved.revision,
      preview_frame: previewFrame,
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
    const updated = await request<Session>(sessionBase + `/source?revision=${session.revision}`, {
      method: 'POST',
      headers: { 'Content-Type': file.type || 'application/octet-stream' },
      body: file,
    });
    setSession(updated);
    setOptions(updated.settings);
  };
  const change = <K extends keyof Options>(key: K, value: Options[K]) => {
    setOptions((old) =>
      old
        ? { ...old, [key]: value, ...(key === 'reference_frame' ? { face_position: -1 } : {}) }
        : old,
    );
  };
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
    const selected = source ? options?.source_position : options?.face_position;
    const choose = (position: number) =>
      change(source ? 'source_position' : 'face_position', position);
    return (
      <div>
        <div className="faceswap-frame">
          <img
            src={imageUrl(job, 'original.png')}
            alt={source ? 'Source 얼굴 선택' : '교체 대상 얼굴 선택'}
          />
          {faces.map((face) => (
            <button
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
            </button>
          ))}
        </div>
        <div className="faceswap-faces">
          {faces.map((face) => (
            <button
              key={face.position}
              type="button"
              aria-pressed={selected === face.position}
              aria-label={`${source ? 'Source' : '대상'} 얼굴 ${face.position + 1} 썸네일`}
              onClick={() => choose(face.position)}
            >
              <img src={imageUrl(job, face.file)} alt={`얼굴 ${face.position + 1}`} />
              {face.position + 1}
            </button>
          ))}
        </div>
        {!faces.length && <p>얼굴이 검출되지 않았습니다. 다른 이미지나 프레임을 선택하세요.</p>}
      </div>
    );
  };
  useEffect(() => {
    dialog.current?.showModal();
    return () => dialog.current?.close();
  }, []);
  useEffect(() => {
    let alive = true;
    void request<{ sessions: Session[] }>(`/videos/${detail.video.asset_id}/faceswap-sessions`)
      .then((value) => {
        if (alive) {
          setSessions(value.sessions);
          if (value.sessions[0]) {
            loadSession(value.sessions[0]);
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
          if (!controller.signal.aborted) {
            setJobs(value.jobs);
          }
        }
      } catch (e) {
        if (!controller.signal.aborted) {
          setError(e instanceof Error ? e.message : '상태 조회 실패');
        }
      } finally {
        if (!controller.signal.aborted) {
          timer = setTimeout(poll, 2500);
        }
      }
    };
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [session?.session_id]);
  return (
    <dialog
      className="faceswap-dialog"
      ref={dialog}
      onCancel={onClose}
      aria-labelledby="faceswap-title"
    >
      <header>
        <div>
          <h2 id="faceswap-title">얼굴 합성</h2>
          <p>{detail.video.original_filename}</p>
        </div>
        <button className="icon" title="닫기" onClick={onClose}>
          <X />
        </button>
      </header>
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {!capability?.ready && <p role="status">{capability?.reason || 'Worker 연결 확인 중…'}</p>}
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
        <button disabled={busy} onClick={() => void guarded(newSession)}>
          새 설정
        </button>
        {session && (
          <button disabled={busy || active.length > 0} onClick={() => void guarded(deleteSession)}>
            설정 삭제
          </button>
        )}
      </div>
      {session && options && (
        <>
          <fieldset disabled={busy || !capability?.ready} className="faceswap-grid">
            <section>
              <h3>1. Source 얼굴</h3>
              <input
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
              <button
                disabled={!session.source_file}
                onClick={() => void guarded(() => submit('analyze_source'))}
              >
                Source 얼굴 찾기
              </button>
              {facePicker(sourceJob, true)}
            </section>
            <section>
              <h3>2. 교체 대상</h3>
              <video
                controls
                preload="metadata"
                src={`${base}/videos/${detail.video.asset_id}/stream`}
              />
              <label>
                기준 프레임 번호 (1부터)
                <input
                  type="number"
                  min="1"
                  value={options.reference_frame}
                  onChange={(e) => change('reference_frame', Number(e.target.value))}
                />
              </label>
              {frameCount && (
                <label>
                  프레임 탐색 · 총 {frameCount} 프레임
                  <input
                    type="range"
                    min="1"
                    max={frameCount}
                    value={options.reference_frame}
                    onChange={(e) => change('reference_frame', Number(e.target.value))}
                  />
                </label>
              )}
              <p className="muted">선택한 프레임에서 교체할 얼굴을 눌러주세요.</p>
              <button onClick={() => void guarded(() => submit('analyze_reference'))}>
                이 프레임 얼굴 찾기
              </button>
              {facePicker(referenceJob, false)}
            </section>
            <section>
              <h3>3. 합성 설정</h3>
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
              <button
                onClick={() =>
                  void guarded(async () => {
                    await save();
                  })
                }
              >
                설정 저장
              </button>
            </section>
            <section>
              <h3>4. 미리보기</h3>
              <label>
                확인할 프레임 번호
                <input
                  type="number"
                  min="1"
                  value={previewFrame}
                  onChange={(e) => setPreviewFrame(Number(e.target.value))}
                />
              </label>
              <button
                disabled={
                  !sourceJob ||
                  !referenceJob ||
                  options.source_position < 0 ||
                  options.face_position < 0
                }
                onClick={() => void guarded(() => submit('preview'))}
              >
                미리보기 생성
              </button>
              {shownPreview && (
                <>
                  <div className="faceswap-compare">
                    <img src={imageUrl(shownPreview, 'original.png')} alt="합성 전" />
                    <img
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
                  </p>
                </>
              )}
              <div className="faceswap-history">
                {previews.map((j) => (
                  <button key={j.job_id} onClick={() => setSelectedPreview(j.job_id)}>
                    <img src={imageUrl(j, 'preview.png')} alt="이전 미리보기" />
                    프레임 {j.metadata.faceswap_result?.frame_number} · v
                    {j.metadata.faceswap.revision}
                  </button>
                ))}
              </div>
            </section>
          </fieldset>
          <button
            className="primary"
            disabled={busy || !capability?.ready || !currentPreview}
            onClick={() => void guarded(() => submit('render'))}
          >
            현재 설정으로 전체 영상 처리
          </button>
          <p>
            최대 10분씩 순차 합성 후 하나의 영상으로 연결하고 인코딩합니다. 실패한 경우 완료된
            구간부터 이어서 처리합니다.
          </p>
          {!currentPreview && <p>현재 설정의 미리보기를 생성한 후 전체 처리를 시작하세요.</p>}
          <section>
            <h3>분석·미리보기 요청</h3>
            {jobs
              .filter((j) => j.metadata.faceswap_operation !== 'render')
              .map((j) => (
                <div className="faceswap-request" key={j.job_id}>
                  <span>
                    {
                      (
                        {
                          analyze_source: 'Source 분석',
                          analyze_reference: '대상 분석',
                          preview: '미리보기',
                        } as Record<string, string>
                      )[j.metadata.faceswap_operation]
                    }{' '}
                    · {statusLabels[j.status]}
                    {j.error && ` · ${j.error}`}
                  </span>
                  {!['COMPLETED', 'FAILED', 'CANCELLED'].includes(j.status) && (
                    <button
                      onClick={() =>
                        void guarded(async () => {
                          await jsonPost(`/jobs/${j.job_id}/cancel`, {});
                        })
                      }
                    >
                      취소
                    </button>
                  )}
                  {['FAILED', 'CANCELLED'].includes(j.status) && (
                    <button
                      onClick={() =>
                        void guarded(async () => {
                          await jsonPost(`/jobs/${j.job_id}/retry`, {});
                        })
                      }
                    >
                      재시도
                    </button>
                  )}
                  {['COMPLETED', 'FAILED', 'CANCELLED'].includes(j.status) && (
                    <button
                      onClick={() =>
                        void guarded(async () => {
                          await request(`/jobs/${j.job_id}`, { method: 'DELETE' });
                          setJobs((old) => old.filter((v) => v.job_id !== j.job_id));
                        })
                      }
                    >
                      삭제
                    </button>
                  )}
                </div>
              ))}
          </section>
        </>
      )}
    </dialog>
  );
};
