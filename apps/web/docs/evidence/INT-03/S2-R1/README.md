# S2-R1 · STT revision 충돌 근거 보완

기준 parent: 06f8ce0844bd2b6aa8636e6e5b193c8182ed628c. 앱 source/API/shared/Worker·배포 설정은 변경하지 않는다. 기존 INT-03의 원 화면/요청/실패·README/manifest는 당시 제출 이력 그대로 보존하며 이 하위 디렉터리만 새 보완 근거다.

## 수정
- 서버 충돌 fixture는 revision1에서2로 변경한다. 모든 다른 revision PUT은409로 거절하고 실제 설정은 바꾸지 않는다. 실제 LLMSettingsStore의 revision 불일치 거절/성공 시 증가 계약에 맞췄다.
- 최초409 직후 OpenAI/whisper-1 일반 입력 보존을 확인한다. GET 없이 같은 revision1 재시도도409이고 성공 안내가 없다.
- 사용자가 명시적으로 설정 새로 불러오기를 눌러 서버 revision2/Gemini/fixture-gemini를 채택한다. 이전 편집/삭제 의도를 자동보존한다고 기록하지 않는다.
- OpenAI 재선택→모델 공란→whisper-1 재선택→PUT revision2→200/server revision3과 성공 안내를 확인한다.
- ledger는 최초 StrictMode의 GET200/revision1 두 번과 이후 PUT1/409→PUT1/409→GET200/revision2→PUT2/200/revision3을 그대로 기록한다. 초기 GET 횟수를 고정1로 가정하지 않는다. stale 재시도 사이 자동 GET 없음도 별도 assert한다.

## 실행/실패와 범위
1440/390 기존 연결2개를 보완하여 최종2PASS, pageerror0. 최초 RED2개는 기존 fixture가 stale retry를 성공시켜 오류가 없다는 assertion으로 실패했다. fixture 교정 후 초기 GET1개라는 test 가정 때문에2개가 실패했고 StrictMode의 초기GET2개를 분리한 뒤 최종2PASS했다. 모두 같은2개의 재실행이지 새 테스트 수가 아니다.
저장소 필수 commit 검사 lint/format:check/npm test40/build와 browser 타입검사 통과. 다른 browser suite/Python/모델/전체 검사를 추가 실행하지 않았다. 기존12개 수치는 원9PASS/3FAIL+settings3PASS 국소 재실행 이력으로 유지하며 이번2개와 합산하지 않는다.

## 화면
stale-rejected-*:409 실패 안내. server-settings-reloaded-*:편집을 서버 Gemini 값으로 교체. stt-reselected-saved-*:사용자가 OpenAI/whisper-1을 다시 선택한 상태. 총6캡처는2개의3시점이다. 충족된 얼굴/큐/티켓/저장소 화면은 재촬영하지 않았다. 이어지는 기존 연결 행동은 그대로 실행하되 새 화면은 STT 보완만 저장한다.

## 경계
안전 API fixture다. 실제 provider/GPU/유료 호출·삭제/키변경·Worker 시작·S2 운영배포·자동 인증 원복은 없다. 기존 승인 이미지+임시무인증/단일 배포를 유지한다. 서버 과금 집행/API 우회 방지/계획 원자적 일치의 별도 미구현·미검증도 유지한다.
