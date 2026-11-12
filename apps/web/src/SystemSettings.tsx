import { PageTitle } from './PageTitle';
import './system-settings.css';
export const SystemSettings = () => (
  <main className="settings-page">
    <PageTitle>시스템</PageTitle>
    <nav className="system-settings-links" aria-label="설정 항목">
      <a href="#/serving/connections">
        공급자·API 키 설정 <span aria-hidden="true">›</span>
      </a>
      <a href="#/serving">
        모델 설정 <span aria-hidden="true">›</span>
      </a>
      <a href="#/workflows">
        워크플로우 설정 <span aria-hidden="true">›</span>
      </a>
    </nav>
  </main>
);
