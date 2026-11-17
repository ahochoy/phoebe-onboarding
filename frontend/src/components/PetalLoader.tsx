import loader from "../assets/brand/larkspur-loader.svg";

/**
 * The Larkspur petal loader beside a text label. The label is the status message.
 */
export function PetalLoader({ size, label }: { size: number; label: string }) {
  return (
    <span className="inline-flex items-center gap-2">
      <img src={loader} alt="" aria-hidden="true" width={size} height={size} />
      <span role="status">{label}</span>
    </span>
  );
}
