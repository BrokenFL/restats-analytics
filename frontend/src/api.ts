export type KpisResponse = {
  total_records: number | null;
  closed_count: number | null;
  active_count: number | null;
  active_inventory_current?: number | null;
  active_inventory_snapshot?: number | null;
  active_inventory_snapshot_date?: string | null;
  avg_sold_price: number | null;
  avg_list_price: number | null;
  avg_sp_lp_ratio: number | null;
};

export type TrendRow = {
  period: string;
  sold_count: number;
  avg_sold_price: number | null;
  min_sold_price: number | null;
  max_sold_price: number | null;
};

export type TrendsResponse = {
  months: number;
  frequency: "monthly" | "quarterly" | "annual";
  rows: TrendRow[];
};

export type StatusRow = {
  status: string;
  count: number;
};

export type InventoryResponse = {
  rows: StatusRow[];
};

export type CityOption = { city: string; count: number };
export type SubdivisionOption = { final_subdivision: string; city?: string | null; count: number };
export type PropertyTypeOption = { property_type: string; count: number };
export type GeoZoneOption = { geo_zone: string; count: number };
export type PropertyGroupOption = { value: "ALL" | "SINGLE_FAMILY" | "TOWNHOME_CONDO"; label: string };

export type FilterOptionsResponse = {
  cities: CityOption[];
  subdivisions: SubdivisionOption[];
  property_types: PropertyTypeOption[];
  geo_zones: GeoZoneOption[];
  property_groups: PropertyGroupOption[];
};

export type DashboardBootstrapResponse = {
  config: ReportConfig;
  filters: Filters;
  report_summary: ReportSummaryResponse;
  kpis: KpisResponse;
  trends: TrendsResponse;
  inventory: InventoryResponse;
  recent_listings: RecentListingsResponse;
  rankings: SubdivisionRankingsResponse;
  filter_options?: FilterOptionsResponse;
};

export type RecentListing = {
  listing_number: string;
  sold_date: string | null;
  short_address: string | null;
  city: string | null;
  final_subdivision: string | null;
  geo_zone: string | null;
  property_type: string | null;
  status: string | null;
  total_bedrooms?: number | null;
  baths_total?: number | null;
  sqft_living?: number | null;
  list_price: number | null;
  sold_price: number | null;
  sold_ppsf?: number | null;
  geo_lat?: number | null;
  geo_lon?: number | null;
  sp_lp_ratio: number | null;
  cabana_flag?: boolean | null;
};

export type RecentListingsResponse = {
  rows: RecentListing[];
  limit: number;
};

export type ReportPeriodMetrics = {
  sold_count: number | null;
  total_sales_volume: number | null;
  median_sold_price: number | null;
  avg_sold_price: number | null;
  median_price_per_sqft: number | null;
  avg_list_price: number | null;
  avg_sp_lp: number | null;
  cash_sales_percent: number | null;
  new_listings: number | null;
  pending_sales: number | null;
  pending_inventory?: number | null;
  active_inventory: number | null;
  months_supply: number | null;
  median_dom: number | null;
  avg_dom?: number | null;
  median_listing_discount: number | null;
};

export type ReportSummaryResponse = {
  report_mode: "rolling" | "monthly" | "quarterly" | "annual" | "custom";
  period_days: number;
  period_label: string;
  current_start: string;
  current_end: string;
  previous_start: string;
  previous_end: string;
  current: ReportPeriodMetrics;
  previous: ReportPeriodMetrics;
  delta_pct: ReportPeriodMetrics;
};

export type ReportListing = {
  listing_number: string;
  parcel_id: string | null;
  short_address: string | null;
  city: string | null;
  geo_zone: string | null;
  final_subdivision: string | null;
  property_type: string | null;
  status: string | null;
  unit_number: string | null;
  listing_date: string | null;
  under_contract_date: string | null;
  sold_date: string | null;
  effective_active_end_date: string | null;
  list_price: number | null;
  original_list_price: number | null;
  sold_price: number | null;
  sold_ppsf: number | null;
  sp_lp_ratio: number | null;
  total_bedrooms: number | null;
  baths_total: number | null;
  sqft_living: number | null;
  geo_lat: number | null;
  geo_lon: number | null;
  terms_of_sale: string | null;
  cabana_flag: boolean;
  new_listing_in_period: boolean;
  pending_in_period: boolean;
  sold_in_period: boolean;
  active_at_period_end: boolean;
  pending_at_period_end: boolean;
};

