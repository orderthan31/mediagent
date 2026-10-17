import React from 'react';
import { createRoot } from 'react-dom/client';
import { AuthGate } from './AuthGate';
import { VideoWorkspace } from './VideoWorkspace';
import { PageTitleProvider } from './PageTitle';
import './legacy.css';
import './hangyeol.css';
// Frontend publishing must not depend on an API session or change production auth.
import { frontendOnly } from './preview';
const workspace = (
  <PageTitleProvider>
    <VideoWorkspace />
  </PageTitleProvider>
);

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {frontendOnly ? workspace : <AuthGate>{workspace}</AuthGate>}
  </React.StrictMode>,
);
