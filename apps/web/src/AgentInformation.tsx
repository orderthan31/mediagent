import type { Agent } from './AgentCatalog';
// Read-only descriptions derived from baseline native adapters, decision_adapter,
// registered_nodes and model_registry.compatible_uses; not runtime readiness.
type Profile = { role: string; api: string; engine: string; model: string; conditions: string[]; providers?: string; access?: string };
const profiles: Record<string, Profile> = {
  analyze: { role: '영상 구조·길이·스트림 분석', api: '불필요', engine: '로컬 ffprobe · CPU', model: '불필요', conditions: ['읽을 수 있는 영상 파일'] },
  extract_audio: { role: '영상에서 오디오 추출', api: '기본 추출 불필요 · 기존 경로의 부가 발성분석은 Gemini API 조건부', engine: '로컬 FFmpeg · CPU', model: '기본 추출 불필요', conditions: ['오디오 스트림이 있는 영상', '출력: 모노 16kHz PCM 오디오'] },
  preprocess_audio: { role: '음성 전처리·타임라인 매핑', api: '기본 전처리 불필요', engine: '로컬 FFmpeg · CPU / NVIDIA VAD 선택 시 별도 GPU·모델', model: '기본 전처리 불필요 · NVIDIA VAD 모델 조건부', conditions: ['PCM WAV 오디오', 'NVIDIA VAD: 기존 고정 처리 경로용 · 새 순차/병렬 어댑터 미지원', '유료 발성분석이 켜진 새 전처리 경로 미지원'] },
  transcribe: { role: '음성 인식·구간별 전사', api: '필수 · 현재 제공 어댑터는 외부 음성 인식 API', engine: '로컬 오디오 분할 + 외부 음성 인식', model: '오디오 전사 지원 모델', providers: 'Gemini · OpenAI · xAI · OpenRouter (허용 전사 모델 한정)', access: '오디오 전송 · 영상/이미지 원본 입력 없음', conditions: ['오디오와 동일 생산 경로의 타임라인', '로컬 전사 모델 어댑터 미제공'] },
  translate: { role: '전사문을 대상 언어로 번역', api: '필수 · 현재 제공 어댑터는 외부 텍스트 API', engine: '외부 텍스트 모델', model: '텍스트 번역 지원 모델', providers: 'Gemini · OpenAI · xAI · OpenRouter · Anthropic (호환 모델 한정)', access: '전사문 텍스트 · 영상/이미지 원본 전송 없음', conditions: ['시간 정보가 있는 전사문 · 대상 언어', '로컬 번역 모델 어댑터 미제공'] },
  generate_subtitle: { role: '전사 구간을 SRT 자막으로 구성', api: '불필요', engine: '로컬 자막 처리 · ffprobe · CPU', model: '불필요', conditions: ['시간 정보가 있는 전사문', '원본 영상 길이에 맞는 자막 구간'] },
  encode: { role: '영상 인코딩·자막 번인/내장', api: '불필요', engine: '로컬 FFmpeg · 새 어댑터는 CPU / 기존 경로는 NVENC 또는 CPU', model: '불필요', conditions: ['영상 필수', '자막: 번인/내장 시 필수 · 자막 없음 모드에서는 생략 가능'] },
  validate_video: { role: '출력 영상·코덱·재생 가능 여부 검증', api: '불필요', engine: '로컬 ffprobe·FFmpeg · CPU', model: '불필요', conditions: ['인코딩 결과 영상', '원본 정보·인코딩 옵션에 맞춰 검증'] },
  faceswap: { role: '얼굴 합성', api: '외부 LLM API 불필요', engine: '로컬 FaceFusion · 전용 Python 환경', model: 'FaceFusion 로컬 모델', conditions: ['합성 세션·미리보기 필수', '실행 provider·CUDA 등 자원은 FaceFusion 환경에 따름', '별도 합성 실행 경로 · 새 순차 어댑터 미지원'] },
  decision: { role: 'LLM 구조화 판단·조건 경로 선택', api: '판단 어댑터 필요 · 기본 등록 어댑터는 외부 API', engine: '구조화 JSON 응답 검증', model: 'decision 용도 호환 모델 · 구조화 JSON 응답 필수', providers: 'Gemini · OpenAI · xAI · OpenRouter · Anthropic (등록 호환 모델 한정)', access: '텍스트/JSON 내용 또는 영상·오디오 메타데이터만 전달', conditions: ['영상·오디오: 메타데이터만 전달 · 원본 바이트 전송 없음', '텍스트/JSON: UTF-8 · 1MiB 이하', '이미지 원본 입력·영상/이미지 멀티모달 모델 전송 미지원', '출력: pass/review/reject · confidence 0~1 · reason', '기본 로컬 판단 모델 어댑터 미제공'] },
  review: { role: '사람 검수·승인 대기', api: '불필요', engine: '검수 상태·자료 처리 · CPU', model: '불필요', conditions: ['선택한 자료 유형의 입력', '후속 진행은 사람의 명시적 승인 필요'] },
  select: { role: '선택한 경로로 자료 전달', api: '불필요', engine: '로컬 흐름 제어 · CPU', model: '불필요', conditions: ['선택한 자료 유형의 입력', '경로 A / B / 양쪽 선택', 'AI 자동 판단 아님'] },
  join: { role: '선택된 결과 참조를 목록으로 합류', api: '불필요', engine: '로컬 결과 참조 처리 · CPU', model: '불필요', conditions: ['서로 다른 유형의 입력 허용', '출력은 결과 참조 목록 · 영상/오디오 병합 아님'] },
};
const types: Record<string, string> = { video: '영상', audio: '오디오', transcript: '전사문 JSON', subtitle: '자막 UTF-8', media_metadata: '영상 정보 JSON', timeline_map: '타임라인 JSON', validation_report: '검증 결과 JSON', decision_result: '판단 결과 JSON', artifact_manifest: '결과 목록 JSON', faceswap_session: '합성 세션', faceswap_preview: '합성 미리보기' };
export const AgentInformation = ({ agent }: { agent: Agent }) => {
  const profile = profiles[agent.id];
  const portRows = (side: 'inputs' | 'outputs') => <dl className="ui02-agent-ports">{Object.entries(agent[side]).map(([port, type]) => {
    const option = agent.port_types_from_options?.[side]?.[port];
    const kinds = option ? agent.options[option] || [type] : [type];
    return <div key={port}><dt><code>{port}</code>{side === 'inputs' && <span className="ui02-revision">{agent.optional_inputs.includes(port) ? '조건부' : '필수'}</span>}</dt><dd>{kinds.map(kind => <span className="ui02-agent-chip" key={kind}>{types[kind] || kind}</span>)}</dd></div>;
  })}</dl>;
  return <div className="ui02-agent-detail">
    <section className="ui02-definition-summary"><h2>처리 정보</h2><dl className="ui02-agent-facts">
      {([['처리 역할', profile?.role], ['식별자', agent.id], ['API 연동', profile?.api], ['실행 자원', profile?.engine], ['모델 능력', profile?.model], ...(profile?.providers ? [['지원 어댑터', profile.providers]] : []), ...(profile?.access ? [['모델 전달 범위', profile.access]] : [])]).map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value || '미제공'}</dd></div>)}
    </dl></section>
    <section className="ui02-definition-summary"><h2>받는 입력</h2>{portRows('inputs')}</section>
    <section className="ui02-definition-summary"><h2>출력</h2>{portRows('outputs')}</section>
    <section className="ui02-definition-summary"><h2>필수 조건·지원 범위</h2><ul className="ui02-agent-conditions">{profile ? profile.conditions.map(condition => <li key={condition}>{condition}</li>) : <li>추가 조건 정보 미제공</li>}</ul></section>
  </div>;
};
