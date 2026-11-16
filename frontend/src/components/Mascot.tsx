interface MascotProps {
  size?: number;
  mood?: "idle" | "cheer";
}

// An original eastern phoebe: grey-brown back, pale belly, dark head, a thin
// black bill and a long tail it habitually pumps. Decorative only.
export function Mascot({ size = 40, mood = "idle" }: MascotProps) {
  const cheer = mood === "cheer";
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      width={size}
      height={size}
      viewBox="0 0 64 64"
      className={cheer ? "motion-safe:animate-bounce" : undefined}
    >
      {/* tail */}
      <path d="M14 40 L3 52 L8 55 L22 46 Z" fill="#5f5148" />
      {/* body */}
      <ellipse cx="32" cy="40" rx="19" ry="15" fill="#7a6a5e" transform="rotate(-12 32 40)" />
      {/* belly */}
      <ellipse cx="38" cy="45" rx="11" ry="9" fill="#f1e9dd" transform="rotate(-12 38 45)" />
      {/* wing */}
      <path d="M17 38 C24 28 38 30 42 42 C32 46 22 45 17 38 Z" fill="#5f5148" />
      {/* head */}
      <circle cx="42" cy="22" r="11" fill="#2f2a27" />
      {/* bill */}
      <path d="M51 21 L60 23 L51 26 Z" fill="#171412" />
      {/* eye */}
      <circle cx="44.5" cy="20.5" r="2.4" fill="#faf7f4" />
      <circle cx="45" cy="20.5" r="1.2" fill="#171412" />
      {/* legs */}
      <path d="M30 54 V60 M38 53 V60" stroke="#171412" strokeWidth="2" strokeLinecap="round" />
      {cheer && (
        <g stroke="#8a4b00" strokeWidth="2.4" strokeLinecap="round">
          <path d="M26 8 L22 3" />
          <path d="M34 6 V0" />
          <path d="M18 14 L12 12" />
        </g>
      )}
    </svg>
  );
}
