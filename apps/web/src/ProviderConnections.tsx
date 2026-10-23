import { useEffect, useState } from 'react';
import { PageTitle } from './PageTitle';
import { LoadingSkeleton } from './LoadingSkeleton';
import { Pagination, usePagination } from './Pagination';
import { request } from './api';
import { Button } from './hangyeol/primitives/button';
import { Input } from './hangyeol/primitives/input';
import {
  connectionDefaults,
  isFrontierProvider,
  connectionsEndpoint,
  type ServingConnection,
} from './serving-connection';
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
  const [secret, setSecret] = useState('');
  const [removeSecret, setRemoveSecret] = useState(false);
  const [createdIdentity, setCreatedIdentity] = useState('');
  const [busy, setBusy] = useState('load');
  const [error, setError] = useState('');
  const identity = route.match(/^#\/serving\/connections\/([a-f0-9]{32})(?:\/edit)?$/)?.[1];
  const form = route.endsWith('/edit') || route === '#/serving/connections/new';
  const selected = rows.find((row) => row.id === identity);
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
      const id = identity || createdIdentity || crypto.randomUUID().replaceAll('-', '');
      const saved = await request<ServingConnection>(connectionsEndpoint + '/' + id, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          provider,
          ...(!renewalBackend || !isFrontierProvider(provider)
            ? { endpoint: endpoint.trim() }
            : {}),
          revision,
          ...(renewalBackend && !isFrontierProvider(provider) ? { protocol } : {}),
        }),
      });
      setRevision(saved.revision);
      setCreatedIdentity(id);
      if (renewalBackend && (secret || removeSecret)) {
        try {
          await request<ServingConnection>(connectionsEndpoint + '/' + id + '/credential', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              revision: saved.revision,
              secret: removeSecret ? null : secret,
            }),
          });
        } catch {
          throw new Error(
            '공급자 정보는 저장했지만 API 키는 저장하지 못했습니다. 최신 공급자에서 다시 시도하세요.',
          );
        }
      }
      setSecret('');
      location.hash = '/serving/connections/' + id;
    } catch (value) {
      setError(value instanceof Error ? value.message : '저장하지 못했습니다.');
    } finally {
      setBusy('');
    }
  };
  useEffect(() => {
    setBusy('load');
    setCreatedIdentity('');
    setSecret('');
    setRemoveSecret(false);
    if (!identity) {
      setName('');
      setEndpoint('');
      setRevision(0);
      setProvider(renewalBackend ? 'openai_compatible' : 'openai');
      setProtocol('openai_compatible');
    }
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
  }, [identity, route]);
  return (
    <main className="serving-page">
      <PageTitle>
        {identity
          ? name ||
            (error ? '공급자 조회 실패' : busy === 'load' ? '공급자 상세' : '공급자를 찾을 수 없음')
          : form
            ? '공급자 추가'
            : '공급자'}
      </PageTitle>
      {!form && !identity && <ServingTabs connections />}
      {error && (
        <p className="alert" role="alert">
          {error}
        </p>
      )}
      {busy === 'load' ? (
        <LoadingSkeleton layout={form || identity ? 'form' : 'list'} label="공급자 불러오는 중" />
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
              <select
                value={provider}
                onChange={(event) => {
                  const next = event.target.value;
                  setProvider(next);
                  if (renewalBackend) {
                    const defaults = connectionDefaults[next];
                    if (defaults) {
                      setEndpoint(defaults.endpoint);
                      setProtocol(defaults.protocol);
                    }
                    // Never carry a newly typed key to a different provider.
                    setSecret('');
                    setRemoveSecret(false);
                  }
                }}
              >
                {Object.entries(providers).map(([id, label]) => (
                  <option key={id} value={id}>
                    {renewalBackend && id === 'openai_compatible'
                      ? '사용자 지정 서버 (OpenAI-compatible)'
                      : label}
                  </option>
                ))}
              </select>
            </label>
            {renewalBackend && !isFrontierProvider(provider) && (
              <label>
                API 프로토콜
                <select value={protocol} onChange={(event) => setProtocol(event.target.value)}>
                  <option value="openai_compatible">OpenAI-compatible</option>
                  <option value="openai">OpenAI</option>
                  <option value="gemini">Gemini API</option>
                  <option value="anthropic">Anthropic API</option>
                </select>
              </label>
            )}
            {(!renewalBackend || !isFrontierProvider(provider)) && (
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
            )}
            {renewalBackend && isFrontierProvider(provider) && (
              <p>
                {selected?.provider === provider && selected.address_mode === 'legacy_preserved'
                  ? '기존 별도 주소·프로토콜·키 연결을 그대로 보존합니다. 공식 모델 조회에는 새 공식 공급자 연결을 등록하세요.'
                  : '공식 주소·인증 방식은 서버에서 지정합니다. URL 입력은 필요 없습니다.'}
              </p>
            )}
            <label>
              API 키
              <Input
                type="password"
                disabled={!renewalBackend || removeSecret}
                value={secret}
                maxLength={4096}
                onChange={(event) => setSecret(event.target.value)}
                placeholder={
                  renewalBackend
                    ? '변경할 때만 입력 · DB 암호화 저장, 다시 표시하지 않음'
                    : '목업 · 입력 불가'
                }
                autoComplete="off"
              />
            </label>
            {renewalBackend && identity && (
              <label>
                <input
                  type="checkbox"
                  checked={removeSecret}
                  onChange={(event) => {
                    setRemoveSecret(event.target.checked);
                    setSecret('');
                  }}
                />
                기존 API 키 전체 폐기 · 이전 버전도 사용 중지
              </label>
            )}
          </fieldset>
          {renewalBackend && <p>등록은 연결·모델 호출 성공을 뜻하지 않습니다.</p>}
          <div className="page-actions">
            <Button
              type="submit"
              disabled={!name.trim() || !!busy || (!!identity && revision === 0)}
              loading={busy === 'save'}
            >
              저장
            </Button>
          </div>
        </form>
      ) : identity ? (
        selected && (
          <>
            <dl className="serving-resource-facts">
              <div>
                <dt>공급자</dt>
                <dd>{providers[selected.provider] || selected.provider}</dd>
              </div>
              <div>
                <dt>접속 주소</dt>
                <dd>{selected.endpoint || '기본 주소'}</dd>
              </div>
              {renewalBackend && (
                <div>
                  <dt>API 프로토콜</dt>
                  <dd>{selected.protocol || '미설정'}</dd>
                </div>
              )}
              <div>
                <dt>API 키</dt>
                <dd>{selected.credential === 'reference_set' ? 'DB 암호화 저장됨' : '미설정'}</dd>
              </div>
              <div>
                <dt>연결 확인</dt>
                <dd>미확인</dd>
              </div>
            </dl>
            <div className="page-actions">
              <Button
                onClick={() => {
                  location.hash = '/serving/connections/' + identity + '/edit';
                }}
              >
                수정
              </Button>
            </div>
          </>
        )
      ) : (
        <section className="ui02-list" aria-label="공급자">
          {page.items.map((row) => (
            <a
              key={row.id}
              href={'#/serving/connections/' + row.id}
              className="ui02-list-item provider-resource-row"
            >
              <div className="ui02-list-copy">
                <strong className="ui02-list-title">{row.name}</strong>
                <p className="ui02-list-meta">
                  {[
                    row.name === (providers[row.provider] || row.provider)
                      ? ''
                      : providers[row.provider] || row.provider,
                    row.endpoint || '기본 주소',
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
              </div>
            </a>
          ))}
          {!error && !shown.length && (
            <p className="ui02-empty">{query ? '검색 결과 없음' : '등록된 공급자 없음'}</p>
          )}
        </section>
      )}
      {!form && !identity && !busy && !error && <Pagination {...page} />}
    </main>
  );
};
