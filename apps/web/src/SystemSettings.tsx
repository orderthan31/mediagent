import { PageTitle } from './PageTitle';
import { StorageOverview } from './StorageOverview';
import './system-settings.css';
export const SystemSettings = ({ storage = false }: { storage?: boolean }) => (
  <main className="settings-page">
    <PageTitle>{storage ? '저장소 현황' : '시스템'}</PageTitle>
    {storage ? (
      <StorageOverview />
    ) : (
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
        <a href="#/settings/storage">
          저장소 현황 <span aria-hidden="true">›</span>
        </a>
      </nav>
    )}
  </main>
);
