import type { Job } from './api';
import type { VideoUpload, VideoAsset, SubtitleInput } from './video-api';
import type { RegisteredModel } from './registered-models';
import {
  mockCatalog,
  mockId,
  seedDefinitions,
  seedModels,
  seedVideos,
  seedJobs,
  seedUploads,
  seedSubtitleInputs,
  seedLlm,
  seedServing,
  cueTracks,
  providers,
  sttModels,
  type MockDefinition,
} from './mock-data';

// This module is dynamically imported only in DEV publishing mode. No fetch,
// provider SDK, credential store, DB or worker connection belongs in this module.
type Document = Record<string, any>;
type State = {
  videos: VideoAsset[];
  jobs: Job[];
  uploads: VideoUpload[];
  definitions: MockDefinition[];
  models: RegisteredModel[];
  subtitles: Record<string, SubtitleInput[]>;
  drafts: Record<string, Document>;
  llm: Document;
  serving: Document;
  queue: Document;
  tickets: Record<string, Document[]>;
  history: Record<string, MockDefinition[]>;
  sessions: Record<string, Document>;
  faceJobs: Record<string, Document[]>;
  cleanedTemporary?: string[];
};
const storageKey = 'mideagent-publishing-fixtures-v1';
const clone = <T>(value: T): T => structuredClone(value);
const uid = () =>
  [...crypto.getRandomValues(new Uint8Array(16))]
    .map((n) => n.toString(16).padStart(2, '0'))
    .join('');
const stamp = () => new Date().toISOString();
const initial = (): State => {
  const definitions = seedDefinitions();
  const jobs = seedJobs();
  return {
    videos: seedVideos(),
    jobs,
    definitions,
    models: seedModels(),
    uploads: seedUploads(),
    subtitles: seedSubtitleInputs(),
    drafts: {},
    llm: seedLlm(),
    serving: seedServing(),
    queue: {
      revision: 1,
      paused: true,
      order: jobs.filter((j) => j.status === 'QUEUED').map((j) => j.job_id),
    },
    tickets: {},
    history: Object.fromEntries(definitions.map((d) => [d.id, [clone(d)]])),
    sessions: {},
    faceJobs: {},
  };
};
const restore = (): State => {
  try {
    const raw = sessionStorage.getItem(storageKey);
    if (raw) {
      const value = JSON.parse(raw);
      if (
        Array.isArray(value.videos) &&
        Array.isArray(value.definitions) &&
        value.history &&
        value.tickets
      )
        return value;
    }
  } catch {
    /* Storage can be unavailable in private browsing. Keep memory usable. */
  }
  return initial();
};
let state = restore();
const persist = () => {
  try {
    sessionStorage.setItem(storageKey, JSON.stringify(state));
  } catch {
    /* in-memory preview still works */
  }
};
export const resetMock = () => {
  state = initial();
  persist();
  location.reload();
};
const ensure = <T>(value: T | undefined, name: string): T => {
  if (!value) throw new Error(`목업 ${name}을 찾을 수 없습니다.`);
  return value;
};
const requireRevision = (body: Document, current: Document) => {
  if (body.revision !== undefined && body.revision !== current.revision)
    throw new Error('목업 편집본이 바뀌었습니다. 새로 불러온 뒤 저장해 주세요.');
};
const draftFor = (id: string) =>
  (state.drafts[id] ||= {
    revision: 1,
    duration: 12,
    languages: { original: 'en', translated: 'ko' },
    tracks: clone(cueTracks),
  });
const modelBindings = (definition: MockDefinition) =>
  Object.fromEntries(
    definition.nodes
      .filter((n) => n.model_ref)
      .flatMap((n) => {
        const row = state.models.find((m) => m.id === n.model_ref?.model_id);
        const version = row?.versions[String(n.model_ref?.revision)];
        return version ? [[n.id, version]] : [];
      }),
  );
