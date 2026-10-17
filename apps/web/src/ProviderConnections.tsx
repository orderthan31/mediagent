import { useEffect, useState } from 'react';
import { ChevronRight, KeyRound } from 'lucide-react';
import { PageTitle } from './PageTitle';
import { Pagination, usePagination } from './Pagination';
import { request } from './api';
import { Button } from './hangyeol/primitives/button';
import { Input } from './hangyeol/primitives/input';
import { connectionsEndpoint, type ServingConnection } from './serving-connection';
import { renewalBackend } from './preview';
import './serving-connections.css';

export const ServingTabs = ({ connections = false }: { connections?: boolean }) => (
  <nav className="serving-tabs" aria-label="서빙 구분">
    <a href="#/serving" aria-current={!connections ? 'page' : undefined}>
      모델
    </a>
    <a href="#/serving/connections" aria-current={connections ? 'page' : undefined}>
      공급자
    </a>
  </nav>
);
export const ProviderConnections = ({ route, query }: { route: string; query: string }) => {
  const [rows, setRows] = useState<ServingConnection[]>([]);
  const [providers, setProviders] = useState<Record<string, string>>({});
  const [name, setName] = useState('');
  const [provider, setProvider] = useState(renewalBackend ? 'openai_compatible' : 'openai');
  const [protocol, setProtocol] = useState('openai_compatible');
  const [endpoint, setEndpoint] = useState('');
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState('load');
  const [error, setError] = useState('');
  const identity = route.match(/^#\/serving\/connections\/([a-f0-9]{32})\/edit$/)?.[1];
  const form = !!identity || route === '#/serving/connections/new';
  const shown = rows.filter((row) =>
    `${row.name} ${providers[row.provider] || row.provider}`
      .toLocaleLowerCase()
      .includes(query.toLocaleLowerCase()),
  );
  const page = usePagination(shown, query);
  const save = async () => {
    if (!name.trim() || busy) {
      return;
    }
    setBusy('save');
    setError('');
    try {
      const id = identity || crypto.randomUUID().replaceAll('-', '');
      await request<ServingConnection>(connectionsEndpoint + '/' + id, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          provider,
          endpoint: endpoint.trim(),
          revision,
          ...(renewalBackend ? { protocol } : {}),
        }),
      });
      location.hash = '/serving/connections';
    } catch (value) {
      setError(value instanceof Error ? value.message : '저장하지 못했습니다.');
    } finally {
      setBusy('');
    }
  };
  useEffect(() => {
    const controller = new AbortController();
    void request<{ connections: ServingConnection[]; providers: Record<string, string> }>(
      connectionsEndpoint,
      { signal: controller.signal },
    )
      .then((result) => {
        if (controller.signal.aborted) {
          return;
        }
        setRows(result.connections);
        setProviders(result.providers);
        if (identity) {
          const selected = result.connections.find((row) => row.id === identity);
          if (!selected) {
            throw new Error('공급자를 찾을 수 없습니다.');
          }
          setName(selected.name);
          setProvider(selected.provider);
          setProtocol(selected.protocol || 'openai_compatible');
          setEndpoint(selected.endpoint);
          setRevision(selected.revision);
        }
      })
      .catch((value) => {
        if (!controller.signal.aborted) {
          setError(value instanceof Error ? value.message : '불러오지 못했습니다.');
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setBusy('');
        }
      });
    return () => controller.abort();
  }, [identity]);
  return (
    <main className="serving-page">
      <PageTitle>
        {form ? (identity ? name || '공급자 불러오는 중' : '공급자 추가') : '공급자'}
      </PageTitle>
      {!form && <ServingTabs connections />}
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {busy === 'load' ? (
        <p role="status">불러오는 중</p>
      ) : form ? (
        <form
          className="connection-form"
          onSubmit={(event) => {
            event.preventDefault();
            void save();
          }}
        >
          <fieldset disabled={!!busy || (!!identity && revision === 0)}>
            <label>
              이름
              <Input
                value={name}
                maxLength={80}
                onChange={(event) => setName(event.target.value)}
                required
              />
            </label>
            <label>
              공급자
              <select value={provider} onChange={(event) => setProvider(event.target.value)}>
                {Object.entries(providers).map(([id, label]) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            {renewalBackend && (
              <label>
                API 프로토콜
                <select value={protocol} onChange={(event) => setProtocol(event.target.value)}>
                  <option value="openai_compatible">OpenAI-compatible</option>
                  <option value="openai">OpenAI</option>
                  <option value="gemini">Gemini · 실행 연결 준비 중</option>
                  <option value="anthropic">Anthropic · 실행 연결 준비 중</option>
                </select>
              </label>
            )}
            <label>
              {renewalBackend ? 'API 기본 주소' : '접속 주소 · 선택'}
              <Input
                value={endpoint}
                maxLength={2048}
                required={renewalBackend}
                placeholder={renewalBackend ? 'http://localhost:8000/v1' : '기본 주소 사용'}
                onChange={(event) => setEndpoint(event.target.value)}
              />
            </label>
            <label>
              API 키
              <Input
                type="password"
                disabled
                value=""
                placeholder={
                  renewalBackend
                    ? '보안 참조 연결 준비 중 · 현재 무키 연결만 등록'
                    : '목업 · 입력 불가'
                }
                autoComplete="off"
              />
            </label>
            <Button type="submit" disabled={!name.trim()} loading={busy === 'save'}>
              저장
            </Button>
          </fieldset>
        </form>
      ) : (
        <section className="ui02-list" aria-label="공급자">
          {page.items.map((row) => (
            <a
              key={row.id}
              href={'#/serving/connections/' + row.id + '/edit'}
              className="ui02-list-item connection-row"
            >
              <KeyRound size={22} />
              <div className="ui02-list-copy">
                <strong className="ui02-list-title">{row.name}</strong>
                <p className="ui02-list-meta">
                  {providers[row.provider] || row.provider} ·{' '}
                  {row.credential === 'reference_set' ? '키 참조 설정' : '키 미설정'}
                </p>
              </div>
              <ChevronRight size={18} />
            </a>
          ))}
          {!error && !shown.length && (
            <p className="ui02-empty">{query ? '검색 결과 없음' : '등록된 공급자 없음'}</p>
          )}
        </section>
      )}
      {!form && !busy && !error && <Pagination {...page} />}
    </main>
  );
};
