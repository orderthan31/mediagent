type PurposeItem = {
  runtime_uses: string[];
  profile: unknown | null;
  classification_status?: 'supported' | 'unsupported' | 'unknown';
  provider_purpose?: string;
};
export const catalogPurposeLabel = (item: PurposeItem) => {
  if (item.runtime_uses.length) {
    return item.runtime_uses
      .map((use) =>
        use === 'translation' ? '번역 후보' : use === 'transcription' ? '전사 후보' : use,
      )
      .join(' · ');
  }
  if (item.classification_status === 'unsupported') {
    return (item.provider_purpose ? item.provider_purpose + ' · ' : '') + '현재 제품 미지원';
  }
  return item.profile ? '등록만 가능, 실행 어댑터 미지원' : '근거 미확인';
};
