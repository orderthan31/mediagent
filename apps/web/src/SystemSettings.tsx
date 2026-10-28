import { PageTitle } from './PageTitle';
export const SystemSettings = () => (
  <main className="settings-page">
    <PageTitle>시스템</PageTitle>
    <section>
      <h2>공급자와 API 키</h2>
      <p>등록된 연결과 API 키를 확인하고 변경합니다.</p>
      <a href="#/serving/connections">공급자·API 키 설정</a>
    </section>
    <section>
      <h2>모델</h2>
      <p>사용할 전사·번역 모델을 추가하고 수정합니다.</p>
      <a href="#/serving">모델 설정</a>
    </section>
    <section>
      <h2>작업 설정</h2>
      <p>저장된 워크플로우의 모델과 언어를 수정합니다.</p>
      <a href="#/workflows">워크플로우 설정</a>
    </section>
  </main>
);
