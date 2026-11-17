import jordanMoore from "../assets/people/jordan-moore.webp";
import melindaGrant from "../assets/people/melinda-grant.webp";

/** Seeded people with a photo, keyed by exact name. Anyone else gets initials. */
export const PHOTOS: Readonly<Record<string, string>> = {
  "Melinda Grant": melindaGrant,
  "Jordan Moore": jordanMoore,
};

/** First and last initials, uppercase; "?" for a blank name. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  const first = parts[0]!;
  const last = parts.length > 1 ? parts[parts.length - 1]! : "";
  return (first.charAt(0) + last.charAt(0)).toUpperCase();
}
