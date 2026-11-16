/** Only plain web links are rendered as links; anything else (javascript:, data:, ...) is not. */
export function isWebUrl(link: string): boolean {
  return /^https?:\/\//i.test(link);
}
