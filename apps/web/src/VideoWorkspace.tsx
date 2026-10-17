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
import { mediaUrl, Job, request, resumeUpload, uploadRequest } from './api';
import { JobDetail } from './JobDetail';
import { SettingsPage } from './SettingsPage';
import { ModelRegistryPage } from './ModelRegistryPage';
import { ServingPage } from './ServingPage';
import { WorkflowStart } from './WorkflowStart';
import { WorkflowEditor } from './WorkflowEditor';
import { WorkflowTickets } from './WorkflowTickets';
import { failureMessage, isContentBlocked } from './job-failure';
import { StageProgress } from './StageProgress';
import { ExecutionPopover } from './ExecutionPopover';
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
import { WorkspaceChrome } from './WorkspaceChrome';
import { WorkflowCatalog } from './WorkflowCatalog';
import { AgentCatalog } from './AgentCatalog';
import { Button } from './hangyeol/primitives/button';
import { EmptyState } from './hangyeol/components/empty-state';
import { StorageAssetRow, StorageVideoInfo } from './StorageVideo';
import { StorageUploads } from './StorageUploads';
import { executionRequest } from './execution-request';
import './video-workspace.css';
import './workspace-polish.css';
import './workspace-shell.css';
import './storage.css';
import './feature-renewal.css';
export const VideoWorkspace = () => {
  const [agentLabel, setAgentLabel] = useState('');
  const agentIdentity = location.hash.startsWith('#/agents/')
    ? decodeURIComponent(location.hash.slice('#/agents/'.length))
    : undefined;
  const [route, setRoute] = useState(location.hash || '#/jobs'),
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
  const startView = route === '#/start';
  const productTicketsView = route === '#/work-tickets' || route === '#/recovery-tickets';
  const servingView = route === '#/serving' || route.startsWith('#/serving/');
  const modelIdentity = route.match(/^#\/serving\/([a-f0-9]{32})/)?.[1];
  const workflowIdentity = route.match(/^#\/workflows\/([a-f0-9]{32})/)?.[1];
  const editorView = route === '#/workflows/new' || !!workflowIdentity;
  const catalogView = route === '#/workflows' || route === '#/workflow-editor';
  const graphTicketsView = route === '#/graph-tickets';
  const decisionTicketsView = route === '#/decision-tickets';
  const reviewTicketsView = route === '#/review-tickets';
  const workflowTicketsView =
    productTicketsView ||
    route === '#/workflow-tickets' ||
    graphTicketsView ||
    reviewTicketsView ||
    decisionTicketsView;
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
      <div className="ui02-list">
        {items.map((job) => (
          <article key={job.job_id} className="ui02-list-item">
            <div className="ui02-list-copy">
              <a className="ui02-list-title" href={`#/jobs/${job.job_id}`}>
                {job.original_filename}
              </a>
              <p className="ui02-list-meta">
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
            <div className="row-actions ui02-list-actions">
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
                      executionRequest(
                        `/jobs/${job.job_id}/${job.status === 'READY' ? 'start' : 'retry'}`,
                      ),
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
            </div>
            <div className="ui02-list-extra">
              <StageProgress job={job} />
            </div>
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
      const next = (location.hash || '#/jobs').replace(
        /^(#\/workflows\/[a-f0-9]{32})\/edit$/,
        '$1',
      );
      if (next !== location.hash) {
        window.history.replaceState(null, '', next);
      }
      setRoute(next);
      setWorkflow(false);
      setFaceswap(false);
      setDetail(null);
      setSubtitleInputs([]);
      setQuery('');
      window.scrollTo(0, 0);
    };
    navigate();
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
      <div className="video-workspace renewed-workspace ui02-workspace">
        <WorkspaceChrome
          route={route}
          agentLabel={agentLabel}
          query={query}
          onQuery={setQuery}
          onUpload={() => {
            resume.current = null;
            input.current?.click();
          }}
          uploadCount={uploads.length + pendingSessions.length}
          uploadContent={
            <StorageUploads
              uploads={uploads}
              sessions={pendingSessions}
              online={online}
              busy={busy}
              onPause={(key) => queue.pause(key)}
              onResume={(key) => queue.resume(key)}
              onRemove={(key) => queue.remove(key)}
              onRegister={(id) =>
                void action(id, () => request(`/video-uploads/${id}/complete`, { method: 'POST' }))
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
          }
        />
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
        {startView ? (
          <WorkflowStart />
        ) : workflowTicketsView ? (
          <WorkflowTickets
            work={productTicketsView}
            recovery={route === '#/recovery-tickets'}
            key={
              productTicketsView
                ? route === '#/recovery-tickets'
                  ? 'recovery'
                  : 'work'
                : decisionTicketsView
                  ? 'decision'
                  : reviewTicketsView
                    ? 'review'
                    : graphTicketsView
                      ? 'graph'
                      : 'sequential'
            }
            decision={decisionTicketsView}
            graph={graphTicketsView || reviewTicketsView}
            review={reviewTicketsView}
          />
        ) : route === '#/agents' || route.startsWith('#/agents/') ? (
          <AgentCatalog
            key={route}
            query={query}
            identity={agentIdentity}
            onLabel={setAgentLabel}
          />
        ) : catalogView ? (
          <WorkflowCatalog query={query} />
        ) : editorView ? (
          <WorkflowEditor key={route} initialId={workflowIdentity} />
        ) : servingView ? (
          route === '#/serving/roles' ? (
            <ServingPage />
          ) : (
            <ModelRegistryPage
              key={route}
              form={route === '#/serving/new' || route.endsWith('/edit')}
              identity={modelIdentity}
              query={query}
            />
          )
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
                      <div>
                        <h1>{detail.video.original_filename}</h1>
                      </div>
                    </div>
                    <StorageVideoInfo video={detail.video} assetId={assetId} />
                  </>
                ) : (
                  <p role="status">영상 불러오는 중</p>
                )}
              </>
            ) : (
              <>
                <div className="workspace-page-heading">
                  <div>
                    <h1>{jobsView ? '작업' : '원본'}</h1>
                  </div>
                </div>
                {jobsView && <ExecutionPopover jobs={jobs} onChanged={refresh} />}

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
          src={mediaUrl(`/videos/${assetId}/thumbnail`)}
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