export type ReportListingsResponse = {
  report_mode: "rolling" | "monthly" | "quarterly" | "annual" | "custom";
  period_label: string;
  current_start: string;
  current_end: string;
  row_count: number;
  rows: ReportListing[];
};

export type MarketMapPoint = {
  listing_number: string;
  sold_date: string | null;
  short_address: string | null;
  city: string | null;
  final_subdivision: string | null;
  sold_price: number | null;
  geo_lat: number;
  geo_lon: number;
};

export type MarketMapPointsResponse = {
  report_mode: "rolling" | "monthly" | "quarterly" | "annual" | "custom";
  period_label: string;
  current_start: string;
  current_end: string;
  row_count: number;
  rows: MarketMapPoint[];
};

export type SubdivisionRankingRow = {
  final_subdivision: string;
  city: string | null;
  sold_count: number;
  avg_sold_price: number | null;
  avg_list_price: number | null;
  avg_sp_lp: number | null;
  avg_dom: number | null;
};

export type SubdivisionRankingsResponse = {
  report_mode: "rolling" | "monthly" | "quarterly" | "annual" | "custom";
  period_days: number;
  period_label: string;
  current_start: string;
  current_end: string;
  rows: SubdivisionRankingRow[];
};

export type PeriodSeriesRow = {
  period: string;
  start_date: string;
  end_date: string;
  sold_count: number | null;
  total_sales_volume: number | null;
  median_sold_price: number | null;
  median_price_per_sqft: number | null;
  new_listings: number | null;
  pending_sales: number | null;
  active_inventory: number | null;
  months_supply: number | null;
  median_dom: number | null;
  median_listing_discount: number | null;
  avg_sp_lp: number | null;
  cash_sales_percent: number | null;
};

export type PeriodSeriesResponse = {
  frequency: "monthly" | "quarterly" | "annual";
  periods: number;
  rows: PeriodSeriesRow[];
};

export type OpsStatusResponse = {
  database: {
    path: string;
    listing_count: number;
    last_mls_status_date: string | null;
    last_off_market_sold_date: string | null;
    last_sold_date?: string | null;
    mls_status_lag_days?: number | null;
    sold_lag_days?: number | null;
    property_type_distribution: Array<{ property_type: string | null; cnt: number }>;
    status_distribution?: Array<{ status: string; cnt: number }>;
    status_bucket_distribution?: Array<{ status: string; cnt: number }>;
  };
  duplicate_audit: {
    available: boolean;
    path: string;
    generated_at?: string;
    duplicate_listing_number_count?: number;
    near_duplicate_count?: number;
    cross_source_count?: number;
    error?: string;
  };
  guardrail_audit?: {
    available: boolean;
    path: string;
    generated_at?: string;
    checks?: Record<string, number>;
    total_failures?: number;
    passed?: boolean;
    error?: string;
  };
  last_run?: {
    available: boolean;
    path: string;
    pipeline?: string;
    status?: string;
    started_at?: string;
    finished_at?: string;
    updated_at?: string;
    details?: Record<string, string | number | boolean | null>;
    error?: string | null;
  };
};

export type ParityMetricRow = {
  metric: string;
  legacy_value: number | null;
  api_value: number | null;
  delta: number | null;
  delta_pct: number | null;
  in_tolerance: boolean;
};

export type ParityResponse = {
  mode: "monthly" | "quarterly" | "annual";
  current_start: string;
  current_end: string;
  tolerance_pct: number;
  metrics: ParityMetricRow[];
  mismatch_count: number;
};

export type ReportConfig = {
  reportMode: "rolling" | "monthly" | "quarterly" | "annual" | "custom";
  periodDays: number;
  refYear?: number;
  refMonth?: number;
  refQuarter?: number;
  startDate?: string;
  endDate?: string;
};

export type CmaComp = {
  listing_number: string;
  bucket?: string | null;
  final_score?: number | null;
  similarity_score?: number | null;
  recency_multiplier?: number | null;
  location_points?: number | null;
  base_points?: number | null;
  feature_points?: number | null;
  recency_days?: number | null;
  distance_miles?: number | null;
  sold_date?: string | null;
  sold_price?: number | null;
  list_price?: number | null;
  ppsf?: number | null;
  short_address?: string | null;
  city?: string | null;
  final_subdivision?: string | null;
  property_type?: string | null;
  geo_lat?: number | null;
  geo_lon?: number | null;
  total_bedrooms?: number | null;
  baths_total?: number | null;
  sqft_living?: number | null;
  year_built?: number | null;
};

