import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import { jsonPost, type VideoAsset } from './video-api';
import { Button } from './hangyeol/primitives/button';
import { Input } from './hangyeol/primitives/input';
import { Badge } from './hangyeol/primitives/badge';
import { ReviewPanel, type ReviewDocument } from './ReviewPanel';
import { DecisionPanel, type DecisionEvidence } from './DecisionPanel';
import type { RegisteredVersion } from './registered-models';
import { RecoveryActions, TicketSnapshotRestore } from './RecoveryActions';
import './serving.css';
import './workflow-tickets.css';

type Definition = {
  id: string;
  revision: number;
  name: string;
  catalog_version: number;
  inputs: Record<string, string>;
  nodes: { id: string; type: string; options: Record<string, string> }[];
  edges: unknown[];
};
type Spec = { id: string; label: string };
type Artifact = {
  type: string;
  path?: string;
  bytes: number;
  sha256: string;
  reference?: { node: string; port: string };
};
type Step = {
  id: string;
  type: string;
  status: string;
  artifacts: Record<string, Artifact>;
  partial_artifacts: Record<string, Artifact>;
  blocked_by?: string[];
  error_type?: string;
};
type Ticket = {
  id: string;
  revision: number;
  status: string;
  asset: { asset_id: string; original_filename: string };
  definition: Definition;
  options: {
    source_language: string;
    target_language: string;
    video_description: string;
    branch_choices?: Record<string, string>;
  };
  sequence?: { choices?: Record<string, string> };
  steps: Step[];
  confirmation: { token: string } | null;
  settings_snapshot: Record<string, string | boolean | number> | null;
  error?: string;
  phase?: number;
  reviews?: Record<string, ReviewDocument>;
  decisions?: Record<string, DecisionEvidence>;
  model_bindings?: Record<string, RegisteredVersion>;
  model_availability?: Record<string, { active: boolean; new_revision_available: boolean }>;
};
type Plan = {
  model_bindings?: Record<string, RegisteredVersion>;
  model_admission?: Record<string, { active: boolean; state_revision: number }>;
  token: string;
  settings: Record<string, string | number | boolean>;
  paid_roles: string[];
  ready?: boolean;
  eligible_steps?: string[];
  steps: { id: string; type: string; options: Record<string, string>; selected?: boolean }[];
  choices?: Record<string, string>;
  notice: string;
};
type Capability = {
  supported: boolean;
  reasons: { message: string; node_id: string | null }[];
  notice: string;
};
type Runtime = { connected: boolean; mode: string; notice: string };
const stateLabel: Record<string, string> = {
  held: '생성 보류',
  confirmed: '계획 확인 · 실행 대기',
  running: '단계 처리 중',
  cancelling: '취소 접수 · 진행 호출 정리 중',
  cancelled: '취소됨 · 결과 보존',
  quarantined: '늦은 결과 격리 · 자동 재사용 없음',
  failed: '첫 실패 중단',
  completed: '선택 단계 완료',
  pending: '대기',
  succeeded: '성공',
  skipped: '미선택 건너뜀',
  blocked: '선행 실패로 차단',
};
const graphPayload = (d: Definition) => ({
  catalog_version: d.catalog_version,
  revision: d.revision,
  name: d.name,
  inputs: d.inputs,
  nodes: d.nodes,
  edges: d.edges,
});

