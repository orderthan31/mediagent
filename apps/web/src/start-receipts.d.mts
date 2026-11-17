export type PendingStart = { request_id: string; receipt_id?: string };
export type StartReceipt = Readonly<{
  id: string;
  job_id: string | null;
  state: string;
  code: string;
}>;
export function validReceiptId(id: unknown): id is string;
export function validNonce(id: unknown): id is string;
export function readPendingStart(scope?: string, storage?: Storage): PendingStart | null;
export function rememberPendingStart(
  scope: string,
  value: PendingStart,
  storage?: Storage,
): PendingStart;
export function forgetPendingStart(scope: string, storage?: Storage): void;
export function parseStartReceipt(value: unknown): StartReceipt;
export function isKnownStartRequestState(state: string): boolean;
export function startRequestLabel(state: string): string;
export function isStartRequestPending(state: string): boolean;
export function startReceiptRoute(value: PendingStart): string;
export function parseStartRequestRoute(
  route: string,
): { receipt_id?: string; request_id?: string } | null;
