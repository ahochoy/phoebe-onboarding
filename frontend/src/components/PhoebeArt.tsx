import avatar32 from "../assets/brand/phoebe-avatar-32.webp";
import avatar64 from "../assets/brand/phoebe-avatar-64.webp";
import celebrating256 from "../assets/brand/phoebe-celebrating-256.webp";
import celebrating512 from "../assets/brand/phoebe-celebrating-512.webp";
import checklist256 from "../assets/brand/phoebe-onboarding-checklist-256.webp";
import checklist512 from "../assets/brand/phoebe-onboarding-checklist-512.webp";
import oops256 from "../assets/brand/phoebe-oops-error-256.webp";
import oops512 from "../assets/brand/phoebe-oops-error-512.webp";
import pointing256 from "../assets/brand/phoebe-pointing-256.webp";
import pointing512 from "../assets/brand/phoebe-pointing-512.webp";
import thinking256 from "../assets/brand/phoebe-thinking-256.webp";
import thinking512 from "../assets/brand/phoebe-thinking-512.webp";
import waving256 from "../assets/brand/phoebe-waving-256.webp";
import waving512 from "../assets/brand/phoebe-waving-512.webp";

export type Pose =
  "waving" | "thinking" | "pointing" | "celebrating" | "onboarding-checklist" | "oops-error";

const POSES: Record<Pose, { x1: string; x2: string }> = {
  waving: { x1: waving256, x2: waving512 },
  thinking: { x1: thinking256, x2: thinking512 },
  pointing: { x1: pointing256, x2: pointing512 },
  celebrating: { x1: celebrating256, x2: celebrating512 },
  "onboarding-checklist": { x1: checklist256, x2: checklist512 },
  "oops-error": { x1: oops256, x2: oops512 },
};

/** A decorative Phoebe illustration. Width and height are set so layout never shifts. */
export function PhoebeArt({
  pose,
  size,
  className,
}: {
  pose: Pose;
  size: number;
  className?: string;
}) {
  const { x1, x2 } = POSES[pose];
  return (
    <img
      src={x1}
      srcSet={`${x1} 1x, ${x2} 2x`}
      alt=""
      aria-hidden="true"
      width={size}
      height={size}
      className={className}
    />
  );
}

/** Phoebe's head, cropped for small avatars. */
export function PhoebeAvatar({ size }: { size: number }) {
  return (
    <img
      src={avatar32}
      srcSet={`${avatar32} 1x, ${avatar64} 2x`}
      alt=""
      aria-hidden="true"
      width={size}
      height={size}
      className="rounded-full"
    />
  );
}
