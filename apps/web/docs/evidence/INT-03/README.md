# INT-03 · 통합 후보 검증 근거

## 범위
feat/faceswap 52fb198...와 보존 WIP 중 source/test/docs 78개를 16a7c6329b96607ade15dcf682ca7c6b6d5f4057로 일반 공유했다. 개인 이미지 첨부 1개는 제외했다. renewal acc5c912...의 한결 UI·실패/stale·유료 명시확인/재확인·request_id·검수/revision·비밀키 재입력 안내와 기능을 조합했다.

## 구현 대응
- 얼굴 합성: FaceSwapDialog/JobDetail/TicketSummary/StageProgress. 기존 source/API/shared/Worker·청크/3.9 브리지/모델 계약 유지. 실제 Button/Input/Badge/Progress 소비와 토큰 기반 레이아웃, 긴 이름/닫기·단일열·마스크 설정.
- 작업 큐: QueuePanel/JobTiming/VideoWorkspace. 큐 순서·pause/revision·선택취소와 자원 대기/복구 표시 유지. 조회 미확인·이전 조회를 정상 빈 큐와 구분.
- 저장 공간: StorageSettings. 기존 안전 정리 API/보호·최대100개 계약 유지. 전체 사용량/본인 작업 구분, 모바일 작업 카드와 명시 삭제 확인. 이번 연결 테스트는 확인을 취소하며 실제 삭제 요청 없음.
- 전사: SettingsPage + feature settings/transport. 공급자별 제한된 STT 모델 선택·전사 fallback 보존. renewal의 키 상태/모델조회와 연결성 구분, 저장실패/충돌 입력 정책 유지.
- 배포 입력: apps/web/Dockerfile의 vendor 선복사 1줄. 운영 전용 Dockerfile만으로 숨기지 않고 실제 source Docker build로 통과 확인.

## 검증과 실패
verification.json 및 logs 참고. 서로 다른 단계/재실행을 테스트 수로 합산하지 않는다. Backend는 feature와 88파일 bytes 대응을 확인해 기존 국소 실행을 재사용했다. Python94개 범위의 최종 결과는93 pass/Windows전용1 skip, 별도 STT/청크/설정/유료guard/실행·lifecycle49 pass. Node40 pass, 타입 포함 빌드·lint·format·browser 타입 통과. 브라우저 고유12개: 신규2(1440/390), workflow4/ticket3/settings3. 첫 settings3 실패는 새 저장소/catalog 응답 없는 fixture 문제였고 fixture만 보완해 해당3개 재확인했다. 이전 S1 증거 파일은 덮어쓰지 않고 regression-*에 저장했다.

## 화면·동선
*-view-* 파일은 최종 viewport 캡처, 기존 짧은 이름 PNG는 최초 fullpage 캡처 이력이다. journey-1440/390.json은 안전fixture 연결 요청만 담는다. 검수 대기/합성/결과 전환은 fixture에서 공급한 상태다. 실제 엔진/모델·미디어 처리/재생·다운로드/성능·과금 성공을 뜻하지 않는다.

## 운영과 승인 경계
S2 소스는 운영에 배포하지 않았다. 긴급 요청의 기존 승인 배포 임시 무인증은 별도로 처리했으며 그 설정/비공개 주소/실제 데이터는 Git에 포함하지 않는다. 원본 stash/bundle/데이터/DB/키 보존. 실제 GPU/provider/유료·사용자 삭제·Worker 시작·master merge·registry 발행 없음. 혜지의 기획/UI 리뷰 요청 후보이며 S2 자동 완료가 아니다.
