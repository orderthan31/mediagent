import { PageTitle } from './PageTitle';
import { StorageOverview } from './StorageOverview';
import { SystemResources } from './SystemResources';
import './system-settings.css';
export const SystemSettings = ({ storage = false }: { storage?: boolean }) => (
  <main className="settings-page system-settings">
    <PageTitle>{storage ? '저장소 현황' : '시스템'}</PageTitle>
    {storage ? (
      <StorageOverview />
    ) : (
      <>
        <SystemResources embedded />
        <nav className="system-settings-links" aria-label="시스템 항목">
          <a href="#/settings/storage">
            저장소 현황 <span aria-hidden="true">›</span>
          </a>
        </nav>
      </>
    )}
  </main>
);
