import loader from "../assets/brand/larkspur-loader.svg";

/**
 * The Larkspur petal loader beside a text label. The label is the status message;
 * pass `announce={false}` where an existing live region already says the same thing.
 */
export function PetalLoader({
  size,
  label,
  announce = true,
}: {
  size: number;
  label: string;
  announce?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-2">
      <img src={loader} alt="" aria-hidden="true" width={size} height={size} />
      <span role={announce ? "status" : undefined}>{label}</span>
    </span>
  );
}
