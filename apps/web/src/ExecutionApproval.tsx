import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import { Button } from './hangyeol/primitives/button';
import './execution-approval.css';

type Cost = { state: 'may_charge' | 'no_external_call' | 'unknown'; amount: null; notice: string };
type Quote = { token: string; cost: Cost; input_sha256: string; risk_required?: boolean };
type Grant = { id: string; state: string; confirmed_at: number; expires_at: number; server_time?: number; cost: Cost };
export type ExecutionHeaders = Record<string, string>;
export const ExecutionApproval = ({ path, payload, requestId, actionLabel, disabled = false, onExecute }: {
  path: string;
  payload: Record<string, unknown>;
  requestId: string;
  actionLabel: string;
  disabled?: boolean;
  onExecute: (headers: ExecutionHeaders) => Promise<void>;
}) => {
  const selection = JSON.stringify({ path, payload });
  const [quote, setQuote] = useState<(Quote & { selection: string }) | null>(null);
  const [grant, setGrant] = useState<(Grant & { selection: string; localExpiry: number }) | null>(null);
  const [paid, setPaid] = useState(false), [risk, setRisk] = useState(false);
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [, tick] = useState(0);
  const confirmId = useRef(crypto.randomUUID()), generation = useRef(0), inFlight = useRef(false);
  useEffect(() => {
    generation.current++;
    setQuote(null); setGrant(null); setPaid(false); setRisk(false); setError('');
    confirmId.current = crypto.randomUUID();
  }, [selection]);
  useEffect(() => { const timer = window.setInterval(() => tick(value => value + 1), 1000); return () => clearInterval(timer); }, []);
  const current = quote?.selection === selection ? quote : null;
  const approved = grant?.selection === selection ? grant : null;
  const expired = !!approved && Date.now() >= approved.localExpiry;
  const known = !!current && ['may_charge', 'no_external_call'].includes(current.cost.state);
  const load = async () => {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(''); setQuote(null); setGrant(null); setPaid(false); setRisk(false);
    confirmId.current = crypto.randomUUID();
    const version = ++generation.current;
    try {
      const value = await request<Quote>('/execution-approvals/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: selection });
      if (!value || !/^[a-f0-9]{64}$/.test(value.token) || !/^[a-f0-9]{64}$/.test(value.input_sha256) || !value.cost || !['may_charge','no_external_call','unknown'].includes(value.cost.state) || value.cost.amount !== null) throw new Error('서버 비용 분류/입력 계획을 확인하지 못했습니다. 무료로 취급하지 않습니다.');
      if (version === generation.current) setQuote({ ...value, selection });
    } catch (e) { if (version === generation.current) setError(e instanceof Error ? e.message : '서버 계획 조회 실패 · 실행 차단'); }
    finally { inFlight.current = false; setBusy(false); }
  };
  const confirm = async () => {
    if (inFlight.current || !current || !known || (current.cost.state === 'may_charge' && !paid) || (current.risk_required && !risk)) return;
    inFlight.current = true; setBusy(true); setError('');
    const version = generation.current;
    try {
      const value = await request<Grant>('/execution-approvals/confirm', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...JSON.parse(selection), token: current.token, request_id: confirmId.current, paid_confirmed: paid, risk_confirmed: risk }) });
      if (!value || !/^[a-f0-9]{32}$/.test(value.id) || !Number.isFinite(value.expires_at) || !Number.isFinite(value.confirmed_at)) throw new Error('서버 승인 저장을 확인하지 못했습니다. 실행하지 않습니다.');
      if (version === generation.current) setGrant({ ...value, selection, localExpiry: Date.now() + Math.max(0, value.expires_at - (value.server_time ?? Date.now() / 1000)) * 1000 });
    } catch (e) { if (version === generation.current) setError(e instanceof Error ? e.message : '승인 저장 실패'); }
    finally { inFlight.current = false; setBusy(false); }
  };
  const execute = async () => {
    if (inFlight.current || !approved || approved.state !== 'confirmed' || expired || disabled) return;
    inFlight.current = true; setBusy(true); setError('');
    try { await onExecute({ 'X-Execution-Approval': approved.id, 'X-Execution-Request': requestId }); }
    catch (e) { setError(e instanceof Error ? e.message : '실행 입장 결과 미확인 · 자동 재시도 없음'); setGrant(null); }
    finally { inFlight.current = false; setBusy(false); }
  };
  return <section className="execution-approval" aria-label="서버 실행 승인">
    <h3>서버 실행 승인</h3>
    <p>현재 입력 bytes SHA·남은 계획·옵션·고정 모델/서빙·선택 경로를 서버에서 다시 확인합니다.</p>
    <Button variant="secondary" disabled={busy} onClick={() => void load()}>서버 실행 계획 조회</Button>
    {current && <>
      <p className={current.cost.state === 'unknown' ? 'alert' : 'serving-help'}>
        {current.cost.state === 'unknown' ? '비용 분류 미확인/오류 · 실행 차단. 체크로 우회할 수 없습니다.' : current.cost.state === 'may_charge' ? '유료 발생 가능 · 금액 미산정(null). 무료/0원·비용 상한 보장이 아닙니다.' : '이 미실행 계획은 외부 provider 호출 없음. 무료 요금제나 금액 견적의 보장이 아닙니다.'}
      </p>
      {current.cost.state === 'unknown' && <p>{current.cost.notice}</p>}
      <p className="execution-input-sha">실제 사용할 입력 SHA <code>{current.input_sha256}</code></p>
      {current.cost.state === 'may_charge' && <label className="serving-check"><input type="checkbox" aria-label="유료가능·금액미산정 비용 확인" checked={paid} disabled={busy} onChange={event => setPaid(event.target.checked)} />금액 미산정 상태와 유료 비용 발생 가능성을 명시 확인합니다. 비용 상한·환불 보장은 아닙니다.</label>}
      {current.risk_required && <label className="serving-check"><input type="checkbox" aria-label="legacy 불명 중복호출 위험 별도확인" checked={risk} disabled={busy} onChange={event => setRisk(event.target.checked)} />이전 호출 결과 불명·중복 호출/과금 위험을 비용 확인과 별도로 확인합니다.</label>}
      <Button disabled={busy || !known || (current.cost.state === 'may_charge' && !paid) || (!!current.risk_required && !risk)} onClick={() => void confirm()}>서버 실행 승인 저장</Button>
    </>}
    {approved && <p role="status">{expired ? '미소비 승인 15분 만료 · 현재 계획 조회 후 명시 재확인 필요' : '서버 승인 저장됨 · 아직 실행하지 않음 · 미소비 승인만 15분 만료'}</p>}
    {error && <p role="alert" className="alert">{error}</p>}
    <p className="serving-help">확인 저장 ≠ 실행/큐 등록. 실행 입장에서 한 번 소비하며, 새로고침/동일 확인으로 만료를 연장하지 않습니다. 이미 소비한 승인은 자동 충전·재호출하지 않습니다. 입력 고정 복사본의 저장 공간이 필요합니다.</p>
    <Button disabled={busy || disabled || !approved || approved.state !== 'confirmed' || expired} onClick={() => void execute()}>{actionLabel}</Button>
  </section>;
};
