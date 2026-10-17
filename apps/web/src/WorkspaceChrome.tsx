import { useEffect, useRef, useState, type ReactNode } from 'react';
import {
  Boxes,
  BriefcaseBusiness,
  Folder,
  GitBranch,
  Layers,
  Settings,
  Menu,
  PanelLeft,
  Upload,
  X,
  Plus,
  Search,
  ChevronRight,
  UsersRound,
} from 'lucide-react';
import { AccountMenu } from './AuthGate';
import { frontendOnly, renewalBackend } from './preview';
import { PageTitleSlot } from './PageTitle';
import './ui02-shell.css';
const sections = [
  { name: '작업', href: '#/jobs', icon: BriefcaseBusiness },
  { name: '원본', href: '#/', icon: Folder },
  { name: '워크플로우', href: '#/workflows', icon: GitBranch },
  { name: '에이전트', href: '#/agents', icon: Boxes },
  { name: '서빙', href: '#/serving', icon: Layers },
  { name: '시스템', href: '#/settings', icon: Settings },
  ...(frontendOnly || renewalBackend
    ? [{ name: '계정 관리', href: '#/account', icon: UsersRound }]
    : []),
];
export const WorkspaceChrome = ({
  route,
  query,
  onQuery,
  onUpload,
  uploadContent,
  uploadCount,
  agentLabel,
}: {
  route: string;
  query: string;
  onQuery: (value: string) => void;
  onUpload: () => void;
  uploadContent: ReactNode;
  uploadCount: number;
  agentLabel?: string;
}) => {
  const [wide, setWide] = useState(() => matchMedia('(min-width: 56rem)').matches);
  const [collapsed, setCollapsed] = useState(false),
    [drawer, setDrawer] = useState(false),
    [uploads, setUploads] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null),
    toggle = useRef<HTMLButtonElement>(null);
  const group =
    route.includes('workflow-editor') || route.startsWith('#/workflows')
      ? 2
      : route.startsWith('#/agents')
        ? 3
        : route.startsWith('#/serving')
          ? 4
          : route.startsWith('#/settings')
            ? 5
            : route === '#/' || route.startsWith('#/videos/')
              ? 1
              : 0;
  const accountView = route.startsWith('#/account');
  const current = accountView ? { name: '계정 관리', href: '#/account' } : sections[group];
  const child =
    route === '#/account/new'
      ? '발급'
      : route === '#/serving/connections'
        ? '공급자'
        : route.startsWith('#/agents/')
          ? agentLabel || '상세'
          : route === '#/serving/roles'
            ? '역할 설정'
            : route === '#/start'
              ? '추가'
              : /\/new$/.test(route)
                ? '추가'
                : /\/edit$/.test(route)
                  ? route.startsWith('#/workflows/')
                    ? '상세'
                    : '편집'
                  : route.startsWith('#/serving/') ||
                      route.startsWith('#/videos/') ||
                      /^#\/jobs\//.test(route) ||
                      /^#\/workflows\//.test(route)
                    ? '상세'
                    : route.includes('tickets')
                      ? '워크플로우 작업'
                      : '';
  const list = !child || route === '#/serving/connections';
  const action =
    accountView || (renewalBackend && group !== 4)
      ? null
      : group === 0
        ? { label: '새 작업', href: '#/start' }
        : group === 1
          ? null
          : group === 2
            ? child
              ? null
              : {
                  label: '새 워크플로우',
                  href: '#/workflows/new',
                }
            : group === 4
              ? route.startsWith('#/serving/connections')
                ? { label: '공급자 추가', href: '#/serving/connections/new' }
                : { label: '모델 추가', href: '#/serving/new' }
              : null;
  const links = (
    <>
      <nav aria-label="주 메뉴">
        {sections.map((item, index) => (
          <a
            href={item.href}
            key={item.name}
            aria-current={
              (accountView ? item.href === '#/account' : group === index) ? 'page' : undefined
            }
            title={item.name}
            onClick={() => setDrawer(false)}
          >
            <item.icon size={20} aria-hidden="true" />
            <span>{item.name}</span>
          </a>
        ))}
      </nav>
      {!frontendOnly && (
        <div className="ui02-session">
          <AccountMenu />
        </div>
      )}
    </>
  );
  useEffect(() => {
    const media = matchMedia('(min-width: 56rem)');
    const changed = () => {
      setWide(media.matches);
      setDrawer(false);
    };
    media.addEventListener('change', changed);
    return () => media.removeEventListener('change', changed);
  }, []);
  useEffect(() => {
    document.documentElement.style.setProperty(
      '--ui02-rail',
      wide ? (collapsed ? 'var(--m-rail-collapsed)' : 'var(--m-rail-width)') : '0px',
    );
  }, [wide, collapsed]);
  useEffect(() => {
    if (drawer && !wide) {
      dialog.current?.showModal();
    } else {
      dialog.current?.close();
    }
  }, [drawer, wide]);
  useEffect(() => {
    setDrawer(false);
    setUploads(false);
  }, [route]);
  return (
    <>
      <header className="ui02-gnb">
        <div className="ui02-brand-group">
          <button
            ref={toggle}
            className="ui02-icon"
            aria-label={wide ? (collapsed ? '메뉴 펼치기' : '메뉴 접기') : '메뉴 열기'}
            aria-expanded={wide ? !collapsed : drawer}
            onClick={() => (wide ? setCollapsed((value) => !value) : setDrawer(true))}
          >
            {wide ? <PanelLeft size={21} /> : <Menu size={22} />}
          </button>
          <a href="#/jobs" className="ui02-brand" aria-label="mideagent">
            <strong>mideagent</strong>
          </a>
          <nav className="ui02-breadcrumb" aria-label="브레드크럼">
            {child && (
              <>
                <a href={current.href}>{current.name}</a>
                <ChevronRight size={14} aria-hidden="true" />
              </>
            )}
            <PageTitleSlot />
          </nav>
        </div>
        <div className="ui02-page-actions">
          {list && group !== 5 && !accountView && (!renewalBackend || group === 4) && (
            <div className="ui02-search">
              <Search size={20} aria-hidden="true" />
              <input
                type="search"
                aria-label={`${current.name} 검색`}
                placeholder={`${current.name} 검색`}
                value={query}
                onChange={(event) => onQuery(event.target.value)}
              />
            </div>
          )}
          {group === 1 && list && !renewalBackend && (
            <button className="ui02-primary" aria-label="업로드" title="업로드" onClick={onUpload}>
              <Plus size={20} />
              <span>업로드</span>
            </button>
          )}
          {action && !['편집', '추가'].includes(child) && (
            <a
              className="ui02-primary"
              aria-label={action.label}
              title={action.label}
              href={action.href}
            >
              <Plus size={20} />
              <span>{action.label}</span>
            </a>
          )}
          {!renewalBackend && (
            <button
              className="ui02-icon ui02-upload-trigger"
              aria-label="업로드 상태"
              aria-expanded={uploads}
              onClick={() => setUploads((value) => !value)}
            >
              <Upload size={21} />
              {uploadCount > 0 && <span>{uploadCount}</span>}
            </button>
          )}
        </div>
      </header>
      {wide && (
        <aside className="ui02-lnb" data-collapsed={collapsed}>
          {links}
        </aside>
      )}
      <dialog
        ref={dialog}
        className="ui02-drawer"
        onCancel={(event) => {
          event.preventDefault();
          setDrawer(false);
          toggle.current?.focus();
        }}
        onClick={(event) => {
          if (event.target === event.currentTarget) {
            setDrawer(false);
          }
        }}
      >
        <div className="ui02-drawer-heading">
          <strong>mideagent</strong>
          <button className="ui02-icon" aria-label="메뉴 닫기" onClick={() => setDrawer(false)}>
            <X size={21} />
          </button>
        </div>
        {!wide && links}
      </dialog>

      {uploads && (
        <section className="ui02-upload-popover" aria-label="업로드 상태">
          <div className="ui02-upload-content">{uploadContent}</div>
          <button
            className="ui02-icon ui02-upload-close"
            aria-label="업로드 상태 닫기"
            onClick={() => setUploads(false)}
          >
            <X size={18} />
          </button>
        </section>
      )}
    </>
  );
};
