export default function OrionMark({ size = 42, className = "" }) {
  return <span
    className={`orion-mark ${className}`.trim()}
    style={{ "--orion-mark-size": `${size}px` }}
    aria-hidden="true"
  >
    <span className="orion-mark-core">O</span>
    <i className="orion-ring orion-ring-one" />
    <i className="orion-ring orion-ring-two" />
    <b className="orion-star orion-star-one" />
    <b className="orion-star orion-star-two" />
  </span>;
}
