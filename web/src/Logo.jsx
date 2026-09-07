export default function Logo({ size = 24, tone = "solid" }) {
  const tile = tone === "solid" ? "var(--teal)" : "var(--ink)";
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img"
         aria-label="Relay Desk" style={{ display: "block", flex: "0 0 auto" }}>
      <rect width="32" height="32" rx="8" fill={tile} />
      <rect x="6.5" y="14.5" width="9" height="3" rx="1.5" fill="#fff" />
      <path d="M19 10.5 L24.5 16 L19 21.5" fill="none" stroke="#fff"
            strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