const planFor = (definition: MockDefinition) => ({
  token: '0'.repeat(64),
  paid_roles: [],
  notice: '목업 계획 · 실제 실행/과금 없음',
  settings: {},
  ready: true,
  model_bindings: modelBindings(definition),
  eligible_steps: definition.nodes.map((n) => n.id),
  steps: definition.nodes.map((n) => ({ ...n, selected: true })),
});
const reviewDoc = () => ({
  kind: 'transcript',
  editable: true,
  read_only_reason: '',
  source: { kind: 'mock', filename: '샘플 전사문' },
  revision: 1,
  state_revision: 1,
  sha256: '0'.repeat(64),
  document_sha256: '0'.repeat(64),
  target: 'mock-review',
  cues: clone(cueTracks.translated),
  status: 'waiting',
  request_changes_reason: '',
  approval: null,
});
const ticketFor = (body: Document, status = 'held'): Document => {
  const definition = ensure(
    state.definitions.find((d) => d.id === body.definition_id) || state.definitions[0],
    '워크플로우',
  );
  const asset = ensure(
    state.videos.find((v) => v.asset_id === body.asset_id) || state.videos[0],
    '원본',
  );
  return {
    id: uid(),
    revision: 1,
    control_revision: 0,
    status,
    created_at: stamp(),
    asset: clone(asset),
    definition: clone(definition),
    options: {
      source_language: 'auto',
      target_language: 'ko',
      video_description: '',
      ...body.options,
    },
    steps: definition.nodes.map((n, i) => ({
      id: n.id,
      type: n.type,
      status:
        status === 'completed'
          ? 'succeeded'
          : status === 'awaiting_review' && i === 0
            ? 'succeeded'
            : 'pending',
      artifacts: {},
      partial_artifacts: {},
    })),
    confirmation: null,
    settings_snapshot: {},
    phase: 0,
    reviews: {},
    decisions: {},
    model_bindings: modelBindings(definition),
    model_availability: {},
  };
};
const ticketsFor = (namespace: string) =>
  (state.tickets[namespace] ||= [
    ticketFor(
      { definition_id: state.definitions[0]?.id, asset_id: state.videos[0]?.asset_id },
      'confirmed',
    ),
    ticketFor(
      { definition_id: state.definitions[2]?.id, asset_id: state.videos[2]?.asset_id },
      'awaiting_review',
    ),
  ].map((t, i) => ({
    ...t,
    id: mockId(namespace.split('').reduce((n, c) => n + c.charCodeAt(0), 700) + i),
    ...(i === 1
      ? {
          reviews: { review: reviewDoc() },
          phase: 1,
          decisions: {
            decision: {
              status: 'succeeded',
              selected_port: 'a',
              judgment: {
                version: 1,
                label: 'review',
                confidence: 0.82,
                reason: '목업 판단 근거 · 사람이 확인할 자료가 있어요.',
              },
              adapter: { id: 'mock-decision', revision: 'sample', schema_version: 1, paid: false },
              input: { kind: 'mock_metadata' },
            },
          },
        }
      : {}),
  })));
const newJob = (asset: VideoAsset, body: Document): Job => ({
  ...clone(seedJobs()[0]),
  job_id: uid(),
  status: 'READY',
  original_filename: asset.original_filename,
  expected_size: asset.size_bytes,
  uploaded_bytes: asset.size_bytes,
  created_at: stamp(),
  completed_at: null,
  error: null,
  metadata: {
    asset_id: asset.asset_id,
    duration: 12,
    workflow: {
      template: body.template || 'full',
      stages: [
        'analyze',
        'extract_audio',
        'transcribe',
        'translate',
        'generate_subtitle',
        'encode',
      ],
    },
    result_files: [],
  },
  ...body.options,
});
const storageSnapshot = () => {
  const jobs = state.jobs
    .map((j) => ({
      job_id: j.job_id,
      filename: j.original_filename,
      status: j.status,
      input: j.expected_size,
      work: j.expected_size / 2,
      output: j.status === 'COMPLETED' ? j.expected_size : 0,
      total_bytes: j.expected_size * 1.5 + (j.status === 'COMPLETED' ? j.expected_size : 0),
      temporary_bytes: j.expected_size / 2,
      deletable: ['COMPLETED', 'FAILED', 'CANCELLED'].includes(j.status),
    }))
    .map((j) =>
      state.cleanedTemporary?.includes(j.job_id)
        ? { ...j, work: 0, temporary_bytes: 0, total_bytes: j.total_bytes - j.work }
        : j,
    );
  const categories = {
    library: state.videos.reduce((s, v) => s + v.size_bytes, 0),
    input: jobs.reduce((s, j) => s + j.input, 0),
    work: jobs.reduce((s, j) => s + j.work, 0),
    output: jobs.reduce((s, j) => s + j.output, 0),
    uploads: state.uploads.reduce((s, u) => s + u.uploaded_bytes, 0),
    faceswap: 0,
    other: 2048,
  };
  return {
    checked_at: Date.now() / 1000,
    disk: {
      total_bytes: 512 * 1024 ** 3,
      used_bytes: 180 * 1024 ** 3,
      free_bytes: 332 * 1024 ** 3,
    },
    host_disk: null,
    container: false,
    total_bytes: Object.values(categories).reduce((s, n) => s + n, 0),
    quota_bytes: 100 * 1024 ** 3,
    categories,
    jobs,
  };
};
const faceOptions = () => ({
  reference_frame: 1,
  face_position: 0,
  source_position: 0,
  distance: 0.6,
  preset: 'balanced',
  video_codec: 'h264',
  mask_types: ['box'],
  mask_blur: 0.3,
  mask_padding: [0, 0, 0, 0],
  mask_areas: ['upper-face', 'lower-face'],
  mask_regions: ['skin'],
  detector_angles: [0],
});

