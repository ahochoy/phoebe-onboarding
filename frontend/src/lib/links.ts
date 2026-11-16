/**
 * Only plain web links are rendered as links; anything else (javascript:, data:, ...) is not.
 * Same-origin absolute paths (hosted seed sources such as /seed-sources/benefits.html) count,
 * but protocol-relative `//host` and `/\host` do not: browsers treat those as other origins.
 */
export function isWebUrl(link: string): boolean {
  return /^https?:\/\//i.test(link) || /^\/(?![/\\])/.test(link);
}