export type CmaRunResponse = {
  subject: Record<string, unknown>;
  as_of_date: string;
  valuation: Record<string, unknown>;
  confidence_grade: string;
  confidence_reason: string;
  pending_projection: Record<string, unknown>;
  surrounding_discount_metrics: Record<string, unknown>;
  pending_pressure_guardrail: Record<string, unknown>;
  closing_trends: Record<string, unknown>;
  community_insights: Record<string, unknown>;
  surrounding_area_context: Record<string, unknown>;
  community_scope: Record<string, unknown>;
  comps: CmaComp[];
};

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

async function getJson<T>(path: string): Promise<T> {
  const url = `${API_BASE}${path}`;
  let response: Response;
  try {
    response = await fetch(url);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown network error";
    throw new Error(`Cannot reach API at ${url}. ${msg}`);
  }
  if (!response.ok) {
    throw new Error(`API request failed (${response.status} ${response.statusText}) at ${url}`);
  }
  return (await response.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const url = `${API_BASE}${path}`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (err) {
    const msg = err instanceof Error ? err.message : "Unknown network error";
    throw new Error(`Cannot reach API at ${url}. ${msg}`);
  }
  if (!response.ok) {
    const detail = await response.text().catch(() => "");
    throw new Error(`API request failed (${response.status} ${response.statusText}) at ${url}${detail ? `: ${detail}` : ""}`);
  }
  return (await response.json()) as T;
}

export async function fetchKpis(soldSince: string): Promise<KpisResponse> {
  const query = soldSince ? `?sold_since=${encodeURIComponent(soldSince)}` : "";
  return getJson<KpisResponse>(`/api/summary/kpis${query}`);
}

type Filters = {
  city?: string;
  finalSubdivision?: string;
  geoZone?: string;
  propertyGroup?: "ALL" | "SINGLE_FAMILY" | "TOWNHOME_CONDO";
};

function buildQuery(params: Record<string, string | number | undefined>): string {
  const qp = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v != null && `${v}`.trim() !== "") qp.set(k, `${v}`);
  });
  const s = qp.toString();
  return s ? `?${s}` : "";
}

export async function fetchKpisWithFilters(soldSince: string, filters: Filters): Promise<KpisResponse> {
  const query = buildQuery({
    sold_since: soldSince || undefined,
    city: filters.city,
    final_subdivision: filters.finalSubdivision,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup
  });
  return getJson<KpisResponse>(`/api/summary/kpis${query}`);
}

export async function fetchTrends(
  months = 12,
  filters: Filters = {},
  frequency: "monthly" | "quarterly" | "annual" = "monthly",
  startDate?: string,
  endDate?: string
): Promise<TrendsResponse> {
  const query = buildQuery({
    months,
    frequency,
    start_date: startDate,
    end_date: endDate,
    city: filters.city,
    final_subdivision: filters.finalSubdivision,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup
  });
  return getJson<TrendsResponse>(`/api/market/trends${query}`);
}

export async function fetchInventory(filters: Filters = {}): Promise<InventoryResponse> {
  const query = buildQuery({
    city: filters.city,
    final_subdivision: filters.finalSubdivision,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup
  });
  return getJson<InventoryResponse>(`/api/inventory/by-status${query}`);
}

export async function fetchFilterOptions(filters: Filters = {}): Promise<FilterOptionsResponse> {
  const query = buildQuery({
    city: filters.city,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup
  });
  return getJson<FilterOptionsResponse>(`/api/filters/options${query}`);
}

export async function fetchDashboardBootstrap(
  config: ReportConfig,
  filters: Filters = {},
  soldSince?: string
): Promise<DashboardBootstrapResponse> {
  const query = buildQuery({
    report_mode: config.reportMode,
    period_days: config.periodDays,
    ref_year: config.refYear,
    ref_month: config.refMonth,
    ref_quarter: config.refQuarter,
    start_date: config.startDate,
    end_date: config.endDate,
    city: filters.city,
    final_subdivision: filters.finalSubdivision,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup,
    sold_since: soldSince
  });
  return getJson<DashboardBootstrapResponse>(`/api/dashboard/bootstrap${query}`);
}

export async function fetchRecentListings(limit = 25, filters: Filters = {}, soldSince?: string): Promise<RecentListingsResponse> {
  const query = buildQuery({
    limit,
    city: filters.city,
    final_subdivision: filters.finalSubdivision,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup,
    sold_since: soldSince
  });
  return getJson<RecentListingsResponse>(`/api/listings/recent${query}`);
}

