import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import { Button } from './hangyeol/primitives/button';
import type { ServingConnection } from './serving-connection';
import type { ModelProfile } from './ModelProfileFields';

export type CatalogModel = {
  id: string;
  label: string;
  profile: ModelProfile | null;
  runtime_uses: string[];
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
}: {
  connection: ServingConnection;
  revision: number;
  model: string;
  onPick: (item: CatalogModel | null, binding: CatalogBinding) => void;
  onQueryStart: (binding: CatalogBinding) => void;
}) => {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [purpose, setPurpose] = useState('all');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const sequence = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(false);
  const binding = { connection_id: connection.id, connection_revision: revision };
  const query = async () => {
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
  const selected = catalog?.models.find((item) => item.id === model);
  const candidates = catalog?.models.filter((item) => matches(item, purpose)) || [];
  const noKey = connection.credential !== 'reference_set';
  const legacy = connection.address_mode === 'legacy_preserved';
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      sequence.current++;
      controller.current?.abort();
    };
  }, []);
  return (
    <section className="serving-help model-catalog-picker" aria-label="공식 모델 조회">
      <p>
        저장된 연결의 키로 서버에서 공식 모델 목록만 조회합니다. 생성·전사·번역은 실행하지 않습니다.
      </p>
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
        disabled={busy || noKey || legacy || !revision}
        onClick={() => void query()}
      >
        {busy ? '공식 목록 조회 중' : '공식 모델 목록 조회'}
      </Button>
      {error && <p role="alert">목록 조회 실패 · {error}</p>}
      {catalog && (
        <p role="status">
          공식 목록 {catalog.models.length}개 조회됨 · 실제 모델 실행·품질은 미검증
        </p>
      )}
      <label>
        모델 용도
        <select
          aria-label="모델 용도"
          value={purpose}
          onChange={(event) => {
            setPurpose(event.target.value);
            if (selected && !matches(selected, event.target.value)) {
              onPick(null, binding);
            }
          }}
        >
          <option value="all">전체 · 용도 미확인 포함</option>
          <option value="translation">번역 · 현재 어댑터 후보</option>
          <option value="transcription">전사 · 시간정보 어댑터 후보</option>
          <option value="registration">분류 확인 · 등록용 메타데이터</option>
        </select>
      </label>
      <label>
        공식 모델
        <select
          aria-label="공식 모델"
          value={model}
          disabled={!catalog || busy}
          onChange={(event) => {
            onPick(catalog?.models.find((item) => item.id === event.target.value) || null, binding);
          }}
        >
          <option value="">목록 조회 후 모델 선택</option>
          {model && !candidates.some((item) => item.id === model) && (
            <option value={model}>{model} · 유지된 입력, 목록 재선택 필요</option>
          )}
          {candidates.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label || item.id}
              {!item.profile
                ? ' · 용도 미확인'
                : !item.runtime_uses.length
                  ? ' · 등록만 가능, 실행 어댑터 미지원'
                  : ''}
            </option>
          ))}
        </select>
      </label>
      {catalog && !candidates.length && (
        <p>이 용도에 확인된 모델이 없습니다. 목록 조회 성공을 실행 지원으로 간주하지 않습니다.</p>
      )}
      {selected && <p>{selected.reason}</p>}
    </section>
  );
};
