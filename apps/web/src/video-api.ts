import { Job, request } from './api';
import { formatStorageGB } from './capacity-format';
export type VideoAsset = {
  web_preview?: {
    status: 'ready' | 'failed' | 'unavailable' | 'deferred';
    excerpt_seconds?: number;
    coverage?: 'full';
  };
  media_kind?: 'audio' | 'image' | 'subtitle';
  media_type?: string;
  asset_id: string;
  original_filename: string;
  uploaded_by?: string | null;
  size_bytes: number;
  processing_supported?: boolean;
  created_at: string;
  media?: {
    duration?: number;
    segments?: number;
    format?: string;
    width?: number;
    height?: number;
    has_audio?: boolean;
    codec?: string;
    orientation?: number;
    sample_rate?: number;
    channels?: number;
    frame_rate?: string;
  };
  provenance: {
    kind: string;
    job_id?: string;
    parent_asset_id?: string;
  };
};
export type VideoUpload = {
  upload_id: string;
  filename: string;
  expected_size: number;
  uploaded_bytes: number;
  status: string;
  asset_id?: string;
  created_at: string;
};
export type SubtitleInput = {
  artifact_id: string;
  filename: string;
  language: string;
  cue_count: number;
  created_at: string;
  provenance: {
    kind: string;
    revision?: number;
  };
};
export type AudioInput = {
  job_id: string;
  created_at: string;
  size_bytes: number;
};
export type VideoDetail = {
  video: VideoAsset;
  jobs: Job[];
};
export const templates: Record<string, string> = {
  faceswap: '얼굴 합성',
  full: '전체 처리',
  extract_audio: '음성 추출',
  transcribe: '전사만',
  transcribe_translate: '전사 + 번역',
  translate: '번역만',
  encode: '인코딩만',
};
export const stageLabels: Record<string, string> = {
  transcription_agent: '전사 에이전트',
  translation_agent: '번역 에이전트',
  subtitle_video_agent: '자막 영상 제작 에이전트',
  subtitle_file_agent: '자막 파일 제작 에이전트',
  video_conversion_agent: '영상 변환 에이전트',
  audio_extraction_agent: '음성 추출 에이전트',
  faceswap: '얼굴 합성',
  analyze: '영상 확인',
  extract_audio: '음성 추출',
  preprocess_audio: '음성 전처리',
  transcribe: '전사',
  translate: '번역',
  generate_subtitle: '자막 저장',
  encode: '인코딩',
  validate_video: '결과 검증',
};
export const statusLabels: Record<string, string> = {
  HELD: '보류 · 응답 확인 필요',
  PROCESSING_REVIEW: '처리 여부 확인 필요',
  FACE_SWAPPING: '얼굴 합성 중',
  UPLOADING: '업로드 중',
  READY: '실행 대기',
  QUEUED: '처리 대기',
  ANALYZING: '영상 분석',
  EXTRACTING_AUDIO: '음성 추출',
  PREPROCESSING_AUDIO: '음성 전처리',
  TRANSCRIBING: '전사 중',
  FILTERING_TRANSCRIPT: '전사 정리',
  TRANSLATING: '번역 중',
  GENERATING_SUBTITLE: '자막 저장',
  AWAITING_REVIEW: '자막 검토',
  ENCODING: '인코딩 중',
  VALIDATING: '결과 검증',
  COMPLETED: '완료',
  FAILED: '실패',
  CANCELLED: '중단됨',
};
export const sizeLabel = (n: number) =>
  Number.isSafeInteger(n) && n >= 0 ? formatStorageGB(n) : '미확인';
export const durationLabel = (n?: number) =>
  n === undefined ? '' : `${Math.floor(n / 60)}분 ${Math.floor(n % 60)}초`;
export const jsonPost = <T>(path: string, body: unknown) =>
  request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
