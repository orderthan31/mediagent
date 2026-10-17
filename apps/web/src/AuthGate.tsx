import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { Captions, LogIn, LogOut, RefreshCw } from 'lucide-react';
import { ApiError, request } from './api';
import { sessionEvents, setCsrfToken } from './auth-session';
import { Theme } from './hangyeol/foundation/theme';
import { TextField } from './hangyeol/components/text-field';
import { Button } from './hangyeol/primitives/button';
import { renewalBackend } from './preview';
import './auth.css';
type Session = {
  enabled: boolean;
  setup_required?: boolean;
  backend?: string;
  user: {
    id: string;
    username: string;
    role?: 'admin' | 'user';
  } | null;
  csrf_token?: string;
};
const AuthContext = createContext<{
  session: Session;
  logout: () => void;
  busy: boolean;
} | null>(null);
export const useWorkspaceAuth = () => useContext(AuthContext);
export const AccountMenu = () => {
  const auth = useContext(AuthContext);
  if (!auth?.session.user) {
    return null;
  }
  return (
    <div className="account-menu">
      <span className="account-username" title={auth.session.user.username}>
        {auth.session.user.username}
      </span>
      <Button
        variant="quiet"
        title="로그아웃"
        aria-label="로그아웃"
        disabled={auth.busy}
        onClick={auth.logout}
      >
        <LogOut size={18} />
        로그아웃
      </Button>
    </div>
  );
};
export const AuthGate = ({ children }: { children: ReactNode }) => {
  const [session, setSession] = useState<Session | null>(null);
  const [username, setUsername] = useState(''),
    [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [notice, setNotice] = useState('');
  const setup = renewalBackend && session?.setup_required === true;
  const [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [attempt, setAttempt] = useState(0);
  const accept = (value: Session) => {
    setCsrfToken(value.csrf_token);
    setSession(value);
  };
  const login = async () => {
    if (busy) {
      return;
    }
    setBusy(true);
    setError('');
    try {
      if (setup) {
        if (password !== confirmation) {
          throw new Error('비밀번호 확인이 일치하지 않습니다.');
        }
        await request('/auth/bootstrap', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ username, password }),
        });
        accept(await request<Session>('/auth/session'));
        setNotice('관리자 계정을 생성했습니다. 로그인해 주세요.');
        return;
      }
      const result = await request<Session>('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      setPassword('');
      accept(result);
      setNotice('');
    } catch (e) {
      setPassword('');
      setError(e instanceof Error ? e.message : '로그인에 실패했습니다.');
    } finally {
      setPassword('');
      setConfirmation('');
      setBusy(false);
    }
  };
  const logout = async () => {
    if (busy) {
      return;
    }
    setBusy(true);
    setError('');
    try {
      await request('/auth/logout', { method: 'POST' });
      accept({ enabled: true, user: null });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        accept({ enabled: true, user: null });
      } else {
        setError(e instanceof Error ? e.message : '로그아웃에 실패했습니다.');
      }
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    const abort = new AbortController();
    setError('');
    request<Session>('/auth/session', { signal: abort.signal })
      .then((value) => {
        if (!abort.signal.aborted) {
          accept(value);
        }
      })
      .catch((e) => {
        if (!abort.signal.aborted) {
          setError(e instanceof Error ? e.message : '서버에 연결할 수 없습니다.');
        }
      });
    const expired = () => {
      setSession({ enabled: true, user: null });
      setPassword('');
      setError('세션이 만료되었습니다. 다시 로그인하세요.');
    };
    sessionEvents.addEventListener('expired', expired);
    return () => {
      abort.abort();
      sessionEvents.removeEventListener('expired', expired);
    };
  }, [attempt]);
  if (session && (!session.enabled || session.user)) {
    return (
      <AuthContext.Provider value={{ session, logout: () => void logout(), busy }}>
        {error && (
          <div className="alert" role="alert">
            {error}
          </div>
        )}
        {children}
      </AuthContext.Provider>
    );
  }
  return (
    <Theme mode="light" palette="Indigo" className="auth-shell">
      <header className="auth-header">
        <a className="auth-brand" href="/" aria-label="mideagent 처음으로">
          <span className="auth-brand-symbol" aria-hidden="true">
            <Captions size={23} />
          </span>
          <span>mideagent</span>
        </a>
        <span className="auth-header-note">미디어 작업 공간</span>
      </header>
      <main className="auth-main">
        <section className="auth-panel" aria-labelledby="auth-title">
          <div className="auth-intro">
            <p className="auth-eyebrow">다시 이어가는 작업</p>
            <h1 id="auth-title" className="text-g-title leading-g-title font-semibold">
              {setup ? '최초 관리자 생성' : session ? '작업 공간에 로그인' : '작업 공간 연결'}
            </h1>
            <p className="auth-description">
              {setup
                ? '관리자 계정을 만든 뒤 로그인해 주세요.'
                : session
                  ? '영상과 자막 작업을 이어가세요.'
                  : error
                    ? '서버 연결에 실패했어요. 연결 상태를 확인한 뒤 다시 시도해 주세요.'
                    : '서버 연결과 로그인 상태를 확인하고 있어요.'}
            </p>
          </div>
          {notice && <p role="status">{notice}</p>}
          {error && (
            <div className="auth-error" role="alert">
              <strong>{session ? '로그인하지 못했어요' : '서버에 연결하지 못했어요'}</strong>
              <p>{error}</p>
            </div>
          )}
          {!session ? (
            error ? (
              <div className="auth-connection">
                <p>서버 실행 상태와 네트워크를 확인한 뒤 다시 연결해 주세요.</p>
                <Button className="w-full" onClick={() => setAttempt((n) => n + 1)}>
                  <RefreshCw size={18} aria-hidden="true" />
                  다시 연결
                </Button>
              </div>
            ) : (
              <div className="auth-pending" role="status" aria-live="polite">
                <RefreshCw size={20} className="auth-spinner" aria-hidden="true" />
                <span>연결 중...</span>
              </div>
            )
          ) : (
            <form
              className="auth-form"
              aria-busy={busy}
              onSubmit={(e) => {
                e.preventDefault();
                void login();
              }}
            >
              <div className="auth-fields">
                <TextField
                  label="사용자 이름"
                  autoFocus
                  autoComplete="username"
                  name="username"
                  required
                  maxLength={64}
                  value={username}
                  disabled={busy}
                  onChange={(e) => setUsername(e.target.value)}
                />
                <TextField
                  label="비밀번호"
                  type="password"
                  autoComplete={setup ? 'new-password' : 'current-password'}
                  name="password"
                  required
                  maxLength={256}
                  minLength={renewalBackend ? 12 : undefined}
                  value={password}
                  disabled={busy}
                  onChange={(e) => setPassword(e.target.value)}
                />
                {setup && (
                  <TextField
                    label="비밀번호 확인"
                    name="confirmation"
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={12}
                    maxLength={256}
                    value={confirmation}
                    disabled={busy}
                    onChange={(event) => setConfirmation(event.target.value)}
                  />
                )}
              </div>
              <Button type="submit" className="w-full" loading={busy} disabled={busy}>
                <LogIn size={18} aria-hidden="true" />
                {busy ? '처리 중...' : setup ? '관리자 생성' : '로그인'}
              </Button>
              <p className="auth-form-note">
                {setup
                  ? '아이디 3~64자 · 비밀번호 12~256자'
                  : '이 작업 공간에 등록된 계정으로 로그인해 주세요.'}
              </p>
            </form>
          )}
        </section>
        <p className="auth-footer">영상 보관 · 작업 관리 · 자막 검수</p>
      </main>
    </Theme>
  );
};
