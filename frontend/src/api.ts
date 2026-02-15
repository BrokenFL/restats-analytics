export type KpisResponse = {
  total_records: number | null;
  closed_count: number | null;
  active_count: number | null;
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
export type SubdivisionOption = { final_subdivision: string; count: number };
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

export type RecentListing = {
  listing_number: string;
  sold_date: string | null;
  short_address: string | null;
  city: string | null;
  final_subdivision: string | null;
  geo_zone: string | null;
  property_type: string | null;
  status: string | null;
  list_price: number | null;
  sold_price: number | null;
  sp_lp_ratio: number | null;
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
  active_inventory: number | null;
  months_supply: number | null;
  median_dom: number | null;
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
    property_type_distribution: Array<{ property_type: string | null; cnt: number }>;
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

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`);
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
  propertyType?: string;
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
    property_type: filters.propertyType,
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
    property_type: filters.propertyType,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup
  });
  return getJson<TrendsResponse>(`/api/market/trends${query}`);
}

export async function fetchInventory(filters: Filters = {}): Promise<InventoryResponse> {
  const query = buildQuery({
    city: filters.city,
    final_subdivision: filters.finalSubdivision,
    property_type: filters.propertyType,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup
  });
  return getJson<InventoryResponse>(`/api/inventory/by-status${query}`);
}

export async function fetchFilterOptions(filters: Filters = {}): Promise<FilterOptionsResponse> {
  const query = buildQuery({
    city: filters.city,
    geo_zone: filters.geoZone,
    property_type: filters.propertyType,
    property_group: filters.propertyGroup
  });
  return getJson<FilterOptionsResponse>(`/api/filters/options${query}`);
}

export async function fetchRecentListings(limit = 25, filters: Filters = {}, soldSince?: string): Promise<RecentListingsResponse> {
  const query = buildQuery({
    limit,
    city: filters.city,
    final_subdivision: filters.finalSubdivision,
    property_type: filters.propertyType,
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
    property_type: filters.propertyType,
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
    property_type: filters.propertyType,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup
  });
  return getJson<ReportSummaryResponse>(`/api/market/report-summary${query}`);
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
    property_type: filters.propertyType,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup
  });
  return getJson<SubdivisionRankingsResponse>(`/api/market/subdivision-rankings${query}`);
}

export async function fetchOpsStatus(): Promise<OpsStatusResponse> {
  return getJson<OpsStatusResponse>("/api/ops/status");
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
    property_type: filters.propertyType,
    geo_zone: filters.geoZone,
    property_group: filters.propertyGroup
  });
  return getJson<PeriodSeriesResponse>(`/api/market/period-series${query}`);
}