export const WorkflowTickets = ({
  graph: graphMode = false,
  review: reviewMode = false,
  decision: decisionMode = false,
  work: workMode = false,
  recovery = false,
  initialTicketId = '',
}: {
  graph?: boolean;
  review?: boolean;
  decision?: boolean;
  work?: boolean;
  recovery?: boolean;
  initialTicketId?: string;
}) => {
  const work = workMode || recovery;
  const decision = decisionMode || work;
  const review = reviewMode || decision,
    graph = graphMode || decision;
  const base = recovery
    ? '/settings/recovery-tickets'
    : work
      ? '/settings/work-tickets'
      : decision
        ? '/settings/decision-tickets'
        : review
          ? '/settings/review-tickets'
          : graph
            ? '/settings/graph-tickets'
            : '/settings/workflow-tickets';
  const reviewUpdate = async () => {
    setPlan(null);
    setPaid(false);
    if (ticket) {
      applyTicket(await request<Ticket>(base + '/' + ticket.id));
    }
  };
  const runRequest = useRef<{
    key: string;
    body: { request_id: string; revision: number; token: string };
  } | null>(null);
  const plannable = review
    ? ['held', 'confirmed', 'awaiting_review', 'awaiting_decision', 'continuation_confirmed']
    : ['held', 'confirmed'];
  const states: Record<string, string> = graph
    ? {
        ...stateLabel,
        failed: '선택 가지 실패 · 독립 결과 보존',
        ...(review
          ? {
              awaiting_decision: '판단 완료 · 선택 후행 확인 대기',
              awaiting_review: '사람 검수 대기',
              waiting: '사람 검수 대기',
              continuation_confirmed: '이어 실행 계획 확인 · 요청 대기',
            }
          : {}),
      }
    : stateLabel;
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [definitions, setDefinitions] = useState<{ id: string; name: string; revision: number }[]>(
    [],
  );
  const [assets, setAssets] = useState<VideoAsset[]>([]);
  const [catalog, setCatalog] = useState<Spec[]>([]);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [definition, setDefinition] = useState<Definition | null>(null);
  const [definitionId, setDefinitionId] = useState('');
  const [assetId, setAssetId] = useState('');
  const [sourceLanguage, setSourceLanguage] = useState('auto');
  const [targetLanguage, setTargetLanguage] = useState('ko');
  const [description, setDescription] = useState('');
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());
  const [capability, setCapability] = useState<Capability | null>(null);
  const [ticket, setTicket] = useState<Ticket | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [paid, setPaid] = useState(false);
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState('load');
  const [error, setError] = useState('');
  const [status, setStatus] = useState('');
  const selection = useRef(0);
  const label = (kind: string) => catalog.find((c) => c.id === kind)?.label || kind;
  const applyTicket = (next: Ticket) =>
    setTicket((previous) =>
      previous?.id === next.id && previous.revision > next.revision ? previous : next,
    );
  const changed = () => {
    selection.current++;
    setTicket(null);
    setPlan(null);
    setPaid(false);
    setRequestId(crypto.randomUUID());
    setError('');
    setStatus(
      '입력/옵션을 변경했습니다. 새 티켓·새 계획 확인이 필요합니다. 기존 티켓에는 소급하지 않습니다.',
    );
  };
  const loadList = async () => {
    const r = await request<{ tickets: Ticket[] }>(base);
    setTickets(r.tickets);
  };
  const load = async () => {
    setBusy('load');
    setError('');
    setReady(false);
    try {
      const [d, v, r, c, t] = await Promise.all([
        request<{ definitions: { id: string; name: string; revision: number }[] }>(
          '/settings/workflow-definitions',
        ),
        request<{ videos: VideoAsset[] }>('/videos'),
        request<Runtime>(base + '/runtime'),
        request<{ nodes: Spec[] }>('/settings/node-catalog'),
        request<{ tickets: Ticket[] }>(base),
      ]);
      setDefinitions(d.definitions);
      setAssets(v.videos);
      setRuntime(r);
      setCatalog(c.nodes);
      setTickets(t.tickets);
      setReady(true);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : '조회 실패. 현재 상태를 정상/빈 목록으로 판단하지 않습니다.',
      );
    } finally {
      setBusy('');
    }
  };
  const chooseDefinition = async (identity: string) => {
    changed();
    setDefinitionId(identity);
    setDefinition(null);
    setCapability(null);
    if (!identity) {
      return;
    }
    setBusy('definition');
    try {
      const d = await request<Definition>('/settings/workflow-definitions/' + identity);
      const nextChoices = Object.fromEntries(
        d.nodes.filter((n) => n.type === 'select').map((n) => [n.id, n.options.selection || 'a']),
      );
      setChoices(nextChoices);
      const cap = await jsonPost<Capability>(
        base + '/capability',
        graph ? { definition: graphPayload(d), choices: nextChoices } : graphPayload(d),
      );
      setDefinition(d);
      setCapability(cap);
      setDefinitions((rows) =>
        rows.map((row) =>
          row.id === d.id ? { id: d.id, name: d.name, revision: d.revision } : row,
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : '정의/실행 범위 조회 실패');
    } finally {
      setBusy('');
    }
  };
  const chooseBranch = async (identity: string, value: string) => {
    const next = { ...choices, [identity]: value };
    setChoices(next);
    changed();
    setCapability(null);
    if (!definition) {
      return;
    }
    setBusy('choice');
    try {
      setCapability(
        await jsonPost<Capability>(base + '/capability', {
          definition: graphPayload(definition),
          choices: next,
        }),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : '분기 실행 범위 재확인 실패');
    } finally {
      setBusy('');
    }
  };
  const create = async () => {
    if (!definition || !capability?.supported || !assetId) {
      return;
    }
    setBusy('create');
    setError('');
    setStatus('');
    try {
      const next = await jsonPost<Ticket>(base, {
        request_id: requestId,
        definition_id: definition.id,
        definition_revision: definition.revision,
        asset_id: assetId,
        options: {
          source_language: sourceLanguage,
          target_language: targetLanguage,
          video_description: description,
          ...(graph ? { branch_choices: choices } : {}),
        },
      });
      selection.current++;
      setTicket(next);
      setPlan(null);
      setPaid(false);
      setStatus(
        '티켓을 생성했거나 같은 요청의 기존 티켓을 불러왔습니다. 기존 큐 등록·자동 실행은 하지 않았습니다.',
      );
      await loadList();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : '생성 실패. 같은 입력/요청 ID로 재전송할 수 있습니다.',
      );
    } finally {
      setBusy('');
    }
  };
  const open = async (identity: string) => {
    setBusy('read');
    setError('');
    try {
      selection.current++;
      applyTicket(await request<Ticket>(base + '/' + identity));
      setPlan(null);
      setPaid(false);
      setStatus(
        '티켓 서버값을 다시 불러왔습니다. 정의/서빙 snapshot은 최신 편집으로 자동 교체하지 않습니다.',
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : '티켓 조회 실패');
    } finally {
      setBusy('');
    }
  };
  const getPlan = async () => {
    if (!ticket) {
      return;
    }
    setBusy('plan');
    setError('');
    setPaid(false);
    setPlan(null);
    try {
      setPlan(await request<Plan>(base + '/' + ticket.id + '/plan'));
    } catch (e) {
      setError(e instanceof Error ? e.message : '계획 조회 실패');
    } finally {
      setBusy('');
    }
  };
  const confirm = async () => {
    if (!ticket || !plan) {
      return;
    }
    setBusy('confirm');
    setError('');
    try {
      runRequest.current = null;
      applyTicket(
        await jsonPost<Ticket>(base + '/' + ticket.id + '/confirm', {
          revision: ticket.revision,
          token: plan.token,
          paid_confirmed: paid,
        }),
      );
      setStatus('확인한 계획을 저장했습니다. 아직 실행하지 않았습니다.');
      await loadList();
    } catch (e) {
      setError(e instanceof Error ? e.message : '확인 실패. 계획을 명시적으로 다시 불러오세요.');
    } finally {
      setBusy('');
    }
  };
  const start = async () => {
    if (!ticket || !plan) {
      return;
    }
    setBusy('start');
    setError('');
    try {
      const operation = review && (ticket.phase || 0) > 0 ? 'continue' : 'start';
      const key = ticket.id + ':' + plan.token + ':' + operation;
      if (runRequest.current?.key !== key) {
        runRequest.current = {
          key,
          body: { request_id: crypto.randomUUID(), revision: ticket.revision, token: plan.token },
        };
      }
      applyTicket(
        await jsonPost<Ticket>(
          base + '/' + ticket.id + '/' + operation,
          review ? runRequest.current.body : { revision: ticket.revision, token: plan.token },
        ),
      );
      if (review) {
        setPlan(null);
        setPaid(false);
      }
      await loadList();
      setStatus('실행 응답을 저장했습니다. 실제 단계 상태와 산출물을 확인하세요.');
    } catch (e) {
      setError(e instanceof Error ? e.message : '실행 요청 실패. 자동 재시도하지 않습니다.');
    } finally {
      setBusy('');
    }
  };
  const artifactLink = (step: Step, port: string, meta: Artifact, partial: boolean) =>
    !meta.path ? (
      <span key={port} className="artifact-reference">
        참조 {port} · {meta.reference?.node}.{meta.reference?.port} · {meta.type}
      </span>
    ) : (
      <a
        key={port}
        className={partial ? 'partial-link' : 'artifact-link'}
        href={`/api${base}/${ticket?.id}/artifacts/${encodeURIComponent(step.id)}/${encodeURIComponent(port)}${partial ? '?partial=true' : ''}`}
      >
        {partial ? '부분 결과' : '산출물'} {port} · {meta.bytes} bytes
      </a>
    );
  useEffect(() => {
    void load().then(() => {
      if (initialTicketId) {
        void open(initialTicketId);
      }
    });
  }, []);
  useEffect(() => {
    if (!ticket || (!['running', 'cancelling'].includes(ticket.status) && busy !== 'start')) {
      return;
    }
    const generation = selection.current,
      identity = ticket.id;
    let stopped = false;
    const timer = window.setInterval(() => {
      void request<Ticket>(base + '/' + identity)
        .then((next) => {
          if (!stopped && selection.current === generation) {
            applyTicket(next);
          }
        })
        .catch(() => {
          if (!stopped) {
            setError(
              '진행 조회 실패 · 이전 상태를 표시 중입니다. 실행을 재요청하지 말고 서버값을 다시 불러오세요.',
            );
          }
        });
    }, 1000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [ticket?.id, ticket?.status, busy]);

  return (
    <main className="serving-page workflow-tickets">
      <div className="serving-heading">
        <div>
          <p className="workspace-eyebrow">
            {work
              ? '작업 · 계획 확인과 실행은 별도'
              : decision
                ? '구조화 판단 · 서버 조건 평가 · 결과 고정 · 선택 후행 새 확인'
                : review
                  ? '원하는 지원 지점 · 영속 검수 대기 · 명시 승인·이어 실행'
                  : graph
                    ? '수동 선택 · 제어된 동시 진행 · 결과 참조 합류'
                    : '정의 기반 순차 처리'}
          </p>
          <h1>
            {recovery
              ? '복구 계약 작업 티켓'
              : work
                ? '작업 티켓'
                : decision
                  ? 'AI 판단 워크플로우 티켓'
                  : review
                    ? '사람 검수 워크플로우 티켓'
                    : graph
                      ? '분기·병렬 워크플로우 티켓'
                      : '순차 워크플로우 티켓'}
          </h1>
        </div>
        <Button variant="secondary" disabled={!!busy} onClick={() => void load()}>
          서버 목록 새로 불러오기
        </Button>
      </div>
      {decision && !work && (
        <p className="serving-help">
          이전 티켓은 기존 계약을 유지합니다. <a href="#/recovery-tickets">새 복구 계약 티켓</a>으로
          자동 변환하지 않습니다.
        </p>
      )}
      {work && (
        <nav aria-label="작업 티켓 계약">
          <a href="#/work-tickets">기존 등록 모델 티켓</a> ·{' '}
          <a href="#/recovery-tickets">새 복구 계약 티켓</a>
        </nav>
      )}
      {decision && !work && (
        <p className="serving-help">
          기본 작업 동선은 영상 + 저장 워크플로우 → 흐름/노드 설정 요약 → 명시 계획 확인 →
          티켓입니다. 이 화면은 신규 AI 판단 경로의 기능 검증 화면이며 내부 실행기를 다시 고르는
          최종 제품 진입이 아닙니다. 처리 옵션은 워크플로우 편집기에서 노드를 클릭해 설정합니다. 이
          이전 티켓 형식은 등록 모델 참조를 사용하지 않습니다. 새 등록 모델 연결은 작업 시작에서
          사용하며 전역 역할 설정을 노드 연결로 간주하지 않습니다.
        </p>
      )}
      <p>
        {work ? (
          '고정된 흐름·모델·현재 미실행 계획을 확인한 뒤 명시 실행합니다. 새 작업은 작업 시작에서 만드세요.'
        ) : (
          <>
            영상과 저장 정의를 선택해 <strong>보류 티켓</strong>을 만듭니다. 생성/계획 확인은
            실행이나 기존 큐 등록이 아닙니다.
          </>
        )}
      </p>
      <p className="serving-help">
        정의는 생성 때 ID·revision·내용을 고정합니다. 계획 확인 때 서빙 설정을 결합하고 변경 시
        재확인을 요구합니다. 비밀키는 복사하지 않습니다.{' '}
        {graph
          ? '독립 가지는 실패를 전파하지 않고 결과를 보존합니다. join은 목록이며 미디어/clock 병합이 아닙니다.'
          : '첫 실패에서 중단합니다.'}{' '}
        {recovery
          ? '자동 재실행은 없습니다. 취소/실패는 원 티켓 보존과 새 복구 티켓·새 계획 확인으로 분리합니다.'
          : '자동 재시도·취소 후 재개는 제공하지 않습니다.'}
      </p>
      {runtime && (
        <p>
          <Badge tone="neutral">
            {runtime.connected
              ? runtime.mode
              : work
                ? '작업 실행기 미연결'
                : decision
                  ? 'AI 판단 실행기 미연결'
                  : review
                    ? '검수 실행기 미연결'
                    : graph
                      ? '병렬 실행기 미연결'
                      : '새 순차 실행기 미연결'}
          </Badge>{' '}
          {runtime.notice}
        </p>
      )}
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {status && <p role="status">{status}</p>}
      {!ready && <p>서버 목록 미확인 · 조회 성공 전에는 새 티켓을 생성하지 않습니다.</p>}
      {!work && (
        <section className="ticket-panel">
          <h2>새 티켓 생성</h2>
          <fieldset disabled={!!busy || !ready}>
            <div className="serving-grid">
              <label>
                입력 영상
                <select
                  aria-label="입력 영상"
                  value={assetId}
                  onChange={(e) => {
                    setAssetId(e.target.value);
                    changed();
                  }}
                >
                  <option value="">영상 선택</option>
                  {assets.map((a) => (
                    <option key={a.asset_id} value={a.asset_id}>
                      {a.original_filename}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                저장 워크플로우
                <select
                  aria-label="저장 워크플로우"
                  value={definitionId}
                  onChange={(e) => void chooseDefinition(e.target.value)}
                >
                  <option value="">저장 정의 선택</option>
                  {definitions.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.name} · r{d.revision}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                입력 언어
                <Input
                  aria-label="입력 언어"
                  value={sourceLanguage}
                  maxLength={40}
                  onChange={(e) => {
                    setSourceLanguage(e.target.value);
                    changed();
                  }}
                />
              </label>
              <label>
                대상 언어
                <Input
                  aria-label="대상 언어"
                  value={targetLanguage}
                  maxLength={40}
                  onChange={(e) => {
                    setTargetLanguage(e.target.value);
                    changed();
                  }}
                />
              </label>
              <label>
                영상 설명
                <Input
                  aria-label="영상 설명"
                  value={description}
                  maxLength={2000}
                  onChange={(e) => {
                    setDescription(e.target.value);
                    changed();
                  }}
                />
              </label>
            </div>
            {graph &&
              definition?.nodes
                .filter((n) => n.type === 'select')
                .map((n) => (
                  <label key={n.id}>
                    수동 분기 {n.id}
                    <select
                      aria-label={`분기 ${n.id} 선택`}
                      value={choices[n.id] || n.options.selection || 'a'}
                      onChange={(e) => void chooseBranch(n.id, e.target.value)}
                    >
                      <option value="a">a 선택</option>
                      <option value="b">b 선택</option>
                      <option value="both">둘 다</option>
                    </select>
                  </label>
                ))}
            <div className="ticket-actions">
              <Button
                variant="secondary"
                disabled={!definitionId}
                onClick={() => void chooseDefinition(definitionId)}
              >
                선택 정의 새로 읽기
              </Button>
              <Button
                disabled={!definition || !capability?.supported || !assetId}
                onClick={() => void create()}
              >
                보류 티켓 생성
              </Button>
            </div>
          </fieldset>
          {definition && (
            <p>
              선택 정의: {definition.name} · revision {definition.revision} ·{' '}
              <a href="#/workflow-editor">편집기로 이동</a>
            </p>
          )}
          {capability && (
            <div className="execution-capability">
              <Badge tone="neutral">
                {capability.supported
                  ? decision
                    ? 'AI 판단 범위 지원'
                    : review
                      ? '검수 범위 지원'
                      : graph
                        ? '분기·병렬 범위 지원'
                        : '순차 범위 지원'
                  : graph
                    ? '현재 병렬 실행 미지원'
                    : '현재 순차 실행 미지원'}
              </Badge>
              <p className="serving-help">
                {capability.notice} 타입 검증 통과와 실제 실행 가능성/성공은 다릅니다.
              </p>
              {!capability.supported && (
                <div className="execution-reasons">
                  {capability.reasons.map((r, i) => (
                    <p key={i}>
                      {r.node_id ? `${r.node_id} · ` : ''}
                      {r.message}
                    </p>
                  ))}
                </div>
              )}
            </div>
          )}
        </section>
      )}
      <section className="ticket-panel">
        <h2>
          {work
            ? '저장된 작업 티켓'
            : decision
              ? '저장된 AI 판단 티켓'
              : review
                ? '저장된 검수 지원 티켓'
                : graph
                  ? '저장된 분기·병렬 티켓'
                  : '저장된 순차 티켓'}
        </h2>
        {ready && tickets.length === 0 && (
          <p>
            {decision
              ? '저장된 AI 판단 티켓 없음.'
              : review
                ? '저장된 검수 지원 티켓 없음.'
                : graph
                  ? '저장된 새 병렬 티켓 없음.'
                  : '저장된 새 순차 티켓 없음.'}{' '}
            기존 고정 workflow/작업은 변경하지 않습니다.
          </p>
        )}
        <div className="ticket-list">
          {tickets.map((t) => (
            <Button
              key={t.id}
              variant="secondary"
              disabled={!!busy}
              onClick={() => void open(t.id)}
            >
              {t.definition.name} · {states[t.status] || t.status} · {t.id.slice(0, 6)}
            </Button>
          ))}
        </div>
      </section>
      {work && (
        <details className="ticket-panel">
          <summary>이전 티켓 · 기능 검증 화면</summary>
          <p>
            <a href="#/recovery-tickets">새 복구 계약 티켓</a> ·{' '}
            <a href="#/workflow-tickets">이전 순차 티켓</a> ·{' '}
            <a href="#/graph-tickets">이전 분기·병렬 티켓</a> ·{' '}
            <a href="#/review-tickets">이전 검수 티켓</a> ·{' '}
            <a href="#/decision-tickets">이전 판단 티켓</a>
          </p>
          <p>기존 티켓/저장소를 보존합니다. 등록 모델 참조로 소급 변환하지 않습니다.</p>
        </details>
      )}
      {ticket && recovery && <RecoveryActions key={ticket.id} ticket={ticket} onOpen={open} />}
      {ticket && (
        <TicketSnapshotRestore
          key={'snapshot-' + ticket.id}
          definitionId={ticket.definition.id}
          ticketId={ticket.id}
          namespace={
            recovery
              ? 'recovery'
              : work
                ? 'work'
                : decision
                  ? 'decision'
                  : review
                    ? 'review'
                    : graph
                      ? 'graph'
                      : 'workflow'
          }
        />
      )}
      {ticket && (
        <section className="ticket-panel ticket-detail">
          <div className="serving-heading">
            <h2>{ticket.definition.name}</h2>
            <Badge tone="neutral">
              <span className="ticket-state">{states[ticket.status] || ticket.status}</span>
            </Badge>
          </div>
          <p>
            {ticket.asset.original_filename} · 고정 정의 r{ticket.definition.revision} · 티켓
            revision {ticket.revision}
          </p>
          <p className="serving-help">
            티켓 {ticket.id} · 언어 {ticket.options.source_language} →{' '}
            {ticket.options.target_language}. 위의 새 입력을 바꾸면 이전 확인을 재사용하지 않습니다.
          </p>
          {graph && (
            <p className="ticket-choices">
              고정 수동 선택:{' '}
              {Object.entries(ticket.sequence?.choices || {})
                .map(([k, v]) => `${k}=${v}`)
                .join(' / ') || '수동 분기 없음'}{' '}
              · 동시 상한 2
            </p>
          )}
          <div className="ticket-actions">
            <Button variant="secondary" disabled={!!busy} onClick={() => void open(ticket.id)}>
              티켓 서버값 다시 불러오기
            </Button>
            <Button
              variant="secondary"
              disabled={!!busy || !plannable.includes(ticket.status)}
              onClick={() => void getPlan()}
            >
              실행 계획 불러오기
            </Button>
          </div>
          {ticket.error && (
            <p className="alert">
              {ticket.error} 성공 단계·부분 파일은 아래에 보존됩니다. 이 티켓은 재개하지 않습니다.
              다시 처리하려면 새 티켓을 별도로 검토하세요.
            </p>
          )}
          {ticket.settings_snapshot && (
            <p>
              확인된 서빙 revision {String(ticket.settings_snapshot.revision)} · 저장/키 보유/모델
              목록은 연결·추론 성공이 아닙니다.
            </p>
          )}
          {plan && (
            <section className="execution-plan">
              <h3>명시 실행 계획 확인</h3>
              <p>
                고정 정의 r{ticket.definition.revision} · 서빙 revision{' '}
                {String(plan.settings.revision)}
              </p>
              <p className="serving-help">
                {plan.notice} 입력/옵션 변경은 새 티켓과 새 확인이 필요합니다.
              </p>
              <ol>
                {plan.steps.map((s) => (
                  <li key={s.id}>
                    {label(s.type)}
                    {review && !plan.eligible_steps?.includes(s.id)
                      ? ' · 이번 실행 제외(보존/검수 선행 대기)'
                      : ''}
                    {s.selected === false ? ' · 미선택 건너뜀' : ''} ·{' '}
                    {Object.entries(s.options)
                      .map(([k, v]) => `${k}=${v}`)
                      .join(' / ') || '정의된 기본 옵션'}
                    {work && plan.model_bindings?.[s.id] && (
                      <p>
                        고정 모델 {plan.model_bindings[s.id].name} · r
                        {plan.model_bindings[s.id].revision} · {plan.model_bindings[s.id].provider}/
                        {plan.model_bindings[s.id].model}
                        {plan.model_admission?.[s.id]?.active === false
                          ? ' · 사용 중지: 이 모델의 미실행 호출 차단. 독립 결과는 보존하며 새 정의·계획·티켓으로 교체하세요.'
                          : ''}
                      </p>
                    )}
                  </li>
                ))}
              </ol>
              {!work && (
                <p>
                  전사 {String(plan.settings.transcription_provider)} /{' '}
                  {String(plan.settings.transcription_model)} · 번역{' '}
                  {String(plan.settings.translation_provider)} /{' '}
                  {String(plan.settings.translation_model)}
                </p>
              )}
              <p>
                {plan.paid_roles.length
                  ? `모델 호출 역할: ${plan.paid_roles.join(', ')} · 외부 공급자 비용이 발생할 수 있습니다.`
                  : '이 선택 단계에는 모델 호출 역할이 없습니다.'}
              </p>
              <label className="serving-check">
                <input
                  type="checkbox"
                  aria-label="유료 모델 호출 확인"
                  checked={paid}
                  disabled={!!busy || plan.paid_roles.length === 0}
                  onChange={(e) => setPaid(e.target.checked)}
                />
                계획의 유료 모델 호출을 명시적으로 확인
              </label>
              <div className="ticket-actions">
                <Button
                  disabled={
                    !!busy ||
                    (review && !plan.ready) ||
                    (plan.paid_roles.length > 0 && !paid) ||
                    !plannable.includes(ticket.status)
                  }
                  onClick={() => void confirm()}
                >
                  계획 확인 저장
                </Button>
                <Button
                  disabled={
                    !!busy ||
                    !runtime?.connected ||
                    !(review ? ['confirmed', 'continuation_confirmed'] : ['confirmed']).includes(
                      ticket.status,
                    ) ||
                    ticket.confirmation?.token !== plan.token
                  }
                  onClick={() => void start()}
                >
                  {review && (ticket.phase || 0) > 0
                    ? '확인한 계획 이어 실행 요청'
                    : '확인한 계획 실행 요청'}
                </Button>
              </div>
              {!runtime?.connected && (
                <p className="serving-help">
                  현재 실행기가 미연결이라 실행 요청은 비활성입니다. 기존 큐/Worker를 자동 시작하지
                  않습니다.
                </p>
              )}
            </section>
          )}
          <ol className="ticket-steps">
            {ticket.steps.map((step) => (
              <li
                className="ticket-step"
                key={step.id}
                data-node-id={step.id}
                data-status={step.status}
              >
                <h3>
                  {label(step.type)} ·{' '}
                  {decision && step.type === 'decision' && step.status === 'waiting'
                    ? '판단 완료 · 선택 후행 확인 대기'
                    : graph && step.status === 'failed'
                      ? '실패'
                      : states[step.status] || step.status}
                </h3>
                {graph && <p className="serving-help">노드 {step.id}</p>}
                {work && ticket.model_bindings?.[step.id] && (
                  <div className="node-model-snapshot">
                    <p>
                      고정 모델 {ticket.model_bindings[step.id].name} · r
                      {ticket.model_bindings[step.id].revision} ·{' '}
                      {ticket.model_bindings[step.id].provider}/
                      {ticket.model_bindings[step.id].model}
                    </p>
                    {ticket.model_availability?.[step.id]?.new_revision_available && (
                      <p>새 revision 있음 · 기존 pin 유지</p>
                    )}
                    {ticket.model_availability?.[step.id]?.active === false && (
                      <p>
                        사용 중지 · 이 모델의 미실행 호출 차단, 완료/독립 결과 보존. 교체는 새
                        정의·계획·티켓으로 진행하세요.
                      </p>
                    )}
                  </div>
                )}
                {(step.blocked_by || step.error_type) && (
                  <p className="serving-help">
                    {step.blocked_by
                      ? `필수 선행 실패/차단: ${step.blocked_by.join(', ')}`
                      : `단계 실패: ${step.error_type}`}
                  </p>
                )}
                {decision && step.type === 'decision' && (
                  <DecisionPanel
                    compact={work}
                    evidence={ticket.decisions?.[step.id]}
                    status={step.status}
                  />
                )}
                {review && ticket.reviews?.[step.id] && (
                  <ReviewPanel
                    key={ticket.id + ':' + step.id}
                    ticketBase={base}
                    ticketId={ticket.id}
                    node={step.id}
                    initial={ticket.reviews[step.id]}
                    executed={step.status === 'succeeded'}
                    changed={reviewUpdate}
                  />
                )}
                <div className="ticket-artifacts">
                  {Object.entries(step.artifacts).map(([p, m]) => artifactLink(step, p, m, false))}
                  {Object.entries(step.partial_artifacts).map(([p, m]) =>
                    artifactLink(step, p, m, true),
                  )}
                </div>
                {Object.keys(step.artifacts).length === 0 &&
                  Object.keys(step.partial_artifacts).length === 0 && (
                    <p className="serving-help">아직 저장된 산출물 없음</p>
                  )}
              </li>
            ))}
          </ol>
        </section>
      )}
      <p className="serving-help">
        {recovery
          ? '복구는 owner·입출력 SHA·고정 정의/옵션/모델·선택 입력과 완료 receipt를 대조합니다. 결과 불명은 자동 재호출하지 않고 별도 위험 확인과 새 계획을 요구합니다. 외부 호출 exactly-once나 즉시 취소/환불 보장은 없습니다.'
          : decision
            ? '판단 adapter의 구조화 결과와 서버 조건으로 정확히 한 경로만 선택합니다. review/reject는 라벨이며 자동 검수 생성/가지 종료 명령이 아닙니다. 판단 결과는 고정하고, 결과·미실행 경로·서빙 새 계획 확인 뒤 별도 이어실행합니다. 오류/형식/조건 실패는 차단하며 기본경로·자동 재판정·일반 복구는 없습니다. 영상/음성 판단은 현재 metadata-only 계약이고 실미디어 모델 추론을 뜻하지 않습니다.'
            : review
              ? '검수 대기는 해당 후행만 멈춥니다. 승인 전 필수 join은 대기하고 독립 가지의 성공/부분 결과는 보존합니다. 최신 서빙은 미실행 부분의 새 계획 확인에만 사용하며 완료 단계는 재실행하지 않습니다. 실패 재시도·crash 복구·AI Decision은 미지원입니다.'
              : graph
                ? '수동 선택·독립 병렬·선택 필수 합류를 지원합니다. 합류 출력은 노드ID.포트 결과 참조 manifest이며 미디어/clock 병합 또는 단일 미디어 입력이 아닙니다. 얼굴 합성 세션/preview·GPU VAD·새 사람검수/AI Decision은 미지원입니다.'
                : '지원 범위는 단일 처리 사슬입니다. 얼굴 합성 세션/preview·GPU VAD·추가 검수/Decision·병렬/합류는 이번 순차 어댑터에서 미지원입니다.'}{' '}
        단계 상태는 실행기가 기록한 결과이며 실모델 품질 검증을 뜻하지 않습니다.
      </p>
    </main>
  );
};
