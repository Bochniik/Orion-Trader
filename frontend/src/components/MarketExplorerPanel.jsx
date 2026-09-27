
import {
  useEffect,
  useMemo,
  useState,
} from "react";

import StockLogo from "./StockLogo";

import {
  Activity,
  ArrowDownRight,
  ArrowUpRight,
  Atom,
  Banknote,
  Bot,
  Boxes,
  Building2,
  Car,
  ChevronDown,
  Cloud,
  Cpu,
  Factory,
  Flame,
  FlaskConical,
  Gauge,
  HeartPulse,
  Landmark,
  Layers3,
  Leaf,
  LockKeyhole,
  RadioTower,
  RefreshCw,
  Rocket,
  Search,
  Shield,
  ShoppingCart,
  Utensils,
  Zap,
} from "lucide-react";

import {
  getMarketCatalogueQuotes,
  getMarketCatalogueSector,
  getMarketCatalogueSectors,
  getMarketCatalogueStatus,
  getMarketCatalogueTheme,
  getMarketCatalogueThemes,
  getMarketExplorer,
} from "../api/api";

import "./MarketExplorerPanel.css";


const PAGE_SIZES = [
  25,
  50,
  100,
  250,
  1000,
];


const LISTS = [
  [
    "most_active",
    "Most active",
    Activity,
  ],
  [
    "gainers",
    "Biggest winners",
    ArrowUpRight,
  ],
  [
    "losers",
    "Biggest losers",
    ArrowDownRight,
  ],
  [
    "relative_volume",
    "Relative volume",
    Gauge,
  ],
  [
    "most_volatile",
    "Most volatile",
    Flame,
  ],
  [
    "buy_pressure",
    "Buy pressure",
    ArrowUpRight,
  ],
  [
    "sell_pressure",
    "Sell pressure",
    ArrowDownRight,
  ],
];


const SECTOR_ICONS = {
  technology: Cpu,
  semiconductors: Cpu,
  energy: Flame,
  financial_services: Landmark,
  financials: Landmark,
  healthcare: HeartPulse,
  consumer_cyclical: ShoppingCart,
  consumer_defensive: ShoppingCart,
  consumer: ShoppingCart,
  industrials: Factory,
  communication_services: RadioTower,
  communication: RadioTower,
  utilities: Zap,
  basic_materials: Layers3,
  materials: Layers3,
  real_estate: Building2,
};


const THEME_ICONS = {
  ai: Cpu,
  ev: Car,
  oil_gas: Flame,
  cybersecurity: LockKeyhole,
  quantum: Atom,
  space: Rocket,
  defense: Shield,
  robotics: Bot,
  biotech: FlaskConical,
  nuclear: Atom,
  renewables: Leaf,
  crypto: Banknote,
  cloud: Cloud,
  fintech: Banknote,
  food: Utensils,
};


function pct(
  value
) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "—";
  }

  return `${number > 0 ? "+" : ""}${number.toFixed(2)}%`;
}


function money(
  value
) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "—";
  }

  return new Intl.NumberFormat(
    "en-US",
    {
      style: "currency",
      currency: "USD",
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }
  ).format(number);
}


function compact(
  value
) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "—";
  }

  return Intl.NumberFormat(
    "en",
    {
      notation: "compact",
      maximumFractionDigits: 1,
    }
  ).format(number);
}


