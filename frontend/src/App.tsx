import { useEffect, useMemo, useState } from "react";
import {
  fetchFilterOptions,
  fetchInventory,
  fetchKpisWithFilters,
  fetchMarketPeriodSeries,
  fetchOpsStatus,
  fetchRecentListingsForRange,
  fetchReportSummary,
  fetchSubdivisionRankings,
  fetchTrends,
  type FilterOptionsResponse,
  type InventoryResponse,
  type KpisResponse,
  type OpsStatusResponse,
  type PeriodSeriesResponse,
  type RecentListingsResponse,
  type ReportConfig,
  type ReportSummaryResponse,
  type SubdivisionRankingsResponse,
  type TrendsResponse
} from "./api";

type PropertyGroup = "ALL" | "SINGLE_FAMILY" | "TOWNHOME_CONDO";
type ReportMode = "rolling" | "monthly" | "quarterly" | "annual" | "custom";
type SnapshotMetricKey =
  | "sold_count"
  | "total_sales_volume"
  | "median_sold_price"
  | "median_price_per_sqft"
  | "new_listings"
  | "pending_sales"
  | "active_inventory"
  | "months_supply"
  | "median_dom"
  | "median_listing_discount"
  | "cash_sales_percent"
  | "avg_sold_price";

const METRIC_ICONS: Record<string, string> = {
  "Sold Count": "/icons/closed-listings.png",
  "Sales Volume": "/icons/total-volume.png",
  "Median Sold Price": "/icons/median-sold-price.png",
  "Median PPSF": "/icons/median-ppsf.png",
  "New Listings": "/icons/new-listings.png",
  "Pending Sales": "/icons/pending-listings.png",
  "Active Inventory": "/icons/active-listings.png",
  "Months Supply": "/icons/msi.png",
  "Median DOM": "/icons/avg-dom.png",
  "Cash Sales %": "/icons/closed-listings.png",
  "Median Discount": "/icons/listing-discount.png",
  "Avg Sold Price": "/icons/avg-sales-price.png",
  "Market Grade": "/icons/market-grade.png",
};

