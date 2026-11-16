import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import './model-selection.css';
import {
  catalogPurposeLabel,
  selectCatalogPurpose,
  type CatalogProfileVariant,
} from './model-catalog-purpose';
import { Button } from './hangyeol/primitives/button';
import type { ServingConnection } from './serving-connection';
import type { ModelProfile } from './ModelProfileFields';

export type CatalogModel = {
  id: string;
  label: string;
  profile: ModelProfile | null;
  runtime_uses: string[];
  profile_variants?: Record<string, CatalogProfileVariant>;
  classification_status?: 'supported' | 'unsupported' | 'unknown';
  provider_purpose?: string;
  registration_token?: string;
  evidence: string[];
  reason: string;
};
export type CatalogBinding = { connection_id: string; connection_revision: number };
type Catalog = CatalogBinding & {
  complete: boolean;
  models: CatalogModel[];
  inference_verified: false;
};
const matches = (item: CatalogModel, purpose: string) =>
  purpose === 'all' ||
  (purpose === 'registration' ? !!item.profile : item.runtime_uses.includes(purpose));

export const ModelCatalogPicker = ({
  connection,
  revision,
  model,
  onPick,
  onQueryStart,
  initialPurpose = 'all',
}: {
  initialPurpose?: string;
  connection: ServingConnection;
  revision: number;
  model: string;
  onPick: (item: CatalogModel | null, binding: CatalogBinding) => void;
  onQueryStart: (binding: CatalogBinding) => void;
}) => {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [purpose, setPurpose] = useState(initialPurpose);
  const [search, setSearch] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const binding = { connection_id: connection.id, connection_revision: revision };
  const query = async () => {
    if (
      connection.credential !== 'reference_set' ||
      connection.address_mode === 'legacy_preserved' ||
      connection.active === false ||
      !revision
    ) {
      return;
    }
    const requestId = ++sequence.current;
    controller.current?.abort();
    const signal = new AbortController();
    controller.current = signal;
    setBusy(true);
    setError('');
    setCatalog(null);
    onQueryStart(binding);
    try {
      const result = await request<Catalog>(
        '/settings/serving-connections/' + connection.id + '/model-catalog',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ connection_revision: revision }),
          signal: signal.signal,
        },
      );
      if (!mounted.current || requestId !== sequence.current) {
        return;
      }
      if (
        !result.complete ||
        !Array.isArray(result.models) ||
        result.connection_id !== connection.id ||
        result.connection_revision !== revision
      ) {
        throw new Error('선택한 연결의 완전한 모델 목록을 확인하지 못했습니다.');
      }
      setCatalog(result);
    } catch (value) {
      if (mounted.current && requestId === sequence.current && !signal.signal.aborted) {
        setError(value instanceof Error ? value.message : '공식 모델 목록 조회 실패');
      }
    } finally {
      if (mounted.current && requestId === sequence.current) {
        setBusy(false);
      }
    }
  };
  const currentCatalog =
    catalog?.connection_id === connection.id && catalog?.connection_revision === revision
      ? catalog
      : null;
  const selectedRaw = currentCatalog?.models.find((item) => item.id === model);
  const selected = selectedRaw ? selectCatalogPurpose(selectedRaw, purpose) : undefined;
  const candidates =
    currentCatalog?.models
      .map((item) => selectCatalogPurpose(item, purpose))
      .filter((item) => matches(item, purpose))
      .filter(
        (item) =>
          item.id === model ||
          `${item.id} ${item.label}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()),
      ) || [];
  const noKey = connection.credential !== 'reference_set';
  const legacy = connection.address_mode === 'legacy_preserved';
  useEffect(() => {
    mounted.current = true;
    setCatalog(null);
    setBusy(false);
    setError('');
    return () => {
      mounted.current = false;
      sequence.current++;
      controller.current?.abort();
    };
  }, [connection.id, revision]);
  return (
    <section className="model-catalog-picker" aria-label="공식 모델 조회">
      <p>목록 조회만 진행하며 모델은 실행하지 않습니다.</p>
      {noKey && (
        <p role="status">저장된 API 키가 없습니다. 공급자 설정에서 키를 먼저 등록하세요.</p>
      )}
      {legacy && (
        <p role="status">
          기존 별도 주소·키 연결을 보존 중입니다. 공식 조회에는 새 공식 공급자 연결을 등록하세요.
        </p>
      )}
      <Button
        variant="secondary"
        disabled={busy || noKey || legacy || !revision || connection.active === false}
        onClick={() => void query()}
      >
        {busy ? '공식 목록 조회 중' : '공식 모델 목록 조회'}
      </Button>
      {error && <p role="alert">목록 조회 실패 · {error}</p>}
      {currentCatalog && <p role="status">모델 {currentCatalog.models.length}개</p>}
      <label>
        모델 용도
        <select
          aria-label="모델 용도"
          value={purpose}
          onChange={(event) => {
            setPurpose(event.target.value);
            if (selectedRaw && !busy && !noKey && !legacy && connection.active !== false) {
              const next = selectCatalogPurpose(selectedRaw, event.target.value);
              onPick(matches(next, event.target.value) ? next : null, binding);
            }
          }}
        >
          <option value="all">전체</option>
          <option value="translation">번역</option>
          <option value="transcription">전사 (시간정보 포함)</option>
          <option value="registration">기타 등록 가능 모델</option>
        </select>
      </label>
      <label>
        모델 검색
        <input
          type="search"
          aria-label="공식 모델 검색"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="이름 또는 모델 ID"
        />
      </label>
      <label>
        공식 모델
        <select
          aria-label="공식 모델"
          value={model}
          disabled={!currentCatalog || busy || noKey || legacy || connection.active === false}
          onChange={(event) => {
            if (!currentCatalog || busy || noKey || legacy || connection.active === false) {
              return;
            }
            onPick(candidates.find((item) => item.id === event.target.value) || null, binding);
          }}
        >
          <option value="">목록 조회 후 모델 선택</option>
          {model && !candidates.some((item) => item.id === model) && (
            <option value={model}>{model} · 유지된 입력, 목록 재선택 필요</option>
          )}
          {candidates.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label || item.id}
              {' · ' + catalogPurposeLabel(item)}
            </option>
          ))}
        </select>
      </label>
      {currentCatalog && !candidates.length && <p>이 용도에 확인된 모델이 없습니다.</p>}
      {selected && (
        <details>
          <summary>모델 확인 정보</summary>
          <p>{selected.reason}</p>
        </details>
      )}
    </section>
  );
};
