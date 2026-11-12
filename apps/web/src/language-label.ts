const names = new Intl.DisplayNames(['ko'], { type: 'language' });

// Display only: never write the localized name into a workflow or model request.
export const languageLabel = (code?: string) => {
  if (!code) {
    return '미지정';
  }
  if (code === 'auto') {
    return '자동 감지';
  }
  if (code === 'und') {
    return '미지정';
  }
  try {
    return names.of(code) || code;
  } catch {
    return code;
  }
};
