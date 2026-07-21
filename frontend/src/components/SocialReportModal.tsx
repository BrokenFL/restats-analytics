import { useEffect, useMemo, useRef, useState } from "react";
import type { ReportSummaryResponse } from "../api";

type Platform = "instagram" | "linkedin";

type Props = {
  open: boolean;
  loading: boolean;
  error: string | null;
  currentSummary: ReportSummaryResponse | null;
  yearAgoSummary: ReportSummaryResponse | null;
  scopeTitle: string;
  locationLabel: string;
  onClose: () => void;
};

const COLORS = {
  navy: "#092a5e",
  teal: "#078b89",
  orange: "#f04416",
  gold: "#c5a06d",
  white: "rgba(255,255,255,0.88)",
};

function percentChange(current: number | null | undefined, previous: number | null | undefined): number | null {
  if (current == null || previous == null || previous === 0) return null;
  return ((current - previous) / Math.abs(previous)) * 100;
}

function compactMoney(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (Math.abs(value) >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(value);
}

function formatYoy(value: number | null, compact = false): string {
  if (value == null || !Number.isFinite(value)) return "YOY N/A";
  const arrow = value > 0 ? "↑" : value < 0 ? "↓" : "→";
  const precision = compact || Math.abs(value) >= 100 ? 0 : 1;
  return `${arrow} ${Math.abs(value).toFixed(precision)}% YOY`;
}

function drawFittedText(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  maxWidth: number,
  initialSize: number,
  family: string,
  weight = "400"
) {
  let size = initialSize;
  while (size > 22) {
    ctx.font = `${weight} ${size}px ${family}`;
    if (ctx.measureText(text).width <= maxWidth) break;
    size -= 2;
  }
  ctx.fillText(text, x, y);
  return size;
}

function titleLines(ctx: CanvasRenderingContext2D, title: string): string[] {
  const words = title.trim().toUpperCase().split(/\s+/).filter(Boolean);
  if (!words.length) return ["PALM BEACH COUNTY"];
  ctx.font = "400 86px Georgia, serif";
  if (ctx.measureText(words.join(" ")).width <= 900) return [words.join(" ")];
  let best: string[] = [words.slice(0, Math.ceil(words.length / 2)).join(" "), words.slice(Math.ceil(words.length / 2)).join(" ")];
  let bestDelta = Number.POSITIVE_INFINITY;
  for (let index = 1; index < words.length; index += 1) {
    const candidate = [words.slice(0, index).join(" "), words.slice(index).join(" ")];
    const delta = Math.abs(ctx.measureText(candidate[0]).width - ctx.measureText(candidate[1]).width);
    if (delta < bestDelta) {
      best = candidate;
      bestDelta = delta;
    }
  }
  return best;
}

function safeFilename(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}

export function SocialReportModal({
  open,
  loading,
  error,
  currentSummary,
  yearAgoSummary,
  scopeTitle,
  locationLabel,
  onClose,
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [platform, setPlatform] = useState<Platform>("instagram");
  const [copied, setCopied] = useState<"caption" | "alt" | null>(null);

  const metrics = useMemo(() => {
    const current = currentSummary?.current;
    const prior = yearAgoSummary?.current;
    return {
      sold: current?.sold_count ?? null,
      avgPrice: current?.avg_sold_price ?? null,
      avgDom: current?.avg_dom ?? null,
      saleToList: current?.avg_sp_lp ?? null,
      soldYoy: percentChange(current?.sold_count, prior?.sold_count),
      avgPriceYoy: percentChange(current?.avg_sold_price, prior?.avg_sold_price),
      avgDomYoy: percentChange(current?.avg_dom, prior?.avg_dom),
      saleToListYoy: percentChange(current?.avg_sp_lp, prior?.avg_sp_lp),
    };
  }, [currentSummary, yearAgoSummary]);

  const periodLabel = currentSummary?.period_label ?? "Market Snapshot";
  const dataThrough = currentSummary?.current_end ?? "";
  const dataThroughLabel = dataThrough
    ? new Date(`${dataThrough}T12:00:00`).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric" })
    : "latest available date";

  const caption = useMemo(() => {
    const sold = metrics.sold == null ? "N/A" : Math.round(metrics.sold).toLocaleString();
    const avgDom = metrics.avgDom == null ? "N/A" : Math.round(metrics.avgDom).toLocaleString();
    if (platform === "linkedin") {
      return `${scopeTitle} | ${periodLabel}\n\n${sold} closed sales (${formatYoy(metrics.soldYoy, true)}), an average sold price of ${compactMoney(metrics.avgPrice)} (${formatYoy(metrics.avgPriceYoy)}), ${avgDom} average days on market (${formatYoy(metrics.avgDomYoy, true)}), and ${metrics.saleToList == null ? "N/A" : `${metrics.saleToList.toFixed(1)}%`} average sale-to-list (${formatYoy(metrics.saleToListYoy)}).\n\nMLS data through ${dataThroughLabel}.`;
    }
    return `${scopeTitle} ${periodLabel} market snapshot ✨\n\n${sold} closed sales · ${compactMoney(metrics.avgPrice)} average sold price · ${avgDom} average days on market · ${metrics.saleToList == null ? "N/A" : `${metrics.saleToList.toFixed(1)}%`} sale-to-list.\n\nMLS data through ${dataThroughLabel}.\n\n#PalmBeachCountyRealEstate #MarketUpdate #ReStats`;
  }, [dataThroughLabel, metrics, periodLabel, platform, scopeTitle]);

  const altText = useMemo(() => {
    return `${scopeTitle} ${periodLabel} market snapshot. ${metrics.sold == null ? "No" : Math.round(metrics.sold)} closed sales, ${compactMoney(metrics.avgPrice)} average sold price, ${metrics.avgDom == null ? "unavailable" : Math.round(metrics.avgDom)} average days on market, and ${metrics.saleToList == null ? "unavailable" : `${metrics.saleToList.toFixed(1)} percent`} average sale-to-list ratio. Year-over-year changes are ${formatYoy(metrics.soldYoy, true)} for sales, ${formatYoy(metrics.avgPriceYoy)} for average sold price, ${formatYoy(metrics.avgDomYoy, true)} for days on market, and ${formatYoy(metrics.saleToListYoy)} for sale-to-list. MLS data through ${dataThroughLabel}.`;
  }, [dataThroughLabel, metrics, periodLabel, scopeTitle]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onClose, open]);

  useEffect(() => {
    if (!open || !canvasRef.current || !currentSummary || !yearAgoSummary) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    canvas.width = 1080;
    canvas.height = 1080;
    const background = new Image();
    background.src = "/assets/social-report-background.png";
    background.onload = () => {
      ctx.clearRect(0, 0, 1080, 1080);
      ctx.drawImage(background, 0, 0, 1080, 1080);
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";

      ctx.fillStyle = COLORS.navy;
      ctx.font = "400 58px Georgia, serif";
      ctx.fillText("ReStats", 540, 66);
      ctx.fillStyle = COLORS.orange;
      ctx.fillRect(500, 106, 80, 4);

      const lines = titleLines(ctx, scopeTitle);
      const titleY = lines.length === 1 ? [238] : [202, 294];
      lines.forEach((line, index) => {
        ctx.fillStyle = COLORS.navy;
        drawFittedText(ctx, line, 540, titleY[index], 930, 90, "Georgia, serif");
      });

      ctx.strokeStyle = COLORS.teal;
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(180, 350);
      ctx.lineTo(900, 350);
      ctx.stroke();
      ctx.fillStyle = COLORS.teal;
      ctx.font = "700 34px Arial, sans-serif";
      ctx.fillText(`${periodLabel.toUpperCase()} MARKET SNAPSHOT`, 540, 392);

      ctx.fillStyle = COLORS.white;
      ctx.strokeStyle = COLORS.gold;
      ctx.lineWidth = 2;
      ctx.fillRect(72, 430, 936, 285);
      ctx.strokeRect(72, 430, 936, 285);
      ctx.fillStyle = COLORS.teal;
      ctx.font = "400 142px Georgia, serif";
      ctx.fillText(metrics.sold == null ? "—" : Math.round(metrics.sold).toLocaleString(), 540, 535);
      ctx.fillStyle = COLORS.navy;
      ctx.font = "700 42px Arial, sans-serif";
      ctx.fillText("CLOSED SALES", 540, 640);
      ctx.fillStyle = metrics.soldYoy != null && metrics.soldYoy >= 0 ? COLORS.teal : COLORS.orange;
      ctx.font = "700 30px Arial, sans-serif";
      ctx.fillText(formatYoy(metrics.soldYoy, true), 540, 686);

      const cards = [
        { value: compactMoney(metrics.avgPrice), label: "AVG SOLD PRICE", yoy: metrics.avgPriceYoy, tone: metrics.avgPriceYoy != null && metrics.avgPriceYoy >= 0 ? COLORS.teal : COLORS.orange },
        { value: metrics.avgDom == null ? "—" : Math.round(metrics.avgDom).toLocaleString(), label: "AVG DAYS ON MARKET", yoy: metrics.avgDomYoy, tone: metrics.avgDomYoy != null && metrics.avgDomYoy < 0 ? COLORS.teal : COLORS.orange },
        { value: metrics.saleToList == null ? "—" : `${metrics.saleToList.toFixed(1)}%`, label: "AVG SALE-TO-LIST", yoy: metrics.saleToListYoy, tone: metrics.saleToListYoy != null && metrics.saleToListYoy >= 0 ? COLORS.teal : COLORS.orange },
      ];
      cards.forEach((card, index) => {
        const x = 72 + index * 312;
        ctx.fillStyle = COLORS.white;
        ctx.strokeStyle = COLORS.gold;
        ctx.fillRect(x, 715, 312, 210);
        ctx.strokeRect(x, 715, 312, 210);
        ctx.fillStyle = COLORS.teal;
        drawFittedText(ctx, card.value, x + 156, 790, 270, 66, "Georgia, serif");
        ctx.fillStyle = COLORS.orange;
        ctx.fillRect(x + 128, 835, 56, 4);
        ctx.fillStyle = COLORS.navy;
        drawFittedText(ctx, card.label, x + 156, 867, 280, 23, "Arial, sans-serif", "700");
        ctx.fillStyle = card.tone;
        ctx.font = "700 22px Arial, sans-serif";
        ctx.fillText(formatYoy(card.yoy, card.label.includes("DAYS")), x + 156, 905);
      });

      ctx.fillStyle = COLORS.navy;
      drawFittedText(ctx, `${locationLabel}, Florida`, 540, 976, 740, 44, "Georgia, serif");
      ctx.fillStyle = COLORS.navy;
      ctx.globalAlpha = 0.86;
      ctx.font = "italic 23px Georgia, serif";
      ctx.fillText(`MLS data through ${dataThroughLabel}`, 540, 1024);
      ctx.globalAlpha = 1;
    };
  }, [currentSummary, dataThroughLabel, locationLabel, metrics, open, periodLabel, scopeTitle, yearAgoSummary]);

  if (!open) return null;

  const copyText = async (kind: "caption" | "alt", value: string) => {
    await navigator.clipboard.writeText(value);
    setCopied(kind);
    window.setTimeout(() => setCopied(null), 1800);
  };

  const download = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `restats-${safeFilename(scopeTitle)}-${safeFilename(periodLabel)}-${platform}.png`;
      anchor.click();
      URL.revokeObjectURL(url);
    }, "image/png");
  };

  return (
    <div className="social-modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section className="social-modal" role="dialog" aria-modal="true" aria-labelledby="social-report-title">
        <div className="social-modal-header">
          <div>
            <p className="eyebrow">Social report</p>
            <h2 id="social-report-title">Create a monthly market post</h2>
            <p>Exact ReStats metrics in the approved editorial template.</p>
          </div>
          <button className="modal-close" type="button" aria-label="Close social report" onClick={onClose}>×</button>
        </div>

        <div className="social-platform-tabs" role="tablist" aria-label="Social platform">
          <button type="button" role="tab" aria-selected={platform === "instagram"} className={platform === "instagram" ? "active" : ""} onClick={() => setPlatform("instagram")}>Instagram</button>
          <button type="button" role="tab" aria-selected={platform === "linkedin"} className={platform === "linkedin" ? "active" : ""} onClick={() => setPlatform("linkedin")}>LinkedIn</button>
        </div>

        {loading ? <div className="social-report-state">Loading year-over-year comparison…</div> : null}
        {error ? <div className="social-report-state error">{error}</div> : null}
        {!loading && !error ? (
          <div className="social-modal-grid">
            <div className="social-preview-wrap">
              <canvas ref={canvasRef} className="social-preview" role="img" aria-label={altText} />
              <button className="btn primary social-download" type="button" onClick={download}>Download PNG</button>
              <p>1080 × 1080 PNG · ready for {platform === "instagram" ? "Instagram" : "LinkedIn"}</p>
            </div>
            <div className="social-copy-column">
              <label>
                Suggested caption
                <textarea readOnly value={caption} rows={10} />
              </label>
              <button className="btn" type="button" onClick={() => void copyText("caption", caption)}>{copied === "caption" ? "Copied" : "Copy caption"}</button>
              <label>
                Alt text
                <textarea readOnly value={altText} rows={8} />
              </label>
              <button className="btn" type="button" onClick={() => void copyText("alt", altText)}>{copied === "alt" ? "Copied" : "Copy alt text"}</button>
              <p className="social-source-note">Source: ReStats MLS analysis through {dataThroughLabel}. Always review before publishing.</p>
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}
