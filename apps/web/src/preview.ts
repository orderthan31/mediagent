/** Publishing-only helpers. Production builds never enable this branch. */
export const frontendOnly = import.meta.env.DEV && import.meta.env.VITE_FRONTEND_ONLY === '1';
// Explicit opt-in; preserve the existing publishing preview and legacy API.
export const renewalBackend = !frontendOnly && import.meta.env.VITE_RENEWAL_BACKEND === '1';

// The private HTTP preview may not expose randomUUID (secure-context API).
// Use cryptographic random bytes only in this isolated development preview.
if (frontendOnly && typeof crypto.randomUUID !== 'function') {
  Object.defineProperty(crypto, 'randomUUID', {
    value: () => {
      const bytes = crypto.getRandomValues(new Uint8Array(16));
      bytes[6] = (bytes[6] & 15) | 64;
      bytes[8] = (bytes[8] & 63) | 128;
      const hex = [...bytes].map((value) => value.toString(16).padStart(2, '0')).join('');
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    },
  });
}

export const mediaUrl = (path: string): string => {
  const clean = path.replace(/^\/api/, '');
  if (!frontendOnly) {
    return (import.meta.env.VITE_API_BASE_URL || '/api') + clean;
  }
  if (/\/files\/sample-face\.svg/.test(clean)) {
    return '/mock/sample-face.svg';
  }
  if (/thumbnail|\/files\//.test(clean)) {
    const identity = clean.match(/[a-f0-9]{32}/)?.[0] || '0';
    return `/mock/poster-${parseInt(identity.slice(-2), 16) % 3}.svg`;
  }
  if (/original\.(srt|txt)(\?|$)/.test(clean)) {
    return '/mock/sample-original.srt';
  }
  if (/\.(srt|txt)(\?|$)/.test(clean) || /\/input$/.test(clean)) {
    return '/mock/sample.srt';
  }
  if (/\.json(\?|$)|\/artifacts\//.test(clean)) {
    return '/mock/sample.json';
  }
  if (/\.wav(\?|$)/.test(clean)) {
    return '/mock/sample.wav';
  }
  return '/mock/sample.mp4';
};