export async function fetchRecentListingsForRange(
  limit = 25,
  filters: Filters = {},
  startDate?: string,
  endDate?: string,
  soldSince?: string
): Promise<RecentListingsResponse> {
  const query = buildQuery({
    limit,
    city: filters.city,
    final_subdivision: filters.finalSubdivision,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup,
    start_date: startDate,
    end_date: endDate,
    sold_since: soldSince
  });
  return getJson<RecentListingsResponse>(`/api/listings/recent${query}`);
}

export async function fetchReportSummary(config: ReportConfig, filters: Filters = {}): Promise<ReportSummaryResponse> {
  const query = buildQuery({
    report_mode: config.reportMode,
    period_days: config.periodDays,
    ref_year: config.refYear,
    ref_month: config.refMonth,
    ref_quarter: config.refQuarter,
    start_date: config.startDate,
    end_date: config.endDate,
    city: filters.city,
    final_subdivision: filters.finalSubdivision,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup
  });
  return getJson<ReportSummaryResponse>(`/api/market/report-summary${query}`);
}

export async function fetchReportListings(config: ReportConfig, filters: Filters = {}): Promise<ReportListingsResponse> {
  const query = buildQuery({
    report_mode: config.reportMode,
    period_days: config.periodDays,
    ref_year: config.refYear,
    ref_month: config.refMonth,
    ref_quarter: config.refQuarter,
    start_date: config.startDate,
    end_date: config.endDate,
    city: filters.city,
    final_subdivision: filters.finalSubdivision,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup
  });
  return getJson<ReportListingsResponse>(`/api/market/report-listings${query}`);
}

export async function fetchMarketMapPoints(
  config: ReportConfig,
  filters: Filters = {},
  limit = 1000
): Promise<MarketMapPointsResponse> {
  const query = buildQuery({
    report_mode: config.reportMode,
    period_days: config.periodDays,
    ref_year: config.refYear,
    ref_month: config.refMonth,
    ref_quarter: config.refQuarter,
    start_date: config.startDate,
    end_date: config.endDate,
    city: filters.city,
    final_subdivision: filters.finalSubdivision,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup,
    limit,
  });
  return getJson<MarketMapPointsResponse>(`/api/market/map-points${query}`);
}

export async function fetchSubdivisionRankings(
  config: ReportConfig,
  minSales: number,
  limit: number,
  filters: Filters = {}
): Promise<SubdivisionRankingsResponse> {
  const query = buildQuery({
    report_mode: config.reportMode,
    period_days: config.periodDays,
    ref_year: config.refYear,
    ref_month: config.refMonth,
    ref_quarter: config.refQuarter,
    start_date: config.startDate,
    end_date: config.endDate,
    min_sales: minSales,
    limit,
    city: filters.city,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup
  });
  return getJson<SubdivisionRankingsResponse>(`/api/market/subdivision-rankings${query}`);
}

export async function fetchOpsStatus(): Promise<OpsStatusResponse> {
  return getJson<OpsStatusResponse>("/api/ops/status");
}

export async function fetchParity(
  mode: "monthly" | "quarterly" | "annual",
  year: number,
  month?: number,
  quarter?: number,
  filters: Filters = {}
): Promise<ParityResponse> {
  const query = buildQuery({
    mode,
    year,
    month,
    quarter,
    city: filters.city,
    final_subdivision: filters.finalSubdivision,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup,
  });
  return getJson<ParityResponse>(`/api/ops/parity${query}`);
}

export async function fetchMarketPeriodSeries(
  frequency: "monthly" | "quarterly" | "annual",
  periods: number,
  filters: Filters = {},
  endDate?: string,
  endYear?: number,
  endMonth?: number,
  endQuarter?: number
): Promise<PeriodSeriesResponse> {
  const query = buildQuery({
    frequency,
    periods,
    end_date: endDate,
    end_year: endYear,
    end_month: endMonth,
    end_quarter: endQuarter,
    city: filters.city,
    final_subdivision: filters.finalSubdivision,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup
  });
  return getJson<PeriodSeriesResponse>(`/api/market/period-series${query}`);
}

export async function runCma(parcel: string, asOfDate?: string, topN = 15): Promise<CmaRunResponse> {
  return postJson<CmaRunResponse>("/api/cma/run", {
    parcel,
    as_of_date: asOfDate,
    top_n: topN,
  });
}
