import { useEffect, useRef, useState } from 'react';
import {
  ArrowLeft,
  FileVideo,
  FolderOpen,
  ListVideo,
  Pause,
  Play,
  Plus,
  Search,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { base, Job, request, resumeUpload, uploadRequest } from './api';
import { AccountMenu } from './AuthGate';
import { JobDetail } from './JobDetail';
import { SettingsPage } from './SettingsPage';
import { ServingPage } from './ServingPage';
import { WorkflowEditor } from './WorkflowEditor';
import { WorkflowTickets } from './WorkflowTickets';
import { failureMessage, isContentBlocked } from './job-failure';
import { StageProgress } from './StageProgress';
import { QueuePanel } from './QueuePanel';
import { JobTiming } from './JobTiming';
import { SubtitleEditor } from './SubtitleEditor';
import { UploadItem, UploadQueue } from './upload-queue';
import { isVideoFile } from './video-file';
import { WorkflowDialog } from './WorkflowDialog';
import { FaceSwapDialog } from './FaceSwapDialog';
import {
  jsonPost,
  statusLabels,
  SubtitleInput,
  templates,
  VideoAsset,
  VideoDetail,
  VideoUpload,
} from './video-api';
import { Theme } from './hangyeol/foundation/theme';
import { GNB } from './hangyeol/components/gnb';
import { TextField } from './hangyeol/components/text-field';
import { Button } from './hangyeol/primitives/button';
import { EmptyState } from './hangyeol/components/empty-state';
import { StorageAssetRow, StorageVideoInfo } from './StorageVideo';
import { StorageUploads } from './StorageUploads';
import './video-workspace.css';
import './workspace-polish.css';
import './workspace-shell.css';
import './storage.css';
import './feature-renewal.css';
const workspaceLinks = [
  { id: 'videos', label: '영상 보관함', href: '#/' },
  { id: 'jobs', label: '작업 목록', href: '#/jobs' },
  { id: 'serving', label: '노드·서빙', href: '#/serving' },
  { id: 'editor', label: '워크플로우', href: '#/workflow-editor' },
  { id: 'workflow-tickets', label: '순차 티켓', href: '#/workflow-tickets' },
  { id: 'settings', label: '설정', href: '#/settings' },
];
export const VideoWorkspace = () => {
  const [route, setRoute] = useState(location.hash || '#/'),
    [videos, setVideos] = useState<VideoAsset[]>([]),
    [jobs, setJobs] = useState<Job[]>([]),
    [sessions, setSessions] = useState<VideoUpload[]>([]);
  const [uploads, setUploads] = useState<UploadItem[]>([]),
    [query, setQuery] = useState(''),
    [error, setError] = useState(''),
    [online, setOnline] = useState(false),
    [busy, setBusy] = useState('');
  const [hasConfirmedList, setHasConfirmedList] = useState(false),
    [listFailed, setListFailed] = useState(false);
  const [detail, setDetail] = useState<VideoDetail | null>(null),
    [subtitleInputs, setSubtitleInputs] = useState<SubtitleInput[]>([]),
    [workflow, setWorkflow] = useState(false),
    [faceswap, setFaceswap] = useState(false),
    [review, setReview] = useState<Job | null>(null);
  const input = useRef<HTMLInputElement>(null),
    srtInput = useRef<HTMLInputElement>(null),
    resume = useRef<{
      id: string;
      legacy: boolean;
    } | null>(null);
  const [confirm, setConfirm] = useState<{
    title: string;
    action: () => Promise<void>;
  } | null>(null);
  const [queue] = useState(
    () =>
      new UploadQueue(async (item, signal, changed) => {
        const legacy = !!item.payload.legacy;
        if (!item.jobId) {
          const created = await uploadRequest<{
            upload_id: string;
          }>('/video-uploads', {
            method: 'POST',
            signal,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename: item.name, size: item.size, request_id: item.key }),
          });
          item.jobId = created.upload_id;
          changed();
        }
        await resumeUpload(
          item.file!,
          item.jobId!,
          signal,
          (n) => {
            item.progress = n;
            changed();
          },
          legacy ? '/uploads' : '/video-uploads',
        );
      }),
  );
  const assetId = route.match(/^#\/videos\/([a-f0-9]{32})$/)?.[1],
    jobId = route.match(/^#\/jobs\/([a-f0-9]{32})$/)?.[1];
  const jobsView = route === '#/jobs';
  const settingsView = route === '#/settings';
  const servingView = route === '#/serving';
  const editorView = route === '#/workflow-editor';
  const workflowTicketsView = route === '#/workflow-tickets';
  const currentHref = workflowTicketsView
    ? '#/workflow-tickets'
    : editorView
      ? '#/workflow-editor'
      : servingView
        ? '#/serving'
        : settingsView
          ? '#/settings'
          : jobsView || jobId
            ? '#/jobs'
            : '#/';
  const locationLabel = workflowTicketsView
    ? '순차 워크플로우 티켓'
    : editorView
      ? '워크플로우 편집기'
      : servingView
        ? '노드·서빙'
        : settingsView
          ? '설정'
          : jobId
            ? '작업 목록 / 작업 상세'
            : jobsView
              ? '작업 목록'
              : assetId
                ? '영상 보관함 / 영상 상세'
                : '영상 보관함';
  const shownVideos = videos.filter((v) =>
    v.original_filename.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );
  const pendingSessions = sessions.filter(
    (s) => !s.asset_id && !uploads.some((u) => u.jobId === s.upload_id),
  );
  const refresh = async (signal?: AbortSignal) => {
    const [v, j, u] = await Promise.all([
      request<{
        videos: VideoAsset[];
      }>('/videos', { signal }),
      request<{
        jobs: Job[];
      }>('/jobs', { signal }),
      request<{
        uploads: VideoUpload[];
      }>('/video-uploads', { signal }),
    ]);
    if (signal?.aborted) {
      return;
    }
    setVideos(v.videos);
    setJobs(j.jobs);
    setSessions(u.uploads);
    setOnline(true);
    setHasConfirmedList(true);
    setListFailed(false);
    queue.forgetCompleted([
      ...u.uploads.filter((x) => x.asset_id).map((x) => x.upload_id),
      ...j.jobs.filter((x) => x.status !== 'UPLOADING').map((x) => x.job_id),
    ]);
  };
  const action = async (key: string, operation: () => Promise<unknown>) => {
    if (busy) {
      return;
    }
    setBusy(key);
    setError('');
    try {
      await operation();
      await refresh();
      setConfirm(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : '요청 실패');
    } finally {
      setBusy('');
    }
  };
  const chooseFiles = (files: FileList | null) => {
    if (!files) {
      return;
    }
    const selected = Array.from(files),
      rejected: string[] = [];
    if (input.current) {
      input.current.value = '';
    }
    setError('');
    for (const file of selected) {
      if (!isVideoFile(file)) {
        rejected.push(file.name);
        continue;
      }
      if (resume.current) {
        queue.add(file, { legacy: resume.current.legacy }, resume.current.id);
        resume.current = null;
        break;
      }
      queue.add(file, {});
    }
    if (rejected.length) {
      setError(`영상 파일만 업로드할 수 있습니다: ${rejected.join(', ')}`);
    }
  };
  const chooseResume = (id: string, legacy = false) => {
    resume.current = { id, legacy };
    input.current?.click();
  };
  const attachSrt = async (file: File | undefined) => {
    if (!file || !assetId) {
      return;
    }
    await action('srt', async () => {
      if (file.size > 4 * 1024 ** 2) {
        throw new Error('SRT는 4MB 이하만 첨부할 수 있습니다.');
      }
      await jsonPost(`/videos/${assetId}/subtitles`, {
        filename: file.name,
        language: 'auto',
        content: await file.text(),
      });
      const s = await request<{
        subtitles: SubtitleInput[];
      }>(`/videos/${assetId}/subtitles`);
      setSubtitleInputs(s.subtitles);
    });
    if (srtInput.current) {
      srtInput.current.value = '';
    }
  };
  const terminal = (j: Job) => ['COMPLETED', 'FAILED', 'CANCELLED'].includes(j.status);
  const jobRows = (items: Job[]) => {
    return (
      <div className="video-job-list">
        {items.map((job) => (
          <article key={job.job_id} className="video-job-row">
            <div>
              <a className="job-title" href={`#/jobs/${job.job_id}`}>
                {job.original_filename}
              </a>
              <p>
                {templates[job.metadata.workflow?.template || 'full']} ·{' '}
                {new Date(job.created_at).toLocaleString('ko-KR')}
              </p>
              <span className={'status ' + job.status.toLowerCase()}>
                {job.status === 'AWAITING_REVIEW' && job.metadata.content_block_review
                  ? '차단 구간 검토'
                  : isContentBlocked(job)
                    ? '콘텐츠 차단'
                    : statusLabels[job.status] || job.status}
              </span>
              {failureMessage(job) && (
                <p className="alert" role="alert">
                  {failureMessage(job)}
                </p>
              )}
            </div>
            <div className="row-actions">
              {job.status === 'UPLOADING' && (
                <button
                  className="icon"
                  title="업로드 재개"
                  onClick={() => chooseResume(job.job_id, true)}
                >
                  <Upload size={17} />
                </button>
              )}
              {['READY', 'FAILED', 'CANCELLED'].includes(job.status) && (
                <button
                  className="icon"
                  title={job.status === 'READY' ? '작업 시작' : '중단 단계부터 재시도'}
                  disabled={!!busy}
                  onClick={() =>
                    void action(job.job_id, () =>
                      request(`/jobs/${job.job_id}/${job.status === 'READY' ? 'start' : 'retry'}`, {
                        method: 'POST',
                      }),
                    )
                  }
                >
                  <Play size={17} />
                </button>
              )}
              {job.status === 'AWAITING_REVIEW' && (
                <button onClick={() => setReview(job)}>자막 검토</button>
              )}
              {!terminal(job) && !['READY', 'UPLOADING'].includes(job.status) && (
                <button
                  className="icon"
                  title="작업 중단"
                  disabled={!!busy}
                  onClick={() =>
                    void action(job.job_id, () =>
                      request(`/jobs/${job.job_id}/cancel`, { method: 'POST' }),
                    )
                  }
                >
                  <Pause size={17} />
                </button>
              )}
              {!job.metadata.asset_id && job.status !== 'UPLOADING' && (
                <button
                  disabled={!!busy}
                  onClick={() =>
                    void action(job.job_id, async () => {
                      const a = await request<VideoAsset>(`/jobs/${job.job_id}/register-source`, {
                        method: 'POST',
                      });
                      location.hash = `/videos/${a.asset_id}`;
                    })
                  }
                >
                  <FolderOpen size={15} />
                  원본 등록
                </button>
              )}
              {terminal(job) && (
                <button
                  className="icon danger"
                  title="작업 삭제"
                  onClick={() =>
                    setConfirm({
                      title: `${job.original_filename} 작업과 결과 파일을 삭제할까요?`,
                      action: async () => {
                        await request(`/jobs/${job.job_id}`, { method: 'DELETE' });
                      },
                    })
                  }
                >
                  <Trash2 size={17} />
                </button>
              )}
            </div>
            <StageProgress job={job} />
            <JobTiming job={job} />
          </article>
        ))}
        {!items.length && (
          <div className="library-empty">
            <ListVideo size={30} />
            <p>작업이 없습니다.</p>
          </div>
        )}
      </div>
    );
  };
  useEffect(() => {
    const navigate = () => {
      setRoute(location.hash || '#/');
      setWorkflow(false);
      setFaceswap(false);
      setDetail(null);
      setSubtitleInputs([]);
      setQuery('');
      window.scrollTo(0, 0);
    };
    window.addEventListener('hashchange', navigate);
    return () => window.removeEventListener('hashchange', navigate);
  }, []);
  useEffect(() => {
    queue.onChange = () => setUploads(queue.items.map((x) => ({ ...x })));
    queue.activate();
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        await refresh(controller.signal);
      } catch {
        if (!controller.signal.aborted) {
          setOnline(false);
          setListFailed(true);
        }
      } finally {
        if (!controller.signal.aborted) {
          timer = setTimeout(poll, 2500);
        }
      }
    };
    void poll();
    const visibility = () => queue.suspend(document.visibilityState === 'hidden');
    document.addEventListener('visibilitychange', visibility);
    const leave = (e: BeforeUnloadEvent) => {
      if (queue.items.some((x) => x.file)) {
        e.preventDefault();
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', leave);
    return () => {
      controller.abort();
      clearTimeout(timer);
      queue.dispose();
      document.removeEventListener('visibilitychange', visibility);
      window.removeEventListener('beforeunload', leave);
    };
  }, [queue]);
  useEffect(() => {
    if (!assetId) {
      return;
    }
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const d = await request<VideoDetail>(`/videos/${assetId}`, { signal: controller.signal });
        const s = await request<{
          subtitles: SubtitleInput[];
        }>(`/videos/${assetId}/subtitles`, { signal: controller.signal });
        if (!controller.signal.aborted) {
          setDetail(d);
          setSubtitleInputs(s.subtitles);
        }
      } catch (e) {
        if (!controller.signal.aborted) {
          setError(e instanceof Error ? e.message : '영상 조회 실패');
        }
      } finally {
        if (!controller.signal.aborted) {
          timer = setTimeout(poll, 3000);
        }
      }
    };
    void poll();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [assetId]);
  return (
    <Theme mode="light" palette="Indigo" className="workspace-theme">
      <div className="video-workspace renewed-workspace">
        <GNB
          className="workspace-header"
          items={workspaceLinks}
          currentHref={currentHref}
          label="작업 공간 탐색"
          logo={
            <a className="workspace-brand" href="#/" aria-label="mideagent 영상 보관함">
              <span className="workspace-brand-symbol" aria-hidden="true">
                <FileVideo size={22} />
              </span>
              <strong>mideagent</strong>
            </a>
          }
          actions={
            <div className="workspace-session">
              <span className={'workspace-connection ' + (online ? 'online' : '')} role="status">
                {online ? '서버 연결됨' : '서버 연결 확인 필요'}
              </span>
              <AccountMenu />
            </div>
          }
        />
        <div className="workspace-route-context">
          <p aria-label="현재 위치">{locationLabel}</p>
          <span>영상·자막 작업 공간</span>
        </div>
        <input
          ref={input}
          type="file"
          multiple={!resume.current}
          hidden
          onChange={(e) => chooseFiles(e.target.files)}
        />
        <input
          ref={srtInput}
          type="file"
          accept=".srt"
          hidden
          onChange={(e) => void attachSrt(e.target.files?.[0])}
        />
        {workflowTicketsView ? (
          <WorkflowTickets />
        ) : editorView ? (
          <WorkflowEditor />
        ) : servingView ? (
          <ServingPage />
        ) : settingsView ? (
          <SettingsPage />
        ) : jobId ? (
          <JobDetail
            id={jobId}
            key={jobId}
            labels={statusLabels}
            promotedAssetId={
              videos.find((v) => v.provenance.kind === 'result' && v.provenance.job_id === jobId)
                ?.asset_id
            }
          />
        ) : (
          <main className="video-main">
            {!online && (
              <p className="workspace-connection-notice" role="status">
                서버 연결을 확인해 주세요. 목록 정보가 최신이 아닐 수 있어요.
              </p>
            )}
            {error && (
              <p role="alert" className="alert">
                {error}
                <button className="icon" title="오류 닫기" onClick={() => setError('')}>
                  <X size={16} />
                </button>
              </p>
            )}
            {assetId ? (
              <>
                {detail ? (
                  <>
                    <div className="storage-detail-heading">
                      <a className="storage-back" href="#/">
                        <ArrowLeft size={18} aria-hidden="true" />
                        영상 보관함으로
                      </a>
                      <div>
                        <p className="workspace-eyebrow">원본 영상</p>
                        <h1>{detail.video.original_filename}</h1>
                      </div>
                      <Button variant="secondary" onClick={() => setFaceswap(true)}>
                        얼굴 합성
                      </Button>
                      <Button onClick={() => setWorkflow(true)}>
                        <Play size={17} aria-hidden="true" />새 작업
                      </Button>
                    </div>
                    <StorageVideoInfo
                      video={detail.video}
                      assetId={assetId}
                      onDelete={() =>
                        setConfirm({
                          title: '원본 영상을 삭제할까요? 연결된 작업이 있으면 삭제할 수 없습니다.',
                          action: async () => {
                            await request(`/videos/${assetId}`, { method: 'DELETE' });
                            location.hash = '/';
                          },
                        })
                      }
                    />
                    <section className="asset-subtitles">
                      <div className="section-heading">
                        <h2>
                          자막 입력 <small>{subtitleInputs.length}</small>
                        </h2>
                        <button disabled={!!busy} onClick={() => srtInput.current?.click()}>
                          <Plus size={16} />
                          SRT 첨부
                        </button>
                      </div>
                      {subtitleInputs.length ? (
                        <ul>
                          {subtitleInputs.map((s) => (
                            <li key={s.artifact_id}>
                              <span>{s.filename}</span>
                              <small>
                                {s.language} · {s.cue_count}개 ·{' '}
                                {s.provenance.kind === 'job_subtitle'
                                  ? `작업 자막 v${s.provenance.revision}`
                                  : '외부 첨부'}
                              </small>
                            </li>
                          ))}
                        </ul>
                      ) : (
                        <p className="muted">첨부된 자막이 없습니다.</p>
                      )}
                    </section>
                    <section>
                      <div className="section-heading">
                        <h2>
                          작업 기록 <small>{detail.jobs.length}</small>
                        </h2>
                      </div>
                      {jobRows(detail.jobs)}
                    </section>
                  </>
                ) : (
                  <p role="status">영상 불러오는 중</p>
                )}
              </>
            ) : (
              <>
                <div className="workspace-page-heading">
                  <div>
                    <p className="workspace-eyebrow">{jobsView ? '실행과 검수' : '원본 영상'}</p>
                    <h1>{jobsView ? '작업 목록' : '영상 보관함'}</h1>
                    <p className="workspace-page-description">
                      {jobsView
                        ? '생성한 작업의 진행 상태와 결과를 확인하세요.'
                        : '보관된 영상을 찾고, 필요한 작업을 이어가세요.'}
                    </p>
                  </div>
                  <div className="workspace-page-actions">
                    <span>
                      {online
                        ? `${jobsView ? jobs.length : videos.length}개`
                        : hasConfirmedList
                          ? `마지막 확인 ${jobsView ? jobs.length : videos.length}개 · 최신이 아닐 수 있음`
                          : listFailed
                            ? '개수 확인 불가'
                            : '개수 확인 중'}
                    </span>
                    <Button
                      onClick={() => {
                        resume.current = null;
                        input.current?.click();
                      }}
                    >
                      <Upload size={17} aria-hidden="true" />
                      영상 업로드
                    </Button>
                  </div>
                </div>
                {jobsView && <QueuePanel jobs={jobs} onChanged={refresh} />}
                {!jobsView && (
                  <StorageUploads
                    uploads={uploads}
                    sessions={pendingSessions}
                    online={online}
                    busy={busy}
                    onPause={(key) => queue.pause(key)}
                    onResume={(key) => queue.resume(key)}
                    onRemove={(key) => queue.remove(key)}
                    onRegister={(id) =>
                      void action(id, () =>
                        request(`/video-uploads/${id}/complete`, { method: 'POST' }),
                      )
                    }
                    onChooseResume={(id) => chooseResume(id)}
                    onDeleteSession={(session) =>
                      setConfirm({
                        title: `${session.filename} 업로드를 삭제할까요?`,
                        action: async () => {
                          await request(`/video-uploads/${session.upload_id}`, {
                            method: 'DELETE',
                          });
                        },
                      })
                    }
                  />
                )}
                <div className="workspace-search">
                  <TextField
                    label={jobsView ? '작업 검색' : '영상 검색'}
                    type="search"
                    placeholder="파일 이름으로 검색"
                    prefix={<Search size={18} aria-hidden="true" />}
                    value={query}
                    onValueChange={setQuery}
                    clearable
                  />
                </div>
                {jobsView ? (
                  jobRows(
                    jobs.filter((j) =>
                      j.original_filename.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
                    ),
                  )
                ) : (
                  <div className="asset-list storage-library">
                    {shownVideos.map((v) => (
                      <StorageAssetRow
                        key={v.asset_id}
                        video={v}
                        thumbnail={<Thumbnail assetId={v.asset_id} />}
                      />
                    ))}
                    {!shownVideos.length && online && (
                      <EmptyState
                        className="storage-empty"
                        illustration={<FolderOpen size={32} aria-hidden="true" />}
                        heading={query ? '검색 결과가 없습니다.' : '등록된 원본 영상이 없습니다.'}
                        description={
                          query
                            ? '다른 파일 이름으로 검색하거나 검색어를 지워주세요.'
                            : '영상 업로드로 원본을 보관하고 작업을 시작하세요.'
                        }
                      />
                    )}
                  </div>
                )}
              </>
            )}
          </main>
        )}
        {workflow && detail && (
          <WorkflowDialog
            detail={detail}
            onClose={() => setWorkflow(false)}
            onCreated={(job) => {
              setWorkflow(false);
              location.hash = `/jobs/${job.job_id}`;
              void refresh();
            }}
          />
        )}
        {faceswap && detail && (
          <FaceSwapDialog
            detail={detail}
            onClose={() => setFaceswap(false)}
            onCreated={(job) => {
              setFaceswap(false);
              location.hash = `/jobs/${job.job_id}`;
              void refresh();
            }}
          />
        )}
        {review && (
          <SubtitleEditor
            job={review}
            onClose={() => setReview(null)}
            onRendered={() => void refresh()}
          />
        )}
        {confirm && (
          <Confirm
            title={confirm.title}
            error={error}
            busy={!!busy}
            onClose={() => setConfirm(null)}
            onConfirm={() => void action('delete', confirm.action)}
          />
        )}
      </div>
    </Theme>
  );
};
const Thumbnail = ({ assetId }: { assetId: string }) => {
  const [failed, setFailed] = useState(false);
  return (
    <div className="asset-thumbnail">
      {failed ? (
        <FileVideo size={24} aria-label="미리보기 없음" />
      ) : (
        <img
          src={`${base}/videos/${assetId}/thumbnail`}
          width={480}
          height={270}
          alt=""
          loading="lazy"
          decoding="async"
          onError={() => setFailed(true)}
        />
      )}
    </div>
  );
};
const Confirm = ({
  title,
  error,
  busy,
  onClose,
  onConfirm,
}: {
  title: string;
  error: string;
  busy: boolean;
  onClose: () => void;
  onConfirm: () => void;
}) => {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    ref.current?.showModal();
    return () => ref.current?.close();
  }, []);
  return (
    <dialog
      className="confirm-modal storage-confirm"
      aria-labelledby="workspace-confirm-title"
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        if (!busy) {
          onClose();
        }
      }}
    >
      <h2 id="workspace-confirm-title">{title}</h2>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      <div>
        <Button variant="secondary" autoFocus disabled={busy} onClick={onClose}>
          취소
        </Button>
        <Button className="storage-confirm-delete" disabled={busy} onClick={onConfirm}>
          삭제
        </Button>
      </div>
    </dialog>
  );
};
