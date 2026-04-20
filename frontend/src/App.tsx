import { useEffect, useMemo, useRef, useState } from "react";
import type React from "react";
import type { TooltipProps } from "recharts";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ResponsiveContainer,
  AreaChart,
  Area,
  Legend,
  BarChart,
  Bar,
  Cell,
  ReferenceLine,
} from "recharts";

const API_BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000";
const API = `${API_BASE}/monitoring`;
const REVIEW_PAGE_SIZE = 4;
const ALERT_PAGE_SIZE = 4;

type KPI = {
  drift_status: string;
  low_confidence_rate: number;
  total_requests_today: number;
  active_alerts: number;
};

type ConfidenceTrend = { threshold: number; points: { hour: string; avg_confidence: number }[] };
type ClassRatioPoint = { hour: string; beverages: number; snacks: number };
type DriftTrend = {
  thresholds: { embedding: number; confidence: number; class: number };
  points: { timestamp: string; embedding_score: number; confidence_score: number; class_score: number; is_drift: boolean }[];
};
type Alert = { id: number; alert_type: string; message: string; timestamp: string; resolved: boolean };
type ReviewItem = {
  id: number;
  predicted_class: string;
  confidence: number;
  timestamp: string;
  quality_warnings: string[];
  review_reason: string;
  suspicious_score: number;
};
type PerfTrend = { thresholds: { accuracy: number; f1: number }; points: { hour: string; accuracy: number; f1: number; labeled: number }[] };
type PerfSummary = {
  confusion_matrix: Record<string, Record<string, number>>;
  per_class: { class: string; precision: number; recall: number; f1: number; support: number }[];
  coverage: { labeled: number; unlabeled: number };
  warning: string;
};

type ToastItem = {
  id: number;
  text: string;
  kind: "alert" | "info";
};

const ratioTooltipFormatter = ((value: number | string | readonly (number | string)[] | undefined, name?: string) => {
  const numeric = Number(Array.isArray(value) ? value[0] : value ?? 0);
  return [`${numeric.toFixed(1)}%`, String(name ?? "")];
}) as unknown as TooltipProps<number, string>["formatter"];

const uiStyles = `
  :root {
    --bg: #fff8ef;
    --panel: rgba(255, 252, 247, 0.94);
    --panel-border: rgba(15, 23, 42, 0.14);
    --card: linear-gradient(145deg, rgba(255,255,255,0.95), rgba(255,247,235,0.95));
    --text-main: #0f172a;
    --muted: #475569;
  }

  .kpi-card, .panel-block, .list-card {
    transition: transform 200ms ease, box-shadow 220ms ease, border-color 200ms ease;
  }
  .kpi-card:hover, .list-card:hover {
    transform: translateY(-4px);
    box-shadow: 0 16px 32px rgba(12, 74, 110, 0.12);
  }
  .panel-block:hover {
    transform: translateY(-2px);
    box-shadow: 0 20px 40px rgba(30, 41, 59, 0.12);
    border-color: rgba(14, 116, 144, 0.24);
  }
  .badge-live {
    animation: pulse 2.5s ease-in-out infinite;
  }
  @keyframes pulse {
    0% { box-shadow: 0 0 0 0 rgba(34,197,94,0.4); }
    70% { box-shadow: 0 0 0 14px rgba(34,197,94,0); }
    100% { box-shadow: 0 0 0 0 rgba(34,197,94,0); }
  }
  .fade-in {
    animation: fadeUp 320ms ease;
  }
  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(6px); }
    to { opacity: 1; transform: translateY(0); }
  }

  .pulse-line {
    filter: drop-shadow(0 0 6px rgba(15,118,110,0.24));
  }
`;

