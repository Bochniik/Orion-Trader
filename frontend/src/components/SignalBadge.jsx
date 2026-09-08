export default function SignalBadge({ signal }) {
  const cls = signal === "BUY" ? "buy" : signal === "SELL" ? "sell" : "hold";

  return (
    <span className={`badge ${cls}`}>
      {signal || "WAITING"}
    </span>
  );
}