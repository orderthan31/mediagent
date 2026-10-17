import { useEffect, useState } from 'react';
import { request } from './api';
import { useWorkspaceAuth } from './AuthGate';
import { PageTitle } from './PageTitle';
import { Pagination, usePagination } from './Pagination';
import { Button } from './hangyeol/primitives/button';
import { TextField } from './hangyeol/components/text-field';
import './account.css';

type Account = {
  id: string;
  username: string;
  role: 'admin' | 'user';
  active: boolean;
  created_at: string;
};
export const LiveAccounts = ({ create = false }: { create?: boolean }) => {
  const auth = useWorkspaceAuth();
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const admin = auth?.session.user?.role === 'admin';
  const page = usePagination(accounts, 'live-accounts');
  const issue = async () => {
    if (busy) {
      return;
    }
    if (password !== confirmation) {
      setError('비밀번호 확인이 일치하지 않습니다.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await request<Account>('/accounts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      location.hash = '/account';
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '계정 발급 실패');
    } finally {
      setPassword('');
      setConfirmation('');
      setBusy(false);
    }
  };
  useEffect(() => {
    const controller = new AbortController();
    setError('');
    if (!admin || create) {
      setLoading(false);
      return;
    }
    setLoading(true);
    void request<{ accounts: Account[] }>('/accounts', { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted) {
          setAccounts(data.accounts);
        }
      })
      .catch((reason) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : '계정 조회 실패');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [admin, create]);
  return (
    <main className="serving-page account-page">
      <PageTitle>{create ? '계정 발급' : '계정 관리'}</PageTitle>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}
      {!admin ? (
        <dl className="account-facts">
          <div>
            <dt>아이디</dt>
            <dd>{auth?.session.user?.username}</dd>
          </div>
          <div>
            <dt>권한</dt>
            <dd>사용자</dd>
          </div>
          {create && <p role="alert">계정 발급은 관리자만 할 수 있습니다.</p>}
        </dl>
      ) : create ? (
        <form
          className="page-form account-create"
          onSubmit={(event) => {
            event.preventDefault();
            void issue();
          }}
        >
          <fieldset disabled={busy}>
            <TextField
              label="아이디"
              name="new-username"
              autoComplete="off"
              minLength={3}
              maxLength={64}
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
            <TextField
              label="비밀번호"
              name="new-password"
              type="password"
              autoComplete="new-password"
              minLength={12}
              maxLength={256}
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <TextField
              label="비밀번호 확인"
              name="confirm-password"
              type="password"
              autoComplete="new-password"
              minLength={12}
              maxLength={256}
              required
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
            />
            <p className="form-note">비밀번호는 12~256자로 입력하세요.</p>
            <div className="form-actions">
              <Button
                variant="quiet"
                onClick={() => {
                  location.hash = '/account';
                }}
              >
                취소
              </Button>
              <Button type="submit" loading={busy}>
                계정 발급
              </Button>
            </div>
          </fieldset>
        </form>
      ) : (
        <section className="account-members" aria-labelledby="live-members-title">
          <div className="section-heading">
            <h2 id="live-members-title">계정 목록</h2>
            <a className="ui02-text-action" href="#/account/new">
              계정 발급
            </a>
          </div>
          {loading ? (
            <p role="status">계정 불러오는 중</p>
          ) : (
            !error && (
              <>
                <div className="account-table">
                  <div className="account-table-head">
                    <span>아이디</span>
                    <span>권한</span>
                    <span>생성일</span>
                  </div>
                  {page.items.map((row) => (
                    <div className="account-table-row" key={row.id}>
                      <strong>
                        {row.username}
                        {row.id === auth?.session.user?.id && <small>나</small>}
                      </strong>
                      <span>{row.role === 'admin' ? '관리자' : '사용자'}</span>
                      <time dateTime={row.created_at}>
                        {new Date(row.created_at).toLocaleDateString('ko-KR')}
                      </time>
                    </div>
                  ))}
                </div>
                <Pagination {...page} />
              </>
            )
          )}
        </section>
      )}
    </main>
  );
};
