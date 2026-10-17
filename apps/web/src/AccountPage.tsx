import { useState } from 'react';
import { PageTitle } from './PageTitle';
import { Pagination, usePagination } from './Pagination';
import { LogOut } from 'lucide-react';
import { Button } from './hangyeol/primitives/button';
import { TextField } from './hangyeol/components/text-field';
import { issuePreviewAccount, logoutPreview, usePreviewAccounts } from './publishing-accounts';
import './account.css';

export const AccountPage = ({ create = false }: { create?: boolean }) => {
  const { accounts, currentId } = usePreviewAccounts();
  const page = usePagination(accounts, 'accounts');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [error, setError] = useState('');
  const current = accounts.find((row) => row.id === currentId);
  const admin = current?.role === 'admin';
  const issue = () => {
    setError('');
    if (!password || password !== confirmation) {
      setError('비밀번호와 비밀번호 확인이 일치해야 합니다.');
      return;
    }
    try {
      issuePreviewAccount(username);
      setPassword('');
      setConfirmation('');
      location.hash = '/account';
    } catch (value) {
      setError(value instanceof Error ? value.message : '계정을 발급하지 못했습니다.');
    }
  };
  return (
    <main className="serving-page account-page">
      <PageTitle>{create ? '계정 발급' : '계정 관리'}</PageTitle>
      {current && (
        <div className="account-identity">
          <div>
            <strong>{current.username}</strong>
            <span>{admin ? '관리자' : '사용자'}</span>
          </div>
          <Button
            variant="quiet"
            onClick={() => {
              logoutPreview();
              location.hash = '/login';
            }}
          >
            <LogOut size={15} />
            로그아웃
          </Button>
        </div>
      )}
      {!accounts.length ? (
        <div className="account-empty">
          <p>등록된 계정이 없습니다.</p>
          <a className="ui02-primary" href="#/setup">
            관리자 계정 생성
          </a>
        </div>
      ) : !current ? (
        <div className="account-empty">
          <p>로그인이 필요합니다.</p>
          <a className="ui02-primary" href="#/login">
            로그인
          </a>
        </div>
      ) : create ? (
        admin ? (
          <form
            className="page-form account-create"
            onSubmit={(event) => {
              event.preventDefault();
              issue();
            }}
          >
            <TextField
              label="아이디"
              name="new-username"
              autoComplete="off"
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
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
            <TextField
              label="비밀번호 확인"
              name="confirm-password"
              type="password"
              autoComplete="new-password"
              required
              value={confirmation}
              onChange={(event) => setConfirmation(event.target.value)}
            />
            {error && (
              <p role="alert" className="form-error">
                {error}
              </p>
            )}
            <p className="form-note">목업 · 비밀번호를 저장하지 않습니다.</p>
            <div className="form-actions">
              <Button
                variant="quiet"
                onClick={() => {
                  location.hash = '/account';
                }}
              >
                취소
              </Button>
              <Button type="submit">계정 발급</Button>
            </div>
          </form>
        ) : (
          <p role="alert">계정 발급은 관리자만 할 수 있습니다.</p>
        )
      ) : admin ? (
        <section className="account-members" aria-labelledby="members-title">
          <div className="section-heading">
            <h2 id="members-title">계정 목록</h2>
            <a className="ui02-text-action" href="#/account/new">
              계정 발급
            </a>
          </div>
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
                  {row.id === currentId && <small>나</small>}
                </strong>
                <span>{row.role === 'admin' ? '관리자' : '사용자'}</span>
                <time dateTime={row.created_at}>
                  {new Date(row.created_at).toLocaleDateString('ko-KR')}
                </time>
              </div>
            ))}
          </div>
          <Pagination {...page} />
        </section>
      ) : (
        <dl className="account-facts">
          <div>
            <dt>아이디</dt>
            <dd>{current.username}</dd>
          </div>
          <div>
            <dt>권한</dt>
            <dd>사용자</dd>
          </div>
        </dl>
      )}
    </main>
  );
};
