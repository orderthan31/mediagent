import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, FileVideo, FolderOpen, Plus, Search, Trash2, Upload, X } from 'lucide-react';
import { mediaUrl, Job, request, resumeUpload, uploadRequest } from './api';
import { PageTitle } from './PageTitle';
import { Pagination, usePagination } from './Pagination';
import { frontendOnly, renewalBackend } from './preview';
import { ticketNumber, workflowName } from './job-identity';
import { AccountPage } from './AccountPage';
import { PublishingAuth } from './PublishingAuth';
import { JobDetail } from './JobDetail';
import { RenewalJobDetail } from './RenewalJobDetail';
import { SettingsPage } from './SettingsPage';
import { ModelRegistryPage } from './ModelRegistryPage';
import { ProviderConnections } from './ProviderConnections';
import { ServingPage } from './ServingPage';
import { WorkflowStart } from './WorkflowStart';
import { WorkflowEditor } from './WorkflowEditor';
import { WorkflowTickets } from './WorkflowTickets';
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
import { LegacyArchivePage } from './LegacyArchivePage';
import { WorkflowCatalog } from './WorkflowCatalog';
import { AgentCatalog } from './AgentCatalog';
import { useWorkspaceAuth } from './AuthGate';
import { isOrdinaryRoute } from './workspace-access';
import { Button } from './hangyeol/primitives/button';
import { EmptyState } from './hangyeol/components/empty-state';
import { StorageAssetRow, StorageVideoInfo } from './StorageVideo';
import { StorageUploads } from './StorageUploads';
import './video-workspace.css';
import './workspace-polish.css';
import './workspace-shell.css';
import './storage.css';
import './feature-renewal.css';
import './workspace-layout.css';
export const VideoWorkspace = () => {
  const auth = useWorkspaceAuth();
  const administrator = frontendOnly || auth?.session.user?.role === 'admin';
  const [runtimeReady, setRuntimeReady] = useState(!renewalBackend);
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
        try {
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
        } catch (error) {
          if (error instanceof TypeError) {
            throw new Error('전송 연결 끊김');
          }
          throw error;
        }
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
  const videoPage = usePagination(shownVideos, route + query);
  const jobPage = usePagination(
    jobs.filter((job) =>
      `${ticketNumber(job)} ${job.original_filename} ${workflowName(job)}`
        .toLocaleLowerCase()
        .includes(query.toLocaleLowerCase()),
    ),
    route + query,
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
  const jobRows = (items: Job[]) => (
    <div className="job-ledger-scroll" role="region" aria-label="작업 목록" tabIndex={0}>
      <table className="job-ledger">
        <colgroup>
          <col className="job-ticket-column" />
          <col />
          <col />
          <col className="job-state-column" />
          <col className="job-created-column" />
        </colgroup>
        <thead>
          <tr>
            <th scope="col">티켓번호</th>
            <th scope="col">원본</th>
            <th scope="col">워크플로우</th>
            <th scope="col">상태</th>
            <th scope="col">생성일</th>
          </tr>
        </thead>
        <tbody>
          {items.map((job) => (
            <tr key={job.job_id}>
              <td>
                <a
                  className="job-ticket-link"
                  href={`#/jobs/${job.job_id}`}
                  title={ticketNumber(job)}
                >
                  {ticketNumber(job)}
                </a>
              </td>
              <td>
                <span title={job.original_filename}>{job.original_filename}</span>
              </td>
              <td>
                <span className="job-workflow" title={workflowName(job)}>
                  {workflowName(job)}
                </span>
              </td>
              <td>
                <span className={'status job-state ' + job.status.toLowerCase()}>
                  {job.status === 'AWAITING_REVIEW'
                    ? '검토 대기'
                    : statusLabels[job.status] || job.status}
                </span>
              </td>
              <td>
                <time className="job-created" dateTime={job.created_at}>
                  {new Date(job.created_at).toLocaleString('ko-KR', {
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                  })}
                </time>
              </td>
            </tr>
          ))}
          {!items.length && (
            <tr>
              <td colSpan={5}>
                <p className="ui02-empty">작업이 없습니다.</p>
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
  useEffect(() => {
    const navigate = () => {
      // Capability discovery below keeps foundation-only API media paths closed.
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
    if (!renewalBackend) {
      return;
    }
    const controller = new AbortController();
    void request<{ features: string[] }>('/capabilities', { signal: controller.signal })
      .then((value) => {
        if (!controller.signal.aborted) {
          setRuntimeReady(value.features.includes('verified_uploads'));
        }
      })
      .catch(() => {
        /* Existing foundation-only boundary remains closed. */
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!runtimeReady) {
      return; // Never activate media paths against a foundation-only API.
    }
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
  }, [queue, runtimeReady]);
  useEffect(() => {
    if (!runtimeReady || !assetId) {
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
  }, [assetId, runtimeReady]);
  if (frontendOnly && (route === '#/setup' || route === '#/login')) {
    return <PublishingAuth key={route} setup={route === '#/setup'} />;
  }
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
        {!administrator && !isOrdinaryRoute(route) ? (
          <main className="serving-page">
            <PageTitle>접근 권한 없음</PageTitle>
            <p role="alert">관리자만 이용할 수 있는 화면입니다.</p>
            <a href="#/jobs">작업으로 돌아가기</a>
          </main>
        ) : renewalBackend && route === '#/settings/legacy' ? (
          <LegacyArchivePage />
        ) : renewalBackend &&
          (!runtimeReady || workflowTicketsView || settingsView || route === '#/serving/roles') &&
          !(route.startsWith('#/account') || (servingView && route !== '#/serving/roles')) ? (
          <main className="serving-page">
            <PageTitle>
              {route.startsWith('#/workflows')
                ? '워크플로우'
                : route.startsWith('#/agents')
                  ? '에이전트'
                  : settingsView
                    ? '시스템'
                    : route === '#/' || assetId
                      ? '원본'
                      : '작업'}
            </PageTitle>
            <p role="status">
              이 화면의 PostgreSQL 연동은 아직 준비 중입니다. 기존 데이터나 실행기는 연결하지
              않았습니다.
            </p>
            {administrator && (
              <>
                <a className="ui02-text-action" href="#/serving">
                  서빙 관리
                </a>
                <br />
                <a className="ui02-text-action" href="#/settings/legacy">
                  이관된 구버전 이력
                </a>
              </>
            )}
          </main>
        ) : (frontendOnly || renewalBackend) && route.startsWith('#/account') ? (
          <AccountPage key={route} create={route === '#/account/new'} />
        ) : startView ? (
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
          (frontendOnly || renewalBackend) && route.startsWith('#/serving/connections') ? (
            <ProviderConnections key={route} route={route} query={query} />
          ) : route === '#/serving/roles' && !frontendOnly ? (
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
          renewalBackend ? (
            <RenewalJobDetail id={jobId} key={jobId} />
          ) : (
            <JobDetail
              id={jobId}
              key={jobId}
              labels={statusLabels}
              promotedAssetId={
                videos.find((v) => v.provenance.kind === 'result' && v.provenance.job_id === jobId)
                  ?.asset_id
              }
            />
          )
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
                    <PageTitle>{detail.video.original_filename}</PageTitle>
                    <StorageVideoInfo video={detail.video} assetId={assetId} />
                  </>
                ) : (
                  <p role="status">영상 불러오는 중</p>
                )}
              </>
            ) : (
              <>
                <PageTitle>{jobsView ? '작업' : '원본'}</PageTitle>

                {jobsView ? (
                  <>
                    {jobRows(jobPage.items)}
                    {hasConfirmedList && (
                      <Pagination {...jobPage} disabled={!online}>
                        {!renewalBackend && <ExecutionPopover jobs={jobs} onChanged={refresh} />}
                      </Pagination>
                    )}
                  </>
                ) : (
                  <>
                    <div className="asset-list storage-library">
                      {videoPage.items.map((v) => (
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
                    {hasConfirmedList && <Pagination {...videoPage} disabled={!online} />}
                  </>
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