function Sparkline({
  values,
  positive,
}) {
  const clean = (
    Array.isArray(values)
      ? values
      : []
  )
    .map(Number)
    .filter(Number.isFinite);

  if (clean.length < 2) {
    return (
      <span className="market-v3-spark-empty">
        —
      </span>
    );
  }

  const width = 96;
  const height = 30;

  const min = Math.min(
    ...clean
  );

  const max = Math.max(
    ...clean
  );

  const span = Math.max(
    max - min,
    0.000001
  );

  const points = clean
    .map(
      (
        value,
        index
      ) => {
        const x =
          (index /
            Math.max(
              clean.length - 1,
              1
            )) *
          width;

        const y =
          height -
          ((value - min) /
            span) *
            (height - 6) -
          3;

        return `${x.toFixed(1)},${y.toFixed(1)}`;
      }
    )
    .join(" ");

  return (
    <svg
      className={
        positive
          ? "market-v3-spark positive"
          : "market-v3-spark negative"
      }
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <polyline
        points={points}
        fill="none"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}


function CatalogueTable({
  rows,
  quotes,
  onAnalyze,
}) {
  return (
    <div className="market-v3-table-wrap">
      <div className="market-v3-table-head">
        <span>Name</span>
        <span>Symbol</span>
        <span>Current price</span>
        <span>Change</span>
        <span>Trend</span>
        <span>Exchange</span>
      </div>

      <div className="market-v3-table-body">
        {rows.map(
          (
            row
          ) => {
            const ticker = String(
              row.ticker || ""
            ).toUpperCase();

            const quote =
              quotes?.[ticker] || {};

            const change = Number(
              quote.change_pct
            );

            const positive =
              Number.isFinite(change)
                ? change >= 0
                : true;

            return (
              <button
                type="button"
                key={ticker}
                className="market-v3-row"
                onClick={() =>
                  onAnalyze?.(
                    ticker
                  )
                }
              >
               <span className="market-v3-company">
                 <StockLogo
                   ticker={ticker}
                   name={row.company_name}
                   size={34}
                 />

                 <span className="market-v3-company-copy">
                   <strong>
                     {row.company_name ||
                       ticker}
                  </strong>

                  <small>
                    {row.industry ||
                     row.sector ||
                     "US equity"}
                 </small>
               </span>
              </span>

                <span className="market-v3-symbol">
                  {ticker}
                </span>

                <span className="market-v3-price">
                  {money(
                    quote.price
                  )}
                </span>

                <span
                  className={
                    positive
                      ? "market-v3-change positive"
                      : "market-v3-change negative"
                  }
                >
                  {Number.isFinite(
                    change
                  )
                    ? `${positive ? "▲" : "▼"} ${Math.abs(change).toFixed(2)}%`
                    : "—"}
                </span>

                <span className="market-v3-trend">
                  <Sparkline
                    values={
                      quote.sparkline
                    }
                    positive={
                      positive
                    }
                  />
                </span>

                <span className="market-v3-exchange">
                  {row.exchange ||
                    "—"}
                </span>
              </button>
            );
          }
        )}
      </div>
    </div>
  );
}


function MarketListTable({
  rows,
  mode,
  onAnalyze,
}) {
  return (
    <div className="market-v3-table-wrap">
      <div className="market-v3-table-head market-list">
        <span>Name</span>
        <span>Symbol</span>
        <span>Current price</span>
        <span>Change</span>
        <span>Market metric</span>
        <span>Exchange</span>
      </div>

      <div className="market-v3-table-body">
        {rows.map(
          (
            row
          ) => {
            const positive =
              Number(
                row.change_pct
              ) >= 0;

            let metric = "—";

            if (
              mode ===
              "most_active"
            ) {
              metric = `$${compact(
                row.dollar_volume
              )}`;
            } else if (
              mode ===
              "relative_volume"
            ) {
              metric =
                Number.isFinite(
                  Number(
                    row.relative_volume
                  )
                )
                  ? `${Number(
                      row.relative_volume
                    ).toFixed(2)}x`
                  : "—";
            } else if (
              mode ===
              "most_volatile"
            ) {
              metric = pct(
                row.daily_range_pct
              );
            } else if (
              mode ===
                "buy_pressure" ||
              mode ===
                "sell_pressure"
            ) {
              metric =
                Number.isFinite(
                  Number(
                    row.pressure_proxy
                  )
                )
                  ? Number(
                      row.pressure_proxy
                    ).toFixed(0)
                  : "—";
            }

            return (
              <button
                type="button"
                key={
                  row.ticker
                }
                className="market-v3-row"
                onClick={() =>
                  onAnalyze?.(
                    row.ticker
                  )
                }
              >
                <span className="market-v3-company">
                 <StockLogo
                    ticker={row.ticker}
                    name={row.company_name}
                    size={34}
                 />

                   <span className="market-v3-company-copy">
                     <strong>
                       {row.company_name ||
                        row.ticker}
                    </strong>

                    <small>
                      US equity
                   </small>
                 </span>
                </span>

                <span className="market-v3-symbol">
                  {String(
                    row.ticker || ""
                  ).toUpperCase()}
                </span>

                <span className="market-v3-price">
                  {money(
                    row.price
                  )}
                </span>

                <span
                  className={
                    positive
                      ? "market-v3-change positive"
                      : "market-v3-change negative"
                  }
                >
                  {positive
                    ? "▲"
                    : "▼"}{" "}
                  {Math.abs(
                    Number(
                      row.change_pct
                    )
                  ).toFixed(
                    2
                  )}
                  %
                </span>

                <span className="market-v3-exchange">
                  {metric}
                </span>

                <span className="market-v3-exchange">
                  —
                </span>
              </button>
            );
          }
        )}
      </div>
    </div>
  );
}


function GroupNav({
  groups,
  selected,
  type,
  onSelect,
}) {
  return (
    <aside className="market-v3-sidebar">
      <div className="market-v3-sidebar-title">
        {type === "sectors"
          ? "Sectors"
          : "Thematic"}
      </div>

      <div className="market-v3-group-nav">
        {Object.entries(
          groups
        )
          .sort(
            (
              a,
              b
            ) =>
              String(
                a[1]?.label ||
                  ""
              ).localeCompare(
                String(
                  b[1]?.label ||
                    ""
                )
              )
          )
          .map(
            ([
              id,
              group,
            ]) => {
              const Icon =
                type ===
                "sectors"
                  ? SECTOR_ICONS[
                      id
                    ] ||
                    Layers3
                  : THEME_ICONS[
                      id
                    ] ||
                    Boxes;

              return (
                <button
                  type="button"
                  key={id}
                  className={
                    selected ===
                    id
                      ? "active"
                      : ""
                  }
                  onClick={() =>
                    onSelect(
                      id
                    )
                  }
                >
                  <Icon
                    size={17}
                  />

                  <span>
                    {
                      group.label
                    }
                  </span>

                  <small>
                    {group.member_count ??
                      0}
                  </small>
                </button>
              );
            }
          )}
      </div>
    </aside>
  );
}


export default function MarketExplorerPanel({
  onAnalyze,
}) {
  const [
    marketData,
    setMarketData,
  ] = useState(
    null
  );

  const [
    sectors,
    setSectors,
  ] = useState(
    {}
  );

  const [
    themes,
    setThemes,
  ] = useState(
    {}
  );

  const [
    view,
    setView,
  ] = useState(
    "themes"
  );

  const [
    list,
    setList,
  ] = useState(
    "most_active"
  );

  const [
    pageSize,
    setPageSize,
  ] = useState(
    25
  );

  const [
    selectedGroup,
    setSelectedGroup,
  ] = useState(
    null
  );

  const [
    openedGroup,
    setOpenedGroup,
  ] = useState(
    null
  );

  const [
    quotes,
    setQuotes,
  ] = useState(
    {}
  );

  const [
    loading,
    setLoading,
  ] = useState(
    true
  );

  const [
    refreshing,
    setRefreshing,
  ] = useState(
    false
  );

  const [
    error,
    setError,
  ] = useState(
    ""
  );

  async function load(
    quiet = false
  ) {
    try {
      quiet
        ? setRefreshing(
            true
          )
        : setLoading(
            true
          );

      const [
        nextMarket,
        nextSectors,
        nextThemes,
      ] =
        await Promise.all(
          [
            getMarketExplorer(),
            getMarketCatalogueSectors(),
            getMarketCatalogueThemes(),
          ]
        );

      setMarketData(
        nextMarket
      );

      setSectors(
        nextSectors?.groups ||
          {}
      );

      setThemes(
        nextThemes?.groups ||
          {}
      );

      setError(
        ""
      );
    } catch (
      err
    ) {
      setError(
        err?.message ||
          "Market Explorer unavailable."
      );
    } finally {
      setLoading(
        false
      );

      setRefreshing(
        false
      );
    }
  }

  useEffect(
    () => {
      load();
    },
    []
  );

  const groupContainer =
    view ===
    "sectors"
      ? sectors
      : themes;

  useEffect(
    () => {
      if (
        view ===
        "lists"
      ) {
        return;
      }

      const ids =
        Object.keys(
          groupContainer
        );

      if (
        !selectedGroup &&
        ids.length
      ) {
        setSelectedGroup(
          ids[0]
        );
      }
    },
    [
      view,
      groupContainer,
      selectedGroup,
    ]
  );

  useEffect(
    () => {
      async function run() {
        if (
          view ===
            "lists" ||
          !selectedGroup
        ) {
          return;
        }

        try {
          setError(
            ""
          );

          const result =
            view ===
            "sectors"
              ? await getMarketCatalogueSector(
                  selectedGroup,
                  {
                    signal:
                      undefined,
                  }
                )
              : await getMarketCatalogueTheme(
                  selectedGroup,
                  {
                    signal:
                      undefined,
                  }
                );

          setOpenedGroup(
            result
          );

          const visible =
            (
              result?.items ||
              []
            ).slice(
              0,
              pageSize
            );

          const quoteResult =
            await getMarketCatalogueQuotes(
              visible.map(
                (
                  row
                ) =>
                  row.ticker
              )
            );

          setQuotes(
            quoteResult?.items ||
              {}
          );
        } catch (
          err
        ) {
          setError(
            err?.message ||
              "Could not load group."
          );
        }
      }

      run();
    },
    [
      view,
      selectedGroup,
      pageSize,
    ]
  );

  if (
    loading
  ) {
    return (
      <section className="market-explorer-panel">
        <div className="market-explorer-empty">
          Loading market explorer…
        </div>
      </section>
    );
  }

  const selectedRows =
    marketData?.lists?.[
      list
    ] || [];

  const groupRows =
    (
      openedGroup?.items ||
      []
    ).slice(
      0,
      pageSize
    );

  const CurrentIcon =
    selectedGroup
      ? view ===
        "sectors"
        ? SECTOR_ICONS[
            selectedGroup
          ] ||
          Layers3
        : THEME_ICONS[
            selectedGroup
          ] ||
          Boxes
      : Boxes;

  return (
    <section className="market-explorer-panel market-v3">
      <header className="market-explorer-header">
        <div>
          <p className="core-eyebrow">
            MARKET DISCOVERY
          </p>

          <h2>
            Explore the market
          </h2>

          <p>
            Browse the market first.
            Send any stock to Orion
            Engine only when you want
            analysis.
          </p>
        </div>

        <button
          type="button"
          className="market-explorer-refresh"
          onClick={() =>
            load(
              true
            )
          }
          disabled={
            refreshing
          }
        >
          <RefreshCw
            size={
              16
            }
          />
          Refresh
        </button>
      </header>

      <nav className="market-explorer-tabs">
        <button
          type="button"
          className={
            view ===
            "lists"
              ? "active"
              : ""
          }
          onClick={() =>
            setView(
              "lists"
            )
          }
        >
          <Activity
            size={
              15
            }
          />
          Market lists
        </button>

        <button
          type="button"
          className={
            view ===
            "sectors"
              ? "active"
              : ""
          }
          onClick={() => {
            setView(
              "sectors"
            );
            setSelectedGroup(
              null
            );
          }}
        >
          <Layers3
            size={
              15
            }
          />
          Sectors
        </button>

        <button
          type="button"
          className={
            view ===
            "themes"
              ? "active"
              : ""
          }
          onClick={() => {
            setView(
              "themes"
            );
            setSelectedGroup(
              null
            );
          }}
        >
          <Boxes
            size={
              15
            }
          />
          Themes
        </button>
      </nav>

      {error ? (
        <div className="core-error">
          {error}
        </div>
      ) : null}

      {view ===
        "lists" && (
        <>
          <div className="market-explorer-list-picker">
            {LISTS.map(
              ([
                id,
                label,
                Icon,
              ]) => (
                <button
                  type="button"
                  key={
                    id
                  }
                  className={
                    list ===
                    id
                      ? "active"
                      : ""
                  }
                  onClick={() =>
                    setList(
                      id
                    )
                  }
                >
                  <Icon
                    size={
                      14
                    }
                  />
                  {
                    label
                  }
                </button>
              )
            )}
          </div>

          <MarketListTable
            rows={
              selectedRows
            }
            mode={
              list
            }
            onAnalyze={
              onAnalyze
            }
          />
        </>
      )}

           {view !== "lists" && (
        <div className="market-v3-layout market-v3-layout-wide">
          <div className="market-v3-content">
            {openedGroup ? (
              <>
                <div className="market-v3-group-hero">
                  <div className="market-v3-group-title">
                    <span className="market-v3-hero-icon">
                      <CurrentIcon size={30} />
                    </span>

                    <div>
                      <p className="core-eyebrow">
                        {view === "sectors"
                          ? "SECTOR"
                          : "THEME"}
                      </p>

                      <h3>
                        {openedGroup.label}
                      </h3>

                      <p>
                        {openedGroup.description ||
                          `${openedGroup.member_count || 0} classified tradable stocks`}
                      </p>
                    </div>
                  </div>

                  <div className="market-v3-controls">
                    <label className="market-v3-group-select">
                      <span>
                        {view === "sectors"
                          ? "Sector"
                          : "Theme"}
                      </span>

                      <select
                        value={selectedGroup || ""}
                        onChange={(event) =>
                          setSelectedGroup(
                            event.target.value
                          )
                        }
                      >
                        {Object.entries(groupContainer)
                          .sort((a, b) =>
                            String(
                              a[1]?.label || ""
                            ).localeCompare(
                              String(
                                b[1]?.label || ""
                              )
                            )
                          )
                          .map(([id, group]) => (
                            <option
                              key={id}
                              value={id}
                            >
                              {group.label}
                            </option>
                          ))}
                      </select>
                    </label>

                    <label>
                      <span>Show</span>

                      <select
                        value={pageSize}
                        onChange={(event) =>
                          setPageSize(
                            Number(
                              event.target.value
                            )
                          )
                        }
                      >
                        {PAGE_SIZES.map((value) => (
                          <option
                            key={value}
                            value={value}
                          >
                            {value}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                </div>

                <CatalogueTable
                  rows={groupRows}
                  quotes={quotes}
                  onAnalyze={onAnalyze}
                />

              </>
            ) : (
              <div className="market-explorer-empty">
                Select a group.
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}