export const mockRequest = async <T>(path: string, init: RequestInit = {}): Promise<T> => {
  init.signal?.throwIfAborted();
  const url = new URL(path, 'https://mock.invalid');
  if (url.origin !== 'https://mock.invalid')
    throw new Error('목업에서 외부 URL은 호출하지 않습니다.');
  const route = url.pathname.replace(/^\/api/, '').replace(/\/$/, '') || '/';
  const method = (init.method || 'GET').toUpperCase();
  const body: Document = typeof init.body === 'string' ? JSON.parse(init.body || '{}') : {};
  const parts = route.split('/').filter(Boolean);
  let value: unknown;
  const change = method !== 'GET';

  if (route === '/videos') value = { videos: state.videos };
  else if (route === '/jobs') value = { jobs: state.jobs };
  else if (route === '/video-uploads') {
    if (method === 'POST') {
      const upload = {
        upload_id: uid(),
        filename: body.filename || '샘플 업로드.mp4',
        expected_size: body.size || 0,
        uploaded_bytes: body.size || 0,
        status: 'UPLOADED',
        created_at: stamp(),
      };
      state.uploads.unshift(upload);
      value = upload;
    } else value = { uploads: state.uploads };
  } else if (parts[0] === 'video-uploads' || parts[0] === 'uploads') {
    const upload = ensure(
      state.uploads.find((u) => u.upload_id === parts[1]),
      '업로드',
    );
    if (method === 'DELETE') {
      state.uploads = state.uploads.filter((u) => u !== upload);
      value = {};
    } else if (parts[2] === 'complete') {
      if (!upload.asset_id) {
        const asset = {
          ...clone(seedVideos()[0]),
          asset_id: uid(),
          original_filename: upload.filename,
          size_bytes: upload.expected_size,
          created_at: stamp(),
          provenance: { kind: 'upload' },
        };
        state.videos.unshift(asset);
        state.subtitles[asset.asset_id] = [];
        upload.asset_id = asset.asset_id;
      }
      upload.status = 'COMPLETED';
      upload.uploaded_bytes = upload.expected_size;
      value = upload;
    } else value = { ...upload, uploaded_bytes: upload.expected_size, resumable: false };
  } else if (parts[0] === 'videos' && parts[1]) {
    const asset = ensure(
      state.videos.find((v) => v.asset_id === parts[1]),
      '원본',
    );
    if (parts[2] === 'subtitles' || parts[2] === 'subtitle-inputs') {
      const subtitles = (state.subtitles[asset.asset_id] ||= []);
      if (method === 'POST') {
        const subtitle = {
          artifact_id: uid(),
          filename: body.filename || '샘플 가져온 자막.srt',
          language: body.language || 'ko',
          cue_count: 4,
          created_at: stamp(),
          provenance: { kind: 'external' },
        };
        subtitles.unshift(subtitle);
        value = subtitle;
      } else value = { subtitles };
    } else if (parts[2] === 'audio-inputs')
      value = {
        audio_inputs: state.jobs
          .filter((j) => j.metadata.asset_id === asset.asset_id)
          .map((j) => ({ job_id: j.job_id, created_at: j.created_at, size_bytes: 384000 })),
      };
    else if (parts[2] === 'workflow-plan') {
      const stages =
        body.template === 'extract_audio'
          ? ['analyze', 'extract_audio']
          : body.template === 'encode'
            ? ['encode', 'validate_video']
            : [
                'analyze',
                'extract_audio',
                'preprocess_audio',
                'transcribe',
                'translate',
                'generate_subtitle',
                'encode',
                'validate_video',
              ];
      value = { stages, reused: [], paid_stages: [] };
    } else if (parts[2] === 'workflows' || parts[2] === 'jobs') {
      const job = newJob(asset, body);
      state.jobs.unshift(job);
      value = job;
    } else if (parts[2] === 'faceswap-sessions') {
      if (method === 'POST') {
        const session = {
          session_id: uid(),
          asset_id: asset.asset_id,
          revision: 1,
          settings: faceOptions(),
          source_file: 'sample-face.svg',
          source_sha256: '0'.repeat(64),
        };
        state.sessions[session.session_id] = session;
        value = session;
      } else
        value = {
          sessions: Object.values(state.sessions).filter((s) => s.asset_id === asset.asset_id),
        };
    } else if (method === 'DELETE') {
      state.videos = state.videos.filter((v) => v !== asset);
      delete state.subtitles[asset.asset_id];
      value = {};
    } else
      value = {
        video: asset,
        jobs: state.jobs.filter((j) => j.metadata.asset_id === asset.asset_id),
      };
  } else if (parts[0] === 'jobs' && parts[1]) {
    const job = ensure(
      state.jobs.find((j) => j.job_id === parts[1]),
      '작업',
    );
    if (parts[2] === 'preview') {
      const draft = draftFor(job.job_id);
      value = {
        video_available: job.status === 'COMPLETED',
        expired: false,
        tracks: {
          original: {
            available: true,
            partial: job.status !== 'COMPLETED',
            cues: draft.tracks.original,
          },
          translated: {
            available: true,
            partial: job.status !== 'COMPLETED',
            cues: draft.tracks.translated,
          },
        },
      };
    } else if (parts[2] === 'subtitles') {
      const draft = draftFor(job.job_id);
      if (method === 'PUT') {
        requireRevision(body, draft);
        draft.tracks = clone(body.tracks);
        draft.revision++;
        job.metadata.subtitle_revision = draft.revision;
        if (body.action === 'render') job.status = 'QUEUED';
      }
      value = draft;
    } else if (parts[2] === 'cancel') {
      job.status = 'CANCELLED';
      job.metadata.cancel_requested = false;
      value = job;
    } else if (parts[2] === 'retry' || parts[2] === 'start') {
      job.status = 'QUEUED';
      job.error = null;
      job.metadata.failed_stage = undefined;
      state.queue.order.push(job.job_id);
      value = job;
    } else if (parts[2] === 'promote-video' || parts[2] === 'register-source') {
      const asset = {
        ...clone(seedVideos()[0]),
        asset_id: uid(),
        original_filename: job.original_filename.replace('.mp4', '_결과.mp4'),
        created_at: stamp(),
        provenance: { kind: 'result', job_id: job.job_id, parent_asset_id: job.metadata.asset_id },
      };
      state.videos.unshift(asset);
      value = asset;
    } else if (method === 'DELETE') {
      state.jobs = state.jobs.filter((j) => j !== job);
      value = {};
    } else value = job;
  } else if (route === '/queue') {
    if (method === 'PATCH') {
      requireRevision(body, state.queue);
      if (body.order) state.queue.order = body.order;
      if (typeof body.paused === 'boolean') state.queue.paused = body.paused;
      state.queue.revision++;
    }
    const ids = state.jobs.filter((j) => j.status === 'QUEUED').map((j) => j.job_id);
    const order = [
      ...new Set([...state.queue.order.filter((id: string) => ids.includes(id)), ...ids]),
    ];
    value = { ...state.queue, order, jobs: order };
  } else if (route === '/queue/cancel-pending') {
    for (const job of state.jobs)
      if (body.job_ids?.includes(job.job_id) && job.status === 'QUEUED') job.status = 'CANCELLED';
    state.queue.revision++;
    value = {};
  } else if (route === '/settings/node-catalog') value = mockCatalog;
  else if (route === '/settings/node-validation')
    value = { valid: true, notice: '목업 표시 · 실제 유형/엔진 검사 아님' };
  else if (route === '/settings/registered-models/compatibility')
    value = {
      uses: /transcri|audio|whisper/.test(body.model || '')
        ? ['transcription']
        : ['translation', 'decision'],
      reason: '목업 호환 용도',
    };
  else if (parts[0] === 'settings' && parts[1] === 'registered-models') {
    if (!parts[2]) value = { models: state.models, providers };
    else {
      let row = state.models.find((m) => m.id === parts[2]);
      if (parts[3] === 'availability') {
        row = ensure(row, '모델');
        requireRevision(body, row);
        row.active = body.active;
        row.state_revision++;
        row.revision++;
        value = row;
      } else if (method === 'PUT') {
        if (row) requireRevision(body, row);
        const revision = (row?.current_revision || 0) + 1;
        const version = {
          model_id: parts[2],
          revision,
          name: body.name,
          provider: body.provider,
          model: body.model,
          uses: body.uses,
          sha256: '0'.repeat(64),
        };
        if (row) {
          row.revision++;
          row.current_revision = revision;
          row.versions[String(revision)] = version;
        } else {
          row = {
            id: parts[2],
            revision: 1,
            current_revision: revision,
            state_revision: 1,
            active: true,
            connection: '목업 · 실제 연결 미확인',
            versions: { [String(revision)]: version },
          };
          state.models.push(row);
        }
        value = row;
      } else value = ensure(row, '모델');
    }
  } else if (route === '/settings/workflow-definitions/validate')
    value = {
      valid: body.nodes?.length > 0,
      issues: body.nodes?.length
        ? []
        : [{ node_id: null, edge_id: null, message: '에이전트를 추가해 주세요.' }],
      notice: '목업 구성 확인 · 실제 서버 검증 아님',
    };
  else if (parts[0] === 'settings' && parts[1] === 'workflow-definitions') {
    const identity = parts[2];
    if (!identity)
      value = {
        definitions: state.definitions.map(({ id, name, revision }) => ({ id, name, revision })),
      };
    else {
      const current = state.definitions.find((d) => d.id === identity);
      if (parts[3] === 'versions')
        value = {
          versions: (state.history[identity] || []).map((d) => ({
            revision: d.revision,
            sha256: '0'.repeat(64),
            source: { kind: 'mock' },
          })),
        };
      else if (parts[3] === 'restore') {
        const doc = ensure(current, '워크플로우');
        requireRevision(body, doc);
        const prior =
          body.source?.kind === 'definition_revision'
            ? state.history[identity]?.find((d) => d.revision === body.source.revision)
            : doc;
        const next = { ...clone(ensure(prior, '이력')), revision: doc.revision + 1 };
        state.definitions = state.definitions.map((d) => (d.id === identity ? next : d));
        (state.history[identity] ||= []).push(clone(next));
        value = next;
      } else if (method === 'PUT') {
        if (current) requireRevision(body, current);
        const next = {
          ...body,
          id: identity,
          revision: (current?.revision || 0) + 1,
        } as MockDefinition;
        state.definitions = [...state.definitions.filter((d) => d.id !== identity), next];
        (state.history[identity] ||= []).push(clone(next));
        value = next;
      } else value = ensure(current, '워크플로우');
    }
  } else if (route === '/settings/llm/stt-models') value = { providers: sttModels };
  else if (route === '/settings/llm/models')
    value = {
      models: ['sample-text-model', 'sample-decision-model', 'sample-transcription-model'],
    };
  else if (route === '/settings/llm') {
    if (method === 'PUT') {
      requireRevision(body, state.llm);
      // Discard secret fields entirely. The preview never stores entered keys.
      const { credential_updates: _discardedKeys, api_key: _discardedKey, ...ordinary } = body;
      state.llm = {
        ...state.llm,
        ...ordinary,
        revision: state.llm.revision + 1,
        credentials: seedLlm().credentials,
        has_api_key: false,
        key_source: 'none',
      };
    }
    value = state.llm;
  } else if (route === '/settings/serving') {
    if (method === 'PUT') {
      requireRevision(body, state.serving);
      for (const role of ['transcription', 'translation'])
        state.serving.workers[role] = { ...state.serving.workers[role], ...body.workers?.[role] };
      state.serving.revision++;
      state.serving.fallback_on_error = !!body.fallback_on_error;
      state.serving.fallback_on_block = !!body.fallback_on_block;
    }
    value = state.serving;
  } else if (route === '/settings/storage') value = storageSnapshot();
  else if (route === '/settings/storage/cleanup') {
    const selected = storageSnapshot().jobs.filter(
      (j) => j.deletable && body.job_ids?.includes(j.job_id),
    );
    if (body.mode === 'jobs')
      state.jobs = state.jobs.filter((j) => !selected.some((s) => s.job_id === j.job_id));
    else
      state.cleanedTemporary = [
        ...new Set([...(state.cleanedTemporary || []), ...selected.map((j) => j.job_id)]),
      ];
    value = {
      removed_bytes: selected.reduce(
        (s, j) => s + (body.mode === 'jobs' ? j.total_bytes : j.temporary_bytes),
        0,
      ),
      results: selected.map((j) => ({ job_id: j.job_id, status: 'cleaned' })),
    };
  } else if (route === '/settings/work-entry/inspect') {
    const definition = ensure(
      state.definitions.find((d) => d.id === body.definition_id),
      '워크플로우',
    );
    value = {
      supported: !definition.nodes.some((n) => n.type.startsWith('control_')),
      contract: 'mock',
      definition_id: definition.id,
      definition_revision: definition.revision,
      model_ready: true,
      runtime_connected: false,
      reasons: definition.nodes.some((n) => n.type.startsWith('control_'))
        ? [{ node_id: null, message: '제어 노드 실행 미지원' }]
        : [],
      summary: definition.nodes.map((n) => ({
        ...n,
        inputs: mockCatalog.nodes.find((s) => s.id === n.type)?.inputs || {},
        model: modelBindings(definition)[n.id],
      })),
    };
  } else if (route === '/settings/work-entry/preview')
    value = planFor(
      ensure(
        state.definitions.find((d) => d.id === body.definition_id),
        '워크플로우',
      ),
    );
  else if (route === '/settings/work-entry/create') {
    const namespace = body.recovery_enabled ? 'recovery-tickets' : 'work-tickets';
    const ticket = ticketFor(body);
    ticketsFor(namespace).unshift(ticket);
    const asset = ensure(
      state.videos.find((v) => v.asset_id === body.asset_id),
      '원본',
    );
    state.jobs.unshift({ ...newJob(asset, body), job_id: ticket.id });
    value = ticket;
  } else if (
    parts[0] === 'settings' &&
    /^(workflow|graph|review|decision|work|recovery)-tickets$/.test(parts[1])
  ) {
    const namespace = parts[1],
      list = ticketsFor(namespace),
      identity = parts[2],
      operation = parts[3];
    if (identity === 'runtime')
      value = { connected: false, mode: 'mock', notice: '목업 · 실제 실행 자원 미연결' };
    else if (identity === 'capability')
      value = { supported: true, reasons: [], notice: '목업 표시 · 실제 실행 검증 아님' };
    else if (!identity) {
      if (method === 'POST') {
        const ticket = ticketFor(body);
        list.unshift(ticket);
        value = ticket;
      } else value = { tickets: list };
    } else {
      const ticket = ensure(
        list.find((t) => t.id === identity),
        '작업',
      );
      if (operation === 'plan') value = planFor(ticket.definition);
      else if (operation === 'reviews') {
        const node = parts[4];
        const document = (ticket.reviews[node] ||= reviewDoc());
        if (method === 'PUT') {
          requireRevision(body, document);
          document.cues = clone(body.cues);
          document.revision++;
          document.state_revision++;
        } else if (parts[5] === 'decision') {
          document.status = body.action === 'approve' ? 'approved' : 'changes_requested';
          document.request_changes_reason = body.reason || '';
          document.state_revision++;
          if (document.status === 'approved')
            document.approval = {
              revision: document.revision,
              sha256: document.sha256,
              input_sha256: '0'.repeat(64),
            };
        }
        value = document;
      } else if (operation === 'confirm') {
        requireRevision(body, ticket);
        ticket.status = ticket.phase ? 'continuation_confirmed' : 'confirmed';
        ticket.confirmation = { token: body.token };
        ticket.revision++;
        value = ticket;
      } else if (operation === 'start' || operation === 'continue') {
        ticket.status = 'completed';
        ticket.steps.forEach((s: Document) => {
          s.status = 'succeeded';
        });
        ticket.revision++;
        const job = state.jobs.find((j) => j.job_id === ticket.id);
        if (job) {
          job.status = 'COMPLETED';
          job.completed_at = stamp();
          job.metadata.result_files = ['final.mp4', 'original.srt', 'translated.srt'];
        }
        value = ticket;
      } else if (operation === 'cancel') {
        ticket.status = 'cancelled';
        ticket.control_revision++;
        ticket.revision++;
        value = ticket;
      } else if (operation === 'recover') {
        const child = ticketFor({
          definition_id: ticket.definition.id,
          asset_id: ticket.asset.asset_id,
          options: ticket.options,
        });
        child.recovery_parent = { ticket_id: ticket.id, attempt_id: 'mock' };
        child.reuse_origins = {};
        list.unshift(child);
        value = child;
      } else value = ticket;
    }
  } else if (route === '/execution-approvals/plan')
    value = {
      token: '0'.repeat(64),
      input_sha256: '0'.repeat(64),
      cost: { state: 'no_external_call', amount: null, notice: '목업 · 실제 요청·실행·과금 없음' },
      risk_required: false,
    };
  else if (route === '/execution-approvals/confirm') {
    const now = Date.now() / 1000;
    value = {
      id: uid(),
      state: 'confirmed',
      confirmed_at: now,
      expires_at: now + 900,
      server_time: now,
      cost: { state: 'no_external_call', amount: null, notice: '목업 확인' },
    };
  } else if (route === '/faceswap/capabilities')
    value = {
      ready: true,
      reason: '목업 · FaceFusion/GPU 미연결',
      presets: ['fast', 'balanced', 'quality'],
      version: 'mock',
      fingerprint: 'mock',
    };
  else if (parts[0] === 'faceswap' && parts[1] === 'sessions') {
    const session = ensure(state.sessions[parts[2]], '합성 설정');
    if (parts[3] === 'source') {
      session.source_file = '목업 이미지';
      session.source_sha256 = '0'.repeat(64);
      session.revision++;
      value = session;
    } else if (parts[3] === 'requests') {
      const jobs = (state.faceJobs[session.session_id] ||= []);
      if (method === 'POST') {
        const asset = ensure(
          state.videos.find((v) => v.asset_id === session.asset_id),
          '원본',
        );
        const job = {
          ...newJob(asset, { template: 'faceswap' }),
          status: 'COMPLETED',
          completed_at: stamp(),
          metadata: {
            asset_id: asset.asset_id,
            duration: 12,
            workflow: { template: 'faceswap', stages: ['faceswap', 'encode', 'validate_video'] },
            faceswap: { ...clone(session), fingerprint: 'mock' },
            faceswap_operation: body.operation,
            preview_resolution: body.preview_resolution,
            faceswap_result: {
              faces: [{ position: 0, bbox: [100, 60, 200, 180], file: 'sample-face.svg' }],
              frame_number: body.preview_frame || body.analysis_frame || 1,
              matched_faces: 1,
              frame_count: 144,
              fps: 12,
            },
            result_files: body.operation === 'render' ? ['final.mp4'] : [],
          },
        };
        jobs.unshift(job);
        if (body.operation === 'render') state.jobs.unshift(job);
        value = job;
      } else value = { jobs };
    } else if (method === 'PUT') {
      requireRevision(body, session);
      session.settings = body.settings;
      session.revision++;
      value = session;
    } else if (method === 'DELETE') {
      delete state.sessions[session.session_id];
      value = {};
    } else value = session;
  } else if (route === '/auth/session') value = { enabled: false, user: null };
  else throw new Error(`목업에 연결되지 않은 화면 동작: ${method} ${route}`);

  init.signal?.throwIfAborted();
  if (change) persist();
  return clone(value) as T;
};
