/**
 * The API reports offsets as Python code points; JavaScript strings index by
 * UTF-16 units. Converts a code-point offset into `text` to a UTF-16 index,
 * clamping to `[0, codePointLength]`.
 */
export function cpToUtf16(text: string, cp: number): number {
  if (!(cp > 0)) return 0;
  let index = 0;
  let count = 0;
  while (index < text.length && count < cp) {
    const code = text.codePointAt(index) ?? 0;
    index += code > 0xffff ? 2 : 1;
    count += 1;
  }
  return index;
}