function formatMoney(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

function formatNumber(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function formatPercent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "-";
  return `${value.toFixed(2)}%`;
}

function formatDelta(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "n/a";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(1)}%`;
}

function toIsoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function todayMinusDays(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() - days);
  return toIsoDate(d);
}

function monthDateParts(input: Date): { year: number; month: number } {
  return { year: input.getFullYear(), month: input.getMonth() + 1 };
}

function resolveWindowClient(
  mode: ReportMode,
  periodDays: number,
  refYear: number,
  refMonth: number,
  refQuarter: number,
  startDate?: string,
  endDate?: string
): { start: string; end: string } {
  const today = new Date();
  if (mode === "custom" && startDate && endDate) {
    return { start: startDate, end: endDate };
  }
  if (mode === "monthly") {
    const start = new Date(refYear, refMonth - 1, 1);
    const end = new Date(refYear, refMonth, 0);
    return { start: toIsoDate(start), end: toIsoDate(end) };
  }
  if (mode === "quarterly") {
    const startMonth = (refQuarter - 1) * 3;
    const start = new Date(refYear, startMonth, 1);
    const end = new Date(refYear, startMonth + 3, 0);
    return { start: toIsoDate(start), end: toIsoDate(end) };
  }
  if (mode === "annual") {
    return { start: `${refYear}-01-01`, end: `${refYear}-12-31` };
  }
  const end = today;
  const start = new Date(today);
  start.setDate(start.getDate() - (periodDays - 1));
  return { start: toIsoDate(start), end: toIsoDate(end) };
}

type ChartPadding = { left: number; right: number; top: number; bottom: number };
type ChartDomain = { min: number; max: number };

function getCleanValues(values: Array<number | null | undefined>): number[] {
  return values.map((v) => (v == null || Number.isNaN(v) ? 0 : Number(v)));
}

function getChartDomain(values: number[], includeZero: boolean): ChartDomain {
  if (!values.length) return { min: 0, max: 1 };
  let min = Math.min(...values);
  let max = Math.max(...values);
  if (includeZero) min = Math.min(0, min);
  if (min === max) {
    const bump = min === 0 ? 1 : Math.abs(min) * 0.1;
    min -= bump;
    max += bump;
  }
  return { min, max };
}

function yForValue(value: number, domain: ChartDomain, height: number, pad: ChartPadding): number {
  const chartHeight = height - pad.top - pad.bottom;
  const ratio = (value - domain.min) / (domain.max - domain.min);
  return pad.top + chartHeight - ratio * chartHeight;
}

function xForIndex(index: number, total: number, width: number, pad: ChartPadding): number {
  if (total <= 1) return pad.left;
  const chartWidth = width - pad.left - pad.right;
  return pad.left + (index / (total - 1)) * chartWidth;
}

function buildLinePath(values: number[], domain: ChartDomain, width: number, height: number, pad: ChartPadding): string {
  if (!values.length) return "";
  const points = values.map((v, i) => `${xForIndex(i, values.length, width, pad)},${yForValue(v, domain, height, pad)}`);
  return `M ${points.join(" L ")}`;
}

function buildTicks(domain: ChartDomain, count = 4): number[] {
  if (count < 2) return [domain.min, domain.max];
  return Array.from({ length: count }, (_, i) => domain.min + ((domain.max - domain.min) * i) / (count - 1));
}

function formatCompactNumber(value: number): string {
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function formatAxisValue(value: number, kind: "count" | "currency" | "msi"): string {
  if (kind === "currency") return `$${formatCompactNumber(value)}`;
  if (kind === "msi") return value.toFixed(1);
  return formatCompactNumber(value);
}

type SnapshotMetricSpec = {
  key: SnapshotMetricKey;
  label: string;
  iconKey: string;
  format: "money" | "number" | "percent";
};

const SNAPSHOT_METRIC_SPECS: Record<SnapshotMetricKey, SnapshotMetricSpec> = {
  sold_count: { key: "sold_count", label: "Sold Count", iconKey: "Sold Count", format: "number" },
  total_sales_volume: { key: "total_sales_volume", label: "Sales Volume", iconKey: "Sales Volume", format: "money" },
  median_sold_price: { key: "median_sold_price", label: "Median Sold Price", iconKey: "Median Sold Price", format: "money" },
  median_price_per_sqft: { key: "median_price_per_sqft", label: "Median PPSF", iconKey: "Median PPSF", format: "money" },
  new_listings: { key: "new_listings", label: "New Listings", iconKey: "New Listings", format: "number" },
  pending_sales: { key: "pending_sales", label: "Pending Sales", iconKey: "Pending Sales", format: "number" },
  active_inventory: { key: "active_inventory", label: "Active Inventory", iconKey: "Active Inventory", format: "number" },
  months_supply: { key: "months_supply", label: "Months Supply", iconKey: "Months Supply", format: "number" },
  median_dom: { key: "median_dom", label: "Median DOM", iconKey: "Median DOM", format: "number" },
  median_listing_discount: { key: "median_listing_discount", label: "Median Discount", iconKey: "Median Discount", format: "percent" },
  cash_sales_percent: { key: "cash_sales_percent", label: "Cash Sales %", iconKey: "Cash Sales %", format: "percent" },
  avg_sold_price: { key: "avg_sold_price", label: "Avg Sold Price", iconKey: "Avg Sold Price", format: "money" },
};

function downloadCsv(filename: string, rows: Array<Record<string, unknown>>): void {
  if (!rows.length) return;
  const columns = Object.keys(rows[0]);
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, "\"\"")}"`;
  const lines = [columns.join(",")];
  rows.forEach((row) => lines.push(columns.map((c) => esc(row[c])).join(",")));
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function escapeHtml(value: unknown): string {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function clampScore(value: number): number {
  if (Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(100, value));
}

function scoreDom(dom?: number | null): number | null {
  if (dom == null || Number.isNaN(dom)) return null;
  if (dom <= 30) return 100;
  if (dom <= 45) return 85;
  if (dom <= 60) return 70;
  if (dom <= 90) return 50;
  if (dom <= 120) return 30;
  return 15;
}

function scorePendingToSold(p2s?: number | null): number | null {
  if (p2s == null || Number.isNaN(p2s)) return null;
  if (p2s >= 1.2) return 100;
  if (p2s >= 1.0) return 85;
  if (p2s >= 0.8) return 70;
  if (p2s >= 0.6) return 50;
  if (p2s >= 0.4) return 30;
  return 15;
}

function scoreMsi(msi?: number | null): number | null {
  if (msi == null || Number.isNaN(msi)) return null;
  if (msi <= 2.0) return 100;
  if (msi <= 3.0) return 90;
  if (msi <= 4.0) return 75;
  if (msi <= 5.5) return 60;
  if (msi <= 7.0) return 40;
  if (msi <= 9.0) return 25;
  return 10;
}

function scoreInventoryDelta(invDelta?: number | null): number | null {
  if (invDelta == null || Number.isNaN(invDelta)) return null;
  if (invDelta <= -15) return 100;
  if (invDelta <= -5) return 85;
  if (invDelta <= 5) return 65;
  if (invDelta <= 15) return 45;
  if (invDelta <= 30) return 25;
  return 10;
}

function scoreDiscount(discount?: number | null): number | null {
  if (discount == null || Number.isNaN(discount)) return null;
  if (discount <= 0) return 100;
  if (discount <= 2) return 85;
  if (discount <= 4) return 70;
  if (discount <= 6) return 55;
  if (discount <= 8) return 40;
  if (discount <= 10) return 25;
  return 10;
}

function scoreCash(cash?: number | null): number | null {
  if (cash == null || Number.isNaN(cash)) return null;
  if (cash >= 55) return 100;
  if (cash >= 45) return 85;
  if (cash >= 35) return 70;
  if (cash >= 25) return 55;
  if (cash >= 15) return 40;
  return 25;
}

function averageOrNull(values: Array<number | null>): number | null {
  const clean = values.filter((v): v is number => v != null && !Number.isNaN(v));
  if (!clean.length) return null;
  return clean.reduce((sum, n) => sum + n, 0) / clean.length;
}

function getMarketGradeInfo(reportSummary?: ReportSummaryResponse | null): {
  label: string;
  description: string;
  finalScore: number | null;
  pace: number | null;
  supply: number | null;
  pricing: number | null;
  demand: number | null;
  formula: string;
} {
  if (!reportSummary) {
    return {
      label: "N/A",
      description: "Insufficient data for Market Grade v2.",
      finalScore: null,
      pace: null,
      supply: null,
      pricing: null,
      demand: null,
      formula:
        "Score = 0.30*Pace + 0.30*Supply + 0.25*Pricing + 0.15*Demand; Pace=0.70*DOM+0.30*Pending/Sold; Supply=0.70*MSI+0.30*InventoryΔ",
    };
  }
  const p2s =
    reportSummary.current.sold_count && reportSummary.current.sold_count > 0
      ? (reportSummary.current.pending_sales ?? 0) / reportSummary.current.sold_count
      : null;

  const pace = averageOrNull([
    scoreDom(reportSummary.current.median_dom),
    scorePendingToSold(p2s),
  ]);
  const supply = averageOrNull([
    scoreMsi(reportSummary.current.months_supply),
    scoreInventoryDelta(reportSummary.delta_pct.active_inventory),
  ]);
  const pricing = scoreDiscount(reportSummary.current.median_listing_discount);
  const demand = scoreCash(reportSummary.current.cash_sales_percent);

  const weightedPieces: Array<number> = [];
  if (pace != null) weightedPieces.push(pace * 0.3);
  if (supply != null) weightedPieces.push(supply * 0.3);
  if (pricing != null) weightedPieces.push(pricing * 0.25);
  if (demand != null) weightedPieces.push(demand * 0.15);
  const weightUsed =
    (pace != null ? 0.3 : 0) +
    (supply != null ? 0.3 : 0) +
    (pricing != null ? 0.25 : 0) +
    (demand != null ? 0.15 : 0);
  const finalScore = weightUsed > 0 ? clampScore(weightedPieces.reduce((s, n) => s + n, 0) / weightUsed) : null;

  if (finalScore == null) {
    return {
      label: "N/A",
      description: "Insufficient data for Market Grade v2.",
      finalScore: null,
      pace,
      supply,
      pricing,
      demand,
      formula:
        "Score = 0.30*Pace + 0.30*Supply + 0.25*Pricing + 0.15*Demand; Pace=0.70*DOM+0.30*Pending/Sold; Supply=0.70*MSI+0.30*InventoryΔ",
    };
  }

  let label = "F (Strong Buyer)";
  let description = "High supply and slow absorption favor buyers.";
  if (finalScore >= 80) {
    label = "A (Strong Seller)";
    description = "Very tight supply, fast pace, and strong pricing power.";
  } else if (finalScore >= 65) {
    label = "B (Seller)";
    description = "Seller-leaning with healthy demand and manageable inventory.";
  } else if (finalScore >= 45) {
    label = "C (Balanced)";
    description = "Supply and demand are broadly balanced.";
  } else if (finalScore >= 30) {
    label = "D (Buyer)";
    description = "Buyers have leverage as inventory and time-to-sell rise.";
  }

  return {
    label,
    description,
    finalScore,
    pace,
    supply,
    pricing,
    demand,
    formula:
      "Score = 0.30*Pace + 0.30*Supply + 0.25*Pricing + 0.15*Demand; Pace=0.70*DOM+0.30*Pending/Sold; Supply=0.70*MSI+0.30*InventoryΔ",
  };
}

function MetricVisualCard(props: {
  label: string;
  value: string;
  delta?: string;
  deltaValue?: number | null;
}) {
  const icon = METRIC_ICONS[props.label];
  const deltaClass =
    props.deltaValue == null || Number.isNaN(props.deltaValue)
      ? ""
      : props.deltaValue > 0
      ? "delta-up"
      : props.deltaValue < 0
      ? "delta-down"
      : "delta-flat";
  return (
    <article className="metric-visual-card">
      <div className="metric-visual-head">
        {icon ? <img src={icon} alt={props.label} className="metric-icon" /> : <span className="metric-icon-fallback" />}
        <p className="metric-visual-label">{props.label}</p>
      </div>
      <p className="metric-visual-value">{props.value}</p>
      {props.delta ? <p className={`metric-visual-delta ${deltaClass}`.trim()}>{props.delta}</p> : null}
    </article>
  );
}

function formatMetricValueBySpec(
  format: SnapshotMetricSpec["format"],
  value: number | null | undefined
): string {
  if (format === "money") return formatMoney(value);
  if (format === "percent") return formatPercent(value);
  return formatNumber(value);
}

function buildSmartSnapshotMetrics(reportSummary: ReportSummaryResponse): Array<{
  key: SnapshotMetricKey;
  label: string;
  value: string;
  previous: string;
  delta: string;
  deltaValue: number | null | undefined;
  iconPath?: string;
}> {
  const coreKeys: SnapshotMetricKey[] = [
    "sold_count",
    "total_sales_volume",
    "median_sold_price",
    "active_inventory",
    "months_supply",
  ];

  const contextPool: SnapshotMetricKey[] = [
    "median_price_per_sqft",
    "new_listings",
    "pending_sales",
    "median_dom",
    "median_listing_discount",
    "cash_sales_percent",
    "avg_sold_price",
  ];

  const inventoryHeavy =
    (reportSummary.current.months_supply ?? 0) >= 6 ||
    (reportSummary.delta_pct.months_supply ?? 0) >= 10 ||
    (reportSummary.delta_pct.active_inventory ?? 0) >= 10;
  const pricingHeavy =
    Math.abs(reportSummary.delta_pct.median_sold_price ?? 0) >= 8 ||
    Math.abs(reportSummary.delta_pct.median_price_per_sqft ?? 0) >= 8;
  const velocityHeavy =
    Math.abs(reportSummary.delta_pct.median_dom ?? 0) >= 10 ||
    Math.abs(reportSummary.delta_pct.pending_sales ?? 0) >= 10;

  const scoredContext = contextPool
    .map((key) => {
      const deltaAbs = Math.abs((reportSummary.delta_pct as Record<string, number | null | undefined>)[key] ?? 0);
      let bonus = 0;
      if (inventoryHeavy && (key === "new_listings" || key === "pending_sales" || key === "median_dom")) bonus += 2.5;
      if (pricingHeavy && (key === "median_price_per_sqft" || key === "avg_sold_price" || key === "median_listing_discount")) bonus += 2.5;
      if (velocityHeavy && (key === "median_dom" || key === "pending_sales")) bonus += 2.5;
      if (key === "cash_sales_percent") bonus += 1.0;
      return { key, score: deltaAbs + bonus };
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, 4)
    .map((item) => item.key);

  const selected = [...coreKeys, ...scoredContext];
  return selected.map((key) => {
    const spec = SNAPSHOT_METRIC_SPECS[key];
    const currentValue = (reportSummary.current as Record<string, number | null | undefined>)[key];
    const previousValue = (reportSummary.previous as Record<string, number | null | undefined>)[key];
    const deltaValue = (reportSummary.delta_pct as Record<string, number | null | undefined>)[key];
    return {
      key,
      label: spec.label,
      value: formatMetricValueBySpec(spec.format, currentValue),
      previous: formatMetricValueBySpec(spec.format, previousValue),
      delta: formatDelta(deltaValue),
      deltaValue,
      iconPath: METRIC_ICONS[spec.iconKey],
    };
  });
}

export default function App() {
  const now = new Date();
  const { year: nowYear, month: nowMonth } = monthDateParts(now);
  const nowQuarter = Math.floor((nowMonth - 1) / 3) + 1;

  const [soldSince, setSoldSince] = useState(todayMinusDays(30));
  const [city, setCity] = useState("");
  const [geoZone, setGeoZone] = useState("");
  const [finalSubdivision, setFinalSubdivision] = useState("");
  const [propertyGroup, setPropertyGroup] = useState<PropertyGroup>("ALL");
  const [propertyType, setPropertyType] = useState("");

  const [reportMode, setReportMode] = useState<ReportMode>("rolling");
  const [periodDays, setPeriodDays] = useState(30);
  const [refYear, setRefYear] = useState(nowYear);
  const [refMonth, setRefMonth] = useState(nowMonth);
  const [refQuarter, setRefQuarter] = useState(nowQuarter);
  const [customStart, setCustomStart] = useState(todayMinusDays(30));
  const [customEnd, setCustomEnd] = useState(toIsoDate(now));
  const [seriesFrequency, setSeriesFrequency] = useState<"monthly" | "quarterly" | "annual">("monthly");
  const [seriesPeriods, setSeriesPeriods] = useState(12);

  const [kpis, setKpis] = useState<KpisResponse | null>(null);
  const [trends, setTrends] = useState<TrendsResponse | null>(null);
  const [inventory, setInventory] = useState<InventoryResponse | null>(null);
  const [recentListings, setRecentListings] = useState<RecentListingsResponse | null>(null);
  const [reportSummary, setReportSummary] = useState<ReportSummaryResponse | null>(null);
  const [rankings, setRankings] = useState<SubdivisionRankingsResponse | null>(null);
  const [periodSeries, setPeriodSeries] = useState<PeriodSeriesResponse | null>(null);
  const [opsStatus, setOpsStatus] = useState<OpsStatusResponse | null>(null);
  const [filterOptions, setFilterOptions] = useState<FilterOptionsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const activeWindow = useMemo(
    () => resolveWindowClient(reportMode, periodDays, refYear, refMonth, refQuarter, customStart, customEnd),
    [reportMode, periodDays, refYear, refMonth, refQuarter, customStart, customEnd]
  );

  useEffect(() => {
    let cancelled = false;
    async function loadFilters() {
      try {
        const options = await fetchFilterOptions({
          city,
          geoZone,
          propertyType,
          propertyGroup,
        });
        if (!cancelled) setFilterOptions(options);
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load filter options");
      }
    }
    void loadFilters();
    return () => {
      cancelled = true;
    };
  }, [city, geoZone, propertyType, propertyGroup]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setError(null);
      try {
        const filters = { city, geoZone, finalSubdivision, propertyType, propertyGroup };
        const config: ReportConfig = {
          reportMode,
          periodDays,
          refYear,
          refMonth,
          refQuarter,
          startDate: reportMode === "custom" ? customStart : undefined,
          endDate: reportMode === "custom" ? customEnd : undefined
        };
        const trendFrequency =
          reportMode === "annual" ? "annual" : reportMode === "quarterly" ? "quarterly" : "monthly";

        const [kpisResp, trendsResp, invResp, recentResp, reportResp, rankingsResp, opsResp, seriesResp] = await Promise.all([
          fetchKpisWithFilters(soldSince, filters),
          fetchTrends(12, filters, trendFrequency, activeWindow.start, activeWindow.end),
          fetchInventory(filters),
          fetchRecentListingsForRange(20, filters, activeWindow.start, activeWindow.end, soldSince),
          fetchReportSummary(config, filters),
          fetchSubdivisionRankings(config, 2, 12, filters),
          fetchOpsStatus(),
          fetchMarketPeriodSeries(
            seriesFrequency,
            seriesPeriods,
            filters,
            reportMode === "custom" ? customEnd : undefined,
            refYear,
            refMonth,
            refQuarter
          ),
        ]);
        if (cancelled) return;
        setKpis(kpisResp);
        setTrends(trendsResp);
        setInventory(invResp);
        setRecentListings(recentResp);
        setReportSummary(reportResp);
        setRankings(rankingsResp);
        setOpsStatus(opsResp);
        setPeriodSeries(seriesResp);
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load dashboard data");
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [
    soldSince,
    city,
    geoZone,
    finalSubdivision,
    propertyType,
    propertyGroup,
    reportMode,
    periodDays,
    refYear,
    refMonth,
    refQuarter,
    customStart,
    customEnd,
    seriesFrequency,
    seriesPeriods,
    activeWindow.start,
    activeWindow.end
  ]);

  const inventoryTotal = useMemo(() => (inventory?.rows ?? []).reduce((sum, row) => sum + row.count, 0), [inventory]);
  const inventorySegments = useMemo(() => {
    const palette = ["#008c8a", "#2f6fb3", "#d86f1d", "#2d8a5d", "#7a5aa6", "#b14d5e", "#7c8f42", "#6f6f6f"];
    const rows = inventory?.rows ?? [];
    let start = 0;
    return rows.map((row, i) => {
      const pct = inventoryTotal > 0 ? row.count / inventoryTotal : 0;
      const segment = { ...row, start, end: start + pct, color: palette[i % palette.length] };
      start += pct;
      return segment;
    });
  }, [inventory, inventoryTotal]);

  const yearOptions = useMemo(() => {
    const current = new Date().getFullYear();
    return Array.from({ length: 16 }, (_, i) => current - i);
  }, []);

  const marketScopeLabel = useMemo(() => {
    const parts: string[] = [];
    if (city) parts.push(`City: ${city}`);
    if (geoZone) parts.push(`Geo: ${geoZone}`);
    if (finalSubdivision) parts.push(`Subdivision: ${finalSubdivision}`);
    if (propertyType) parts.push(`Type: ${propertyType}`);
    else if (propertyGroup && propertyGroup !== "ALL") {
      parts.push(
        `Type Group: ${propertyGroup === "SINGLE_FAMILY" ? "Single Family Home" : "Condo/TH/Other"}`
      );
    }
    return parts.length ? parts.join(" | ") : "All Selected Markets";
  }, [city, geoZone, finalSubdivision, propertyType, propertyGroup]);

  const metricRows = useMemo(() => {
    if (!reportSummary) return [];
    return [
      ["Sold Count", formatNumber(reportSummary.current.sold_count), formatNumber(reportSummary.previous.sold_count), formatDelta(reportSummary.delta_pct.sold_count)],
      ["Total Sales Volume", formatMoney(reportSummary.current.total_sales_volume), formatMoney(reportSummary.previous.total_sales_volume), formatDelta(reportSummary.delta_pct.total_sales_volume)],
      ["Median Sold Price", formatMoney(reportSummary.current.median_sold_price), formatMoney(reportSummary.previous.median_sold_price), formatDelta(reportSummary.delta_pct.median_sold_price)],
      ["Median Price Per SqFt", formatMoney(reportSummary.current.median_price_per_sqft), formatMoney(reportSummary.previous.median_price_per_sqft), formatDelta(reportSummary.delta_pct.median_price_per_sqft)],
      ["New Listings", formatNumber(reportSummary.current.new_listings), formatNumber(reportSummary.previous.new_listings), formatDelta(reportSummary.delta_pct.new_listings)],
      ["Pending Sales", formatNumber(reportSummary.current.pending_sales), formatNumber(reportSummary.previous.pending_sales), formatDelta(reportSummary.delta_pct.pending_sales)],
      ["Active Inventory", formatNumber(reportSummary.current.active_inventory), formatNumber(reportSummary.previous.active_inventory), formatDelta(reportSummary.delta_pct.active_inventory)],
      ["Months Supply", formatNumber(reportSummary.current.months_supply), formatNumber(reportSummary.previous.months_supply), formatDelta(reportSummary.delta_pct.months_supply)],
      ["Median DOM", formatNumber(reportSummary.current.median_dom), formatNumber(reportSummary.previous.median_dom), formatDelta(reportSummary.delta_pct.median_dom)],
      ["Median Listing Discount", formatPercent(reportSummary.current.median_listing_discount), formatPercent(reportSummary.previous.median_listing_discount), formatDelta(reportSummary.delta_pct.median_listing_discount)],
      ["Cash Sales %", formatPercent(reportSummary.current.cash_sales_percent), formatPercent(reportSummary.previous.cash_sales_percent), formatDelta(reportSummary.delta_pct.cash_sales_percent)],
    ];
  }, [reportSummary]);

  const historicalRows = periodSeries?.rows ?? [];
  const historicalLabels = useMemo(() => {
    if (!historicalRows.length) return [];
    const mid = Math.floor((historicalRows.length - 1) / 2);
    return [
      { index: 0, label: historicalRows[0].period },
      { index: mid, label: historicalRows[mid].period },
      { index: historicalRows.length - 1, label: historicalRows[historicalRows.length - 1].period },
    ].filter((v, i, arr) => arr.findIndex((x) => x.index === v.index) === i);
  }, [historicalRows]);

  const trendRows = trends?.rows ?? [];
  const marketGradeInfo = useMemo(() => getMarketGradeInfo(reportSummary), [reportSummary]);

  function printMarketReport(): void {
    if (!reportSummary) return;
    const scopeLine = marketScopeLabel;
    const origin = window.location.origin;

    const snapshotMetrics = buildSmartSnapshotMetrics(reportSummary);

    function buildTickValues(min: number, max: number, count = 4): number[] {
      if (min === max) return [min];
      return Array.from({ length: count }, (_, i) => min + ((max - min) * i) / (count - 1));
    }

    function axisLabelFor(value: number, kind: "count" | "currency" | "msi"): string {
      if (kind === "currency") return `$${new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value)}`;
      if (kind === "msi") return value.toFixed(1);
      return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(value);
    }

    function buildLineChartSvg(
      labels: string[],
      valuesInput: number[],
      lineColor: string,
      axisKind: "count" | "currency" | "msi"
    ): string {
      const width = 360;
      const height = 200;
      const pad = { left: 54, right: 12, top: 16, bottom: 34 };
      const values = valuesInput.length ? valuesInput : [0];
      let min = Math.min(...values);
      let max = Math.max(...values);
      if (axisKind !== "currency") min = Math.min(0, min);
      if (min === max) {
        const bump = min === 0 ? 1 : Math.abs(min) * 0.2;
        min -= bump;
        max += bump;
      }

      const chartW = width - pad.left - pad.right;
      const chartH = height - pad.top - pad.bottom;
      const xFor = (i: number) => (values.length <= 1 ? pad.left : pad.left + (i / (values.length - 1)) * chartW);
      const yFor = (v: number) => pad.top + chartH - ((v - min) / (max - min)) * chartH;
      const points = values.map((v, i) => `${xFor(i)},${yFor(v)}`).join(" L ");
      const path = `M ${points}`;
      const yTicks = buildTickValues(min, max, 4);
      const yTickHtml = yTicks
        .map((t) => {
          const y = yFor(t);
          return `<line x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}" stroke="#dfe7e5" stroke-width="1" />
                  <text x="${pad.left - 6}" y="${y + 4}" text-anchor="end" font-size="10" fill="#5b6a68">${escapeHtml(axisLabelFor(t, axisKind))}</text>`;
        })
        .join("");

      const xLabelIdx = Array.from(new Set([0, Math.floor((labels.length - 1) / 2), labels.length - 1])).filter(
        (idx) => idx >= 0 && idx < labels.length
      );
      const xTickHtml = xLabelIdx
        .map((idx) => `<text x="${xFor(idx)}" y="${height - 10}" text-anchor="middle" font-size="10" fill="#5b6a68">${escapeHtml(labels[idx])}</text>`)
        .join("");
      const circles = values
        .map((v, i) => `<circle cx="${xFor(i)}" cy="${yFor(v)}" r="3.5" fill="#d86f1d" />`)
        .join("");

      return `
        <svg viewBox="0 0 ${width} ${height}" width="100%" height="200" role="img" aria-label="chart">
          <rect x="0" y="0" width="${width}" height="${height}" fill="#f8fbfa" rx="12" />
          ${yTickHtml}
          <line x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}" stroke="#bac8c4" stroke-width="1.2" />
          <path d="${path}" stroke="${lineColor}" stroke-width="3" fill="none" />
          ${circles}
          ${xTickHtml}
        </svg>
      `;
    }

    function buildBarChartSvg(labels: string[], valuesInput: number[], barColor: string, axisKind: "currency" | "count"): string {
      const width = 360;
      const height = 200;
      const pad = { left: 54, right: 12, top: 16, bottom: 34 };
      const values = valuesInput.length ? valuesInput : [0];
      const min = 0;
      let max = Math.max(...values);
      if (max <= 0) max = 1;
      const chartW = width - pad.left - pad.right;
      const chartH = height - pad.top - pad.bottom;
      const slotW = chartW / values.length;
      const yFor = (v: number) => pad.top + chartH - ((v - min) / (max - min)) * chartH;

      const yTicks = buildTickValues(min, max, 4);
      const yTickHtml = yTicks
        .map((t) => {
          const y = yFor(t);
          return `<line x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}" stroke="#dfe7e5" stroke-width="1" />
                  <text x="${pad.left - 6}" y="${y + 4}" text-anchor="end" font-size="10" fill="#5b6a68">${escapeHtml(axisLabelFor(t, axisKind === "currency" ? "currency" : "count"))}</text>`;
        })
        .join("");
      const bars = values
        .map((v, i) => {
          const x = pad.left + i * slotW + 3;
          const y = yFor(v);
          const w = Math.max(2, slotW - 6);
          const h = height - pad.bottom - y;
          return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="3" fill="${barColor}" />`;
        })
        .join("");
      const xLabelIdx = Array.from(new Set([0, Math.floor((labels.length - 1) / 2), labels.length - 1])).filter(
        (idx) => idx >= 0 && idx < labels.length
      );
      const xTickHtml = xLabelIdx
        .map((idx) => {
          const x = pad.left + idx * slotW + slotW / 2;
          return `<text x="${x}" y="${height - 10}" text-anchor="middle" font-size="10" fill="#5b6a68">${escapeHtml(labels[idx])}</text>`;
        })
        .join("");

      return `
        <svg viewBox="0 0 ${width} ${height}" width="100%" height="200" role="img" aria-label="chart">
          <rect x="0" y="0" width="${width}" height="${height}" fill="#f8fbfa" rx="12" />
          ${yTickHtml}
          <line x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}" stroke="#bac8c4" stroke-width="1.2" />
          ${bars}
          ${xTickHtml}
        </svg>
      `;
    }

    const graphRows = (periodSeries?.rows ?? []).slice(-12);
    const graphLabels =
      graphRows.length > 0 ? graphRows.map((r) => r.period) : trendRows.slice(-12).map((r) => r.period);
    const soldSeries =
      graphRows.length > 0 ? graphRows.map((r) => r.sold_count ?? 0) : trendRows.slice(-12).map((r) => r.sold_count ?? 0);
    const priceSeries = graphRows.length > 0 ? graphRows.map((r) => r.median_sold_price ?? 0) : [];
    const volumeSeries = graphRows.length > 0 ? graphRows.map((r) => r.total_sales_volume ?? 0) : [];

    const chartsHtml = `
      <section class="chart-section">
        <h2>Market Trend Visuals</h2>
        <div class="chart-grid">
          <article class="chart-card">
            <h3>Closed Sales Trend</h3>
            ${buildLineChartSvg(graphLabels, soldSeries, "#008c8a", "count")}
          </article>
          <article class="chart-card">
            <h3>Median Sold Price Trend</h3>
            ${buildLineChartSvg(graphLabels, priceSeries, "#2f6fb3", "currency")}
          </article>
          <article class="chart-card">
            <h3>Total Sales Volume</h3>
            ${buildBarChartSvg(graphLabels, volumeSeries, "#d86f1d", "currency")}
          </article>
        </div>
      </section>
    `;

    const snapshotHtml = snapshotMetrics
      .map((m) => {
        const deltaClass =
          m.deltaValue == null || Number.isNaN(m.deltaValue) ? "delta-flat" : m.deltaValue > 0 ? "delta-up" : m.deltaValue < 0 ? "delta-down" : "delta-flat";
        const iconSrc = m.iconPath ? `${origin}${m.iconPath}` : "";
        return `
          <article class="stat-card">
            <div class="stat-head">
              ${iconSrc ? `<img src="${escapeHtml(iconSrc)}" alt="${escapeHtml(m.label)}" class="stat-icon" />` : `<span class="stat-icon placeholder"></span>`}
              <p class="stat-label">${escapeHtml(m.label)}</p>
            </div>
            <p class="stat-value">${escapeHtml(m.value)}</p>
            <p class="stat-sub">Prev: ${escapeHtml(m.previous)}</p>
            <p class="stat-delta ${deltaClass}">${escapeHtml(m.delta)}</p>
          </article>
        `;
      })
      .join("");

    const topSubdivisionRows = (rankings?.rows ?? [])
      .slice(0, 6)
      .map(
        (r) => `
          <tr>
            <td>${escapeHtml(r.final_subdivision)}</td>
            <td>${escapeHtml(r.city ?? "-")}</td>
            <td>${escapeHtml(formatNumber(r.sold_count))}</td>
            <td>${escapeHtml(formatMoney(r.avg_sold_price))}</td>
          </tr>`
      )
      .join("");

    const html = `
      <!doctype html>
      <html>
      <head>
        <meta charset="utf-8" />
        <title>Market Report - ${escapeHtml(reportSummary.period_label)}</title>
        <style>
          :root {
            --teal: #008c8a;
            --blue: #2f6fb3;
            --orange: #d86f1d;
            --ink: #1b2625;
            --muted: #5a6967;
          }
          * { box-sizing: border-box; }
          body {
            font-family: "Avenir Next", "Gill Sans", "Trebuchet MS", sans-serif;
            margin: 20px;
            color: var(--ink);
            background: #f4f6f5;
          }
          .hero {
            background: linear-gradient(130deg, #eef9f7 0%, #f7efe7 55%, #eef4fb 100%);
            border: 1px solid #d9e4e1;
            border-radius: 14px;
            padding: 16px 18px;
            margin-bottom: 12px;
          }
          .eyebrow {
            margin: 0;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-size: 11px;
            color: var(--teal);
            font-weight: 700;
          }
          h1 {
            margin: 6px 0 2px;
            font-size: 28px;
            line-height: 1.05;
          }
          .hero-sub {
            margin: 2px 0;
            color: var(--muted);
            font-size: 13px;
          }
          .panel {
            background: #fff;
            border: 1px solid #dce6e3;
            border-radius: 14px;
            padding: 14px;
            margin-bottom: 12px;
          }
          h2 { margin: 0 0 8px; font-size: 18px; }
          h3 { margin: 0 0 8px; font-size: 14px; color: #31413f; }
          .stats-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
          }
          .stat-card {
            border: 1px solid #dde8e5;
            border-radius: 12px;
            padding: 10px;
            background: linear-gradient(180deg, #ffffff 0%, #f8fbfa 100%);
          }
          .stat-head {
            display: flex;
            align-items: center;
            gap: 8px;
          }
          .stat-icon {
            width: 24px;
            height: 24px;
            object-fit: contain;
          }
          .stat-icon.placeholder {
            border-radius: 50%;
            background: #d7e2df;
          }
          .stat-label {
            margin: 0;
            font-size: 11px;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: #4f5f5d;
          }
          .stat-value {
            margin: 6px 0 2px;
            font-size: 30px;
            font-weight: 700;
            line-height: 1;
          }
          .stat-sub {
            margin: 0;
            font-size: 11px;
            color: #61716f;
          }
          .stat-delta {
            margin: 2px 0 0;
            font-size: 12px;
            font-weight: 700;
          }
          .delta-up { color: var(--blue); }
          .delta-down { color: #b53b3b; }
          .delta-flat { color: #61716f; }
          .chart-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 10px;
          }
          .chart-card {
            border: 1px solid #dde8e5;
            border-radius: 12px;
            padding: 10px;
            background: #fff;
          }
          table { border-collapse: collapse; width: 100%; margin-top: 8px; }
          th, td { border-bottom: 1px solid #e6edeb; padding: 8px 6px; text-align: left; font-size: 12px; }
          th { text-transform: uppercase; letter-spacing: 0.04em; color: #4d5d5a; font-size: 11px; }
          @media print {
            body { margin: 0; background: #fff; }
            .panel, .hero { break-inside: avoid; }
          }
        </style>
      </head>
      <body>
        <section class="hero">
          <p class="eyebrow">Douglas Elliman | ReStats Premier</p>
          <h1>Market Snapshot Report</h1>
          <p class="hero-sub"><strong>Period:</strong> ${escapeHtml(reportSummary.period_label)}</p>
          <p class="hero-sub"><strong>Current:</strong> ${escapeHtml(reportSummary.current_start)} to ${escapeHtml(reportSummary.current_end)} | <strong>Previous:</strong> ${escapeHtml(reportSummary.previous_start)} to ${escapeHtml(reportSummary.previous_end)}</p>
          <p class="hero-sub"><strong>Scope:</strong> ${escapeHtml(scopeLine)}</p>
        </section>

        <section class="panel">
          <h2>9-Key Market Snapshot</h2>
          <p class="hero-sub">Auto-selected: 5 core indicators + 4 context metrics based on current market conditions.</p>
          <div class="stats-grid">${snapshotHtml}</div>
        </section>

        ${chartsHtml}

        <section class="panel">
          <h2>Top Subdivision Momentum</h2>
          <table>
            <thead><tr><th>Subdivision</th><th>City</th><th>Sold</th><th>Avg Sold</th></tr></thead>
            <tbody>${topSubdivisionRows}</tbody>
          </table>
        </section>
      </body>
      </html>
    `;

    const w = window.open("", "_blank");
    if (!w) return;
    w.document.write(html);
    w.document.close();
    w.focus();
    w.print();
  }

  function printHistoricalReport(): void {
    const rows = periodSeries?.rows ?? [];
    if (!rows.length) return;
    const scopeLine = marketScopeLabel;
    const periodLabel = reportSummary?.period_label ?? `${activeWindow.start} to ${activeWindow.end}`;
    const generatedOn = new Date().toLocaleDateString("en-US", {
      month: "long",
      day: "numeric",
      year: "numeric",
    });
    const rowsHtml = rows
      .map(
        (r) =>
          `<tr>
            <td>${escapeHtml(r.period)}</td>
            <td>${escapeHtml(formatNumber(r.sold_count))}</td>
            <td>${escapeHtml(formatMoney(r.median_sold_price))}</td>
            <td>${escapeHtml(formatMoney(r.total_sales_volume))}</td>
            <td>${escapeHtml(formatNumber(r.new_listings))}</td>
            <td>${escapeHtml(formatNumber(r.pending_sales))}</td>
            <td>${escapeHtml(formatNumber(r.active_inventory))}</td>
            <td>${escapeHtml(formatNumber(r.months_supply))}</td>
            <td>${escapeHtml(formatNumber(r.median_dom))}</td>
          </tr>`
      )
      .join("");
    const html = `
      <!doctype html>
      <html>
      <head>
        <meta charset="utf-8" />
        <title>Historical Market Report</title>
        <style>
          :root {
            --teal: #008c8a;
            --ink: #1b2625;
            --muted: #5a6967;
            --panel: #f7fbfa;
          }
          * { box-sizing: border-box; }
          body { font-family: "Avenir Next", "Gill Sans", "Trebuchet MS", sans-serif; margin: 20px; color: var(--ink); background: #f4f6f5; }
          .hero {
            background: linear-gradient(130deg, #eef9f7 0%, #f7efe7 55%, #eef4fb 100%);
            border: 1px solid #d9e4e1;
            border-radius: 14px;
            padding: 16px 18px;
            margin-bottom: 12px;
          }
          .eyebrow {
            margin: 0;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            font-size: 11px;
            color: var(--teal);
            font-weight: 700;
          }
          h1 { margin: 6px 0 2px; font-size: 28px; line-height: 1.05; }
          .hero-sub { margin: 2px 0; color: var(--muted); font-size: 13px; }
          .panel {
            background: #fff;
            border: 1px solid #dce6e3;
            border-radius: 14px;
            padding: 14px;
          }
          table { border-collapse: collapse; width: 100%; margin-top: 8px; }
          th, td { border-bottom: 1px solid #e6edeb; padding: 8px 6px; text-align: left; font-size: 12px; }
          th { text-transform: uppercase; letter-spacing: 0.04em; color: #4d5d5a; font-size: 11px; background: var(--panel); }
          .footer { margin-top: 12px; color: var(--muted); font-size: 12px; }
          @media print {
            body { margin: 0; background: #fff; }
            .hero, .panel { break-inside: avoid; }
          }
        </style>
      </head>
      <body>
        <section class="hero">
          <p class="eyebrow">Douglas Elliman | ReStats Premier</p>
          <h1>Historical Market Stats</h1>
          <p class="hero-sub"><strong>Period:</strong> ${escapeHtml(periodLabel)}</p>
          <p class="hero-sub"><strong>Scope:</strong> ${escapeHtml(scopeLine)}</p>
          <p class="hero-sub"><strong>Series:</strong> ${escapeHtml(seriesFrequency)} | <strong>Periods:</strong> ${escapeHtml(seriesPeriods)}</p>
        </section>
        <section class="panel">
          <table>
            <thead>
              <tr><th>Period</th><th>Sold</th><th>Median Sold</th><th>Volume</th><th>New Listings</th><th>Pending</th><th>Inventory</th><th>MSI</th><th>Median DOM</th></tr>
            </thead>
            <tbody>${rowsHtml}</tbody>
          </table>
          <p class="footer">Generated by ReStats Analytics | Data as of ${escapeHtml(generatedOn)}</p>
        </section>
      </body>
      </html>
    `;
    const w = window.open("", "_blank");
    if (!w) return;
    w.document.write(html);
    w.document.close();
    w.focus();
    w.print();
  }

  return (
    <main className="page-shell">
      <header className="hero">
        <div>
          <img src="/icons/elliman-logo.png" alt="Elliman" className="brand-logo" />
          <p className="eyebrow">ReStats Premier</p>
          <h1>Market Intelligence Report</h1>
          <p className="hero-copy">{reportSummary?.period_label ?? `${activeWindow.start} to ${activeWindow.end}`}</p>
        </div>
        <div className="actions">
          <button className="btn" onClick={() => downloadCsv("subdivision_rankings.csv", (rankings?.rows ?? []) as Array<Record<string, unknown>>)}>Export Rankings CSV</button>
          <button className="btn" onClick={() => downloadCsv("recent_closings.csv", (recentListings?.rows ?? []) as Array<Record<string, unknown>>)}>Export Closings CSV</button>
          <button className="btn" onClick={printHistoricalReport}>Print Historical</button>
          <button className="btn ghost" onClick={printMarketReport}>Print Market Report</button>
        </div>
      </header>

      <section className="filter-grid">
        <div className="filter-card">
          <label htmlFor="reportMode">Report Type</label>
          <select id="reportMode" value={reportMode} onChange={(e) => setReportMode(e.target.value as ReportMode)}>
            <option value="rolling">Rolling Window</option>
            <option value="monthly">Monthly Report</option>
            <option value="quarterly">Quarterly Report</option>
            <option value="annual">Annual Report</option>
            <option value="custom">Custom Date Range</option>
          </select>

          {reportMode === "rolling" ? (
            <>
              <label htmlFor="period">Rolling Days</label>
              <select id="period" value={periodDays} onChange={(e) => setPeriodDays(Number(e.target.value))}>
                <option value={30}>30 Days</option>
                <option value={60}>60 Days</option>
                <option value={90}>90 Days</option>
                <option value={180}>180 Days</option>
                <option value={365}>365 Days</option>
              </select>
            </>
          ) : null}

          {reportMode === "monthly" ? (
            <>
              <label htmlFor="year">Year</label>
              <select id="year" value={refYear} onChange={(e) => setRefYear(Number(e.target.value))}>
                {yearOptions.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
              <label htmlFor="month">Month</label>
              <select id="month" value={refMonth} onChange={(e) => setRefMonth(Number(e.target.value))}>
                {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </>
          ) : null}

          {reportMode === "quarterly" ? (
            <>
              <label htmlFor="qyear">Year</label>
              <select id="qyear" value={refYear} onChange={(e) => setRefYear(Number(e.target.value))}>
                {yearOptions.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
              <label htmlFor="quarter">Quarter</label>
              <select id="quarter" value={refQuarter} onChange={(e) => setRefQuarter(Number(e.target.value))}>
                <option value={1}>Q1</option><option value={2}>Q2</option><option value={3}>Q3</option><option value={4}>Q4</option>
              </select>
            </>
          ) : null}

          {reportMode === "annual" ? (
            <>
              <label htmlFor="ayear">Year</label>
              <select id="ayear" value={refYear} onChange={(e) => setRefYear(Number(e.target.value))}>
                {yearOptions.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
            </>
          ) : null}

          {reportMode === "custom" ? (
            <>
              <label htmlFor="start">Start Date</label>
              <input id="start" type="date" value={customStart} onChange={(e) => setCustomStart(e.target.value)} />
              <label htmlFor="end">End Date</label>
              <input id="end" type="date" value={customEnd} onChange={(e) => setCustomEnd(e.target.value)} />
            </>
          ) : null}
        </div>

        <div className="filter-card">
          <label htmlFor="city">City</label>
          <select id="city" value={city} onChange={(e) => setCity(e.target.value)}>
            <option value="">All Cities</option>
            {(filterOptions?.cities ?? []).map((c) => <option key={c.city} value={c.city}>{c.city} ({c.count})</option>)}
          </select>
          <label htmlFor="geo_zone">Geo Location</label>
          <select id="geo_zone" value={geoZone} onChange={(e) => setGeoZone(e.target.value)}>
            <option value="">All Geo Locations</option>
            {(filterOptions?.geo_zones ?? []).map((g) => <option key={g.geo_zone} value={g.geo_zone}>{g.geo_zone} ({g.count})</option>)}
          </select>
          <label htmlFor="soldSince">KPI Sold Since</label>
          <input id="soldSince" type="date" value={soldSince} onChange={(e) => setSoldSince(e.target.value)} />
        </div>

        <div className="filter-card">
          <label htmlFor="subdivision">Subdivision</label>
          <select id="subdivision" value={finalSubdivision} onChange={(e) => setFinalSubdivision(e.target.value)}>
            <option value="">All Subdivisions</option>
            {(filterOptions?.subdivisions ?? []).map((s) => <option key={s.final_subdivision} value={s.final_subdivision}>{s.final_subdivision} ({s.count})</option>)}
          </select>
          <label htmlFor="property_group">Property Group</label>
          <select id="property_group" value={propertyGroup} onChange={(e) => setPropertyGroup(e.target.value as PropertyGroup)}>
            {(filterOptions?.property_groups ?? []).map((pg) => <option key={pg.value} value={pg.value}>{pg.label}</option>)}
          </select>
          <label htmlFor="property_type">Raw Property Type</label>
          <select id="property_type" value={propertyType} onChange={(e) => setPropertyType(e.target.value)}>
            <option value="">All Raw Types</option>
            {(filterOptions?.property_types ?? []).map((p) => <option key={p.property_type} value={p.property_type}>{p.property_type} ({p.count})</option>)}
          </select>
        </div>

        <div className="filter-card">
          <label htmlFor="clear">Reset Filters</label>
          <button
            id="clear"
            className="btn"
            onClick={() => {
              setCity(""); setGeoZone(""); setFinalSubdivision(""); setPropertyGroup("ALL"); setPropertyType("");
            }}
          >
            Reset Location/Type
          </button>
        </div>
      </section>

      {error ? <section className="error">{error}</section> : null}

      <section className="panel report-panel">
        <h2>Market Metrics: {reportSummary?.period_label ?? "Current Period"}</h2>
        <p className="panel-subtitle">
          Current: {reportSummary?.current_start ?? activeWindow.start} to {reportSummary?.current_end ?? activeWindow.end}
        </p>
        <p className="panel-subtitle"><strong>Market Scope:</strong> {marketScopeLabel}</p>
        <div className="kpi-grid report-grid">
          <MetricVisualCard label="Sold Count" value={formatNumber(reportSummary?.current.sold_count)} delta={formatDelta(reportSummary?.delta_pct.sold_count)} deltaValue={reportSummary?.delta_pct.sold_count} />
          <MetricVisualCard label="Sales Volume" value={formatMoney(reportSummary?.current.total_sales_volume)} delta={formatDelta(reportSummary?.delta_pct.total_sales_volume)} deltaValue={reportSummary?.delta_pct.total_sales_volume} />
          <MetricVisualCard label="Median Sold Price" value={formatMoney(reportSummary?.current.median_sold_price)} delta={formatDelta(reportSummary?.delta_pct.median_sold_price)} deltaValue={reportSummary?.delta_pct.median_sold_price} />
          <MetricVisualCard label="Median PPSF" value={formatMoney(reportSummary?.current.median_price_per_sqft)} delta={formatDelta(reportSummary?.delta_pct.median_price_per_sqft)} deltaValue={reportSummary?.delta_pct.median_price_per_sqft} />
          <MetricVisualCard label="New Listings" value={formatNumber(reportSummary?.current.new_listings)} delta={formatDelta(reportSummary?.delta_pct.new_listings)} deltaValue={reportSummary?.delta_pct.new_listings} />
          <MetricVisualCard label="Pending Sales" value={formatNumber(reportSummary?.current.pending_sales)} delta={formatDelta(reportSummary?.delta_pct.pending_sales)} deltaValue={reportSummary?.delta_pct.pending_sales} />
          <MetricVisualCard label="Active Inventory" value={formatNumber(reportSummary?.current.active_inventory)} delta={formatDelta(reportSummary?.delta_pct.active_inventory)} deltaValue={reportSummary?.delta_pct.active_inventory} />
          <MetricVisualCard label="Months Supply" value={formatNumber(reportSummary?.current.months_supply)} delta={formatDelta(reportSummary?.delta_pct.months_supply)} deltaValue={reportSummary?.delta_pct.months_supply} />
          <MetricVisualCard label="Median DOM" value={formatNumber(reportSummary?.current.median_dom)} delta={formatDelta(reportSummary?.delta_pct.median_dom)} deltaValue={reportSummary?.delta_pct.median_dom} />
          <MetricVisualCard label="Median Discount" value={formatPercent(reportSummary?.current.median_listing_discount)} delta={formatDelta(reportSummary?.delta_pct.median_listing_discount)} deltaValue={reportSummary?.delta_pct.median_listing_discount} />
          <MetricVisualCard label="Cash Sales %" value={formatPercent(reportSummary?.current.cash_sales_percent)} delta={formatDelta(reportSummary?.delta_pct.cash_sales_percent)} deltaValue={reportSummary?.delta_pct.cash_sales_percent} />
          <MetricVisualCard label="Avg Sold Price" value={formatMoney(reportSummary?.current.avg_sold_price)} delta={formatDelta(reportSummary?.delta_pct.avg_sold_price)} deltaValue={reportSummary?.delta_pct.avg_sold_price} />
          <MetricVisualCard
            label="Market Grade"
            value={marketGradeInfo.finalScore == null ? marketGradeInfo.label : `${marketGradeInfo.label} (${marketGradeInfo.finalScore.toFixed(1)})`}
          />
        </div>
        <p className="panel-subtitle">
          <strong>Market Grade v2:</strong> {marketGradeInfo.formula}
        </p>
        <p className="panel-subtitle">
          <strong>Grade Read:</strong> {marketGradeInfo.description}
        </p>
        <p className="panel-subtitle">
          <strong>Components (0-100):</strong> Pace {marketGradeInfo.pace == null ? "N/A" : marketGradeInfo.pace.toFixed(1)} | Supply {marketGradeInfo.supply == null ? "N/A" : marketGradeInfo.supply.toFixed(1)} | Pricing {marketGradeInfo.pricing == null ? "N/A" : marketGradeInfo.pricing.toFixed(1)} | Demand {marketGradeInfo.demand == null ? "N/A" : marketGradeInfo.demand.toFixed(1)}
        </p>
        <p className="panel-subtitle">
          Deltas vs previous period: Sold {formatDelta(reportSummary?.delta_pct.sold_count)} | Volume {formatDelta(reportSummary?.delta_pct.total_sales_volume)} | Median Price {formatDelta(reportSummary?.delta_pct.median_sold_price)} | DOM {formatDelta(reportSummary?.delta_pct.median_dom)} | Cash {formatDelta(reportSummary?.delta_pct.cash_sales_percent)}
        </p>
        <div className="table-wrap">
          <table className="data-table compact">
            <thead>
              <tr>
                <th>Metric</th>
                <th>Current</th>
                <th>Previous</th>
                <th>Delta</th>
              </tr>
            </thead>
            <tbody>
              {metricRows.map((r) => (
                <tr key={r[0]}>
                  <td>{r[0]}</td>
                  <td>{r[1]}</td>
                  <td>{r[2]}</td>
                  <td>{r[3]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <h2>Run Status</h2>
        <p className="panel-subtitle">
          MLS last status date: {opsStatus?.database.last_mls_status_date ?? "N/A"} | Off-market last sold date: {opsStatus?.database.last_off_market_sold_date ?? "N/A"} | Total records: {formatNumber(opsStatus?.database.listing_count)}
        </p>
        <p className="panel-subtitle">
          Duplicate audit: {opsStatus?.duplicate_audit.available ? `OK (${opsStatus?.duplicate_audit.generated_at ?? "no timestamp"})` : "Not available"}
          {opsStatus?.duplicate_audit.available
            ? ` | PK dupes: ${opsStatus?.duplicate_audit.duplicate_listing_number_count ?? 0} | Near dupes: ${opsStatus?.duplicate_audit.near_duplicate_count ?? 0} | Cross-source: ${opsStatus?.duplicate_audit.cross_source_count ?? 0}`
            : ""}
        </p>
      </section>

      <section className="panel">
        <div className="listings-head">
          <div>
            <h2>Historical Market Stats</h2>
            <p className="panel-subtitle">Multi-period reporting view (monthly / quarterly / annual)</p>
          </div>
          <div className="inline-controls">
            <select value={seriesFrequency} onChange={(e) => setSeriesFrequency(e.target.value as "monthly" | "quarterly" | "annual")}>
              <option value="monthly">Monthly</option>
              <option value="quarterly">Quarterly</option>
              <option value="annual">Annual</option>
            </select>
            <select value={seriesPeriods} onChange={(e) => setSeriesPeriods(Number(e.target.value))}>
              <option value={6}>6 periods</option>
              <option value={8}>8 periods</option>
              <option value={12}>12 periods</option>
              <option value={16}>16 periods</option>
              <option value={20}>20 periods</option>
            </select>
          </div>
        </div>
        <div className="graph-grid">
          <article className="graph-card">
            <h3>Median Sold Price</h3>
            {(() => {
              const width = 360;
              const height = 170;
              const pad: ChartPadding = { left: 52, right: 10, top: 12, bottom: 24 };
              const values = getCleanValues(historicalRows.map((r) => r.median_sold_price));
              const domain = getChartDomain(values, false);
              const ticks = buildTicks(domain, 4);
              const path = buildLinePath(values, domain, width, height, pad);
              return (
                <svg viewBox={`0 0 ${width} ${height}`} className="linechart small" role="img" aria-label="Historical median sold price chart">
                  <rect x="0" y="0" width={width} height={height} fill="#f6f8f7" rx="10" />
                  {ticks.map((tick, i) => {
                    const y = yForValue(tick, domain, height, pad);
                    return (
                      <g key={`msp-tick-${i}`}>
                        <line x1={pad.left} y1={y} x2={width - pad.right} y2={y} className="chart-gridline" />
                        <text x={pad.left - 6} y={y + 4} textAnchor="end" className="chart-tick-label">{formatAxisValue(tick, "currency")}</text>
                      </g>
                    );
                  })}
                  <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} className="chart-axis" />
                  <path d={path} stroke="#2f6fb3" strokeWidth="3" fill="none" />
                  {historicalLabels.map((label) => (
                    <text key={`msp-label-${label.index}`} x={xForIndex(label.index, values.length, width, pad)} y={height - 6} textAnchor="middle" className="chart-tick-label">{label.label}</text>
                  ))}
                </svg>
              );
            })()}
          </article>
          <article className="graph-card">
            <h3>Total Sales Volume</h3>
            {(() => {
              const width = 360;
              const height = 170;
              const pad: ChartPadding = { left: 52, right: 10, top: 12, bottom: 24 };
              const values = getCleanValues(historicalRows.map((r) => r.total_sales_volume));
              const domain = getChartDomain(values, true);
              const ticks = buildTicks(domain, 4);
              const chartWidth = width - pad.left - pad.right;
              const barSlot = values.length ? chartWidth / values.length : 0;
              return (
                <svg viewBox={`0 0 ${width} ${height}`} className="linechart small" role="img" aria-label="Historical volume chart">
                  <rect x="0" y="0" width={width} height={height} fill="#f6f8f7" rx="10" />
                  {ticks.map((tick, i) => {
                    const y = yForValue(tick, domain, height, pad);
                    return (
                      <g key={`vol-tick-${i}`}>
                        <line x1={pad.left} y1={y} x2={width - pad.right} y2={y} className="chart-gridline" />
                        <text x={pad.left - 6} y={y + 4} textAnchor="end" className="chart-tick-label">{formatAxisValue(tick, "currency")}</text>
                      </g>
                    );
                  })}
                  <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} className="chart-axis" />
                  {values.map((v, i) => {
                    const x = pad.left + i * barSlot + 2;
                    const y = yForValue(v, domain, height, pad);
                    const h = height - pad.bottom - y;
                    return <rect key={historicalRows[i]?.period ?? i} x={x} y={y} width={Math.max(2, barSlot - 4)} height={Math.max(0, h)} fill="#d86f1d" rx="3" />;
                  })}
                  {historicalLabels.map((label) => {
                    const x = values.length
                      ? pad.left + label.index * barSlot + barSlot / 2
                      : pad.left;
                    return <text key={`vol-label-${label.index}`} x={x} y={height - 6} textAnchor="middle" className="chart-tick-label">{label.label}</text>;
                  })}
                </svg>
              );
            })()}
          </article>
          <article className="graph-card">
            <h3>Months Supply (MSI)</h3>
            {(() => {
              const width = 360;
              const height = 170;
              const pad: ChartPadding = { left: 52, right: 10, top: 12, bottom: 24 };
              const values = getCleanValues(historicalRows.map((r) => r.months_supply));
              const domain = getChartDomain(values, true);
              const ticks = buildTicks(domain, 4);
              const path = buildLinePath(values, domain, width, height, pad);
              return (
                <svg viewBox={`0 0 ${width} ${height}`} className="linechart small" role="img" aria-label="Historical months supply chart">
                  <rect x="0" y="0" width={width} height={height} fill="#f6f8f7" rx="10" />
                  {ticks.map((tick, i) => {
                    const y = yForValue(tick, domain, height, pad);
                    return (
                      <g key={`msi-tick-${i}`}>
                        <line x1={pad.left} y1={y} x2={width - pad.right} y2={y} className="chart-gridline" />
                        <text x={pad.left - 6} y={y + 4} textAnchor="end" className="chart-tick-label">{formatAxisValue(tick, "msi")}</text>
                      </g>
                    );
                  })}
                  <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} className="chart-axis" />
                  <path d={path} stroke="#2d8a5d" strokeWidth="3" fill="none" />
                  {historicalLabels.map((label) => (
                    <text key={`msi-label-${label.index}`} x={xForIndex(label.index, values.length, width, pad)} y={height - 6} textAnchor="middle" className="chart-tick-label">{label.label}</text>
                  ))}
                </svg>
              );
            })()}
          </article>
        </div>
        <div className="table-wrap">
          <table className="data-table compact">
            <thead>
              <tr>
                <th>Period</th>
                <th>Sold</th>
                <th>Median Sold</th>
                <th>Volume</th>
                <th>New Listings</th>
                <th>Pending</th>
                <th>Inventory</th>
                <th>MSI</th>
                <th>Median DOM</th>
              </tr>
            </thead>
            <tbody>
              {(periodSeries?.rows ?? []).map((r) => (
                <tr key={r.period}>
                  <td>{r.period}</td>
                  <td>{formatNumber(r.sold_count)}</td>
                  <td>{formatMoney(r.median_sold_price)}</td>
                  <td>{formatMoney(r.total_sales_volume)}</td>
                  <td>{formatNumber(r.new_listings)}</td>
                  <td>{formatNumber(r.pending_sales)}</td>
                  <td>{formatNumber(r.active_inventory)}</td>
                  <td>{formatNumber(r.months_supply)}</td>
                  <td>{formatNumber(r.median_dom)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="two-col">
        <article className="panel">
          <h2>Sales Trend</h2>
          <p className="panel-subtitle">{trends?.frequency ?? "monthly"} aggregation for selected report period</p>
          {(() => {
            const width = 560;
            const height = 190;
            const pad: ChartPadding = { left: 52, right: 12, top: 12, bottom: 28 };
            const values = trendRows.map((row) => row.sold_count);
            const domain = getChartDomain(values, true);
            const ticks = buildTicks(domain, 4);
            const trendPath = buildLinePath(values, domain, width, height, pad);
            const mid = Math.floor((trendRows.length - 1) / 2);
            const xLabels = trendRows.length
              ? [
                  { index: 0, label: trendRows[0].period },
                  { index: mid, label: trendRows[mid].period },
                  { index: trendRows.length - 1, label: trendRows[trendRows.length - 1].period },
                ].filter((v, i, arr) => arr.findIndex((x) => x.index === v.index) === i)
              : [];
            return (
              <svg viewBox={`0 0 ${width} ${height}`} className="linechart" role="img" aria-label="Sales trend chart">
                <rect x="0" y="0" width={width} height={height} fill="#f6f8f7" rx="10" />
                {ticks.map((tick, i) => {
                  const y = yForValue(tick, domain, height, pad);
                  return (
                    <g key={`trend-tick-${i}`}>
                      <line x1={pad.left} y1={y} x2={width - pad.right} y2={y} className="chart-gridline" />
                      <text x={pad.left - 6} y={y + 4} textAnchor="end" className="chart-tick-label">{formatAxisValue(tick, "count")}</text>
                    </g>
                  );
                })}
                <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} className="chart-axis" />
                <path d={trendPath} stroke="#008c8a" strokeWidth="3" fill="none" />
                {trendRows.map((row, i) => (
                  <circle
                    key={row.period}
                    cx={xForIndex(i, trendRows.length, width, pad)}
                    cy={yForValue(row.sold_count, domain, height, pad)}
                    r="4"
                    fill="#d86f1d"
                  />
                ))}
                {xLabels.map((item) => (
                  <text
                    key={`trend-label-${item.index}`}
                    x={xForIndex(item.index, trendRows.length, width, pad)}
                    y={height - 8}
                    textAnchor="middle"
                    className="chart-tick-label"
                  >
                    {item.label}
                  </text>
                ))}
              </svg>
            );
          })()}
        </article>
        <article className="panel">
          <h2>Inventory Mix</h2>
          <p className="panel-subtitle">Status distribution</p>
          <div className="donut-wrap">
            <svg viewBox="0 0 120 120" className="donut" aria-label="Inventory distribution">
              <circle cx="60" cy="60" r="34" fill="none" stroke="#ecf0ef" strokeWidth="16" />
              {inventorySegments.map((seg) => {
                const startAngle = seg.start * Math.PI * 2 - Math.PI / 2;
                const endAngle = seg.end * Math.PI * 2 - Math.PI / 2;
                const x1 = 60 + 34 * Math.cos(startAngle);
                const y1 = 60 + 34 * Math.sin(startAngle);
                const x2 = 60 + 34 * Math.cos(endAngle);
                const y2 = 60 + 34 * Math.sin(endAngle);
                const largeArc = seg.end - seg.start > 0.5 ? 1 : 0;
                return <path key={seg.status} d={`M ${x1} ${y1} A 34 34 0 ${largeArc} 1 ${x2} ${y2}`} stroke={seg.color} strokeWidth="16" fill="none" />;
              })}
            </svg>
            <div className="legend">
              {inventorySegments.map((seg) => (
                <div key={seg.status} className="legend-item">
                  <span className="swatch" style={{ backgroundColor: seg.color }} />
                  <span>{seg.status}</span>
                  <span>{seg.count}</span>
                </div>
              ))}
            </div>
          </div>
        </article>
      </section>

      <section className="panel listings-panel">
        <div className="listings-head">
          <div>
            <h2>Top Subdivision Momentum</h2>
            <p className="panel-subtitle">Ranked by sold count for selected report period</p>
          </div>
          <span className="pill">{rankings?.rows.length ?? 0} ranked</span>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>Subdivision</th><th>City</th><th>Sold</th><th>Avg Sold</th><th>Avg List</th><th>Avg SP/LP</th><th>Avg DOM</th></tr>
            </thead>
            <tbody>
              {(rankings?.rows ?? []).map((row) => (
                <tr key={`${row.final_subdivision}-${row.city ?? "na"}`}>
                  <td>{row.final_subdivision}</td><td>{row.city ?? "-"}</td><td>{formatNumber(row.sold_count)}</td>
                  <td>{formatMoney(row.avg_sold_price)}</td><td>{formatMoney(row.avg_list_price)}</td>
                  <td>{formatPercent(row.avg_sp_lp)}</td><td>{formatNumber(row.avg_dom)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel listings-panel">
        <div className="listings-head">
          <div><h2>Recent Closings</h2><p className="panel-subtitle">Filtered by selected report period</p></div>
          <span className="pill">{recentListings?.rows.length ?? 0} rows</span>
        </div>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr><th>Sold Date</th><th>City</th><th>Geo</th><th>Address</th><th>Subdivision</th><th>Type</th><th>List Price</th><th>Sold Price</th><th>SP/LP</th><th>Listing #</th></tr>
            </thead>
            <tbody>
              {(recentListings?.rows ?? []).map((row) => (
                <tr key={`${row.listing_number}-${row.sold_date ?? "na"}`}>
                  <td>{row.sold_date ?? "-"}</td><td>{row.city ?? "-"}</td><td>{row.geo_zone ?? "-"}</td><td>{row.short_address ?? "-"}</td><td>{row.final_subdivision ?? "-"}</td>
                  <td>{row.property_type ?? "-"}</td><td>{formatMoney(row.list_price)}</td><td>{formatMoney(row.sold_price)}</td>
                  <td>{row.sp_lp_ratio == null ? "-" : `${row.sp_lp_ratio}%`}</td><td className="mono">{row.listing_number}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
