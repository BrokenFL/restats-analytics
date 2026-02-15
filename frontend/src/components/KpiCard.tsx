type Props = {
  label: string;
  value: string;
  accent?: "teal" | "orange" | "blue" | "green";
};

export default function KpiCard({ label, value, accent = "teal" }: Props) {
  return (
    <article className={`kpi-card accent-${accent}`}>
      <p className="kpi-label">{label}</p>
      <p className="kpi-value">{value}</p>
    </article>
  );
}
