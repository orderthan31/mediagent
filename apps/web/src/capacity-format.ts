/** Display only: decimal GB, preserving integer byte/string aggregate precision. */
export const formatStorageGB = (value: string | number): string => {
  if (
    typeof value === 'number'
      ? !Number.isSafeInteger(value) || value < 0
      : !/^(0|[1-9][0-9]*)$/.test(value)
  ) {
    throw new RangeError('확인된 정수 bytes 값이 필요합니다.');
  }
  const hundredths = (BigInt(value) + 5000000n) / 10000000n;
  return `${hundredths / 100n}.${(hundredths % 100n).toString().padStart(2, '0')} GB`;
};
