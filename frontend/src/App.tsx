import { useEffect, useMemo, useRef, useState } from "react";
import {
  fetchFilterOptions,
  fetchInventory,
  fetchKpisWithFilters,
  fetchMarketPeriodSeries,
  fetchRecentListingsForRange,
  fetchReportListings,
  fetchReportSummary,
  fetchSubdivisionRankings,
  fetchTrends,
  runCma,
  type CmaComp,
  type CmaRunResponse,
  type FilterOptionsResponse,
  type InventoryResponse,
  type KpisResponse,
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
type BuilderChartType = "line" | "bar" | "pie" | "dual_axis";
type BuilderMetricKey =
  | "sold_count"
  | "total_sales_volume"
  | "median_sold_price"
  | "median_price_per_sqft"
  | "new_listings"
  | "pending_sales"
  | "pending_inventory"
  | "active_inventory"
  | "months_supply"
  | "median_dom"
  | "median_listing_discount"
  | "cash_sales_percent"
  | "avg_sp_lp"
  | "avg_sold_price";
type DashboardView = "market" | "cma";
type SidebarSection = "overview" | "trends" | "inventory" | "sales" | "neighborhoods" | "reports";

const MARKET_GUARDRAIL_BOUNDS = {
  north: 26.98,
  south: 26.43,
  east: -79.93,
  west: -80.38,
};

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

function formatDateDisplay(value: string | null | undefined): string {
  if (!value) return "-";
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return value;
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function asNumber(value: unknown): number | null {
  if (value == null) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
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

function isSingleFamilyType(value: unknown): boolean {
  const normalized = String(value ?? "").trim().toUpperCase();
  return (
    normalized === "SF" ||
    normalized === "SFH" ||
    normalized === "SINGLE FAMILY" ||
    normalized === "SINGLE-FAMILY" ||
    normalized === "SINGLE FAMILY HOME" ||
    normalized === "SINGLE FAMILY RESIDENCE" ||
    normalized.startsWith("SINGLE FAMILY")
  );
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

const BUILDER_METRIC_OPTIONS: Array<{
  key: BuilderMetricKey;
  label: string;
  kind: "money" | "number" | "percent";
}> = [
  { key: "sold_count", label: "Sold Count", kind: "number" },
  { key: "total_sales_volume", label: "Total Sales Volume", kind: "money" },
  { key: "median_sold_price", label: "Median Sold Price", kind: "money" },
  { key: "median_price_per_sqft", label: "Median Price Per SqFt", kind: "money" },
  { key: "avg_sold_price", label: "Avg Sold Price", kind: "money" },
  { key: "new_listings", label: "New Listings", kind: "number" },
  { key: "pending_sales", label: "New Pending Listings", kind: "number" },
  { key: "pending_inventory", label: "All Pending Listings", kind: "number" },
  { key: "active_inventory", label: "Active Inventory", kind: "number" },
  { key: "months_supply", label: "Months Supply", kind: "number" },
  { key: "median_dom", label: "Median DOM", kind: "number" },
  { key: "avg_sp_lp", label: "Avg SP/LP", kind: "percent" },
  { key: "median_listing_discount", label: "Median Listing Discount", kind: "percent" },
  { key: "cash_sales_percent", label: "Cash Sales %", kind: "percent" },
];

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
        "Market Grade blends pace, supply, pricing, and demand into one score.",
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
        "Market Grade blends pace, supply, pricing, and demand into one score.",
    };
  }

  let label = "F (Strong Buyer)";
  let description = "Buyers have the upper hand right now.";
  if (finalScore >= 80) {
    label = "A (Strong Seller)";
    description = "Homes are moving fast and sellers have strong leverage.";
  } else if (finalScore >= 65) {
    label = "B (Seller)";
    description = "Sellers still have an edge in this market.";
  } else if (finalScore >= 45) {
    label = "C (Balanced)";
    description = "The market is fairly balanced for buyers and sellers.";
  } else if (finalScore >= 30) {
    label = "D (Buyer)";
    description = "Buyers have better negotiating power than sellers.";
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
      "Market Grade blends pace, supply, pricing, and demand into one score.",
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
      <div className="metric-visual-content">
        <p className="metric-visual-label">{props.label}</p>
        <p className="metric-visual-value">{props.value}</p>
        {props.delta ? <p className={`metric-visual-delta ${deltaClass}`.trim()}>{props.delta}</p> : null}
      </div>
      {icon ? <img src={icon} alt={props.label} className="metric-icon" /> : <span className="metric-icon-fallback" />}
    </article>
  );
}

type SaleMapPoint = {
  listingNumber: string;
  lat: number;
  lon: number;
  address: string;
  soldPrice: number | null;
  soldDate: string | null;
  subdivision: string | null;
};

declare global {
  interface Window {
    google?: any;
    __restatsGoogleMapsPromise?: Promise<any>;
  }
}

function loadGoogleMaps(apiKey: string): Promise<any> {
  if (window.google?.maps) return Promise.resolve(window.google);
  if (window.__restatsGoogleMapsPromise) return window.__restatsGoogleMapsPromise;

  window.__restatsGoogleMapsPromise = new Promise((resolve, reject) => {
    const existing = document.getElementById("google-maps-js");
    if (existing) {
      existing.addEventListener("load", () => resolve(window.google));
      existing.addEventListener("error", () => reject(new Error("Google Maps failed to load")));
      return;
    }

    const script = document.createElement("script");
    script.id = "google-maps-js";
    script.async = true;
    script.defer = true;
    script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&libraries=visualization&v=weekly`;
    script.onload = () => resolve(window.google);
    script.onerror = () => reject(new Error("Google Maps failed to load"));
    document.head.appendChild(script);
  });

  return window.__restatsGoogleMapsPromise;
}

function distanceMilesBetween(aLat: number, aLon: number, bLat: number, bLon: number): number {
  const toRad = (value: number) => (value * Math.PI) / 180;
  const earthRadiusMiles = 3958.8;
  const dLat = toRad(bLat - aLat);
  const dLon = toRad(bLon - aLon);
  const lat1 = toRad(aLat);
  const lat2 = toRad(bLat);
  const h =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
  return 2 * earthRadiusMiles * Math.asin(Math.sqrt(h));
}

function filterMarketMapOutliers(points: SaleMapPoint[]): SaleMapPoint[] {
  if (points.length < 3) return points;

  const bounded = points.filter(
    (point) =>
      point.lat >= MARKET_GUARDRAIL_BOUNDS.south &&
      point.lat <= MARKET_GUARDRAIL_BOUNDS.north &&
      point.lon >= MARKET_GUARDRAIL_BOUNDS.west &&
      point.lon <= MARKET_GUARDRAIL_BOUNDS.east
  );
  const basePoints = bounded.length >= Math.max(3, Math.round(points.length * 0.6)) ? bounded : points;
  if (basePoints.length < 4) return basePoints;

  const center = {
    lat: basePoints.reduce((sum, point) => sum + point.lat, 0) / basePoints.length,
    lon: basePoints.reduce((sum, point) => sum + point.lon, 0) / basePoints.length,
  };
  const distances = basePoints
    .map((point) => distanceMilesBetween(center.lat, center.lon, point.lat, point.lon))
    .sort((a, b) => a - b);
  const percentileIndex = Math.min(distances.length - 1, Math.floor(distances.length * 0.9));
  const distanceLimit = Math.max(8, distances[percentileIndex] * 1.35);
  const trimmed = basePoints.filter(
    (point) => distanceMilesBetween(center.lat, center.lon, point.lat, point.lon) <= distanceLimit
  );

  return trimmed.length >= Math.max(3, Math.round(basePoints.length * 0.7)) ? trimmed : basePoints;
}

function MarketGeoMap({ points, scopeLabel }: { points: SaleMapPoint[]; scopeLabel: string }) {
  const mapRef = useRef<HTMLDivElement | null>(null);
  const [mapMode, setMapMode] = useState<"heat" | "pins" | "both">("both");
  const [mapStatus, setMapStatus] = useState<string | null>(null);
  const apiKey = String(import.meta.env.VITE_GOOGLE_MAPS_API_KEY ?? "").trim();
  const filteredPoints = useMemo(() => filterMarketMapOutliers(points), [points]);
  const hiddenOutlierCount = Math.max(0, points.length - filteredPoints.length);
  const hasPoints = filteredPoints.length > 0;

  useEffect(() => {
    if (!apiKey || !mapRef.current || !hasPoints) return;
    let cancelled = false;
    let heatLayer: any = null;
    let markers: any[] = [];

    void loadGoogleMaps(apiKey)
      .then((google) => {
        if (cancelled || !mapRef.current) return;
        const center = {
          lat: filteredPoints.reduce((sum, p) => sum + p.lat, 0) / filteredPoints.length,
          lng: filteredPoints.reduce((sum, p) => sum + p.lon, 0) / filteredPoints.length,
        };
        const map = new google.maps.Map(mapRef.current, {
          center,
          zoom: 11,
          mapTypeControl: false,
          streetViewControl: false,
          fullscreenControl: true,
          styles: [
            { featureType: "poi", stylers: [{ visibility: "off" }] },
            { featureType: "transit", stylers: [{ visibility: "off" }] },
          ],
        });

        const bounds = new google.maps.LatLngBounds();
        filteredPoints.forEach((point) => bounds.extend({ lat: point.lat, lng: point.lon }));
        if (filteredPoints.length > 1) map.fitBounds(bounds, 44);

        if (mapMode === "heat" || mapMode === "both") {
          heatLayer = new google.maps.visualization.HeatmapLayer({
            data: filteredPoints.map((point) => ({
              location: new google.maps.LatLng(point.lat, point.lon),
              weight: Math.max(1, Math.min(8, (point.soldPrice ?? 500000) / 500000)),
            })),
            radius: 34,
            opacity: 0.58,
            map,
          });
        }

        if (mapMode === "pins" || mapMode === "both") {
          const info = new google.maps.InfoWindow();
          markers = filteredPoints.map((point) => {
            const marker = new google.maps.Marker({
              position: { lat: point.lat, lng: point.lon },
              map,
              title: point.address,
              icon: {
                path: google.maps.SymbolPath.CIRCLE,
                scale: 6,
                fillColor: "#17284a",
                fillOpacity: 0.9,
                strokeColor: "#ffffff",
                strokeWeight: 2,
              },
            });
            marker.addListener("click", () => {
              info.setContent(`
                <div class="map-info">
                  <strong>${point.address}</strong><br />
                  ${formatMoney(point.soldPrice)} sold ${point.soldDate ? formatDateDisplay(point.soldDate) : "-"}<br />
                  ${point.subdivision ?? "No subdivision"}<br />
                  <span>${point.listingNumber}</span>
                </div>
              `);
              info.open({ anchor: marker, map });
            });
            return marker;
          });
        }

        setMapStatus(null);
      })
      .catch((err) => {
        if (!cancelled) setMapStatus(err instanceof Error ? err.message : "Map failed to load");
      });

    return () => {
      cancelled = true;
      if (heatLayer) heatLayer.setMap(null);
      markers.forEach((marker) => marker.setMap(null));
    };
  }, [apiKey, filteredPoints, hasPoints, mapMode]);

  const fallbackPoints = useMemo(() => {
    if (!filteredPoints.length) return [];
    const lats = filteredPoints.map((p) => p.lat);
    const lons = filteredPoints.map((p) => p.lon);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const minLon = Math.min(...lons);
    const maxLon = Math.max(...lons);
    const latSpan = Math.max(maxLat - minLat, 0.005);
    const lonSpan = Math.max(maxLon - minLon, 0.005);
    return filteredPoints.map((point) => ({
      ...point,
      x: 6 + ((point.lon - minLon) / lonSpan) * 88,
      y: 90 - ((point.lat - minLat) / latSpan) * 76,
      r: Math.max(4, Math.min(12, (point.soldPrice ?? 400000) / 250000)),
    }));
  }, [filteredPoints]);

  return (
    <section className="panel map-panel">
      <div className="listings-head">
        <div>
          <h2>Neighborhood Heat Map</h2>
          <p className="panel-subtitle">
            {scopeLabel} · {filteredPoints.length} mapped sales in this period
            {hiddenOutlierCount > 0 ? ` · ${hiddenOutlierCount} outlier${hiddenOutlierCount === 1 ? "" : "s"} hidden` : ""}
          </p>
        </div>
        <div className="map-mode-tabs" aria-label="Map display mode">
          <button className={mapMode === "heat" ? "active" : ""} type="button" onClick={() => setMapMode("heat")}>Heat</button>
          <button className={mapMode === "pins" ? "active" : ""} type="button" onClick={() => setMapMode("pins")}>Pins</button>
          <button className={mapMode === "both" ? "active" : ""} type="button" onClick={() => setMapMode("both")}>Both</button>
        </div>
      </div>

      {apiKey && hasPoints ? (
        <div className="google-map" ref={mapRef} role="img" aria-label="Sales heat map and location pins" />
      ) : (
        <div className="fallback-map" role="img" aria-label="Sales location preview map">
          <svg viewBox="0 0 100 100" preserveAspectRatio="none">
            <rect x="0" y="0" width="100" height="100" rx="3" fill="#e7f1ef" />
            <path d="M0 68 C22 55 36 72 52 56 C67 42 78 52 100 38 L100 100 L0 100 Z" fill="#cfe6e0" />
            <path d="M55 0 L100 0 L100 100 L72 100 C66 78 72 62 62 45 C54 31 55 14 55 0 Z" fill="#c9ddf4" opacity="0.9" />
            {fallbackPoints.map((point) => (
              <circle key={point.listingNumber} cx={point.x} cy={point.y} r={point.r} fill="#10a99c" fillOpacity="0.34" stroke="#087f76" strokeWidth="0.8" />
            ))}
          </svg>
          <div className="map-empty">
            {hasPoints
              ? "Add VITE_GOOGLE_MAPS_API_KEY to enable Google Maps heat layer and clickable pins."
              : "No geocoded sales found for the selected period and filters."}
          </div>
        </div>
      )}

      {mapStatus ? <p className="map-status">{mapStatus}</p> : null}
    </section>
  );
}

function MarketPulsePanel({
  reportSummary,
  marketGradeInfo,
  geocodedCount,
  recentCount,
  onPrint,
}: {
  reportSummary: ReportSummaryResponse | null;
  marketGradeInfo: ReturnType<typeof getMarketGradeInfo>;
  geocodedCount: number;
  recentCount: number;
  onPrint: () => void;
}) {
  const priceDelta = reportSummary?.delta_pct.median_price_per_sqft ?? reportSummary?.delta_pct.median_sold_price ?? null;
  const inventoryDelta = reportSummary?.delta_pct.active_inventory ?? null;
  const domDelta = reportSummary?.delta_pct.median_dom ?? null;
  const msi = reportSummary?.current.months_supply ?? null;

  const pulseItems = [
    {
      icon: "↗",
      tone: priceDelta == null || priceDelta >= 0 ? "up" : "down",
      title: priceDelta == null ? "Pricing signal pending" : priceDelta >= 0 ? "Pricing is trending up" : "Pricing is easing",
      body:
        priceDelta == null
          ? "Price movement needs more period data for this filter."
          : `${priceDelta >= 0 ? "Up" : "Down"} ${Math.abs(priceDelta).toFixed(1)}% versus the previous period.`,
    },
    {
      icon: "⌂",
      tone: inventoryDelta == null || inventoryDelta <= 0 ? "up" : "warn",
      title: inventoryDelta == null ? "Inventory read pending" : inventoryDelta <= 0 ? "Inventory tightening" : "Inventory expanding",
      body:
        inventoryDelta == null
          ? "Inventory movement needs more data for this scope."
          : `${formatDelta(inventoryDelta)} active inventory; current MSI is ${msi == null ? "n/a" : msi.toFixed(1)}.`,
    },
    {
      icon: "◷",
      tone: domDelta == null || domDelta <= 0 ? "up" : "warn",
      title: domDelta == null ? "Velocity read pending" : domDelta <= 0 ? "Homes selling faster" : "Days on market rising",
      body:
        domDelta == null
          ? "DOM movement needs more period data."
          : `Median DOM is ${formatDelta(domDelta)} versus the previous period.`,
    },
  ];

  return (
    <aside className="market-pulse panel">
      <div className="pulse-heading">
        <span aria-hidden="true">⌁</span>
        <h2>Market Pulse</h2>
      </div>
      <div className="pulse-grade">
        <span>{marketGradeInfo.label}</span>
        <p>{marketGradeInfo.description}</p>
      </div>
      <div className="pulse-list">
        {pulseItems.map((item) => (
          <article className="pulse-item" key={item.title}>
            <span className={`pulse-icon ${item.tone}`} aria-hidden="true">{item.icon}</span>
            <div>
              <h3>{item.title}</h3>
              <p>{item.body}</p>
            </div>
          </article>
        ))}
      </div>
      <div className="pulse-stats">
        <div>
          <strong>{formatNumber(recentCount)}</strong>
          <span>recent sales</span>
        </div>
        <div>
          <strong>{formatNumber(geocodedCount)}</strong>
          <span>mapped pins</span>
        </div>
      </div>
      <button className="btn pulse-report-btn" onClick={onPrint}>View Full Market Report</button>
    </aside>
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

function formatBuilderValue(
  kind: "money" | "number" | "percent",
  value: number | null | undefined
): string {
  if (kind === "money") return formatMoney(value);
  if (kind === "percent") return formatPercent(value);
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
  const [builderChartType, setBuilderChartType] = useState<BuilderChartType>("line");
  const [builderMetricA, setBuilderMetricA] = useState<BuilderMetricKey>("sold_count");
  const [builderMetricB, setBuilderMetricB] = useState<BuilderMetricKey>("median_sold_price");
  const chartMakerRef = useRef<HTMLDivElement | null>(null);

  const [kpis, setKpis] = useState<KpisResponse | null>(null);
  const [trends, setTrends] = useState<TrendsResponse | null>(null);
  const [inventory, setInventory] = useState<InventoryResponse | null>(null);
  const [recentListings, setRecentListings] = useState<RecentListingsResponse | null>(null);
  const [reportSummary, setReportSummary] = useState<ReportSummaryResponse | null>(null);
  const [rankings, setRankings] = useState<SubdivisionRankingsResponse | null>(null);
  const [periodSeries, setPeriodSeries] = useState<PeriodSeriesResponse | null>(null);
  const [filterOptions, setFilterOptions] = useState<FilterOptionsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reportExporting, setReportExporting] = useState(false);
  const [cmaParcel, setCmaParcel] = useState("");
  const [cmaAsOfDate, setCmaAsOfDate] = useState(toIsoDate(new Date()));
  const [cmaTopN, setCmaTopN] = useState(10);
  const [cmaResult, setCmaResult] = useState<CmaRunResponse | null>(null);
  const [cmaError, setCmaError] = useState<string | null>(null);
  const [cmaLoading, setCmaLoading] = useState(false);
  const [activeView, setActiveView] = useState<DashboardView>("market");
  const [cmaSelectedListing, setCmaSelectedListing] = useState<string | null>(null);
  const [activeSection, setActiveSection] = useState<SidebarSection>("overview");

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

        const [kpisResp, trendsResp, invResp, recentResp, reportResp, rankingsResp, seriesResp] = await Promise.all([
          fetchKpisWithFilters(soldSince, filters),
          fetchTrends(12, filters, trendFrequency, activeWindow.start, activeWindow.end),
          fetchInventory(filters),
          fetchRecentListingsForRange(150, filters, activeWindow.start, activeWindow.end, soldSince),
          fetchReportSummary(config, filters),
          fetchSubdivisionRankings(config, 2, 10, filters),
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
  const builderMetricSpecA = useMemo(
    () => BUILDER_METRIC_OPTIONS.find((m) => m.key === builderMetricA) ?? BUILDER_METRIC_OPTIONS[0],
    [builderMetricA]
  );
  const builderMetricSpecB = useMemo(
    () => BUILDER_METRIC_OPTIONS.find((m) => m.key === builderMetricB) ?? BUILDER_METRIC_OPTIONS[2],
    [builderMetricB]
  );
  const builderLabels = useMemo(() => historicalRows.map((r) => r.period), [historicalRows]);
  const builderValuesA = useMemo(
    () => getCleanValues(historicalRows.map((r) => (r as unknown as Record<string, number | null | undefined>)[builderMetricA])),
    [historicalRows, builderMetricA]
  );
  const builderValuesB = useMemo(
    () => getCleanValues(historicalRows.map((r) => (r as unknown as Record<string, number | null | undefined>)[builderMetricB])),
    [historicalRows, builderMetricB]
  );
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
  const saleMapPoints = useMemo<SaleMapPoint[]>(() => {
    return (recentListings?.rows ?? [])
      .map((row) => {
        const lat = asNumber(row.geo_lat);
        const lon = asNumber(row.geo_lon);
        if (lat == null || lon == null) return null;
        return {
          listingNumber: row.listing_number,
          lat,
          lon,
          address: row.short_address ?? "Unknown address",
          soldPrice: row.sold_price,
          soldDate: row.sold_date,
          subdivision: row.final_subdivision,
        };
      })
      .filter((point): point is SaleMapPoint => point != null);
  }, [recentListings]);
  const cmaComps = cmaResult?.comps ?? [];
  const cmaMapPoints = useMemo(() => {
    if (!cmaResult) return [] as Array<{ kind: "subject" | "comp"; label: string; lat: number; lon: number; comp?: CmaComp }>;
    const points: Array<{ kind: "subject" | "comp"; label: string; lat: number; lon: number; comp?: CmaComp }> = [];
    const sLat = asNumber(cmaResult.subject?.geo_lat);
    const sLon = asNumber(cmaResult.subject?.geo_lon);
    const sLabel = String(cmaResult.subject?.short_address ?? cmaResult.subject?.parcel_id ?? "Subject");
    if (sLat != null && sLon != null) {
      points.push({ kind: "subject", label: sLabel, lat: sLat, lon: sLon });
    }
    cmaComps.forEach((c) => {
      const lat = asNumber(c.geo_lat);
      const lon = asNumber(c.geo_lon);
      if (lat == null || lon == null) return;
      points.push({ kind: "comp", label: c.short_address ?? c.listing_number, lat, lon, comp: c });
    });
    return points;
  }, [cmaResult, cmaComps]);
  const cmaSelectedComp = useMemo(
    () => cmaComps.find((c) => c.listing_number === cmaSelectedListing) ?? cmaComps[0] ?? null,
    [cmaComps, cmaSelectedListing]
  );
  const cmaSubject = cmaResult?.subject ?? null;
  const cmaSubjectFeatureText = useMemo(() => {
    if (!cmaSubject) return "-";
    const features: string[] = [];
    if (Number(cmaSubject?.waterfront) === 1) features.push("Waterfront/View");
    if (Number(cmaSubject?.private_pool) === 1) features.push("Pool");
    if (Number(cmaSubject?.storm_protection_impact_glass) === 1) features.push("Impact Windows");
    const roofYear = asNumber(cmaSubject?.year_roof_installed);
    if (roofYear) features.push(`Roof ${Math.round(roofYear)}`);
    const yb = asNumber(cmaSubject?.year_built);
    if (yb) features.push(`Built ${Math.round(yb)}`);
    return features.length ? features.join(" | ") : "No flagged features";
  }, [cmaSubject]);
  const cmaSubjectStatusLabel = useMemo(() => {
    const raw = String(cmaSubject?.status ?? cmaSubject?.calculated_status ?? "").toUpperCase().trim();
    if (["A", "ACTIVE", "ACT", "CS", "COMING SOON"].includes(raw)) return "Active Listing";
    if (["P", "PENDING", "U", "UNDER CONTRACT"].includes(raw)) return "Pending";
    if (["C", "CLOSED", "S", "SOLD"].includes(raw)) return "Closed";
    return raw || "Unknown";
  }, [cmaSubject]);
  const cmaAdjustmentByListing = useMemo(() => {
    const rows = (cmaResult?.valuation?.comp_adjustments as Array<Record<string, unknown>> | undefined) ?? [];
    const out = new Map<string, Record<string, unknown>>();
    for (const r of rows) {
      const listing = String(r?.listing_number ?? "");
      if (!listing) continue;
      out.set(listing, r);
    }
    return out;
  }, [cmaResult]);

  useEffect(() => {
    setCmaSelectedListing(cmaComps[0]?.listing_number ?? null);
  }, [cmaResult, cmaComps]);

  function printWindowWhenReady(win: Window): void {
    const doc = win.document;
    const waitForImages = (): Promise<void> => {
      const images = Array.from(doc.images ?? []);
      if (!images.length) return Promise.resolve();
      return Promise.all(
        images.map(
          (img) =>
            new Promise<void>((resolve) => {
              if (img.complete) {
                resolve();
                return;
              }
              img.onload = () => resolve();
              img.onerror = () => resolve();
            })
        )
      ).then(() => undefined);
    };

    const startPrint = () => {
      void waitForImages().then(() => {
        setTimeout(() => {
          win.focus();
          win.print();
        }, 120);
      });
    };

    if (doc.readyState === "complete") {
      startPrint();
    } else {
      win.addEventListener("load", startPrint, { once: true });
    }
  }

  function blobToDataUrl(blob: Blob): Promise<string> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onloadend = () => {
        const result = reader.result;
        if (typeof result === "string" && result.length) {
          resolve(result);
          return;
        }
        reject(new Error("Unable to convert blob to data URL"));
      };
      reader.onerror = () => reject(new Error("Failed reading blob"));
      reader.readAsDataURL(blob);
    });
  }

  async function resolveIconForPrint(iconPath?: string): Promise<string> {
    if (!iconPath) return "";
    const absoluteUrl = new URL(iconPath, window.location.href).toString();
    try {
      const res = await fetch(absoluteUrl, { cache: "force-cache" });
      if (!res.ok) return absoluteUrl;
      const blob = await res.blob();
      return await blobToDataUrl(blob);
    } catch {
      return absoluteUrl;
    }
  }

  async function printMarketReport(): Promise<void> {
    if (!reportSummary) return;
    const scopeLine = marketScopeLabel;
    const scopeHeadline = (finalSubdivision || city || "All Selected Markets").toUpperCase();
    const periodHeadline = reportSummary.period_label.toUpperCase();
    const typeLabel = propertyType
      ? propertyType
      : propertyGroup === "SINGLE_FAMILY"
      ? "Single Family"
      : propertyGroup === "TOWNHOME_CONDO"
      ? "Condominiums/Townhomes"
      : "ALL";
    const isSubdivisionReport = Boolean(finalSubdivision);
    const norm = (v: unknown) => String(v ?? "").trim().toUpperCase();

    const snapshotMetrics = buildSmartSnapshotMetrics(reportSummary);
    const snapshotMetricsForPrint = await Promise.all(
      snapshotMetrics.map(async (m) => ({
        ...m,
        iconPath: await resolveIconForPrint(m.iconPath),
      }))
    );

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
      const height = 224;
      const pad = { left: 48, right: 10, top: 14, bottom: 30 };
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
        <svg viewBox="0 0 ${width} ${height}" width="100%" height="224" role="img" aria-label="chart">
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
      const height = 224;
      const pad = { left: 48, right: 10, top: 14, bottom: 30 };
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
        <svg viewBox="0 0 ${width} ${height}" width="100%" height="224" role="img" aria-label="chart">
          <rect x="0" y="0" width="${width}" height="${height}" fill="#f8fbfa" rx="12" />
          ${yTickHtml}
          <line x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}" stroke="#bac8c4" stroke-width="1.2" />
          ${bars}
          ${xTickHtml}
        </svg>
      `;
    }

    function buildDualAxisChartSvg(
      labels: string[],
      leftValuesInput: number[],
      rightValuesInput: number[],
      leftKind: "currency" | "count" | "msi",
      rightKind: "currency" | "count" | "msi"
    ): string {
      const width = 360;
      const height = 224;
      const pad = { left: 44, right: 44, top: 14, bottom: 30 };
      const leftValues = leftValuesInput.length ? leftValuesInput : [0];
      const rightValues = rightValuesInput.length ? rightValuesInput : [0];
      let leftMin = Math.min(...leftValues);
      let leftMax = Math.max(...leftValues);
      let rightMin = Math.min(...rightValues);
      let rightMax = Math.max(...rightValues);
      leftMin = Math.min(0, leftMin);
      rightMin = Math.min(0, rightMin);
      if (leftMin === leftMax) {
        const b = leftMin === 0 ? 1 : Math.abs(leftMin) * 0.2;
        leftMin -= b;
        leftMax += b;
      }
      if (rightMin === rightMax) {
        const b = rightMin === 0 ? 1 : Math.abs(rightMin) * 0.2;
        rightMin -= b;
        rightMax += b;
      }
      const chartW = width - pad.left - pad.right;
      const chartH = height - pad.top - pad.bottom;
      const xFor = (i: number) => (leftValues.length <= 1 ? pad.left : pad.left + (i / (leftValues.length - 1)) * chartW);
      const yLeft = (v: number) => pad.top + chartH - ((v - leftMin) / (leftMax - leftMin)) * chartH;
      const yRight = (v: number) => pad.top + chartH - ((v - rightMin) / (rightMax - rightMin)) * chartH;
      const leftPath = `M ${leftValues.map((v, i) => `${xFor(i)},${yLeft(v)}`).join(" L ")}`;
      const rightPath = `M ${rightValues.map((v, i) => `${xFor(i)},${yRight(v)}`).join(" L ")}`;
      const leftTicks = buildTickValues(leftMin, leftMax, 4);
      const rightTicks = buildTickValues(rightMin, rightMax, 4);
      const leftTickHtml = leftTicks
        .map((t) => {
          const y = yLeft(t);
          return `<line x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}" stroke="#dfe7e5" stroke-width="1" />
                  <text x="${pad.left - 6}" y="${y + 4}" text-anchor="end" font-size="10" fill="#5b6a68">${escapeHtml(axisLabelFor(t, leftKind))}</text>`;
        })
        .join("");
      const rightTickHtml = rightTicks
        .map((t) => {
          const y = yRight(t);
          return `<text x="${width - pad.right + 6}" y="${y + 4}" text-anchor="start" font-size="10" fill="#5b6a68">${escapeHtml(axisLabelFor(t, rightKind))}</text>`;
        })
        .join("");
      const xLabelIdx = Array.from(new Set([0, Math.floor((labels.length - 1) / 2), labels.length - 1])).filter(
        (idx) => idx >= 0 && idx < labels.length
      );
      const xTickHtml = xLabelIdx
        .map((idx) => `<text x="${xFor(idx)}" y="${height - 10}" text-anchor="middle" font-size="10" fill="#5b6a68">${escapeHtml(labels[idx])}</text>`)
        .join("");
      return `
        <svg viewBox="0 0 ${width} ${height}" width="100%" height="224" role="img" aria-label="dual-axis-chart">
          <rect x="0" y="0" width="${width}" height="${height}" fill="#f8fbfa" rx="12" />
          ${leftTickHtml}
          ${rightTickHtml}
          <line x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}" stroke="#bac8c4" stroke-width="1.2" />
          <path d="${leftPath}" stroke="#2f6fb3" stroke-width="3" fill="none" />
          <path d="${rightPath}" stroke="#d86f1d" stroke-width="3" fill="none" />
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
    const inventorySeries = graphRows.length > 0 ? graphRows.map((r) => r.active_inventory ?? 0) : [];
    const msiSeries = graphRows.length > 0 ? graphRows.map((r) => r.months_supply ?? 0) : [];
    const newListingsSeries = graphRows.length > 0 ? graphRows.map((r) => r.new_listings ?? 0) : [];
    const pendingSeries = graphRows.length > 0 ? graphRows.map((r) => r.pending_sales ?? 0) : [];
    const hasInventoryAndMsi =
      inventorySeries.some((v) => v > 0) && msiSeries.some((v) => v > 0) && graphRows.length >= 4;
    const hasSoldAndPrice =
      soldSeries.some((v) => v > 0) && priceSeries.some((v) => v > 0) && graphRows.length >= 4;
    const hasNewAndPending =
      newListingsSeries.some((v) => v > 0) && pendingSeries.some((v) => v > 0) && graphRows.length >= 4;
    const chartCards: string[] = [];
    if (hasSoldAndPrice) {
      chartCards.push(`
        <article class="chart-card">
          <h3>Sold Count vs Median Sold Price</h3>
          ${buildDualAxisChartSvg(graphLabels, soldSeries, priceSeries, "count", "currency")}
          <div class="chart-legend">
            <span class="legend-item" style="color:#2f6fb3"><span class="legend-dot">●</span> Sold Count</span>
            <span class="legend-item" style="color:#d86f1d"><span class="legend-dot">●</span> Median Sold Price</span>
          </div>
        </article>
      `);
    } else {
      chartCards.push(`
        <article class="chart-card">
          <h3>Closed Sales Trend</h3>
          ${buildLineChartSvg(graphLabels, soldSeries, "#008c8a", "count")}
          <div class="chart-legend"><span class="legend-item" style="color:#008c8a"><span class="legend-dot">●</span> Sold Count</span></div>
        </article>
      `);
    }

    if (hasInventoryAndMsi) {
      chartCards.push(`
        <article class="chart-card">
          <h3>Inventory vs Months Supply</h3>
          ${buildDualAxisChartSvg(graphLabels, inventorySeries, msiSeries, "count", "msi")}
          <div class="chart-legend">
            <span class="legend-item" style="color:#2f6fb3"><span class="legend-dot">●</span> Active Inventory</span>
            <span class="legend-item" style="color:#d86f1d"><span class="legend-dot">●</span> Months Supply</span>
          </div>
        </article>
      `);
    } else if (hasNewAndPending) {
      chartCards.push(`
        <article class="chart-card">
          <h3>New Listings vs New Pending</h3>
          ${buildDualAxisChartSvg(graphLabels, newListingsSeries, pendingSeries, "count", "count")}
          <div class="chart-legend">
            <span class="legend-item" style="color:#2f6fb3"><span class="legend-dot">●</span> New Listings</span>
            <span class="legend-item" style="color:#d86f1d"><span class="legend-dot">●</span> New Pending</span>
          </div>
        </article>
      `);
    } else if (priceSeries.some((v) => v > 0)) {
      chartCards.push(`
        <article class="chart-card">
          <h3>Median Sold Price Trend</h3>
          ${buildLineChartSvg(graphLabels, priceSeries, "#2f6fb3", "currency")}
          <div class="chart-legend"><span class="legend-item" style="color:#2f6fb3"><span class="legend-dot">●</span> Median Sold Price</span></div>
        </article>
      `);
    } else {
      chartCards.push(`
        <article class="chart-card">
          <h3>Total Sales Volume</h3>
          ${buildBarChartSvg(graphLabels, volumeSeries, "#d86f1d", "currency")}
          <div class="chart-legend"><span class="legend-item" style="color:#d86f1d"><span class="legend-dot">●</span> Total Sales Volume</span></div>
        </article>
      `);
    }

    const chartsHtml = `
      <section class="chart-section">
        <h2>Market Trend Visuals (Auto-selected)</h2>
        <div class="chart-grid">
          ${chartCards.join("")}
        </div>
      </section>
    `;

    const snapshotHtml = snapshotMetricsForPrint
      .map((m) => {
        const deltaClass =
          m.deltaValue == null || Number.isNaN(m.deltaValue) ? "delta-flat" : m.deltaValue > 0 ? "delta-up" : m.deltaValue < 0 ? "delta-down" : "delta-flat";
        const iconSrc = m.iconPath ?? "";
        return `
          <article class="stat-card">
            <div class="stat-content">
              <p class="stat-label">${escapeHtml(m.label)}</p>
              <p class="stat-value">${escapeHtml(m.value)}</p>
              <p class="stat-sub">Prev: ${escapeHtml(m.previous)}</p>
              <p class="stat-delta ${deltaClass}">${escapeHtml(m.delta)}</p>
            </div>
            ${iconSrc ? `<img src="${escapeHtml(iconSrc)}" alt="${escapeHtml(m.label)}" class="stat-icon" />` : `<span class="stat-icon placeholder"></span>`}
          </article>
        `;
      })
      .join("");

    const PRINT_TABLE_ROW_CAP = 6;

    const topSubdivisionRows = (rankings?.rows ?? [])
      .slice(0, PRINT_TABLE_ROW_CAP)
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

    const scopedRecentRows = (recentListings?.rows ?? [])
      .filter((r) => {
        if (city && norm(r.city) !== norm(city)) return false;
        if (finalSubdivision && norm(r.final_subdivision) !== norm(finalSubdivision)) return false;
        if (geoZone && norm(r.geo_zone) !== norm(geoZone)) return false;
        if (propertyType && norm(r.property_type) !== norm(propertyType)) return false;
        if (!propertyType && propertyGroup === "SINGLE_FAMILY" && !isSingleFamilyType(r.property_type)) return false;
        if (!propertyType && propertyGroup === "TOWNHOME_CONDO" && isSingleFamilyType(r.property_type)) return false;
        if (r.sold_date) {
          if (r.sold_date < reportSummary.current_start || r.sold_date > reportSummary.current_end) return false;
        } else {
          return false;
        }
        return true;
      })
      .slice(0, PRINT_TABLE_ROW_CAP);

    const recentSalesRows = scopedRecentRows
      .map(
        (r) => `
          <tr>
            <td>${escapeHtml(r.short_address ?? "-")}</td>
            <td>${escapeHtml(formatNumber(r.total_bedrooms ?? null))}</td>
            <td>${escapeHtml(formatNumber(r.baths_total ?? null))}</td>
            <td>${escapeHtml(formatNumber(r.sqft_living ?? null))}</td>
            <td>${escapeHtml(formatMoney(r.sold_price ?? null))}</td>
            <td>${escapeHtml(r.sold_ppsf == null ? "-" : formatMoney(r.sold_ppsf))}</td>
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
            margin: 12px;
            color: var(--ink);
            background: #f4f6f5;
          }
          .hero {
            background: linear-gradient(130deg, #eef9f7 0%, #f7efe7 55%, #eef4fb 100%);
            border: 1px solid #d9e4e1;
            border-radius: 14px;
            padding: 12px 14px;
            margin-bottom: 8px;
          }
          .hero-grid {
            display: grid;
            grid-template-columns: 1fr 280px;
            gap: 12px;
            align-items: end;
          }
          .hero-right {
            text-align: right;
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
            margin: 4px 0 2px;
            font-size: 24px;
            line-height: 1.05;
          }
          .scope-big {
            margin: 0;
            font-size: 28px;
            line-height: 1.05;
            font-weight: 800;
            letter-spacing: 0.03em;
          }
          .period-big {
            margin: 2px 0 0;
            font-size: 20px;
            line-height: 1.05;
            font-weight: 700;
            color: #2d5351;
          }
          .hero-sub {
            margin: 2px 0;
            color: var(--muted);
            font-size: 12px;
          }
          .panel {
            background: #fff;
            border: 1px solid #dce6e3;
            border-radius: 14px;
            padding: 10px 12px;
            margin-bottom: 8px;
          }
          h2 { margin: 0 0 6px; font-size: 16px; }
          h3 { margin: 0 0 6px; font-size: 13px; color: #31413f; }
          .stats-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 8px;
          }
          .stat-card {
            display: grid;
            grid-template-columns: minmax(0, 1fr) 64px;
            align-items: center;
            border: 1px solid #dde8e5;
            border-radius: 12px;
            padding: 8px;
            background: linear-gradient(180deg, #ffffff 0%, #f8fbfa 100%);
            gap: 10px;
          }
          .stat-content {
            min-width: 0;
          }
          .stat-icon {
            width: 56px;
            height: 56px;
            object-fit: contain;
            flex-shrink: 0;
            justify-self: end;
          }
          .stat-icon.placeholder {
            border-radius: 10px;
            background: #d7e2df;
          }
          .stat-label {
            margin: 0;
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.04em;
            color: #4f5f5d;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
          }
          .stat-value {
            margin: 4px 0 2px;
            font-size: 22px;
            font-weight: 700;
            line-height: 1;
            white-space: nowrap;
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
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 8px;
          }
          .chart-card {
            border: 1px solid #dde8e5;
            border-radius: 12px;
            padding: 8px;
            background: #fff;
          }
          .chart-legend { margin-top: 6px; font-size: 11px; color: #556563; display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
          .legend-item { display: inline-flex; align-items: center; gap: 4px; font-weight: 700; }
          .legend-dot { font-size: 13px; line-height: 1; }
          .grade-grid { display:grid; grid-template-columns: 180px 1fr; gap: 10px; align-items:center; }
          .grade-label { font-size: 26px; font-weight: 800; margin:0; }
          .grade-sub { margin: 2px 0; font-size: 12px; color: var(--muted); }
          table { border-collapse: collapse; width: 100%; margin-top: 6px; }
          th, td { border-bottom: 1px solid #e6edeb; padding: 6px 5px; text-align: left; font-size: 11px; }
          th { text-transform: uppercase; letter-spacing: 0.04em; color: #4d5d5a; font-size: 10px; }
          @page {
            size: Letter portrait;
            margin: 0.3in;
          }
          @media print {
            * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
            body {
              margin: 0;
              background: #fff;
              font-size: 11px;
              line-height: 1.2;
            }
            .hero {
              padding: 8px 10px;
              margin-bottom: 6px;
              border-radius: 10px;
            }
            .panel {
              padding: 8px 10px;
              margin-bottom: 6px;
              border-radius: 10px;
            }
            .panel, .hero { break-inside: avoid; }
            h1 { font-size: 21px; }
            h2 { font-size: 14px; margin-bottom: 4px; }
            h3 { font-size: 12px; margin-bottom: 4px; }
            .hero-sub, .grade-sub, .chart-legend { font-size: 10px; }
            .scope-big { font-size: 24px; }
            .period-big { font-size: 17px; }
            .stat-value { font-size: 18px; }
            .stat-label, .stat-sub, .stat-delta { font-size: 10px; }
            .stat-icon { width: 44px; height: 44px; }
            .stats-grid { gap: 6px; }
            .chart-grid {
              gap: 6px;
              grid-template-columns: repeat(2, minmax(0, 1fr));
            }
            .chart-card { padding: 6px; }
            .chart-card h3 { font-size: 11px; margin-bottom: 3px; }
            .chart-card svg { height: 164px; width: 100%; display: block; }
            .chart-legend { font-size: 9px; margin-top: 3px; gap: 6px; }
            th, td { padding: 3px 3px; font-size: 9px; }
          }
        </style>
      </head>
      <body>
        <section class="hero">
          <div class="hero-grid">
            <div>
              <p class="eyebrow">Douglas Elliman | ReStats Premier</p>
              <h1>Market Snapshot Report</h1>
              <p class="hero-sub"><strong>Current:</strong> ${escapeHtml(reportSummary.current_start)} to ${escapeHtml(reportSummary.current_end)} | <strong>Previous:</strong> ${escapeHtml(reportSummary.previous_start)} to ${escapeHtml(reportSummary.previous_end)}</p>
              <p class="hero-sub"><strong>Scope:</strong> ${escapeHtml(scopeLine)}</p>
              <p class="hero-sub"><strong>Type:</strong> ${escapeHtml(typeLabel)}</p>
            </div>
            <div class="hero-right">
              <p class="scope-big">${escapeHtml(scopeHeadline)}</p>
              <p class="period-big">${escapeHtml(periodHeadline)}</p>
            </div>
          </div>
        </section>

        <section class="panel">
          <h2>9-Key Market Snapshot</h2>
          <p class="hero-sub">Auto-selected core + context metrics based on current market conditions.</p>
          <div class="stats-grid">${snapshotHtml}</div>
        </section>

        <section class="panel">
          <h2>Market Grade</h2>
          <div class="grade-grid">
            <p class="grade-label">${escapeHtml(marketGradeInfo.label)}</p>
            <div>
              <p class="grade-sub"><strong>Read:</strong> ${escapeHtml(marketGradeInfo.description)}</p>
              <p class="grade-sub"><strong>Components:</strong> Pace ${marketGradeInfo.pace == null ? "N/A" : marketGradeInfo.pace.toFixed(1)} | Supply ${marketGradeInfo.supply == null ? "N/A" : marketGradeInfo.supply.toFixed(1)} | Pricing ${marketGradeInfo.pricing == null ? "N/A" : marketGradeInfo.pricing.toFixed(1)} | Demand ${marketGradeInfo.demand == null ? "N/A" : marketGradeInfo.demand.toFixed(1)}</p>
            </div>
          </div>
        </section>

        ${chartsHtml}

        <section class="panel">
          ${
            isSubdivisionReport
              ? `
                <h2>Most Recent Closed Sales</h2>
                <table>
                  <thead><tr><th>Address</th><th>Beds</th><th>Baths</th><th>Living SqFt</th><th>Purchase Price</th><th>Sold Price / Ft</th></tr></thead>
                  <tbody>${recentSalesRows || `<tr><td colspan="6">No recent closed sales found for this scope.</td></tr>`}</tbody>
                </table>
              `
              : `
                <h2>Top Subdivision Momentum</h2>
                <table>
                  <thead><tr><th>Subdivision</th><th>City</th><th>Sold</th><th>Avg Sold</th></tr></thead>
                  <tbody>${topSubdivisionRows}</tbody>
                </table>
              `
          }
        </section>

        <section class="panel">
          <p class="hero-sub">
            <strong>How to read this report:</strong> Active Inventory is period-end snapshot. Months Supply = period-end inventory / trailing 12-month sales pace, with pace clamped to latest real sold date when needed.
          </p>
        </section>
      </body>
      </html>
    `;

    const w = window.open("", "_blank");
    if (!w) return;
    w.document.write(html);
    w.document.close();
    printWindowWhenReady(w);
  }

  async function exportReportListings(): Promise<void> {
    const filters = { city, geoZone, finalSubdivision, propertyType, propertyGroup };
    const config: ReportConfig = {
      reportMode,
      periodDays,
      refYear,
      refMonth,
      refQuarter,
      startDate: reportMode === "custom" ? customStart : undefined,
      endDate: reportMode === "custom" ? customEnd : undefined,
    };

    setReportExporting(true);
    setError(null);
    try {
      const resp = await fetchReportListings(config, filters);
      const safeScope = (finalSubdivision || geoZone || city || "all-markets")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "");
      downloadCsv(
        `report_listings_${safeScope}_${resp.current_start}_${resp.current_end}.csv`,
        resp.rows as Array<Record<string, unknown>>
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to export report listings");
    } finally {
      setReportExporting(false);
    }
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
    printWindowWhenReady(w);
  }

  function printChartMaker(): void {
    if (!chartMakerRef.current) return;
    const chartHtml = chartMakerRef.current.innerHTML;
    const chartTypeLabel =
      builderChartType === "dual_axis"
        ? "Dual Axis"
        : builderChartType.charAt(0).toUpperCase() + builderChartType.slice(1);
    const scope = marketScopeLabel;
    const w = window.open("", "_blank");
    if (!w) return;
    w.document.write(`
      <!doctype html>
      <html>
      <head>
        <meta charset="utf-8" />
        <title>Chart Maker Print</title>
        <style>
          body { font-family: "Avenir Next", "Gill Sans", "Trebuchet MS", sans-serif; margin: 18px; color: #1f2a28; }
          h1 { margin: 0 0 8px; font-size: 24px; }
          .meta { margin: 0 0 12px; color: #5a6967; font-size: 13px; }
          .chart-maker-canvas { border: 1px solid #dde6e3; border-radius: 12px; padding: 10px; background: #fff; }
          .chart-maker-legend-strip { display: flex; gap: 12px; align-items: center; margin-top: 10px; flex-wrap: wrap; }
          .chart-legend-item { display: inline-flex; align-items: center; gap: 7px; font-size: 13px; color: #33413f; }
          .chart-legend-swatch { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
          .linechart { width: 100%; height: auto; }
          .chart-maker-pie-wrap { display: grid; grid-template-columns: 420px 1fr; gap: 12px; align-items: center; }
          @media print { body { margin: 0; } }
        </style>
      </head>
      <body>
        <h1>Custom Chart</h1>
        <p class="meta"><strong>Type:</strong> ${escapeHtml(chartTypeLabel)} | <strong>Scope:</strong> ${escapeHtml(scope)}</p>
        <div class="chart-maker-canvas">${chartHtml}</div>
      </body>
      </html>
    `);
    w.document.close();
    printWindowWhenReady(w);
  }

  async function handleRunCma(): Promise<void> {
    if (!cmaParcel.trim()) {
      setCmaError("Enter a parcel number to run CMA.");
      return;
    }
    setCmaLoading(true);
    setCmaError(null);
    try {
      const result = await runCma(cmaParcel.trim(), cmaAsOfDate || undefined, cmaTopN);
      setCmaResult(result);
    } catch (err) {
      setCmaResult(null);
      setCmaError(err instanceof Error ? err.message : "Failed to run CMA");
    } finally {
      setCmaLoading(false);
    }
  }

  function jumpToSection(section: SidebarSection): void {
    setActiveSection(section);
    const element = document.getElementById(`section-${section}`);
    if (element) {
      element.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  return (
    <div className="dashboard-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <span className="brand-mark" aria-hidden="true">⌂</span>
          <span>ReStats</span>
        </div>
        <nav className="sidebar-nav" aria-label="Dashboard sections">
          {([
            { id: "overview", label: "Overview", icon: "⌂" },
            { id: "trends", label: "Market Trends", icon: "⌁" },
            { id: "inventory", label: "Inventory", icon: "▤" },
            { id: "sales", label: "Sales", icon: "⌙" },
            { id: "neighborhoods", label: "Neighborhoods", icon: "⌖" },
            { id: "reports", label: "Reports", icon: "▣" },
          ] as Array<{ id: SidebarSection; label: string; icon: string }>).map((item) => (
            <button
              key={item.id}
              className={`nav-item ${activeSection === item.id ? "active" : ""}`}
              type="button"
              onClick={() => jumpToSection(item.id)}
            >
              <span aria-hidden="true">{item.icon}</span>
              {item.label}
            </button>
          ))}
        </nav>
        <div className="market-card">
          <strong>Market Scope</strong>
          <span>{marketScopeLabel}</span>
          <span>{reportSummary?.period_label ?? `${activeWindow.start} to ${activeWindow.end}`}</span>
        </div>
      </aside>

      <main className="page-shell dashboard-main">
      <header className="hero dashboard-topbar">
        <div>
          <p className="eyebrow">Palm Beach County Market Overview</p>
          <h1>Market Intelligence Report</h1>
          <p className="hero-copy">
            {`Data as of ${formatDateDisplay(reportSummary?.current_end ?? activeWindow.end)}`}
          </p>
        </div>
        <div className="actions top-actions">
          <button className="btn" onClick={() => downloadCsv("recent_closings.csv", (recentListings?.rows ?? []) as Array<Record<string, unknown>>)}>
            Export Recent Closings
          </button>
          <button className="btn" onClick={() => void exportReportListings()} disabled={reportExporting}>
            {reportExporting ? "Exporting..." : "Export Listings"}
          </button>
          <button className="btn" onClick={printHistoricalReport}>Print Historical</button>
          <button className="btn primary" onClick={printMarketReport}>Print Market Report</button>
        </div>
      </header>

      {activeView === "market" ? (
      <section className="filter-grid dashboard-filterbar">
        <label className="filter-field" htmlFor="city">
          <span>City</span>
          <select id="city" value={city} onChange={(e) => setCity(e.target.value)}>
            <option value="">All Cities</option>
            {(filterOptions?.cities ?? []).map((c) => <option key={c.city} value={c.city}>{c.city} ({c.count})</option>)}
          </select>
        </label>

        <label className="filter-field" htmlFor="geo_zone">
          <span>Geo Zone</span>
          <select id="geo_zone" value={geoZone} onChange={(e) => setGeoZone(e.target.value)}>
            <option value="">All Geo Zones</option>
            {(filterOptions?.geo_zones ?? []).map((g) => <option key={g.geo_zone} value={g.geo_zone}>{g.geo_zone} ({g.count})</option>)}
          </select>
        </label>

        <label className="filter-field filter-wide" htmlFor="subdivision">
          <span>Subdivision</span>
          <select id="subdivision" value={finalSubdivision} onChange={(e) => setFinalSubdivision(e.target.value)}>
            <option value="">All Subdivisions</option>
            {(filterOptions?.subdivisions ?? []).map((s) => <option key={s.final_subdivision} value={s.final_subdivision}>{s.final_subdivision} ({s.count})</option>)}
          </select>
        </label>

        <label className="filter-field" htmlFor="property_group">
          <span>Building Type</span>
          <select id="property_group" value={propertyGroup} onChange={(e) => setPropertyGroup(e.target.value as PropertyGroup)}>
            {(filterOptions?.property_groups ?? []).map((pg) => <option key={pg.value} value={pg.value}>{pg.label}</option>)}
          </select>
        </label>

        <label className="filter-field" htmlFor="property_type">
          <span>Raw Type</span>
          <select id="property_type" value={propertyType} onChange={(e) => setPropertyType(e.target.value)}>
            <option value="">All Raw Types</option>
            {(filterOptions?.property_types ?? []).map((p) => <option key={p.property_type} value={p.property_type}>{p.property_type} ({p.count})</option>)}
          </select>
        </label>

        <label className="filter-field" htmlFor="reportMode">
          <span>Date Range</span>
          <select id="reportMode" value={reportMode} onChange={(e) => setReportMode(e.target.value as ReportMode)}>
            <option value="rolling">Rolling Window</option>
            <option value="monthly">Monthly Report</option>
            <option value="quarterly">Quarterly Report</option>
            <option value="annual">Annual Report</option>
            <option value="custom">Custom Date Range</option>
          </select>
        </label>

        {reportMode === "rolling" ? (
          <label className="filter-field filter-compact" htmlFor="period">
            <span>Window</span>
            <select id="period" value={periodDays} onChange={(e) => setPeriodDays(Number(e.target.value))}>
              <option value={30}>30 Days</option>
              <option value={60}>60 Days</option>
              <option value={90}>90 Days</option>
              <option value={180}>180 Days</option>
              <option value={365}>365 Days</option>
            </select>
          </label>
        ) : null}

        {reportMode === "monthly" ? (
          <>
            <label className="filter-field filter-compact" htmlFor="year">
              <span>Year</span>
              <select id="year" value={refYear} onChange={(e) => setRefYear(Number(e.target.value))}>
                {yearOptions.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
            </label>
            <label className="filter-field filter-compact" htmlFor="month">
              <span>Month</span>
              <select id="month" value={refMonth} onChange={(e) => setRefMonth(Number(e.target.value))}>
                {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            </label>
          </>
        ) : null}

        {reportMode === "quarterly" ? (
          <>
            <label className="filter-field filter-compact" htmlFor="qyear">
              <span>Year</span>
              <select id="qyear" value={refYear} onChange={(e) => setRefYear(Number(e.target.value))}>
                {yearOptions.map((y) => <option key={y} value={y}>{y}</option>)}
              </select>
            </label>
            <label className="filter-field filter-compact" htmlFor="quarter">
              <span>Quarter</span>
              <select id="quarter" value={refQuarter} onChange={(e) => setRefQuarter(Number(e.target.value))}>
                <option value={1}>Q1</option><option value={2}>Q2</option><option value={3}>Q3</option><option value={4}>Q4</option>
              </select>
            </label>
          </>
        ) : null}

        {reportMode === "annual" ? (
          <label className="filter-field filter-compact" htmlFor="ayear">
            <span>Year</span>
            <select id="ayear" value={refYear} onChange={(e) => setRefYear(Number(e.target.value))}>
              {yearOptions.map((y) => <option key={y} value={y}>{y}</option>)}
            </select>
          </label>
        ) : null}

        {reportMode === "custom" ? (
          <>
            <label className="filter-field" htmlFor="start">
              <span>Start</span>
              <input id="start" type="date" value={customStart} onChange={(e) => setCustomStart(e.target.value)} />
            </label>
            <label className="filter-field" htmlFor="end">
              <span>End</span>
              <input id="end" type="date" value={customEnd} onChange={(e) => setCustomEnd(e.target.value)} />
            </label>
          </>
        ) : null}

        <label className="filter-field" htmlFor="soldSince">
          <span>KPI Since</span>
          <input id="soldSince" type="date" value={soldSince} onChange={(e) => setSoldSince(e.target.value)} />
        </label>

        <div className="filter-actions">
          <button className={`period-pill ${seriesFrequency === "monthly" ? "active" : ""}`} type="button" onClick={() => setSeriesFrequency("monthly")}>Monthly</button>
          <button className={`period-pill ${seriesFrequency === "quarterly" ? "active" : ""}`} type="button" onClick={() => setSeriesFrequency("quarterly")}>Quarterly</button>
          <button className={`period-pill ${seriesFrequency === "annual" ? "active" : ""}`} type="button" onClick={() => setSeriesFrequency("annual")}>Annually</button>
          <button
            className="btn reset-btn"
            type="button"
            onClick={() => {
              setCity(""); setGeoZone(""); setFinalSubdivision(""); setPropertyGroup("ALL"); setPropertyType("");
            }}
          >
            Reset
          </button>
        </div>
      </section>
      ) : null}

      {activeView === "market" && error ? <section className="error">{error}</section> : null}

      {activeView === "cma" ? (
      <section className="panel listings-panel">
        <div className="listings-head">
          <div>
            <h2>CMA Workbench (Beta)</h2>
            <p className="panel-subtitle">Run parcel-level CMA with comp transparency and geo pinpoints.</p>
          </div>
        </div>
        <div className="chart-maker-controls">
          <label>
            Parcel
            <input
              type="text"
              value={cmaParcel}
              onChange={(e) => setCmaParcel(e.target.value)}
              placeholder="e.g. 50-43-43-23-12-000-0044"
            />
          </label>
          <label>
            As-of Date
            <input type="date" value={cmaAsOfDate} onChange={(e) => setCmaAsOfDate(e.target.value)} />
          </label>
          <label>
            Top Comps
            <select value={cmaTopN} onChange={(e) => setCmaTopN(Number(e.target.value))}>
              <option value={10}>10</option>
              <option value={15}>15</option>
              <option value={20}>20</option>
              <option value={25}>25</option>
            </select>
          </label>
          <div className="chart-maker-actions">
            <button className="btn" onClick={() => void handleRunCma()} disabled={cmaLoading}>
              {cmaLoading ? "Running..." : "Run CMA"}
            </button>
          </div>
        </div>
        {cmaError ? <p className="panel-subtitle" style={{ color: "#b53b3b" }}>{cmaError}</p> : null}
        {cmaResult ? (
          <>
            <div className="kpi-grid report-grid">
              <MetricVisualCard label="Recommended Value" value={formatMoney(asNumber(cmaResult.valuation?.final_recommended_value))} />
              <MetricVisualCard label="Value Range Low" value={formatMoney(asNumber(cmaResult.valuation?.low_value))} />
              <MetricVisualCard label="Value Range High" value={formatMoney(asNumber(cmaResult.valuation?.high_value))} />
              <MetricVisualCard label="Confidence" value={`${cmaResult.confidence_grade}`} />
              <MetricVisualCard label="Guardrail State" value={String(cmaResult.pending_pressure_guardrail?.pending_pressure_state ?? "N/A")} />
              <MetricVisualCard label="Comps Used" value={formatNumber(cmaComps.length)} />
            </div>

            <div className="panel">
              <h3>Subject Property</h3>
              <p className="panel-subtitle">
                <strong>Address:</strong> {String(cmaSubject?.short_address ?? "-")} | <strong>Status:</strong> {cmaSubjectStatusLabel}
              </p>
              <p className="panel-subtitle">
                <strong>List Price:</strong> {formatMoney(asNumber(cmaSubject?.list_price))} | <strong>Beds:</strong> {formatNumber(asNumber(cmaSubject?.total_bedrooms))} | <strong>Baths:</strong> {formatNumber(asNumber(cmaSubject?.baths_total))} | <strong>Living SqFt:</strong> {formatNumber(asNumber(cmaSubject?.sqft_living))}
              </p>
              <p className="panel-subtitle">
                <strong>Lot SqFt:</strong> {formatNumber(asNumber(cmaSubject?.lot_sqft))} | <strong>HOA:</strong> {formatMoney(asNumber(cmaSubject?.hoa_poa_coa_monthly))} | <strong>Membership Fee:</strong> {formatMoney(asNumber(cmaSubject?.membership_fee))}
              </p>
              <p className="panel-subtitle"><strong>Feature Flags:</strong> {cmaSubjectFeatureText}</p>
            </div>

            <div className="two-col">
              <article className="panel">
                <h3>Comp Map (Geo)</h3>
                <p className="panel-subtitle"><strong>Buckets:</strong> A = same community sold within 365 days; B = older same-community support; C = fallback comps.</p>
                {(() => {
                  if (cmaMapPoints.length < 2) {
                    return <p className="panel-subtitle">Need subject + at least one comp with geocode to render map.</p>;
                  }
                  const width = 560;
                  const height = 290;
                  const pad = 28;
                  const lats = cmaMapPoints.map((p) => p.lat);
                  const lons = cmaMapPoints.map((p) => p.lon);
                  const minLat = Math.min(...lats);
                  const maxLat = Math.max(...lats);
                  const minLon = Math.min(...lons);
                  const maxLon = Math.max(...lons);
                  const latSpan = Math.max(maxLat - minLat, 0.0015);
                  const lonSpan = Math.max(maxLon - minLon, 0.0015);
                  const xFor = (lon: number) => pad + ((lon - minLon) / lonSpan) * (width - pad * 2);
                  const yFor = (lat: number) => height - pad - ((lat - minLat) / latSpan) * (height - pad * 2);
                  return (
                    <svg viewBox={`0 0 ${width} ${height}`} className="linechart" role="img" aria-label="CMA comp map">
                      <rect x="0" y="0" width={width} height={height} fill="#f6f8f7" rx="10" />
                      {cmaMapPoints.map((p, i) => (
                        <g key={`map-pt-${i}`}>
                          {p.kind === "comp" && p.comp?.listing_number === cmaSelectedComp?.listing_number ? (
                            <circle
                              cx={xFor(p.lon)}
                              cy={yFor(p.lat)}
                              r={9}
                              fill="none"
                              stroke="#1f2a28"
                              strokeWidth={1.8}
                            />
                          ) : null}
                          <circle
                            cx={xFor(p.lon)}
                            cy={yFor(p.lat)}
                            r={p.kind === "subject" ? 7 : 5}
                            className={p.kind === "comp" ? "cma-map-point" : undefined}
                            fill={
                              p.kind === "subject"
                                ? "#0c5f5e"
                                : p.comp?.bucket === "A"
                                ? "#008c8a"
                                : p.comp?.bucket === "B"
                                ? "#2f6fb3"
                                : "#d86f1d"
                            }
                            onClick={() => {
                              if (p.kind === "comp" && p.comp?.listing_number) {
                                setCmaSelectedListing(p.comp.listing_number);
                              }
                            }}
                          />
                          <text x={xFor(p.lon) + 8} y={yFor(p.lat) - 6} className="chart-tick-label">
                            {p.kind === "subject" ? "Subject" : p.comp?.bucket ?? "Comp"}
                          </text>
                        </g>
                      ))}
                    </svg>
                  );
                })()}
                {cmaSelectedComp ? (
                  <div className="cma-map-detail">
                    {(() => {
                      const adj = cmaAdjustmentByListing.get(cmaSelectedComp.listing_number);
                      const adjPct = asNumber(adj?.adjustment_pct);
                      const adjPpsf = asNumber(adj?.adjusted_ppsf);
                      return (
                        <>
                    <p className="panel-subtitle"><strong>Selected Comp:</strong> {cmaSelectedComp.short_address ?? cmaSelectedComp.listing_number}</p>
                    <p className="panel-subtitle">
                      {formatMoney(cmaSelectedComp.sold_price ?? null)} | Raw {formatMoney(cmaSelectedComp.ppsf ?? null)}/ft | Adj {adjPpsf == null ? "-" : `${formatMoney(adjPpsf)}/ft`} | {cmaSelectedComp.distance_miles == null ? "-" : `${cmaSelectedComp.distance_miles.toFixed(2)} mi`} | Bucket {cmaSelectedComp.bucket ?? "-"} | Adj {adjPct == null ? "-" : `${adjPct.toFixed(2)}%`}
                    </p>
                        </>
                      );
                    })()}
                  </div>
                ) : null}
              </article>
              <article className="panel">
                <h3>Guardrails + Notes</h3>
                <p className="panel-subtitle"><strong>Reason:</strong> {cmaResult.confidence_reason}</p>
                <p className="panel-subtitle"><strong>Pending Pressure:</strong> {String(cmaResult.pending_pressure_guardrail?.pending_pressure_state ?? "N/A")}</p>
                <p className="panel-subtitle"><strong>Cap/Floor:</strong> {String(cmaResult.pending_pressure_guardrail?.recommended_value_cap_pct ?? "N/A")}% / {String(cmaResult.pending_pressure_guardrail?.recommended_value_floor_pct ?? "N/A")}%</p>
                <p className="panel-subtitle"><strong>Guardrail Applied:</strong> {String(cmaResult.valuation?.guardrail_applied ?? false)}</p>
                <p className="panel-subtitle"><strong>Pre-Guardrail Value:</strong> {formatMoney(asNumber(cmaResult.valuation?.pre_guardrail_recommended_value))}</p>
                <p className="panel-subtitle"><strong>Adjusted Value:</strong> {formatMoney(asNumber(cmaResult.valuation?.guardrail_adjusted_value))}</p>
                <p className="panel-subtitle"><strong>Guardrail Reason:</strong> {String(cmaResult.valuation?.guardrail_reason ?? "none")}</p>
              </article>
            </div>

            <div className="table-wrap">
              <table className="data-table compact">
                <thead>
                  <tr>
                    <th>Bucket</th><th>Score</th><th>Recency</th><th>Distance</th><th>Sold Date</th><th>Address</th><th>Beds</th><th>Baths</th><th>SqFt</th><th>Sold</th><th>Raw PPSF</th><th>Adj %</th><th>Adj PPSF</th><th>Feature Reasons</th><th>Listing #</th>
                  </tr>
                </thead>
                <tbody>
                  {cmaComps.map((c) => (
                    (() => {
                      const adj = cmaAdjustmentByListing.get(c.listing_number);
                      const adjPct = asNumber(adj?.adjustment_pct);
                      const adjPpsf = asNumber(adj?.adjusted_ppsf);
                      const reasons = Array.isArray(adj?.reasons) ? (adj?.reasons as string[]).join(", ") : "-";
                      return (
                    <tr
                      key={c.listing_number}
                      className={c.listing_number === cmaSelectedComp?.listing_number ? "selected-comp-row" : ""}
                      onClick={() => setCmaSelectedListing(c.listing_number)}
                    >
                      <td>{c.bucket ?? "-"}</td>
                      <td>{formatNumber(c.final_score ?? null)}</td>
                      <td>{formatNumber(c.recency_days ?? null)}d</td>
                      <td>{c.distance_miles == null ? "-" : `${c.distance_miles.toFixed(2)} mi`}</td>
                      <td>{c.sold_date ?? "-"}</td>
                      <td>{c.short_address ?? "-"}</td>
                      <td>{formatNumber(c.total_bedrooms ?? null)}</td>
                      <td>{formatNumber(c.baths_total ?? null)}</td>
                      <td>{formatNumber(c.sqft_living ?? null)}</td>
                      <td>{formatMoney(c.sold_price ?? null)}</td>
                      <td>{formatMoney(c.ppsf ?? null)}</td>
                      <td>{adjPct == null ? "-" : `${adjPct.toFixed(2)}%`}</td>
                      <td>{adjPpsf == null ? "-" : formatMoney(adjPpsf)}</td>
                      <td>{reasons}</td>
                      <td className="mono">{c.listing_number}</td>
                    </tr>
                      );
                    })()
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <p className="panel-subtitle">Run a parcel to see valuation diagnostics, mapped comps, and property features.</p>
        )}
      </section>
      ) : null}

      {activeView === "market" ? (
      <>
      <div className="market-dashboard-grid">
      <div className="market-main-column">
      <section className="panel report-panel section-anchor" id="section-overview">
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
            value={marketGradeInfo.label}
          />
        </div>
        <p className="panel-subtitle">
          <strong>Market Grade v2:</strong> {marketGradeInfo.formula}
        </p>
        <p className="panel-subtitle">
          <strong>Grade Read:</strong> {marketGradeInfo.description}
        </p>
        <p className="panel-subtitle">
          <strong>Component Scores:</strong> Pace {marketGradeInfo.pace == null ? "N/A" : marketGradeInfo.pace.toFixed(1)} | Supply {marketGradeInfo.supply == null ? "N/A" : marketGradeInfo.supply.toFixed(1)} | Pricing {marketGradeInfo.pricing == null ? "N/A" : marketGradeInfo.pricing.toFixed(1)} | Demand {marketGradeInfo.demand == null ? "N/A" : marketGradeInfo.demand.toFixed(1)}
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

      <div className="section-anchor" id="section-neighborhoods">
        <MarketGeoMap points={saleMapPoints} scopeLabel={marketScopeLabel} />
      </div>

      <section className="panel section-anchor" id="section-trends">
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

      </div>
      <div className="section-anchor" id="section-reports">
        <MarketPulsePanel
          reportSummary={reportSummary}
          marketGradeInfo={marketGradeInfo}
          geocodedCount={saleMapPoints.length}
          recentCount={recentListings?.rows.length ?? 0}
          onPrint={() => void printMarketReport()}
        />
      </div>
      </div>

      <section className="panel listings-panel">
        <div className="listings-head">
          <div>
            <h2>Chart Maker</h2>
            <p className="panel-subtitle">Build custom charts from the selected historical series.</p>
          </div>
        </div>
        <div className="chart-maker-controls">
          <label>
            Chart Type
            <select value={builderChartType} onChange={(e) => setBuilderChartType(e.target.value as BuilderChartType)}>
              <option value="line">Line</option>
              <option value="bar">Bar</option>
              <option value="pie">Pie</option>
              <option value="dual_axis">Dual Axis</option>
            </select>
          </label>
          <label>
            Metric A
            <select value={builderMetricA} onChange={(e) => setBuilderMetricA(e.target.value as BuilderMetricKey)}>
              {BUILDER_METRIC_OPTIONS.map((opt) => (
                <option key={`a-${opt.key}`} value={opt.key}>{opt.label}</option>
              ))}
            </select>
          </label>
          {builderChartType === "dual_axis" ? (
            <label>
              Metric B
              <select value={builderMetricB} onChange={(e) => setBuilderMetricB(e.target.value as BuilderMetricKey)}>
                {BUILDER_METRIC_OPTIONS.filter((opt) => opt.key !== builderMetricA).map((opt) => (
                  <option key={`b-${opt.key}`} value={opt.key}>{opt.label}</option>
                ))}
              </select>
            </label>
          ) : null}
          <div className="chart-maker-actions">
            <button className="btn" onClick={printChartMaker}>Print Chart</button>
          </div>
        </div>
        <div className="chart-maker-canvas" ref={chartMakerRef}>
          {(() => {
            if (!builderLabels.length || !builderValuesA.length) {
              return <p className="panel-subtitle">No period-series data available for this chart.</p>;
            }
            const width = 820;
            const height = 320;
            const pad: ChartPadding = { left: 62, right: 62, top: 16, bottom: 34 };
            const valuesA = builderValuesA;
            const domainA = getChartDomain(valuesA, true);
            const ticksA = buildTicks(domainA, 5);
            const xLabels = Array.from(new Set([0, Math.floor((builderLabels.length - 1) / 2), builderLabels.length - 1]));

            if (builderChartType === "pie") {
              const radius = 108;
              const cx = 180;
              const cy = 160;
              const total = valuesA.reduce((s, v) => s + Math.max(0, v), 0);
              const palette = ["#008c8a", "#2f6fb3", "#d86f1d", "#2d8a5d", "#7a5aa6", "#b14d5e", "#7c8f42", "#6f6f6f"];
              let cursor = -Math.PI / 2;
              const slices = valuesA.map((v, i) => ({ label: builderLabels[i], value: Math.max(0, v), color: palette[i % palette.length] })).filter((s) => s.value > 0);
              const topSlices = slices.length > 8 ? slices.sort((a, b) => b.value - a.value).slice(0, 8) : slices;
              return (
                <div className="chart-maker-pie-wrap">
                  <svg viewBox={`0 0 420 ${height}`} className="linechart">
                    <rect x="0" y="0" width="420" height={height} fill="#f6f8f7" rx="10" />
                    {topSlices.map((slice, i) => {
                      const frac = total > 0 ? slice.value / total : 0;
                      const start = cursor;
                      const end = start + frac * Math.PI * 2;
                      cursor = end;
                      const x1 = cx + radius * Math.cos(start);
                      const y1 = cy + radius * Math.sin(start);
                      const x2 = cx + radius * Math.cos(end);
                      const y2 = cy + radius * Math.sin(end);
                      const large = frac > 0.5 ? 1 : 0;
                      return <path key={`pie-${i}`} d={`M ${cx} ${cy} L ${x1} ${y1} A ${radius} ${radius} 0 ${large} 1 ${x2} ${y2} Z`} fill={slice.color} />;
                    })}
                  </svg>
                  <div className="chart-maker-legend">
                    {topSlices.map((slice, i) => (
                      <div className="legend-item" key={`legend-${i}`}>
                        <span className="swatch" style={{ backgroundColor: slice.color }} />
                        <span>{slice.label}</span>
                        <span>{formatBuilderValue(builderMetricSpecA.kind, slice.value)}</span>
                      </div>
                    ))}
                  </div>
                </div>
              );
            }

            if (builderChartType === "dual_axis") {
              const valuesB = builderMetricA === builderMetricB ? builderValuesA : builderValuesB;
              const domainB = getChartDomain(valuesB, true);
              const ticksB = buildTicks(domainB, 5);
              const pathA = buildLinePath(valuesA, domainA, width, height, pad);
              const pathB = valuesB.map((v, i) => `${xForIndex(i, valuesB.length, width, pad)},${yForValue(v, domainB, height, pad)}`).join(" L ");
              return (
                <svg viewBox={`0 0 ${width} ${height}`} className="linechart">
                  <rect x="0" y="0" width={width} height={height} fill="#f6f8f7" rx="10" />
                  {ticksA.map((tick, i) => {
                    const y = yForValue(tick, domainA, height, pad);
                    return (
                      <g key={`dual-a-${i}`}>
                        <line x1={pad.left} y1={y} x2={width - pad.right} y2={y} className="chart-gridline" />
                        <text x={pad.left - 6} y={y + 4} textAnchor="end" className="chart-tick-label">{formatAxisValue(tick, builderMetricSpecA.kind === "money" ? "currency" : "count")}</text>
                      </g>
                    );
                  })}
                  {ticksB.map((tick, i) => {
                    const y = yForValue(tick, domainB, height, pad);
                    return <text key={`dual-b-${i}`} x={width - pad.right + 6} y={y + 4} textAnchor="start" className="chart-tick-label">{formatAxisValue(tick, builderMetricSpecB.kind === "money" ? "currency" : "count")}</text>;
                  })}
                  <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} className="chart-axis" />
                  <path d={pathA} stroke="#2f6fb3" strokeWidth="3" fill="none" />
                  <path d={`M ${pathB}`} stroke="#d86f1d" strokeWidth="3" fill="none" />
                  {xLabels.map((idx) => (
                    <text key={`dual-label-${idx}`} x={xForIndex(idx, builderLabels.length, width, pad)} y={height - 8} textAnchor="middle" className="chart-tick-label">{builderLabels[idx]}</text>
                  ))}
                </svg>
              );
            }

            if (builderChartType === "bar") {
              const chartWidth = width - pad.left - pad.right;
              const slotW = chartWidth / valuesA.length;
              return (
                <svg viewBox={`0 0 ${width} ${height}`} className="linechart">
                  <rect x="0" y="0" width={width} height={height} fill="#f6f8f7" rx="10" />
                  {ticksA.map((tick, i) => {
                    const y = yForValue(tick, domainA, height, pad);
                    return (
                      <g key={`bar-tick-${i}`}>
                        <line x1={pad.left} y1={y} x2={width - pad.right} y2={y} className="chart-gridline" />
                        <text x={pad.left - 6} y={y + 4} textAnchor="end" className="chart-tick-label">{formatAxisValue(tick, builderMetricSpecA.kind === "money" ? "currency" : "count")}</text>
                      </g>
                    );
                  })}
                  <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} className="chart-axis" />
                  {valuesA.map((v, i) => {
                    const x = pad.left + i * slotW + 2;
                    const y = yForValue(v, domainA, height, pad);
                    const h = height - pad.bottom - y;
                    return <rect key={`bar-${i}`} x={x} y={y} width={Math.max(2, slotW - 4)} height={Math.max(0, h)} fill="#008c8a" rx="3" />;
                  })}
                  {xLabels.map((idx) => {
                    const x = pad.left + idx * slotW + slotW / 2;
                    return <text key={`bar-label-${idx}`} x={x} y={height - 8} textAnchor="middle" className="chart-tick-label">{builderLabels[idx]}</text>;
                  })}
                </svg>
              );
            }

            const path = buildLinePath(valuesA, domainA, width, height, pad);
            return (
              <svg viewBox={`0 0 ${width} ${height}`} className="linechart">
                <rect x="0" y="0" width={width} height={height} fill="#f6f8f7" rx="10" />
                {ticksA.map((tick, i) => {
                  const y = yForValue(tick, domainA, height, pad);
                  return (
                    <g key={`line-tick-${i}`}>
                      <line x1={pad.left} y1={y} x2={width - pad.right} y2={y} className="chart-gridline" />
                      <text x={pad.left - 6} y={y + 4} textAnchor="end" className="chart-tick-label">{formatAxisValue(tick, builderMetricSpecA.kind === "money" ? "currency" : "count")}</text>
                    </g>
                  );
                })}
                <line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} className="chart-axis" />
                <path d={path} stroke="#2f6fb3" strokeWidth="3" fill="none" />
                {valuesA.map((v, i) => (
                  <circle key={`line-dot-${i}`} cx={xForIndex(i, valuesA.length, width, pad)} cy={yForValue(v, domainA, height, pad)} r="3.5" fill="#008c8a" />
                ))}
                {xLabels.map((idx) => (
                  <text key={`line-label-${idx}`} x={xForIndex(idx, builderLabels.length, width, pad)} y={height - 8} textAnchor="middle" className="chart-tick-label">{builderLabels[idx]}</text>
                ))}
              </svg>
            );
          })()}
          <div className="chart-maker-legend-strip">
            {(builderChartType === "dual_axis" ? [
              { label: builderMetricSpecA.label, color: "#2f6fb3" },
              { label: builderMetricSpecB.label, color: "#d86f1d" },
            ] : [
              { label: builderMetricSpecA.label, color: builderChartType === "bar" ? "#008c8a" : "#2f6fb3" },
            ]).map((item) => (
              <span className="chart-legend-item" key={item.label}>
                <span className="chart-legend-swatch" style={{ backgroundColor: item.color }} />
                {item.label}
              </span>
            ))}
          </div>
        </div>
      </section>

      <section className="two-col">
        <article className="panel section-anchor" id="section-sales">
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
        <article className="panel section-anchor" id="section-inventory">
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
      </>
      ) : null}
      </main>
    </div>
  );
}
