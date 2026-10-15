# WF-01 · 노드 입출력·서빙 기반

기준0525029fad5b0aa94f3c2180211a200a91e550a8. 다음 캔버스를 위한 기존 실행기 catalog/유형검증·단일 Worker의 논리 역할별 설정이다. 개별 노드/임의 DAG 실행·분산 registry·VPS 분할을 추가한 것이 아니다.

## 실제 재사용 매핑
- video_service.workflows.workflow_plan / media_worker.worker.Worker.process: analyze→extract_audio→preprocess_audio→transcribe→translate→generate_subtitle→encode→validate_video. 영상/음성/시간축/전사/자막/검증결과 유형을 catalog에 정의한다. 고정 template의 모든 stage가 catalog에 있는지 실제 workflow_plan으로 검사했다.
- Worker.process는 media.probe/extract_audio/preprocess_audio, provider.transcribe/translate, shared.subtitles·encoding_args·validation을 호출한다. transcript filtering/timeline restore는 전사 내부 동작, burn은 encode subtitle_mode=burn이지 별도 독립 executor가 아니다.
- 얼굴 합성은 기존 sessions/preview/revision 계약과 media_worker.faceswap.runner.execute 별도 경로다. catalog의 faceswap은 video/session/preview 유형을 요구하며 실제 session·preview 유효성·모델은 기존 실행 API가 판정한다.
- serving.save_serving은 기존 LLMSettingsStore.update에 전사/번역 provider/model/fallback·공유fallback정책을 매핑한다. Worker.process가 기존 resolve 설정을 읽고 GeminiProvider(이름과 달리 다중provider)를 구성하는 경로 그대로다. 임의 endpoint·새 키 저장소·키 교체는 없다. 테스트에서 실제 provider 객체의 OpenAI:whisper-1 identity까지 확인하되 추론은 호출하지 않았다.
- queue/SQLite/owner·고정 template·암호화키·revision source는 변경하지 않는다. FFmpeg/FFprobe·FaceFusion 모델은 현 Worker 환경 지정이라 화면에서 임의 provider/model 저장을 지원하지 않고 이유를 표시한다.

## API와 화면
GET /api/settings/node-catalog, POST /api/settings/node-validation, GET/PUT /api/settings/serving. 기존 settings authorize/CSRF·같은 origin 정책 재사용. JSON8KiB 제한, 미지원 Worker/필드·STT Anthropic/허용목록 밖 모델·같은 primary/fallback 거절. Node검증은 포트 유형/옵션만이고 파일 존재·소유권·시간축·세션/엔진·실제 실행은 확인하지 않는다고 API/UI에 명시한다.
/#/serving은 실제 서버 GET과 PUT에 연결된다. 키관리 UI가 아니며 저장된 키의 출처·마지막 조회 공급자만 노출한다. 저장 성공/모델 목록/Worker 연결·추론을 구분한다. 조회실패는 미확인/저장불가,409는 입력유지/동일stale재시도거절/명시refresh후서버값채택·재선택·새revision저장. 기존 설정 화면과 같은 revision이라 교차편집 충돌도 같은 잠금으로 검출한다.

## 실제 실행 근거
격리 network-none 임시 저장소의 new API/입출력/암호화·설정/기존 workflow 회귀21PASS. 신규5개와 기존16개를 따로 판단하며 다른 전체backend suite를 돌린 것이 아니다. 필수web Node40/lint/format/build/browser타입 통과. 안전API fixture PC1440/390 신규2개 PASS: 조회503→복구→미지원 전사 제외→모델선택→409/동일stale409→명시재조회·재선택→저장·재조회→노드오류유형422/정상200, pageerror0·가로overflow없음.
원 module RED(새 모듈 없음), JSON import attribute 누락, import JSON 빈배열타입의 TS 수정, 실제 헤더sticky 충돌 RED를 보존한다. 신규화면의 local header position/static·checkbox row만 보완했고 최종2개를 재확인했다. 같은2개의 재실행을 새 수로 합산하지 않는다. 기존 Radix/FastAPI·thumbnail fixture 경고도 유지한다.
fixtures/serving.json은 실제 shared serving_settings/node_catalog를 임시 무키 디렉터리에서 생성한 안전계약 자료다. screenshot/events는 명시적fixture이고 실서버 저장이나 추론 성공이 아니다. 최종 배포의 실제 GET/화면/image/SHA 근거는 같은 WF-01에 별도 제출한다.

## 미확인·안전 경계
개별노드실행 API/DAG·버전·분기/합류·AI판단·분산registry는 없음. Worker연결은 미관측이라고 표시하며 모델목록/키보유/저장은 추론성공이 아니다. 실제키/운영설정 저장·GPU/provider/유료·사용자 원본 처리/삭제·Worker/기존대기큐 시작은 하지 않는다. 서버 과금 집행/API우회/계획 원자적 일치 미구현·미검증 유지.
