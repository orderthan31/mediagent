import React from 'react';
import { createRoot } from 'react-dom/client';
import { AuthGate } from './AuthGate';
import { VideoWorkspace } from './VideoWorkspace';
import './legacy.css';
import './hangyeol.css';
createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <AuthGate>
      <VideoWorkspace />
    </AuthGate>
  </React.StrictMode>,
);
