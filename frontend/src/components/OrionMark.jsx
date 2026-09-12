export default function OrionMark({ size = 42, className = "" }) {
  return (
    <img
      className={`orion-mark ${className}`.trim()}
      src="/orion-icon.svg"
      width={size}
      height={size}
      alt=""
      aria-hidden="true"
      draggable="false"
      style={{
        width: `${size}px`,
        height: `${size}px`,
        display: "block",
        flex: "0 0 auto",
        objectFit: "contain",
      }}
    />
  );
}
