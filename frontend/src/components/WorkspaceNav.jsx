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
              className={
                isActive
                  ? "active"
                  : ""
              }
              onClick={() =>
                onNavigate(id)
              }
            >
              <Icon
                size={17}
                strokeWidth={1.8}
                aria-hidden="true"
              />

              <span>
                {label}
              </span>
            </button>
          );
        }
      )}
    </nav>
  );
}