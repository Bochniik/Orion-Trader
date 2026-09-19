import { WORKSPACE_VIEWS } from "../navigation";

export default function WorkspaceNav({
  activeView,
  onNavigate,
}) {
  return (
    <nav
      className="core-nav"
      aria-label="Primary navigation"
    >
      <div className="core-nav-section-label">
        Discover
      </div>

      {WORKSPACE_VIEWS.map(
        ({
          id,
          label,
          icon: Icon,
        }) => {
          const isActive =
            activeView === id;

          return (
            <button
              key={id}
              type="button"
              aria-current={
                isActive
                  ? "page"
                  : undefined
              }
              aria-label={`${label}${isActive ? ", current workspace" : ""}`}
              className={
                isActive
                  ? "active"
                  : ""
              }
              onClick={() =>
                onNavigate(id)
              }
            >
              <span className="core-nav-icon" aria-hidden="true">
                <Icon
                  size={16}
                  strokeWidth={1.8}
                />
              </span>

              <span className="core-nav-label">
                {label}
              </span>

              <span className="core-nav-current" aria-hidden="true">
                Current
              </span>
            </button>
          );
        }
      )}
    </nav>
  );
}