function App() {
  const [kpi, setKpi] = useState<KPI | null>(null);
  const [confTrend, setConfTrend] = useState<ConfidenceTrend | null>(null);
  const [classRatio, setClassRatio] = useState<ClassRatioPoint[]>([]);
  const [driftTrend, setDriftTrend] = useState<DriftTrend | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [alertPage, setAlertPage] = useState<number>(0);
  const [reviewQueue, setReviewQueue] = useState<ReviewItem[]>([]);
  const [reviewPage, setReviewPage] = useState<number>(0);
  const [assignedLabels, setAssignedLabels] = useState<Record<number, string>>({});
  const [perfTrend, setPerfTrend] = useState<PerfTrend | null>(null);
  const [perfSummary, setPerfSummary] = useState<PerfSummary | null>(null);
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const seenUnresolvedAlertIdsRef = useRef<Set<number>>(new Set());

  const pushToast = (text: string, kind: "alert" | "info" = "info") => {
    const toastId = Date.now() + Math.floor(Math.random() * 1000);
    setToasts((prev) => [...prev, { id: toastId, text, kind }]);
    window.setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== toastId));
    }, 4500);
  };

  useEffect(() => {
    let cancelled = false;
    async function fetchAll() {
      setLoading(true);
      setError(null);
      try {
        const [kpiRes, confRes, classRes, driftRes, alertsRes, reviewRes, perfTrendRes, perfSummaryRes] = await Promise.all([
          fetchJson<KPI>(`${API}/kpi`),
          fetchJson<ConfidenceTrend>(`${API}/confidence-trend`),
          fetchJson<ClassRatioPoint[]>(`${API}/class-ratio`),
          fetchJson<DriftTrend>(`${API}/drift-trend`),
          fetchJson<Alert[]>(`${API}/alerts`),
          fetchJson<ReviewItem[]>(`${API}/review-queue`),
          fetchJson<PerfTrend>(`${API}/performance/metrics-over-time`),
          fetchJson<PerfSummary>(`${API}/performance/summary`),
        ]);

        if (!cancelled) {
          setKpi(kpiRes);
          setConfTrend(confRes);
          setClassRatio(classRes);
          setDriftTrend(driftRes);
          setAlerts(alertsRes.filter((a) => !a.resolved));
          setReviewQueue(reviewRes);
          setPerfTrend(perfTrendRes);
          setPerfSummary(perfSummaryRes);
          seenUnresolvedAlertIdsRef.current = new Set(alertsRes.filter((a) => !a.resolved).map((a) => a.id));
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message || "Failed to load data");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetchAll();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let stopped = false;
    const intervalId = window.setInterval(async () => {
      try {
        const [kpiRes, alertsRes] = await Promise.all([fetchJson<KPI>(`${API}/kpi`), fetchJson<Alert[]>(`${API}/alerts`)]);
        if (stopped) return;

        setKpi(kpiRes);
        setAlerts(alertsRes.filter((a) => !a.resolved));

        const latestUnresolved = alertsRes.filter((a) => !a.resolved);
        const nextSeen = new Set(seenUnresolvedAlertIdsRef.current);
        for (const alert of latestUnresolved) {
          if (!nextSeen.has(alert.id)) {
            pushToast(`ALERT: ${alert.alert_type.replaceAll("_", " ")} - ${alert.message}`, "alert");
          }
          nextSeen.add(alert.id);
        }
        seenUnresolvedAlertIdsRef.current = nextSeen;
      } catch {
        // ignore polling errors to keep dashboard responsive
      }
    }, 20000);

    return () => {
      stopped = true;
      window.clearInterval(intervalId);
    };
  }, []);

  useEffect(() => {
    const total = Math.max(1, Math.ceil(reviewQueue.length / REVIEW_PAGE_SIZE));
    if (reviewPage > total - 1) setReviewPage(0);
  }, [reviewQueue, reviewPage]);

  useEffect(() => {
    const total = Math.max(1, Math.ceil(alerts.length / ALERT_PAGE_SIZE));
    if (alertPage > total - 1) setAlertPage(0);
  }, [alerts, alertPage]);

  const handleResolve = async (id: number) => {
    try {
      const resolvedAlert = alerts.find((alert) => alert.id === id);
      await fetch(`${API}/alerts/${id}/resolve`, { method: "POST" });
      setAlerts((prev) => prev.filter((a) => a.id !== id));
      seenUnresolvedAlertIdsRef.current.delete(id);
      setKpi((prev) => (prev ? { ...prev, active_alerts: Math.max(0, prev.active_alerts - 1) } : prev));
      if (resolvedAlert) {
        pushToast(`Resolved alert: ${resolvedAlert.alert_type.replaceAll("_", " ")}`, "info");
      } else {
        pushToast(`Resolved alert #${id}`, "info");
      }
    } catch (e) {
      setError((e as Error).message || "Failed to resolve alert");
    }
  };

  const kpiCards = useMemo(
    () => [
      {
        title: "Drift Status",
        value: kpi?.drift_status ?? "-",
        accent: kpi?.drift_status === "ปกติ" ? "#0f766e" : "#dc2626",
        sub: kpi?.drift_status === "ปกติ" ? "Stable" : "Investigate",
      },
      { title: "Low Confidence Rate (24h)", value: kpi ? formatPercent(kpi.low_confidence_rate) : "-", accent: "#0ea5e9", sub: "conf < 0.6" },
      { title: "Total Requests Today", value: kpi ? formatNumber(kpi.total_requests_today) : "-", accent: "#1d4ed8", sub: "requests" },
      { title: "Active Alerts", value: kpi ? formatNumber(kpi.active_alerts) : "-", accent: kpi && kpi.active_alerts ? "#d97706" : "#64748b", sub: "unresolved" },
    ],
    [kpi],
  );

  const totalReviewPages = Math.max(1, Math.ceil(reviewQueue.length / REVIEW_PAGE_SIZE));
  const pagedReviews = reviewQueue.slice(reviewPage * REVIEW_PAGE_SIZE, reviewPage * REVIEW_PAGE_SIZE + REVIEW_PAGE_SIZE);
  const changeReviewPage = (delta: number) => {
    setReviewPage((prev) => Math.min(Math.max(0, prev + delta), totalReviewPages - 1));
  };

  const totalAlertPages = Math.max(1, Math.ceil(alerts.length / ALERT_PAGE_SIZE));
  const pagedAlerts = alerts.slice(alertPage * ALERT_PAGE_SIZE, alertPage * ALERT_PAGE_SIZE + ALERT_PAGE_SIZE);
  const changeAlertPage = (delta: number) => {
    setAlertPage((prev) => Math.min(Math.max(0, prev + delta), totalAlertPages - 1));
  };

  const driftPoints = useMemo(
    () => (driftTrend?.points ?? []).map((p) => ({ ...p, x: p.timestamp })),
    [driftTrend],
  );

  const confidenceChartPoints = useMemo(
    () =>
      (confTrend?.points ?? []).map((p, idx, arr) => ({
        ...p,
        hoverLabel: formatRelativeBangkokHourLabel(idx, arr.length),
      })),
    [confTrend],
  );

  const classRatioChartPoints = useMemo(
    () =>
      classRatio.map((p, idx, arr) => ({
        ...p,
        hoverLabel: formatRelativeBangkokHourLabel(idx, arr.length),
      })),
    [classRatio],
  );

  const perfTrendChartPoints = useMemo(
    () =>
      (perfTrend?.points ?? []).map((p) => ({
        ...p,
        hoverLabel: formatPerfHourLabel(p.hour),
      })),
    [perfTrend],
  );

  const handleLabel = async (id: number, label: string) => {
    try {
      const res = await fetch(`${API}/review-queue/${id}/label`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ true_label: label }),
      });
      if (!res.ok) {
        throw new Error(`Label API failed (${res.status})`);
      }
      await res.json();

      setAssignedLabels((prev) => ({ ...prev, [id]: label }));
      setReviewQueue((prev) => prev.filter((item) => item.id !== id));
      pushToast(`เลือก label สำหรับ #${id} เป็น ${label}`, "info");

      const [perfTrendRes, perfSummaryRes, kpiRes] = await Promise.all([
        fetchJson<PerfTrend>(`${API}/performance/metrics-over-time`),
        fetchJson<PerfSummary>(`${API}/performance/summary`),
        fetchJson<KPI>(`${API}/kpi`),
      ]);
      setPerfTrend(perfTrendRes);
      setPerfSummary(perfSummaryRes);
      setKpi(kpiRes);
    } catch (e) {
      setError((e as Error).message || "Failed to submit label");
    }
  };

  return (
    <div
      style={{
        minHeight: "100vh",
        background:
          "radial-gradient(115% 120% at 12% 0%, rgba(16,185,129,0.2), transparent 58%), radial-gradient(95% 100% at 100% 0%, rgba(245,158,11,0.2), transparent 54%), linear-gradient(180deg, #fff8ef 0%, #fffdfa 100%)",
        color: "#0f172a",
        padding: "40px 32px 72px",
        fontFamily: "'Manrope', 'Avenir Next', system-ui, -apple-system, sans-serif",
      }}
    >
      <style>{uiStyles}</style>
      <div style={{ maxWidth: 1440, margin: "0 auto", display: "flex", flexDirection: "column", gap: 18 }}>
        {loading && (
          <div style={{ padding: "10px 12px", background: "#ecfeff", border: "1px solid #99f6e4", borderRadius: 12, color: "#134e4a" }} className="fade-in">
            Loading fresh monitoring data...
          </div>
        )}
        {error && (
          <div style={{ padding: "10px 12px", background: "#fef2f2", border: "1px solid #fca5a5", color: "#991b1b", borderRadius: 12 }} className="fade-in">
            {error}
          </div>
        )}

        <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 30, fontWeight: 800, letterSpacing: "-0.02em" }}>ML Monitoring Dashboard</h1>
            <p style={{ margin: 0, color: "#475569", fontSize: 15 }}>Quality, drift, and performance at a glance</p>
          </div>
          <div style={{ display: "flex", gap: 10 }}>
            <Badge color="#0f766e" text="Last 24h" />
          </div>
        </header>

        {toasts.length > 0 && (
          <div style={{ position: "fixed", top: 20, right: 20, display: "grid", gap: 10, zIndex: 1200, maxWidth: 420 }}>
            {toasts.map((toast) => (
              <div
                key={toast.id}
                style={{
                  background: toast.kind === "alert" ? "linear-gradient(145deg, #fca5a5, #ef4444)" : "linear-gradient(145deg, #99f6e4, #5eead4)",
                  border: toast.kind === "alert" ? "1px solid #dc2626" : "1px solid #0f766e",
                  color: toast.kind === "alert" ? "#450a0a" : "#042f2e",
                  padding: "12px 14px",
                  borderRadius: 12,
                  boxShadow: "0 14px 34px rgba(15,23,42,0.12)",
                  fontSize: 13,
                  lineHeight: 1.45,
                  fontWeight: 700,
                }}
              >
                {toast.text}
              </div>
            ))}
          </div>
        )}

        <Grid cols={4}>
          {kpiCards.map((c) => (
            <Card key={c.title} title={c.title} value={c.value} color={c.accent} sub={c.sub} className="kpi-card" />
          ))}
        </Grid>

        <div style={{ marginBottom: 20 }}>
          <Panel title="Confidence Over Time" className="panel-block">
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={confidenceChartPoints}>
                <CartesianGrid strokeDasharray="3 3" stroke="#cbd5e1" />
                <XAxis dataKey="hour" stroke="#64748b" />
                <YAxis domain={[0, 1]} stroke="#64748b" />
                <Tooltip labelFormatter={tooltipHoverDateLabel} />
                <Legend />
                <Line type="monotone" dataKey="avg_confidence" stroke="#0ea5a4" strokeWidth={3} dot={false} />
                <ReferenceLine y={confTrend?.threshold ?? 0.6} stroke="#ea580c" strokeDasharray="5 5" />
              </LineChart>
            </ResponsiveContainer>
          </Panel>
        </div>

        <div style={{ marginBottom: 20 }}>
          <Panel title="Class Ratio Over Time" className="panel-block">
            <ResponsiveContainer width="100%" height={300}>
              <AreaChart data={classRatioChartPoints} stackOffset="expand">
                <CartesianGrid strokeDasharray="3 3" stroke="#cbd5e1" />
                <XAxis dataKey="hour" stroke="#64748b" />
                <YAxis tickFormatter={(v) => `${(v * 100).toFixed(0)}%`} stroke="#64748b" />
                {/* @ts-expect-error Recharts formatter typing is narrower than runtime payloads */}
                <Tooltip formatter={ratioTooltipFormatter} labelFormatter={tooltipHoverDateLabel} />
                <Legend />
                <Area type="monotone" dataKey="beverages" stackId="1" stroke="#14b8a6" fill="#14b8a6" fillOpacity={0.7} />
                <Area type="monotone" dataKey="snacks" stackId="1" stroke="#f59e0b" fill="#f59e0b" fillOpacity={0.65} />
              </AreaChart>
            </ResponsiveContainer>
          </Panel>
        </div>

        <div style={{ marginBottom: 20 }}>
          <Panel title="Drift Score Trend" className="panel-block">
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={driftPoints}>
                <CartesianGrid strokeDasharray="3 3" stroke="#cbd5e1" />
                <XAxis dataKey="x" stroke="#64748b" tickFormatter={(value) => formatTime(String(value))} />
                <YAxis stroke="#64748b" />
                <Tooltip
                  labelFormatter={(label) => formatDateTime(String(label))}
                  formatter={(v) => (typeof v === "number" ? v.toFixed(4) : v)}
                />
                <Legend />
                <Line type="monotone" dataKey="embedding_score" stroke="#f97316" />
                <Line type="monotone" dataKey="confidence_score" stroke="#0284c7" />
                <Line type="monotone" dataKey="class_score" stroke="#0f766e" />
                <ReferenceLine y={driftTrend?.thresholds.embedding ?? 0.5} stroke="#f97316" strokeDasharray="4 4" />
                <ReferenceLine y={driftTrend?.thresholds.confidence ?? 0.5} stroke="#0284c7" strokeDasharray="4 4" />
                <ReferenceLine y={driftTrend?.thresholds.class ?? 0.5} stroke="#0f766e" strokeDasharray="4 4" />
              </LineChart>
            </ResponsiveContainer>
          </Panel>
        </div>

        <div style={{ marginBottom: 20 }}>
          <Panel title="Accuracy & F1 Over Time" className="panel-block">
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={perfTrendChartPoints}>
                <CartesianGrid strokeDasharray="3 3" stroke="#cbd5e1" />
                <XAxis dataKey="hour" stroke="#64748b" />
                <YAxis domain={[0, 1]} stroke="#64748b" />
                <Tooltip labelFormatter={tooltipHoverDateLabel} />
                <Legend />
                <Line type="monotone" dataKey="accuracy" stroke="#0f766e" strokeWidth={3} dot={false} />
                <Line type="monotone" dataKey="f1" stroke="#1d4ed8" />
                <ReferenceLine y={perfTrend?.thresholds.accuracy ?? 0.8} stroke="#0f766e" strokeDasharray="4 4" />
                <ReferenceLine y={perfTrend?.thresholds.f1 ?? 0.8} stroke="#1d4ed8" strokeDasharray="4 4" />
              </LineChart>
            </ResponsiveContainer>
          </Panel>
        </div>

      <Grid cols={2}>
          <Panel title="Review Queue" className="panel-block">
          <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
            {pagedReviews.map((r) => (
              <div
                key={r.id}
                className="list-card"
                style={{
                  background: "linear-gradient(160deg, rgba(255,255,255,0.98), rgba(255,247,237,0.98))",
                  border: "1px solid rgba(14,116,144,0.18)",
                  borderRadius: 12,
                  overflow: "hidden",
                  boxShadow: "0 12px 30px rgba(15,23,42,0.08)",
                  minHeight: 200,
                  display: "flex",
                  flexDirection: "column",
                }}
              >
                <div style={{ height: 120, background: "linear-gradient(135deg, #ecfeff, #fef3c7)", display: "flex", alignItems: "center", justifyContent: "center", color: "#334155", fontSize: 12, fontWeight: 700 }}>
                  Suspicious request
                </div>
                <div style={{ padding: 12, display: "flex", flexDirection: "column", gap: 6, flex: 1 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                    <span style={{ fontWeight: 700 }}>ID #{r.id}</span>
                    <span style={{ color: "#64748b", fontSize: 12 }}>{formatDate(r.timestamp)}</span>
                  </div>
                  <div>
                    Pred: <strong>{r.predicted_class}</strong> ({(r.confidence * 100).toFixed(1)}%)
                  </div>
                  <div style={{ color: "#475569", fontSize: 12, lineHeight: 1.4 }}>
                    {r.review_reason || "Low-confidence or image-quality review"}
                  </div>
                  {assignedLabels[r.id] && (
                    <div
                      style={{
                        alignSelf: "flex-start",
                        padding: "4px 8px",
                        borderRadius: 999,
                        background: "rgba(15,118,110,0.1)",
                        border: "1px solid rgba(15,118,110,0.35)",
                        color: "#0f766e",
                        fontSize: 12,
                        fontWeight: 700,
                      }}
                    >
                      labeled: {assignedLabels[r.id]}
                    </div>
                  )}
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <span style={{ padding: "4px 8px", borderRadius: 999, background: "rgba(2,132,199,0.12)", color: "#0369a1", fontSize: 12, fontWeight: 700 }}>
                      suspicious {r.suspicious_score.toFixed(2)}
                    </span>
                    {r.quality_warnings.map((warning) => (
                      <span key={warning} style={{ padding: "4px 8px", borderRadius: 999, background: "rgba(251,146,60,0.15)", color: "#9a3412", fontSize: 12, fontWeight: 700 }}>
                        {warning}
                      </span>
                    ))}
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    {(() => {
                      const current = assignedLabels[r.id];
                      return (
                        <>
                          <button
                            onClick={() => handleLabel(r.id, "beverages")}
                            style={{
                              flex: 1,
                              padding: "8px 10px",
                              borderRadius: 8,
                              border: current === "beverages" ? "1px solid #0f766e" : "1px solid rgba(100,116,139,0.35)",
                              background: current === "beverages" ? "rgba(15,118,110,0.12)" : "#ffffff",
                              color: "#0f172a",
                              cursor: "pointer",
                              fontWeight: 700,
                            }}
                          >
                            beverages
                          </button>
                          <button
                            onClick={() => handleLabel(r.id, "snacks")}
                            style={{
                              flex: 1,
                              padding: "8px 10px",
                              borderRadius: 8,
                              border: current === "snacks" ? "1px solid #d97706" : "1px solid rgba(100,116,139,0.35)",
                              background: current === "snacks" ? "rgba(217,119,6,0.12)" : "#ffffff",
                              color: "#0f172a",
                              cursor: "pointer",
                              fontWeight: 700,
                            }}
                          >
                            snacks
                          </button>
                        </>
                      );
                    })()}
                  </div>
                  <div style={{ color: "#475569", fontSize: 12 }}>
                    warnings: {r.quality_warnings.length ? r.quality_warnings.join(", ") : "none"}
                  </div>
                </div>
              </div>
            ))}
            {Array.from({ length: Math.max(0, REVIEW_PAGE_SIZE - pagedReviews.length) }).map((_, i) => (
              <div
                key={`placeholder-${i}`}
                style={{
                  border: "1px dashed rgba(148,163,184,0.3)",
                  borderRadius: 12,
                  minHeight: 200,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#64748b",
                  background: "rgba(255,255,255,0.7)",
                }}
              >
                No item
              </div>
            ))}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12 }}>
            <span style={{ color: "#475569", fontSize: 13 }}>Page {reviewPage + 1} / {totalReviewPages}</span>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={() => changeReviewPage(-1)}
                disabled={reviewPage === 0}
                style={{
                  padding: "8px 10px",
                  borderRadius: 8,
                  border: "1px solid rgba(100,116,139,0.35)",
                  background: reviewPage === 0 ? "#e2e8f0" : "#ffffff",
                  color: "#0f172a",
                  cursor: reviewPage === 0 ? "not-allowed" : "pointer",
                }}
              >
                Prev
              </button>
              <button
                onClick={() => changeReviewPage(1)}
                disabled={reviewPage >= totalReviewPages - 1}
                style={{
                  padding: "8px 10px",
                  borderRadius: 8,
                  border: "1px solid rgba(100,116,139,0.35)",
                  background: reviewPage >= totalReviewPages - 1 ? "#e2e8f0" : "#ffffff",
                  color: "#0f172a",
                  cursor: reviewPage >= totalReviewPages - 1 ? "not-allowed" : "pointer",
                }}
              >
                Next
              </button>
            </div>
          </div>
        </Panel>

        <Panel title="Alerts" className="panel-block">
          <div style={{ display: "grid", gap: 12, gridTemplateColumns: "repeat(2, minmax(0, 1fr))" }}>
            {pagedAlerts.map((a) => (
              <div
                key={a.id}
                className="list-card"
                style={{
                  background: "linear-gradient(150deg, rgba(255,255,255,0.98), rgba(255,244,230,0.96))",
                  border: "1px solid rgba(14,116,144,0.18)",
                  borderRadius: 12,
                  padding: 14,
                  display: "flex",
                  flexDirection: "column",
                  gap: 10,
                  minHeight: 150,
                  boxShadow: "0 12px 30px rgba(15,23,42,0.08)",
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 10 }}>
                  <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                    <div style={{ fontWeight: 800, fontSize: 15 }}>{a.alert_type.replaceAll("_", " ")}</div>
                    <div style={{ color: "#64748b", fontSize: 12 }}>{formatDate(a.timestamp)}</div>
                  </div>
                  <div>
                    <button
                      onClick={() => handleResolve(a.id)}
                      style={{
                        background: a.resolved ? "#e2e8f0" : "#0f766e",
                        color: a.resolved ? "#64748b" : "#f8fafc",
                        border: "none",
                        padding: "8px 12px",
                        borderRadius: 999,
                        cursor: a.resolved ? "default" : "pointer",
                        minWidth: 94,
                        fontWeight: 700,
                      }}
                      disabled={a.resolved}
                    >
                      {a.resolved ? "Resolved" : "Resolve"}
                    </button>
                  </div>
                </div>
                <div style={{ color: "#334155", fontSize: 13, lineHeight: 1.5, flex: 1 }}>
                  {a.message}
                </div>
              </div>
            ))}
            {Array.from({ length: Math.max(0, ALERT_PAGE_SIZE - pagedAlerts.length) }).map((_, i) => (
              <div
                key={`alert-placeholder-${i}`}
                style={{
                  border: "1px dashed rgba(148,163,184,0.3)",
                  borderRadius: 12,
                  minHeight: 120,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  color: "#64748b",
                  background: "rgba(255,255,255,0.7)",
                }}
              >
                No alert
              </div>
            ))}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 12 }}>
            <span style={{ color: "#475569", fontSize: 13 }}>Page {alertPage + 1} / {totalAlertPages}</span>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={() => changeAlertPage(-1)}
                disabled={alertPage === 0}
                style={{
                  padding: "8px 10px",
                  borderRadius: 8,
                  border: "1px solid rgba(100,116,139,0.35)",
                  background: alertPage === 0 ? "#e2e8f0" : "#ffffff",
                  color: "#0f172a",
                  cursor: alertPage === 0 ? "not-allowed" : "pointer",
                }}
              >
                Prev
              </button>
              <button
                onClick={() => changeAlertPage(1)}
                disabled={alertPage >= totalAlertPages - 1}
                style={{
                  padding: "8px 10px",
                  borderRadius: 8,
                  border: "1px solid rgba(100,116,139,0.35)",
                  background: alertPage >= totalAlertPages - 1 ? "#e2e8f0" : "#ffffff",
                  color: "#0f172a",
                  cursor: alertPage >= totalAlertPages - 1 ? "not-allowed" : "pointer",
                }}
              >
                Next
              </button>
            </div>
          </div>
        </Panel>
      </Grid>

      <div style={{ marginBottom: 20 }}>
        <Panel title="Labeled vs Unlabeled" className="panel-block">
          <ResponsiveContainer width="100%" height={280}>
            <BarChart
              data={
                perfSummary
                  ? [
                      { name: "Labeled", value: perfSummary.coverage.labeled },
                      { name: "Unlabeled", value: perfSummary.coverage.unlabeled },
                    ]
                  : []
              }
              barCategoryGap="60%"
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#cbd5e1" />
              <XAxis dataKey="name" stroke="#64748b" />
              <YAxis stroke="#64748b" />
              <Tooltip />
              <Bar dataKey="value" radius={[4, 4, 0, 0]} barSize={42}>
                <Cell fill="#0f766e" />
                <Cell fill="#ea580c" />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <div style={{ display: "flex", gap: 14, alignItems: "center", justifyContent: "center", marginTop: 10, color: "#475569", fontSize: 13, fontWeight: 700 }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 12, height: 12, borderRadius: 999, background: "#0f766e", display: "inline-block" }} />
              Labeled
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 12, height: 12, borderRadius: 999, background: "#ea580c", display: "inline-block" }} />
              Unlabeled
            </span>
          </div>
        </Panel>
      </div>

      <Grid cols={2}>
        <Panel title="Confusion Matrix" className="panel-block">
          {perfSummary && <CMTable cm={perfSummary.confusion_matrix} />}
        </Panel>

        <Panel title="Per-Class Performance" className="panel-block">
          <div style={{ display: "grid", gap: 8 }}>
            {perfSummary?.per_class.map((c) => (
              <div
                key={c.class}
                className="list-card"
                style={{
                  background: "linear-gradient(160deg, rgba(255,255,255,0.95), rgba(254,242,232,0.9))",
                  border: "1px solid rgba(14,116,144,0.16)",
                  borderRadius: 10,
                  padding: 12,
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <div style={{ fontWeight: 700 }}>{c.class}</div>
                <div style={{ color: "#475569", fontSize: 14 }}>
                  P {c.precision} | R {c.recall} | F1 {c.f1} (n={c.support})
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </Grid>

      <Panel title="Warning">
        <div
          style={{
            background: "#fffbeb",
            color: "#92400e",
            padding: 14,
            borderRadius: 12,
            border: "1px solid #fbbf24",
            whiteSpace: "pre-line",
          }}
        >
          {perfSummary?.warning ?? "No data available yet"}
        </div>
      </Panel>
      </div>
    </div>
  );
}

function Badge({ color, text, pulse }: { color: string; text: string; pulse?: boolean }) {
  return (
    <span
      className={pulse ? "badge-live" : undefined}
      style={{
        background: `${color}22`,
        color,
        border: `1px solid ${color}44`,
        padding: "6px 10px",
        borderRadius: 999,
        fontSize: 12,
        fontWeight: 700,
      }}
    >
      {text}
    </span>
  );
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json();
}

function Grid({ cols, children }: { cols: number; children: React.ReactNode }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(auto-fit, minmax(${cols === 4 ? 200 : cols === 3 ? 260 : 320}px, 1fr))`,
        gap: 18,
        marginBottom: 20,
      }}
    >
      {children}
    </div>
  );
}

function Card({ title, value, color = "#0f172a", sub, className }: { title: string; value: string | number; color?: string; sub?: string; className?: string }) {
  return (
    <div
      className={className}
      style={{
        background: "linear-gradient(150deg, rgba(255,255,255,0.98), rgba(255,248,240,0.95))",
        border: "1px solid rgba(14,116,144,0.16)",
        padding: 20,
        borderRadius: 18,
        boxShadow: "0 16px 34px rgba(15,23,42,0.08)",
      }}
    >
      <div style={{ color: "#64748b", fontSize: 13, marginBottom: 6 }}>{title}</div>
      <div style={{ fontSize: 32, fontWeight: 800, color }}>{value}</div>
      {sub && <div style={{ color: "#475569", fontSize: 12, marginTop: 6 }}>{sub}</div>}
    </div>
  );
}

function Panel({ title, children, className }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div
      className={className}
      style={{
        background: "rgba(255,255,255,0.92)",
        border: "1px solid rgba(14,116,144,0.16)",
        borderRadius: 18,
        padding: 18,
        boxShadow: "0 18px 40px rgba(15,23,42,0.08)",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
        <h3 style={{ margin: 0, fontSize: 16, fontWeight: 800 }}>{title}</h3>
      </div>
      {children}
    </div>
  );
}

function CMTable({ cm }: { cm: Record<string, Record<string, number>> }) {
  const rows = [
    { label: "จริง beverages", bev: cm.beverages?.beverages ?? 0, snk: cm.beverages?.snacks ?? 0 },
    { label: "จริง snacks", bev: cm.snacks?.beverages ?? 0, snk: cm.snacks?.snacks ?? 0 },
  ];
  return (
    <div style={{ borderRadius: 12, overflow: "hidden", border: "1px solid rgba(148,163,184,0.2)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr 1fr", background: "#ecfeff", padding: "8px 10px", fontWeight: 700 }}>
        <div />
        <div style={{ textAlign: "center" }}>ทำนาย beverages</div>
        <div style={{ textAlign: "center" }}>ทำนาย snacks</div>
      </div>
      {rows.map((r) => (
        <div
          key={r.label}
          style={{
            display: "grid",
            gridTemplateColumns: "1.2fr 1fr 1fr",
            padding: "10px",
            background: "#ffffff",
            borderTop: "1px solid rgba(148,163,184,0.1)",
          }}
        >
          <div style={{ color: "#334155" }}>{r.label}</div>
          <div style={{ textAlign: "center", fontWeight: 700 }}>{r.bev}</div>
          <div style={{ textAlign: "center", fontWeight: 700 }}>{r.snk}</div>
        </div>
      ))}
    </div>
  );
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function formatNumber(value: number) {
  return value.toLocaleString();
}

function formatDate(ts: string) {
  try {
    const d = parseBangkokDate(ts);
    if (Number.isNaN(d.getTime())) return ts;
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Bangkok",
      day: "numeric",
      month: "short",
      year: "numeric",
    }).format(d);
  } catch {
    return ts;
  }
}

function formatTime(ts: string) {
  try {
    const d = parseBangkokDate(ts);
    if (Number.isNaN(d.getTime())) return "";
    return new Intl.DateTimeFormat("en-GB", {
      timeZone: "Asia/Bangkok",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(d);
  } catch {
    return "";
  }
}

function formatDateTime(ts: string) {
  const date = formatDate(ts);
  const time = formatTime(ts);
  return time ? `${date} ${time}` : date;
}

function formatBangkokDateTime(date: Date) {
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Bangkok",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatRelativeBangkokHourLabel(index: number, total: number) {
  if (total <= 0) return "";
  const now = new Date();
  const bangkokNow = new Date(
    now.toLocaleString("sv-SE", {
      timeZone: "Asia/Bangkok",
      hour12: false,
    }).replace(" ", "T") + "+07:00",
  );
  bangkokNow.setMinutes(0, 0, 0);
  const target = new Date(bangkokNow.getTime() - (total - 1 - index) * 60 * 60 * 1000);
  return formatBangkokDateTime(target);
}

function formatPerfHourLabel(value: string) {
  const match = value.match(/^(\d{2})-(\d{2})\s(\d{2}):(\d{2})$/);
  if (!match) return value;

  const month = Number(match[1]);
  const day = Number(match[2]);
  const hour = Number(match[3]);
  const minute = Number(match[4]);
  const year = new Date().getFullYear();
  const date = new Date(`${year}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}T${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}:00+07:00`);
  if (Number.isNaN(date.getTime())) return value;

  return formatBangkokDateTime(date);
}

function tooltipHoverDateLabel(label: React.ReactNode, payload?: ReadonlyArray<{ payload?: { hoverLabel?: string } }>) {
  const hoverLabel = payload?.[0]?.payload?.hoverLabel;
  if (hoverLabel) return hoverLabel;
  if (typeof label === "string" || typeof label === "number") return String(label);
  return "";
}

function parseBangkokDate(ts: string) {
  if (ts.includes("+") || ts.endsWith("Z")) {
    return new Date(ts);
  }
  const normalized = ts.includes("T") ? ts : ts.replace(" ", "T");
  return new Date(`${normalized}+07:00`);
}

export default App;