import { useSyncExternalStore } from 'react';
import { frontendOnly } from './preview';

export type PreviewAccount = {
  id: string;
  username: string;
  role: 'admin' | 'member';
  created_at: string;
};
type AccountState = { accounts: PreviewAccount[]; currentId: string | null };
const key = 'mideagent-publishing-accounts-v1';
const event = 'mideagent-preview-accounts';
const restore = (): AccountState => {
  if (frontendOnly) {
    try {
      const saved = JSON.parse(sessionStorage.getItem(key) || 'null');
      if (Array.isArray(saved?.accounts)) {
        // Explicit projection excludes all password/credential fields.
        return {
          accounts: saved.accounts.map((row: PreviewAccount) => ({
            id: row.id,
            username: row.username,
            role: row.role,
            created_at: row.created_at,
          })),
          currentId: saved.currentId || null,
        };
      }
    } catch {
      /* Tab-local preview remains usable without storage. */
    }
  }
  return { accounts: [], currentId: null };
};
let state = restore();
const subscribe = (changed: () => void) => {
  window.addEventListener(event, changed);
  return () => window.removeEventListener(event, changed);
};
const snapshot = () => state;
const publish = (next: AccountState) => {
  if (!frontendOnly) {
    throw new Error('목업에서만 사용할 수 있습니다.');
  }
  state = next;
  try {
    sessionStorage.setItem(key, JSON.stringify(state));
  } catch {
    /* memory only */
  }
  window.dispatchEvent(new Event(event));
};
export const usePreviewAccounts = () => useSyncExternalStore(subscribe, snapshot, snapshot);
const newAccount = (username: string, role: PreviewAccount['role']): PreviewAccount => {
  const value = username.trim();
  if (!value || value.length > 64) {
    throw new Error('아이디를 64자 이내로 입력해 주세요.');
  }
  if (
    state.accounts.some((row) => row.username.toLocaleLowerCase() === value.toLocaleLowerCase())
  ) {
    throw new Error('이미 사용 중인 아이디입니다.');
  }
  return { id: crypto.randomUUID(), username: value, role, created_at: new Date().toISOString() };
};
export const createPreviewAdmin = (username: string) => {
  if (state.accounts.length) {
    throw new Error('관리자 계정이 이미 있습니다.');
  }
  const account = newAccount(username, 'admin');
  publish({ accounts: [account], currentId: null });
};
export const issuePreviewAccount = (username: string) => {
  if (state.accounts.find((row) => row.id === state.currentId)?.role !== 'admin') {
    throw new Error('관리자로 로그인해 주세요.');
  }
  const account = newAccount(username, 'member');
  publish({ ...state, accounts: [...state.accounts, account] });
};
// Screen navigation only: no password is accepted or verified by the preview store.
export const loginPreview = (username: string) => {
  const account = state.accounts.find((row) => row.username === username.trim());
  if (!account) {
    throw new Error('등록된 아이디를 확인해 주세요.');
  }
  publish({ ...state, currentId: account.id });
};
export const logoutPreview = () => publish({ ...state, currentId: null });
