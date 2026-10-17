import { useState } from 'react';
import { Theme } from './hangyeol/foundation/theme';
import { TextField } from './hangyeol/components/text-field';
import { Button } from './hangyeol/primitives/button';
import { createPreviewAdmin, loginPreview, usePreviewAccounts } from './publishing-accounts';
import './account.css';

export const PublishingAuth = ({ setup: requestedSetup }: { setup: boolean }) => {
  const { accounts } = usePreviewAccounts();
  const setup = requestedSetup || accounts.length === 0;
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [error, setError] = useState('');
  const existingAdmin = setup && accounts.length > 0;
  const submit = () => {
    setError('');
    if (!password || (setup && password !== confirmation)) {
      setError(setup ? '비밀번호와 비밀번호 확인이 일치해야 합니다.' : '비밀번호를 입력해 주세요.');
      return;
    }
    try {
      if (setup) {
        createPreviewAdmin(username);
      } else {
        loginPreview(username);
      }
      setPassword('');
      setConfirmation('');
      location.hash = setup ? '/login' : '/jobs';
    } catch (value) {
      setError(value instanceof Error ? value.message : '입력을 확인해 주세요.');
    }
  };
  return (
    <Theme palette="Indigo" mode="light" className="workspace-theme access-screen">
      <header className="access-header">
        <a href="#/jobs">mideagent</a>
        <span className="preview-mark">목업</span>
      </header>
      <main className="access-main">
        <div className="access-form">
          <h1>{setup ? '관리자 계정 생성' : '로그인'}</h1>
          {existingAdmin ? (
            <>
              <p>관리자 계정이 이미 있습니다.</p>
              <a href="#/login">로그인</a>
            </>
          ) : (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                submit();
              }}
            >
              <TextField
                label="아이디"
                name="username"
                autoComplete="username"
                maxLength={64}
                required
                autoFocus
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
              <TextField
                label="비밀번호"
                name="password"
                type="password"
                autoComplete={setup ? 'new-password' : 'current-password'}
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              {setup && (
                <TextField
                  label="비밀번호 확인"
                  name="confirmation"
                  type="password"
                  autoComplete="new-password"
                  required
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                />
              )}
              {error && (
                <p role="alert" className="form-error">
                  {error}
                </p>
              )}
              <Button type="submit">{setup ? '관리자 계정 생성' : '로그인'}</Button>
              <p className="form-note">목업 · 비밀번호를 저장하거나 인증하지 않습니다.</p>
              {!setup && !accounts.length && <a href="#/setup">관리자 계정 생성</a>}
            </form>
          )}
        </div>
      </main>
    </Theme>
  );
};
