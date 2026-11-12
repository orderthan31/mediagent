import { useEffect, useRef, useState } from 'react';
import { request } from './api';
import type { VideoAsset } from './video-api';
import { PageTitle } from './PageTitle';
import { Button } from './hangyeol/primitives/button';
import './saved-subtitle-render.css';

type Engine = { role: string; revision: number; sha256: string; engine: string };
type Choices = {
  engines: Engine[];
  reason: string;
  options: { preset: string[]; video_codec: string[] };
  execution_reasons: string[];
};
type Plan = {
  token: string;
  input_ready: boolean;
  execution_ready: false;
  input_reasons: string[];
  execution_reasons: string[];
};
const labels: Record<string, string> = {
  fast: '빠르게',
  balanced: '균형',
  quality: '높은 품질',
  h264: 'H.264',
  hevc: 'HEVC',
};
/** Preparation only: explicit read-only input check, no execution or preview authority. */
export const FaceInputPreparation = () => {
  const initial = new URLSearchParams(location.hash.split('?')[1] || '');
  const [photoId, setPhotoId] = useState(initial.get('photo') || '');
  const [targetId, setTargetId] = useState(initial.get('target') || '');
  const [assets, setAssets] = useState<VideoAsset[]>([]);
  const [choices, setChoices] = useState<Choices | null>(null);
  const [engineKey, setEngineKey] = useState('');
  const [preset, setPreset] = useState('');
  const [codec, setCodec] = useState('');
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [error, setError] = useState('');
  const [checking, setChecking] = useState(false);
  const [plan, setPlan] = useState<{ key: string; value: Plan } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const pending = useRef<AbortController | null>(null);
  const photos = assets.filter((a) => a.media_kind === 'image');
  const targets = assets.filter((a) => !a.media_kind);
  const photo = photos.find((a) => a.asset_id === photoId);
  const target = targets.find((a) => a.asset_id === targetId);
  const engine = choices?.engines.find((e) => `${e.revision}:${e.sha256}` === engineKey);
  const selection = {
    photo_asset_id: photoId,
    target_asset_id: targetId,
    engine_revision: engine?.revision ?? null,
    engine_sha256: engine?.sha256 ?? null,
    settings_revision: 1,
    preset,
    video_codec: codec,
  };
  const key = JSON.stringify(selection);
  const current = plan?.key === key ? plan.value : null;
  const canCheck =
    !!photo &&
    !!target &&
    !!choices?.options.preset.includes(preset) &&
    !!choices?.options.video_codec.includes(codec) &&
    !loading &&
    !loadError &&
    !checking;
  const message = (e: unknown) => (e instanceof Error ? e.message : '입력을 확인하지 못했습니다.');
  const invalidate = () => {
    pending.current?.abort();
    setChecking(false);
    setPlan(null);
    setError('');
  };
  const pick = (kind: 'photo' | 'target', id: string) => {
    invalidate();
    if (kind === 'photo') {
      setPhotoId(id);
    } else {
      setTargetId(id);
    }
    const query = new URLSearchParams();
    const p = kind === 'photo' ? id : photoId,
      t = kind === 'target' ? id : targetId;
    if (p) {
      query.set('photo', p);
    }
    if (t) {
      query.set('target', t);
    }
    history.replaceState(null, '', '#/start/faceswap' + (query.size ? '?' + query.toString() : ''));
  };
  const inspect = async () => {
    if (!canCheck) {
      return;
    }
    const controller = new AbortController();
    pending.current = controller;
    setChecking(true);
    setPlan(null);
    setError('');
    try {
      const value = await request<Plan>('/work-entry/faceswap-inputs/inspect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(selection),
        signal: controller.signal,
      });
      if (!controller.signal.aborted) {
        if (
          !/^[a-f0-9]{64}$/.test(value.token) ||
          value.execution_ready !== false ||
          !Array.isArray(value.execution_reasons) ||
          typeof value.input_ready !== 'boolean'
        ) {
          throw new Error('입력 확인 응답을 다시 확인하세요.');
        }
        setPlan({ key, value });
      }
    } catch (e) {
      if (!controller.signal.aborted) {
        setError(message(e));
      }
    } finally {
      if (!controller.signal.aborted) {
        setChecking(false);
      }
    }
  };
  useEffect(() => {
    const c = new AbortController();
    setLoading(true);
    setLoadError('');
    setChoices(null);
    setPlan(null);
    void Promise.all([
      request<{ videos: VideoAsset[] }>('/videos', { signal: c.signal }),
      request<Choices>('/work-entry/faceswap-inputs', { signal: c.signal }),
    ])
      .then(([originals, options]) => {
        if (!c.signal.aborted) {
          setAssets(originals.videos);
          setChoices(options);
        }
      })
      .catch((e) => {
        if (!c.signal.aborted) {
          setLoadError(message(e));
        }
      })
      .finally(() => {
        if (!c.signal.aborted) {
          setLoading(false);
        }
      });
    return () => {
      c.abort();
      pending.current?.abort();
    };
  }, [attempt]);
  return (
    <main className="video-main direct-subtitle-page saved-subtitle-render">
      <PageTitle>얼굴 합성 입력 준비</PageTitle>
      <a href="#/">원본 목록</a>
      <p>
        사진 한 장과 대상 영상, 등록 실행기와 출력 설정을 확인합니다. 얼굴 검출·미리보기·합성은
        실행하지 않습니다.
      </p>
      {loading && <p role="status">원본·등록 실행기 불러오는 중</p>}
      {loadError && (
        <>
          <p role="alert">{loadError}</p>
          <Button onClick={() => setAttempt((v) => v + 1)}>목록 다시 확인</Button>
        </>
      )}
      <div className="saved-render-fields">
        <label>
          원본 사진
          <select
            aria-label="원본 사진"
            value={photoId}
            disabled={loading || !!loadError}
            onChange={(e) => pick('photo', e.target.value)}
          >
            <option value="">사진 선택</option>
            {photos.map((a) => (
              <option key={a.asset_id} value={a.asset_id}>
                {a.original_filename}
              </option>
            ))}
          </select>
        </label>
        <label>
          대상 영상
          <select
            aria-label="대상 영상"
            value={targetId}
            disabled={loading || !!loadError}
            onChange={(e) => pick('target', e.target.value)}
          >
            <option value="">영상 선택</option>
            {targets.map((a) => (
              <option key={a.asset_id} value={a.asset_id}>
                {a.original_filename}
              </option>
            ))}
          </select>
        </label>
        {photo && (
          <p>
            {photo.original_filename}
            <br />
            {photo.media_type} · {photo.media?.width} × {photo.media?.height}
          </p>
        )}
        {target && (
          <p>
            {target.original_filename}
            <br />
            {target.media?.duration}초 · {target.media?.width} × {target.media?.height}
          </p>
        )}
        <label>
          등록 실행기
          <select
            aria-label="등록 실행기"
            value={engineKey}
            disabled={!choices?.engines.length}
            onChange={(e) => {
              invalidate();
              setEngineKey(e.target.value);
            }}
          >
            <option value="">실행기 선택</option>
            {choices?.engines.map((e) => (
              <option key={e.sha256 + e.revision} value={`${e.revision}:${e.sha256}`}>
                {e.engine} · v{e.revision}
              </option>
            ))}
          </select>
        </label>
        <p>{choices?.reason || '등록 정보이며 실제 실행 상태는 확인하지 않았습니다.'}</p>
        <label>
          품질
          <select
            aria-label="품질"
            value={preset}
            disabled={!choices}
            onChange={(e) => {
              invalidate();
              setPreset(e.target.value);
            }}
          >
            <option value="">품질 선택</option>
            {choices?.options.preset.map((v) => (
              <option key={v} value={v}>
                {labels[v] || v}
              </option>
            ))}
          </select>
        </label>
        <label>
          영상 형식
          <select
            aria-label="영상 형식"
            value={codec}
            disabled={!choices}
            onChange={(e) => {
              invalidate();
              setCodec(e.target.value);
            }}
          >
            <option value="">형식 선택</option>
            {choices?.options.video_codec.map((v) => (
              <option key={v} value={v}>
                {labels[v] || v}
              </option>
            ))}
          </select>
        </label>
      </div>
      <p>사진은 JPEG·PNG 10MiB·2400만 화소 이내, 영상은 30초·1280×720·256MiB 이내입니다.</p>
      {!loading && !loadError && ((!!photoId && !photo) || (!!targetId && !target)) && (
        <p role="alert">선택 원본을 확인할 수 없습니다. 목록에서 다시 선택하세요.</p>
      )}
      {error && <p role="alert">{error}</p>}
      {checking && <p role="status">입력 확인 중</p>}
      {current && (
        <section aria-label="입력 확인 결과">
          <p role="status">
            {current.input_ready ? '원본·설정 입력을 확인했습니다.' : '입력 선택을 확인하세요.'}
          </p>
          {current.input_reasons.map((r) => (
            <p key={r}>{r}</p>
          ))}
        </section>
      )}
      <a
        href={`#/start?photo=${encodeURIComponent(photoId)}&target=${encodeURIComponent(targetId)}`}
      >
        저장된 얼굴 합성 워크플로우 선택
      </a>
      <div className="direct-subtitle-actions">
        <Button disabled={!canCheck} onClick={() => void inspect()}>
          입력 확인
        </Button>
        <Button disabled aria-describedby="face-execution-reasons">
          작업 시작
        </Button>
      </div>
      <section id="face-execution-reasons" aria-label="시작할 수 없는 이유">
        <h2>실행 준비는 아직 확인되지 않았습니다.</h2>
        {(
          current?.execution_reasons ||
          choices?.execution_reasons || ['인물 선택과 승인 미리보기가 필요합니다.']
        ).map((r) => (
          <p key={r}>{r}</p>
        ))}
      </section>
    </main>
  );
};
