import { useEffect, useRef, useState } from 'react';
import { jsonPost } from './video-api';
import { mediaUrl, request } from './api';
import { Button } from './hangyeol/primitives/button';

type Preview = {
  id?: string;
  state: 'not_requested' | 'queued' | 'running' | 'ready' | 'cancelled' | 'failed' | 'held';
  stage?: string;
  cancel_requested?: boolean;
  can_cancel?: boolean;
  download_url?: string | null;
  error_code?: string | null;
  sha256?: string;
  media?: { duration: number } | null;
};
const labels: Record<Preview['state'], string> = {
  not_requested: '아직 요청하지 않음',
  queued: '대기 중 · 요청은 저장됨',
  running: '생성 중',
  ready: '전체길이 검증·저장 완료',
  cancelled: '취소됨',
  failed: '생성 실패',
  held: '실행 확인 필요 · 자동 재실행 안 함',
};

export const FullVideoPreview = ({ resource }: { resource: string }) => {
  const [snapshot, setSnapshot] = useState<{ resource: string; value: Preview }>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const sequence = useRef(0);
  const value = snapshot?.resource === resource ? snapshot.value : undefined;

  const action = async (path: string) => {
    if (pending.current) {
      return;
    }
    pending.current = true;
    setBusy(true);
    const turn = ++sequence.current;
    try {
      const next = await jsonPost<Preview>(path, {});
      if (turn === sequence.current) {
        setSnapshot({ resource, value: next });
        setError('');
      }
    } catch (reason) {
      if (turn === sequence.current) {
        setError(
          reason instanceof Error
            ? reason.message
            : '요청 결과를 확인하지 못했습니다. 상태 조회로 확인하세요.',
        );
      }
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };
  const ready = !error && value?.state === 'ready' && value.download_url && !value.cancel_requested;
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const load = async () => {
      if (!pending.current) {
        const turn = ++sequence.current;
        try {
          const next = await request<Preview>(resource, { signal: controller.signal });
          if (!controller.signal.aborted && turn === sequence.current) {
            setSnapshot({ resource, value: next });
            setError('');
          }
        } catch (reason) {
          if (!controller.signal.aborted && turn === sequence.current) {
            setError(
              reason instanceof Error ? reason.message : '전체길이 상태를 확인하지 못했습니다.',
            );
          }
        }
      }
      if (!controller.signal.aborted) {
        timer = setTimeout(load, 2000);
      }
    };
    void load();
    return () => {
      ++sequence.current;
      controller.abort();
      clearTimeout(timer);
    };
  }, [resource]);
  return (
    <section
      className="execution-artifact"
      aria-label="전체길이 WebM"
      style={{ minWidth: 0, maxWidth: '100%', overflowWrap: 'anywhere' }}
    >
      <h3>전체길이 WebM</h3>
      <p role="status">
        {error
          ? '최신 상태 확인 실패'
          : value
            ? value.cancel_requested && value.state === 'running'
              ? '취소 처리 중'
              : labels[value.state]
            : '상태 확인 중'}
      </p>
      {error && <p role="alert">{error}</p>}
      {value?.state === 'queued' && (
        <p>별도 실행기가 대기 작업을 처리합니다. 화면을 닫아도 요청은 유지됩니다.</p>
      )}
      {value?.state === 'held' && <p>이전 실행의 종료를 확인하기 전에는 다시 생성하지 않습니다.</p>}
      {value?.error_code && <p>진단: {value.error_code}</p>}
      <p>
        전용 한도: 원본 4 GiB·6시간·8,294,400픽셀/각 변4096, 출력 512 MiB, 전체 처리 4시간, 디스크
        10 GiB, 동시 생성 1개. 30초판·원본과 별도이며 최대치 성능 보장은 아닙니다.
      </p>
      {value?.state === 'not_requested' && (
        <Button disabled={busy || !!error} onClick={() => void action(resource)}>
          전체길이 생성 요청
        </Button>
      )}
      {value?.can_cancel && value.id && (
        <Button
          variant="secondary"
          disabled={busy || !!value.cancel_requested}
          onClick={() => void action('/video-previews/' + value.id + '/cancel')}
        >
          전체길이 생성 취소
        </Button>
      )}
      {ready && value?.download_url && (
        <>
          <video
            controls
            playsInline
            preload="metadata"
            style={{ width: '100%', maxWidth: 960 }}
            src={mediaUrl(value.download_url)}
          />
          <p>
            전체길이 {value.media?.duration.toFixed(3)}초 · SHA256 {value.sha256}
          </p>
          <a href={mediaUrl(value.download_url + '?download=true')} download>
            전체길이 WebM 받기
          </a>
        </>
      )}
    </section>
  );
};
