import {
  LayoutDashboard,
  Search,
  Star,
  BrainCircuit,
} from "lucide-react";

export const WORKSPACE_VIEWS = [
  {
    id: "today",
    label: "Dashboard",
    description:
      "Market discovery, scanner insights and Orion intelligence",
    icon: LayoutDashboard,
  },
  {
    id: "analyze",
    label: "Analysis",
    description:
      "Analyze one stock with Orion",
    icon: Search,
  },
  {
    id: "intelligence",
    label: "Orion Intelligence",
    description:
      "Prioritized briefings, ticker context and Orion memory",
    icon: BrainCircuit,
  },
  {
    id: "my-stocks",
    label: "Watchlist",
    description:
      "Saved stocks, positions and monitoring",
    icon: Star,
  },
];

const VIEW_IDS = new Set(
  WORKSPACE_VIEWS.map(
    (view) => view.id
  )
);

const LEGACY_VIEWS = {
  overview: "today",
  research: "analyze",
  orion: "analyze",

  opportunities: "today",
  "move-lab": "analyze",
  "live-edge": "today",

  portfolio: "my-stocks",
  strategies: "analyze",
  learn: "analyze",
  automation: "my-stocks",

  dashboard: "today",
  analysis: "analyze",
  intelligence: "intelligence",
  watchlist: "my-stocks",
};

export function viewFromHash(
  hash = ""
) {
  const requested =
    hash.replace(
      /^#\/?/,
      ""
    );

  return VIEW_IDS.has(
    requested
  )
    ? requested
    : LEGACY_VIEWS[
        requested
      ] || "today";
}

export function isWorkspaceView(
  view
) {
  return VIEW_IDS.has(view);
}