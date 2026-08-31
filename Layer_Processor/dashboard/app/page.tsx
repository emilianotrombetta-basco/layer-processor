"use client";

import { geoMercator, geoPath } from "d3-geo";
import { useCallback, useEffect, useMemo, useState } from "react";

const API = "http://127.0.0.1:8765";

function hostOf(url?: string): string {
  if (!url) return "";
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

function faviconOf(url?: string): string {
  const host = hostOf(url);
  return host
    ? `https://www.google.com/s2/favicons?domain=${host}&sz=64`
    : "";
}

function monogram(key: string): string {
  return key.replace(/^[a-z]_/, "").slice(0, 2).toUpperCase() || "··";
}

const checkLabels: Record<string, string> = {
  ok: "Online",
  degradato: "Parziale",
  errore: "Offline",
  senza_link: "No link",
  "…": "Verifico…",
};
const SOURCE_BATCH_DEFAULTS: Record<string, number> = {
  "01": 25,
  "02": 5,
  "03": 2,
  "07": 25,
};

type Scope = {
  level: "region" | "province" | "municipality";
  key: string;
  name: string;
};

type Stage = {
  id: string;
  number: string;
  name: string;
  description: string;
  output: string;
  available: boolean;
  status: string;
  detail?: string;
  errors?: string[];
  targets?: {
    key: string;
    title?: string;
    name?: string;
    state?: "assente" | "presente" | "parziale" | "da_aggiornare";
    features?: number | null;
    stale_sources?: string[];
  }[];
  target_counts?: Record<string, number>;
  final_layers?: number;
  viewer_available?: boolean;
  recommended_batch_size?: number;
};

type CallStatus = {
  id: string;
  label: string;
  status: "running" | "completed" | "failed" | "skipped";
  current?: number;
  total?: number | null;
  items?: number;
  error?: string;
};

type Job = {
  id: string;
  label: string;
  stage: string;
  scope: Scope;
  status: "running" | "completed" | "failed" | "cancelled";
  progress: number;
  current: number;
  total: number;
  elapsed_seconds?: number;
  finished_at?: string | null;
  logs: string[];
  result?: {
    status?: string;
    message?: string;
    maps?: number;
    services?: number;
    layers?: number;
    downloadable_layers?: number;
    failed_maps?: number;
    layers_downloaded?: number;
    layers_failed?: number;
    error?: string;
  } | null;
  calls?: CallStatus[];
  call_counts?: Record<string, number>;
  calls_total?: number;
  calls_truncated?: boolean;
};

type Source = {
  key: string;
  name: string;
  url: string;
  data_url?: string;
  level: string;
  status: string;
  plan_types: string[];
  planning_instruments?: string[];
  links?: { label: string; url: string }[];
  kind?: string;
  adapter?: string;
  data_format?: string;
  expected_datasets?: number;
  downloaded_datasets?: number;
  download_status?: string;
  batch_size?: number;
  download_available?: boolean;
  resumable?: boolean;
  raw_path?: string;
  discover_command?: string;
  download_command?: string;
  notes?: string;
  relationship?: "diretta" | "sovraordinata" | "locale" | "nazionale";
};

type SourcesResponse = {
  scope: Scope;
  total: number;
  active: number;
  status_counts: Record<string, number>;
  sources: Source[];
};

type TerritoryMetrics = {
  source_count: number;
  active_source_count: number;
  final_layers: number;
  regulatory_coverage: number;
  pipeline_completion_pct: number;
  pipeline_completed_steps: number;
  pipeline_total_steps: number;
  pipeline_steps: {
    id: string;
    number: string;
    name: string;
    complete: boolean;
    detail: string;
  }[];
  child_count: number;
  municipality_count: number;
  process_available: boolean;
  sources: Source[];
};

type TerritoryFeature = {
  type: "Feature";
  properties: {
    key: string;
    name: string;
    sigla?: string;
    reg_key?: string;
    prov_key?: string;
    level: Scope["level"];
    metrics: TerritoryMetrics;
  };
  geometry: unknown;
};

type TerritoryResponse = {
  type: "FeatureCollection";
  level: Scope["level"];
  features: TerritoryFeature[];
  registry: {
    regions: number;
    provinces: number;
    municipalities_raw: number;
    geometry_provinces: number;
    geometry_municipalities: number;
  };
};

type DashboardData = {
  generated_at: string;
  scope: Scope;
  scope_summary: {
    available: boolean;
    recognized: number;
    unrecognized: number;
    total: number;
    coverage: number;
    last_run: string | null;
  };
  metrics: {
    canonical_classes: number;
    dictionary_rules: number;
  };
  stages: Stage[];
  job: Job | null;
  active_job: Job | null;
  history: Job[];
};

type FinalLayers = {
  type: "FeatureCollection";
  features: {
    type: "Feature";
    properties: Record<string, unknown>;
    geometry: unknown;
  }[];
  layers: { key: string; name: string; features: number; path: string }[];
  truncated: boolean;
  scope: Scope;
};

const statusLabels: Record<string, string> = {
  pronto: "Pronto",
  completato: "Completato",
  in_esecuzione: "In esecuzione",
  da_implementare: "Non ancora implementato",
  richiede_approvazione: "Richiede approvazione",
  catalogo_mancante: "Catalogo non configurato",
  autenticazione_richiesta: "Richiede autenticazione",
  da_avviare: "Da avviare",
  fallito: "Fallito",
  parziale: "Parziale",
  obiettivo_definito: "Obiettivo definito",
  da_aggiornare: "Da aggiornare",
};

const levelLabels: Record<Scope["level"], string> = {
  region: "Regione",
  province: "Provincia",
  municipality: "Comune",
};

const sourceStatusLabels: Record<string, string> = {
  active: "Attiva",
  metadata: "Solo metadati",
  dead: "Link da verificare",
  todo: "Da configurare",
};

const sourceLevelLabels: Record<string, string> = {
  regione: "Regionale",
  provincia: "Provinciale",
  comune: "Comunale",
  nazionale: "Nazionale",
};

const sourceInstrumentFallback: Record<string, string[]> = {
  r_piemon: ["PTR", "PPR", "PAI", "PRG", "PRGC"],
  r_vda: ["PTP", "PRG", "PRGC"],
  r_vda_prg_status: ["PTP", "PRG", "PRGC"],
  r_vda_prg_updates: ["PRG", "PRGC"],
  r_liguria: [
    "PTCP paesistico",
    "PPR",
    "PTR",
    "PTC",
    "PTM",
    "Piani di bacino",
    "PUC",
  ],
  p_to: ["PTC2"],
  p_bi: ["PTPv"],
  c_001272: ["PRG", "PRGC"],
  n_opencup: ["Programmazione opere pubbliche"],
  n_pnrr: ["PNRR"],
  n_opencoesione: ["Programmi di coesione"],
  n_pums: ["PUMS"],
  n_ainop: ["Opere pubbliche"],
};

function sourceInstruments(source: Source) {
  return source.planning_instruments?.length
    ? source.planning_instruments
    : sourceInstrumentFallback[source.key] ||
        source.plan_types.map((item) => item.toLocaleUpperCase("it"));
}

function sourceRelationship(
  sourceLevel: string,
  scopeLevel: Scope["level"],
): Source["relationship"] {
  if (sourceLevel === "nazionale") return "nazionale";
  const sourceRanks: Record<string, number> = {
    regione: 1,
    provincia: 2,
    comune: 3,
  };
  const scopeRanks: Record<Scope["level"], number> = {
    region: 1,
    province: 2,
    municipality: 3,
  };
  if (sourceRanks[sourceLevel] === scopeRanks[scopeLevel]) return "diretta";
  return sourceRanks[sourceLevel] < scopeRanks[scopeLevel]
    ? "sovraordinata"
    : "locale";
}

function formatDate(value: string | null) {
  if (!value) return "Mai";
  return new Intl.DateTimeFormat("it-IT", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function formatDuration(seconds?: number) {
  if (seconds === undefined) return "0s";
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
}

function metricValue(feature: TerritoryFeature) {
  return feature.properties.metrics.pipeline_completion_pct;
}

function mapFill(feature: TerritoryFeature) {
  const value = Math.max(0, Math.min(100, metricValue(feature)));
  if (value === 0) return "#e7ebe8";
  const ratio = value / 100;
  const start = [213, 229, 220];
  const end = [45, 117, 83];
  const rgb = start.map((channel, index) =>
    Math.round(channel + (end[index] - channel) * ratio),
  );
  return `rgb(${rgb.join(",")})`;
}

function ItalyMap({
  features,
  selectedKey,
  onSelect,
}: {
  features: TerritoryFeature[];
  selectedKey?: string;
  onSelect: (feature: TerritoryFeature) => void;
}) {
  const { paths, labels } = useMemo(() => {
    if (!features.length) return { paths: [], labels: [] };
    const collection = {
      type: "FeatureCollection",
      features,
    };
    const projection = geoMercator().fitExtent(
      [
        [18, 18],
        [582, 592],
      ],
      collection as never,
    );
    const generator = geoPath(projection);
    const paths = features.map((feature) => ({
      feature,
      d: generator(feature as never) || "",
    }));
    // Etichette con declutter: nomi accorciati (via lo "/" bilingue) + repulsione
    // fra riquadri sovrapposti, così i nomi non collidono.
    const lbls = features.map((feature) => {
      const c = generator.centroid(feature as never);
      const raw = (
        feature.properties.sigla || feature.properties.name.split("/")[0]
      ).trim();
      const name = raw.length > 19 ? `${raw.slice(0, 18)}…` : raw;
      return {
        feature,
        name,
        x: Number.isFinite(c[0]) ? c[0] : 0,
        y: Number.isFinite(c[1]) ? c[1] : 0,
        hw: Math.max(name.length * 1.7, 6),
        hh: 6.5,
      };
    });
    for (let pass = 0; pass < 80; pass += 1) {
      for (let i = 0; i < lbls.length; i += 1) {
        for (let j = i + 1; j < lbls.length; j += 1) {
          const a = lbls[i];
          const b = lbls[j];
          const dx = a.x - b.x;
          const dy = a.y - b.y;
          const ox = a.hw + b.hw - Math.abs(dx);
          const oy = a.hh + b.hh - Math.abs(dy);
          if (ox > 0 && oy > 0) {
            if (ox < oy) {
              const s = ((dx >= 0 ? 1 : -1) * ox) / 2;
              a.x += s;
              b.x -= s;
            } else {
              const s = ((dy >= 0 ? 1 : -1) * oy) / 2;
              a.y += s;
              b.y -= s;
            }
          }
        }
      }
    }
    return { paths, labels: lbls };
  }, [features]);

  return (
    <svg
      className="italy-map"
      viewBox="0 0 600 610"
      role="img"
      aria-label="Mappa interattiva dei territori italiani"
    >
      {paths.map(({ feature, d }) => (
        <path
          key={feature.properties.key}
          d={d}
          fill={mapFill(feature)}
          className={
            selectedKey === feature.properties.key ? "selected-shape" : ""
          }
          tabIndex={0}
          role="button"
          aria-label={`${feature.properties.name}: ${metricValue(feature)}% della pipeline completata`}
          onClick={() => onSelect(feature)}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") onSelect(feature);
          }}
        />
      ))}
      {features.length <= 25 &&
        labels.map(({ feature, x, y, name }) => (
          <text key={`label-${feature.properties.key}`} x={x} y={y}>
            <tspan x={x} dy="-0.15em">
              {name}
            </tspan>
            <tspan className="map-percentage" x={x} dy="1.15em">
              {metricValue(feature)}%
            </tspan>
          </text>
        ))}
    </svg>
  );
}

function finalFeatureColor(properties: Record<string, unknown>) {
  const signal = String(properties.signal || properties.semaforo || "").toUpperCase();
  if (signal === "RED") return "#b54d42";
  if (signal === "YELLOW") return "#d3a43a";
  if (signal === "GREEN") return "#438469";
  if (signal === "UNASSESSED") return "#a4aca8";
  const planStatus = String(properties.plan_status_code || "").toUpperCase();
  if (planStatus === "APPROVATO") return "#39755f";
  if (planStatus === "APPROVATO_CARTOGRAFIA_IN_CONSEGNA") return "#72a48c";
  if (planStatus === "DEFINITIVO_IN_VALUTAZIONE") return "#d3a43a";
  if (planStatus === "BOZZA_VALUTATA") return "#d58a46";
  if (planStatus === "BOZZA_IN_VALUTAZIONE") return "#c96d48";
  if (planStatus === "ITER_NON_AVVIATO") return "#a9584d";
  if (planStatus === "NON_DETERMINATO") return "#a4aca8";
  const severity = String(properties.severity || "").toLowerCase();
  if (severity === "blocking") return "#b54d42";
  if (severity === "conditional") return "#d3a43a";
  if (severity === "informative") return "#5d7f9e";
  return "#6f8d80";
}

function FinalLayerMap({ data }: { data: FinalLayers }) {
  const paths = useMemo(() => {
    if (!data.features.length) return [];
    const collection = { type: "FeatureCollection", features: data.features };
    const projection = geoMercator().fitExtent(
      [
        [20, 20],
        [680, 410],
      ],
      collection as never,
    );
    const generator = geoPath(projection);
    return data.features.map((feature, index) => ({
      key: `${String(feature.properties._final_target || "layer")}-${index}`,
      d: generator(feature as never) || "",
      fill: finalFeatureColor(feature.properties),
      label: String(
        feature.properties.comune ||
          feature.properties.constraint_name ||
          feature.properties.signal ||
          "Elemento",
      ),
    }));
  }, [data]);

  return (
    <svg
      className="final-layer-map"
      viewBox="0 0 700 430"
      role="img"
      aria-label={`Layer finali per ${data.scope.name}`}
    >
      {paths.map((item) => (
        <path key={item.key} d={item.d} fill={item.fill}>
          <title>{item.label}</title>
        </path>
      ))}
    </svg>
  );
}

export default function Home() {
  const [tab, setTab] = useState<
    "processes" | "territory" | "sources" | "coverage"
  >("processes");
  const [scope, setScope] = useState<Scope>({
    level: "region",
    key: "01",
    name: "Piemonte",
  });
  const [data, setData] = useState<DashboardData | null>(null);
  const [regions, setRegions] = useState<TerritoryFeature[]>([]);
  const [provinces, setProvinces] = useState<TerritoryFeature[]>([]);
  const [municipalities, setMunicipalities] = useState<TerritoryFeature[]>([]);
  const [registry, setRegistry] = useState<TerritoryResponse["registry"] | null>(
    null,
  );
  const [regionKey, setRegionKey] = useState("01");
  const [provinceKey, setProvinceKey] = useState("");
  const [municipalityQuery, setMunicipalityQuery] = useState("");
  const [mapLevel, setMapLevel] = useState<"region" | "province">("region");
  const [selectedTerritory, setSelectedTerritory] =
    useState<TerritoryFeature | null>(null);
  const [force, setForce] = useState(false);
  const [busy, setBusy] = useState(false);
  const [offline, setOffline] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [conflictJob, setConflictJob] = useState<Job | null>(null);
  const [expandedErrors, setExpandedErrors] = useState<Set<string>>(
    () => new Set(),
  );
  const [finalLayers, setFinalLayers] = useState<FinalLayers | null>(null);
  const [callFilter, setCallFilter] = useState<
    "all" | "running" | "completed" | "failed" | "skipped"
  >("all");
  // Un catalogo territoriale può pesare decine di GB: il primo click usa un
  // batch prudente. "Tutte" resta disponibile come scelta esplicita.
  const [batchSize, setBatchSize] = useState(25);
  const [onlyNew, setOnlyNew] = useState(true);
  const [selectedTargets, setSelectedTargets] = useState<string[]>([]);
  const [provTitle, setProvTitle] = useState("");
  const [provLoading, setProvLoading] = useState(false);
  const [prov, setProv] = useState<{
    available: boolean;
    message?: string;
    composed_at?: string;
    features?: number;
    raw_sources: {
      path: string;
      fingerprint: string;
      source_key: string | null;
      ente: string | null;
      portale: string | null;
    }[];
    layer_sources: {
      source_uuid: string;
      source_title: string;
      source_url: string;
      source_date: string;
    }[];
  } | null>(null);
  const [showAllRegions, setShowAllRegions] = useState(false);
  const [visibleCalls, setVisibleCalls] = useState(20);
  const [showJobDetails, setShowJobDetails] = useState(false);
  const [expandedStages, setExpandedStages] = useState<Set<string>>(
    () => new Set(["compose"]),
  );
  const [historyFilter, setHistoryFilter] = useState<
    "all" | "completed" | "attention"
  >("all");
  const [showAllHistory, setShowAllHistory] = useState(false);
  const [sourceCatalog, setSourceCatalog] = useState<SourcesResponse | null>(
    null,
  );
  const [sourceLoading, setSourceLoading] = useState(false);
  const [sourceQuery, setSourceQuery] = useState("");
  const [sourcePlanFilter, setSourcePlanFilter] = useState("all");
  const [sourceLevelFilter, setSourceLevelFilter] = useState("all");
  const [health, setHealth] = useState<{
    total: number;
    ok: number;
    degradato: number;
    errore: number;
    checked_at: string;
    sources: {
      key: string;
      ente: string;
      status: string;
      checks: { label: string; url: string; ok: boolean; http?: number | null; error?: string }[];
    }[];
  } | null>(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const runHealthCheck = async () => {
    setHealthLoading(true);
    try {
      const r = await fetch(`${API}/api/sources/health`);
      setHealth(await r.json());
    } catch {
      setHealth(null);
    } finally {
      setHealthLoading(false);
    }
  };
  const [coverageMatrix, setCoverageMatrix] = useState<{
    regions: string[];
    region_names: Record<string, string>;
    targets: string[];
    matrix: Record<string, Record<string, number | null>>;
    totals_by_target: Record<string, number>;
    coverage_by_target: Record<string, number>;
    totals_by_region: Record<string, number>;
    total_features: number;
  } | null>(null);
  const [coverageLoading, setCoverageLoading] = useState(false);
  const [onlyActiveSources, setOnlyActiveSources] = useState(false);
  const [onlySourceDownloadable, setOnlySourceDownloadable] = useState(false);
  const [sourceChecks, setSourceChecks] = useState<
    Record<string, { status: string; loading?: boolean }>
  >({});
  const getTerritories = useCallback(
    async (
      level: Scope["level"],
      filters: { region?: string; province?: string; q?: string } = {},
    ) => {
      const params = new URLSearchParams({ level });
      if (filters.region) params.set("region", filters.region);
      if (filters.province) params.set("province", filters.province);
      if (filters.q) params.set("q", filters.q);
      const response = await fetch(`${API}/api/territories?${params}`);
      if (!response.ok) throw new Error("Dati territoriali non disponibili");
      return (await response.json()) as TerritoryResponse;
    },
    [],
  );

  const refresh = useCallback(async () => {
    const params = new URLSearchParams({
      level: scope.level,
      key: scope.key,
      name: scope.name,
    });
    try {
      const response = await fetch(`${API}/api/dashboard?${params}`, {
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Controller non disponibile");
      const payload = (await response.json()) as DashboardData;
      setData(payload);
      if (!payload.active_job) setConflictJob(null);
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, [scope]);

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 1200);
    return () => window.clearInterval(timer);
  }, [refresh]);

  useEffect(() => {
    getTerritories("region")
      .then((response) => {
        setRegions(response.features);
        setRegistry(response.registry);
        const current = response.features.find(
          (item) => item.properties.key === "01",
        );
        if (current) setSelectedTerritory(current);
      })
      .catch(() => setOffline(true));
  }, [getTerritories]);

  useEffect(() => {
    if (!regionKey) {
      setProvinces([]);
      return;
    }
    getTerritories("province", { region: regionKey })
      .then((response) => setProvinces(response.features))
      .catch(() => setProvinces([]));
  }, [getTerritories, regionKey]);

  useEffect(() => {
    if (!provinceKey) {
      setMunicipalities([]);
      return;
    }
    const timer = window.setTimeout(() => {
      getTerritories("municipality", {
        province: provinceKey,
        q: municipalityQuery,
      })
        .then((response) => setMunicipalities(response.features))
        .catch(() => setMunicipalities([]));
    }, 180);
    return () => window.clearTimeout(timer);
  }, [getTerritories, municipalityQuery, provinceKey]);

  useEffect(() => {
    setVisibleCalls(20);
    setShowJobDetails(false);
  }, [data?.job?.id, callFilter]);

  useEffect(() => {
    if (data?.job?.status !== "running") return;
    setExpandedStages((current) => {
      const next = new Set(current);
      next.add(data.job?.stage || "");
      return next;
    });
  }, [data?.job?.id, data?.job?.stage, data?.job?.status]);

  useEffect(() => {
    if (tab !== "coverage") return;
    setCoverageLoading(true);
    fetch(`${API}/api/coverage-matrix`, { cache: "no-store" })
      .then((r) => r.json())
      .then((d) => setCoverageMatrix(d))
      .catch(() => setCoverageMatrix(null))
      .finally(() => setCoverageLoading(false));
  }, [tab]);

  useEffect(() => {
    if (tab !== "sources") return;
    const controller = new AbortController();
    const params = new URLSearchParams(scope);
    setSourceLoading(true);
    fetch(`${API}/api/sources?${params}`, {
      cache: "no-store",
      signal: controller.signal,
    })
      .then((response) => {
        if (!response.ok) throw new Error("Registro fonti non disponibile");
        return response.json() as Promise<SourcesResponse>;
      })
      .then((payload) => setSourceCatalog(payload))
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setSourceCatalog(null);
      })
      .finally(() => {
        if (!controller.signal.aborted) setSourceLoading(false);
      });
    return () => controller.abort();
  }, [scope, tab]);

  const toggleStage = (stageId: string) => {
    setExpandedStages((current) => {
      const next = new Set(current);
      if (next.has(stageId)) next.delete(stageId);
      else next.add(stageId);
      return next;
    });
  };

  const chooseRegion = (key: string, openMap = false) => {
    const feature = regions.find((item) => item.properties.key === key);
    if (!feature) return;
    setBatchSize(SOURCE_BATCH_DEFAULTS[key] ?? 25);
    setRegionKey(key);
    setProvinceKey("");
    setMunicipalityQuery("");
    setScope({ level: "region", key, name: feature.properties.name });
    setSelectedTerritory(feature);
    if (openMap) setMapLevel("province");
  };

  const chooseProvince = (key: string) => {
    const feature = provinces.find((item) => item.properties.key === key);
    if (!feature) return;
    setProvinceKey(key);
    setMunicipalityQuery("");
    setScope({ level: "province", key, name: feature.properties.name });
    setSelectedTerritory(feature);
  };

  const chooseMunicipality = (key: string) => {
    const feature = municipalities.find((item) => item.properties.key === key);
    if (!feature) return;
    setScope({ level: "municipality", key, name: feature.properties.name });
    setSelectedTerritory(feature);
  };

  const runStage = async (stage: string) => {
    setBusy(true);
    setNotice(null);
    try {
      const response = await fetch(`${API}/api/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          stage,
          force: stage === "recognize" && force,
          batch_size: stage === "download" ? batchSize : undefined,
          only_new: stage === "download" ? onlyNew : undefined,
          scope,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        if (payload.active_job) setConflictJob(payload.active_job as Job);
        throw new Error(payload.error || "Avvio non riuscito");
      }
      setConflictJob(null);
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Avvio non riuscito");
    } finally {
      setBusy(false);
    }
  };

  const runSourceDownload = async (sourceKey: string, stage = "download") => {
    setBusy(true);
    setNotice(null);
    try {
      const response = await fetch(`${API}/api/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          stage,
          source: sourceKey,
          only_new: stage === "download" ? onlyNew : undefined,
        }),
      });
      const payload = await response.json();
      if (!response.ok) {
        if (payload.active_job) setConflictJob(payload.active_job as Job);
        throw new Error(payload.error || "Avvio non riuscito");
      }
      setConflictJob(null);
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Avvio non riuscito");
    } finally {
      setBusy(false);
    }
  };

  const runSourcesBatch = async (keys: string[]) => {
    if (keys.length === 0) return;
    setBusy(true);
    setNotice(null);
    try {
      const response = await fetch(`${API}/api/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: "download", sources: keys, only_new: onlyNew }),
      });
      const payload = await response.json();
      if (!response.ok) {
        if (payload.active_job) setConflictJob(payload.active_job as Job);
        throw new Error(payload.error || "Avvio non riuscito");
      }
      setConflictJob(null);
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Avvio non riuscito");
    } finally {
      setBusy(false);
    }
  };

  const checkSource = async (key: string) => {
    setSourceChecks((prev) => ({ ...prev, [key]: { status: "…", loading: true } }));
    try {
      const response = await fetch(
        `${API}/api/sources/check?key=${encodeURIComponent(key)}`,
      );
      const payload = await response.json();
      setSourceChecks((prev) => ({
        ...prev,
        [key]: { status: payload.status || "errore" },
      }));
    } catch {
      setSourceChecks((prev) => ({ ...prev, [key]: { status: "errore" } }));
    }
  };

  const toggleTarget = (key: string) => {
    setSelectedTargets((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  };

  const runCompose = async () => {
    setBusy(true);
    setNotice(null);
    try {
      const response = await fetch(`${API}/api/jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ stage: "compose", targets: selectedTargets, scope }),
      });
      const payload = await response.json();
      if (!response.ok) {
        if (payload.active_job) setConflictJob(payload.active_job as Job);
        throw new Error(payload.error || "Avvio non riuscito");
      }
      setConflictJob(null);
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Avvio non riuscito");
    } finally {
      setBusy(false);
    }
  };

  const stopJob = async () => {
    setBusy(true);
    try {
      const response = await fetch(`${API}/api/jobs/current`, {
        method: "DELETE",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Arresto non riuscito");
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Arresto non riuscito");
    } finally {
      setBusy(false);
    }
  };

  const resumeJob = async (job: Job) => {
    setBusy(true);
    setNotice(null);
    try {
      const response = await fetch(`${API}/api/jobs/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: job.id }),
      });
      const payload = await response.json();
      if (!response.ok) {
        if (payload.active_job) setConflictJob(payload.active_job as Job);
        throw new Error(payload.error || "Ripresa non riuscita");
      }
      setConflictJob(null);
      await refresh();
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Ripresa non riuscita");
    } finally {
      setBusy(false);
    }
  };

  const showFinalLayers = async () => {
    setBusy(true);
    setNotice(null);
    try {
      const params = new URLSearchParams(scope);
      const response = await fetch(`${API}/api/final-layers?${params}`, {
        cache: "no-store",
      });
      const payload = (await response.json()) as FinalLayers;
      if (!response.ok) throw new Error("Layer finali non disponibili");
      setFinalLayers(payload);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "Apertura non riuscita");
    } finally {
      setBusy(false);
    }
  };

  if (!data && offline) {
    return (
      <main className="connection-screen">
        <div>
          <strong>Layer Processor</strong>
          <h1>Controller locale non raggiungibile</h1>
          <p>Avvia la dashboard e riprova la connessione.</p>
          <button onClick={refresh}>Riprova</button>
        </div>
      </main>
    );
  }

  if (!data) {
    return <main className="loading-screen">Caricamento…</main>;
  }

  const activeJob =
    data.active_job?.status === "running"
      ? data.active_job
      : conflictJob?.status === "running"
        ? conflictJob
        : null;
  const running = activeJob?.status === "running";
  const filteredCalls = (data.job?.calls || []).filter(
    (call) => callFilter === "all" || call.status === callFilter,
  );
  const displayedCalls = filteredCalls.slice(-visibleCalls).reverse();
  const filteredHistory = data.history.filter((job) => {
    if (historyFilter === "completed") return job.status === "completed";
    if (historyFilter === "attention") {
      return job.status === "failed" || job.status === "cancelled";
    }
    return true;
  });
  const displayedHistory = filteredHistory.slice(
    0,
    showAllHistory ? filteredHistory.length : 6,
  );
  const mapFeatures = mapLevel === "region" ? regions : provinces;
  const selectedMetrics = selectedTerritory?.properties.metrics;
  const processMetrics = regions.find(
    (feature) => feature.properties.key === regionKey,
  )?.properties.metrics;
  const sortedRegions = [...regions].sort(
    (a, b) =>
      b.properties.metrics.pipeline_completion_pct -
        a.properties.metrics.pipeline_completion_pct ||
      a.properties.name.localeCompare(b.properties.name, "it"),
  );
  const nationalAverage = regions.length
    ? Math.round(
        regions.reduce(
          (total, feature) =>
            total + feature.properties.metrics.pipeline_completion_pct,
          0,
        ) / regions.length,
      )
    : 0;
  const activeRegions = regions.filter(
    (feature) => feature.properties.metrics.pipeline_completion_pct > 0,
  ).length;
  const completeRegions = regions.filter(
    (feature) => feature.properties.metrics.pipeline_completion_pct === 100,
  ).length;
  const nextSelectedStep = selectedMetrics?.pipeline_steps.find(
    (step) => !step.complete,
  );
  const fallbackSourceGroups: { sources: Source[]; levels: string[] }[] = [];

  const goToJob = (job: Job) => {
    setTab("processes");
    setScope(job.scope);
    if (job.scope.level === "region") {
      setRegionKey(job.scope.key);
      setProvinceKey("");
    }
    setExpandedStages((current) => new Set(current).add(job.stage));
    setNotice(null);
    window.setTimeout(() => {
      document
        .getElementById(`stage-${job.stage}`)
        ?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 100);
  };

  const toggleErrors = (stageId: string) => {
    setExpandedErrors((current) => {
      const next = new Set(current);
      if (next.has(stageId)) next.delete(stageId);
      else next.add(stageId);
      return next;
    });
  };
  const selectedRegionSources = regions.find(
    (feature) => feature.properties.key === regionKey,
  )?.properties.metrics.sources;
  if (selectedRegionSources?.length) {
    fallbackSourceGroups.push({
      sources: selectedRegionSources,
      levels:
        scope.level === "region"
          ? ["regione", "provincia", "comune"]
          : ["regione"],
    });
  }
  if (scope.level !== "region") {
    const selectedProvinceSources = provinces.find(
      (feature) => feature.properties.key === provinceKey,
    )?.properties.metrics.sources;
    if (selectedProvinceSources?.length) {
      fallbackSourceGroups.push({
        sources: selectedProvinceSources,
        levels:
          scope.level === "province" ? ["provincia", "comune"] : ["provincia"],
      });
    }
  }
  if (scope.level === "municipality" && selectedMetrics?.sources.length) {
    fallbackSourceGroups.push({
      sources: selectedMetrics.sources,
      levels: ["comune"],
    });
  }
  const fallbackSourceMap = new Map<string, Source>();
  fallbackSourceGroups.forEach((group) => {
    group.sources
      .filter((source) => group.levels.includes(source.level))
      .forEach((source) => {
        fallbackSourceMap.set(source.key, {
          ...source,
          relationship: sourceRelationship(source.level, scope.level),
        });
      });
  });
  const catalogMatchesScope =
    sourceCatalog?.scope.level === scope.level &&
    sourceCatalog.scope.key === scope.key;
  const applicableSources = catalogMatchesScope
    ? sourceCatalog.sources
    : [...fallbackSourceMap.values()];
  const sourcePlanOptions = [
    ...new Set(applicableSources.flatMap(sourceInstruments)),
  ].sort((a, b) => a.localeCompare(b, "it"));
  const normalizedSourceQuery = sourceQuery.trim().toLocaleLowerCase("it");
  const filteredSources = applicableSources.filter((source) => {
    const instruments = sourceInstruments(source);
    const matchesQuery =
      !normalizedSourceQuery ||
      [
        source.name,
        source.key,
        source.level,
        source.notes || "",
        ...instruments,
      ]
        .join(" ")
        .toLocaleLowerCase("it")
        .includes(normalizedSourceQuery);
    const matchesPlan =
      sourcePlanFilter === "all" || instruments.includes(sourcePlanFilter);
    const matchesLevel =
      sourceLevelFilter === "all" || source.level === sourceLevelFilter;
    const matchesStatus = !onlyActiveSources || source.status === "active";
    const matchesDownloadable =
      !onlySourceDownloadable || Boolean(source.download_available);
    return (
      matchesQuery &&
      matchesPlan &&
      matchesLevel &&
      matchesStatus &&
      matchesDownloadable
    );
  });
  const activeSourceTotal = applicableSources.filter(
    (source) => source.status === "active",
  ).length;
  const directSourceTotal = applicableSources.filter(
    (source) => source.relationship === "diretta",
  ).length;
  const instrumentTotal = new Set(applicableSources.flatMap(sourceInstruments))
    .size;

  return (
    <main className="page-shell">
      <header className="app-header">
        <div className="app-brand">
          <span>LP</span>
          <div>
            <strong>Layer Processor</strong>
            <small>Locale</small>
          </div>
        </div>
        <nav aria-label="Sezioni principali">
          <button
            className={tab === "processes" ? "active" : ""}
            onClick={() => setTab("processes")}
          >
            Processi
          </button>
          <button
            className={tab === "territory" ? "active" : ""}
            onClick={() => setTab("territory")}
          >
            Territorio
          </button>
          <button
            className={tab === "sources" ? "active" : ""}
            onClick={() => setTab("sources")}
          >
            Fonti
          </button>
          <button
            className={tab === "coverage" ? "active" : ""}
            onClick={() => setTab("coverage")}
          >
            Copertura
          </button>
        </nav>
        <span className={`connection-state ${offline ? "offline" : ""}`}>
          {offline ? "Disconnesso" : "Connesso"}
        </span>
      </header>

      <section className="scope-bar">
        <div>
          <span>Ambito di lavoro</span>
          <strong>
            {levelLabels[scope.level]} · {scope.name}
          </strong>
        </div>
        <div className="scope-selectors">
          <label>
            Regione
            <select
              value={regionKey}
              onChange={(event) => chooseRegion(event.target.value)}
            >
              {regions.map((feature) => (
                <option
                  key={feature.properties.key}
                  value={feature.properties.key}
                >
                  {feature.properties.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Provincia
            <select
              value={provinceKey}
              onChange={(event) => {
                if (event.target.value) chooseProvince(event.target.value);
                else chooseRegion(regionKey);
              }}
            >
              <option value="">Tutta la regione</option>
              {provinces.map((feature) => (
                <option
                  key={feature.properties.key}
                  value={feature.properties.key}
                >
                  {feature.properties.name}
                </option>
              ))}
            </select>
          </label>
          {provinceKey && (
            <label>
              Comune
              <select
                value={scope.level === "municipality" ? scope.key : ""}
                onChange={(event) => {
                  if (event.target.value)
                    chooseMunicipality(event.target.value);
                  else chooseProvince(provinceKey);
                }}
              >
                <option value="">Tutta la provincia</option>
                {municipalities.map((feature) => (
                  <option
                    key={feature.properties.key}
                    value={feature.properties.key}
                  >
                    {feature.properties.name}
                  </option>
                ))}
              </select>
            </label>
          )}
        </div>
      </section>

      {notice && (
        <div className="notice" role="alert">
          <span>{notice}</span>
          {activeJob && (
            <button className="notice-job-link" onClick={() => goToJob(activeJob)}>
              Vai al processo
            </button>
          )}
          <button onClick={() => setNotice(null)}>×</button>
        </div>
      )}

      {activeJob && (
        <section className="active-job-banner" aria-live="polite">
          <div className="active-job-head">
            <div>
              <small>Processo attivo · {activeJob.scope.name}</small>
              <strong>{activeJob.label}</strong>
            </div>
            <span>Completamento stimato {activeJob.progress}%</span>
          </div>
          <div className="progress-bar">
            <span style={{ width: `${activeJob.progress}%` }} />
          </div>
          <div className="active-job-foot">
            <span>
              {activeJob.current} / {activeJob.total} ·{" "}
              {formatDuration(activeJob.elapsed_seconds)}
            </span>
            <button onClick={() => goToJob(activeJob)}>Vai al processo</button>
          </div>
        </section>
      )}

      {tab === "processes" ? (
        <section className="content">
          <div className="page-title">
            <div>
              <p>Pipeline</p>
              <h1>Processi</h1>
            </div>
            <div className="summary-line">
              <span>
                <strong>{data.scope_summary.total}</strong> dataset
              </span>
              <span>
                <strong>{data.scope_summary.coverage}%</strong> riconosciuti
              </span>
              <span>
                ultimo avvio{" "}
                <strong>{formatDate(data.scope_summary.last_run)}</strong>
              </span>
            </div>
          </div>

          <section className="process-overview">
            <div className="process-overview-score">
              <span>Avanzamento regionale</span>
              <strong>{processMetrics?.pipeline_completion_pct || 0}%</strong>
              <div>
                <i
                  style={{
                    width: `${processMetrics?.pipeline_completion_pct || 0}%`,
                  }}
                />
              </div>
            </div>
            <div className="process-stepper">
              {processMetrics?.pipeline_steps.map((step) => (
                <div
                  key={step.id}
                  className={step.complete ? "complete" : "pending"}
                  title={step.detail}
                >
                  <i>{step.complete ? "✓" : step.number}</i>
                  <span>{step.name}</span>
                </div>
              ))}
            </div>
          </section>

          <div className="stage-list">
            {data.stages.map((stage) => {
              const isStageJob =
                stage.id === data.job?.stage &&
                scope.level === data.job?.scope.level &&
                scope.key === data.job?.scope.key;
              const isActiveJob = Boolean(isStageJob && running);
              const expanded = expandedStages.has(stage.id);
              return (
                <section
                  className={`stage-section stage-${stage.status} stage-kind-${stage.id} ${
                    isActiveJob ? "stage-active" : ""
                  } ${expanded ? "stage-expanded" : "stage-collapsed"}`}
                  key={stage.id}
                  id={`stage-${stage.id}`}
                >
                  <div className="stage-index">{stage.number}</div>
                  <div className="stage-copy">
                    <button
                      className="stage-heading-toggle"
                      onClick={() => toggleStage(stage.id)}
                      aria-expanded={expanded}
                      aria-controls={`stage-content-${stage.id}`}
                    >
                      <span>{stage.name}</span>
                      <i aria-hidden="true">{expanded ? "−" : "+"}</i>
                    </button>
                    <div id={`stage-content-${stage.id}`} className="stage-content">
                    <p>{stage.description}</p>
                    {stage.output && <small>Output: {stage.output}</small>}
                    {stage.detail && (
                      <small className="stage-detail">
                        <span>{stage.detail}</span>
                        {!!stage.errors?.length && (
                          <button
                            className="stage-error-button"
                            onClick={() => toggleErrors(stage.id)}
                          >
                            {expandedErrors.has(stage.id)
                              ? "Nascondi errori"
                              : "Spiega errori"}
                          </button>
                        )}
                      </small>
                    )}
                    {expandedErrors.has(stage.id) && !!stage.errors?.length && (
                      <div className="stage-error-box" role="status">
                        <strong>Dettaglio degli errori</strong>
                        {stage.errors.map((error, index) => (
                          <p key={`${stage.id}-error-${index}`}>{error}</p>
                        ))}
                      </div>
                    )}
                    {stage.targets && (
                      <div className="composition-block">
                        <div className="composition-tools">
                          <span>Scegli i prodotti da generare</span>
                          <button
                            onClick={() =>
                              setSelectedTargets(
                                stage.targets
                                  ?.filter(
                                    (target) =>
                                      target.state !== "presente",
                                  )
                                  .map((target) => target.key) || [],
                              )
                            }
                          >
                            Seleziona mancanti
                          </button>
                          <button onClick={() => setSelectedTargets([])}>
                            Deseleziona
                          </button>
                        </div>
                        <div className="composition-targets">
                        {stage.targets.map((target) => {
                          const st = target.state || "assente";
                          const label =
                            st === "presente"
                              ? "Presente"
                              : st === "parziale"
                                ? "Copertura parziale"
                              : st === "da_aggiornare"
                                ? "Da aggiornare"
                                : "Da comporre";
                          return (
                            <label
                              key={target.key}
                              className={`composition-target state-${st}`}
                            >
                              <input
                                type="checkbox"
                                checked={selectedTargets.includes(target.key)}
                                onChange={() => toggleTarget(target.key)}
                              />
                              <span className="ct-name">
                                {target.title || target.name || target.key}
                              </span>
                              <span className={`ct-state ${st}`}>{label}</span>
                              {typeof target.features === "number" && (
                                <span className="ct-count">
                                  {target.features.toLocaleString("it-IT")}
                                </span>
                              )}
                            </label>
                          );
                        })}
                        </div>
                      </div>
                    )}
                    {stage.id === "load" && (
                      <div className="load-readiness">
                        <strong>Prima del caricamento</strong>
                        <span
                          className={
                            processMetrics?.pipeline_steps.find(
                              (step) => step.id === "compose",
                            )?.complete
                              ? "ready"
                              : ""
                          }
                        >
                          <i>1</i> Composizione completa
                        </span>
                        <span>
                          <i>2</i> Dry-run e controlli di qualità
                        </span>
                        <span>
                          <i>3</i> Approvazione manuale alla pubblicazione
                        </span>
                        <small>
                          Il caricamento resta disabilitato finché i prerequisiti
                          non sono verificati.
                        </small>
                      </div>
                    )}
                    </div>
                  </div>
                  <div className="stage-action">
                    <span className={`stage-badge ${stage.status}`}>
                      {statusLabels[stage.status] || stage.status}
                    </span>
                    {stage.available && !isActiveJob && (
                      <>
                        {stage.id === "recognize" && (
                          <label className="force-option">
                            <input
                              type="checkbox"
                              checked={force}
                              onChange={(event) => setForce(event.target.checked)}
                            />
                            Ricalcola tutto
                          </label>
                        )}
                        {stage.id === "download" && (
                          <>
                            <label className="batch-option" title="Quanti layer per esecuzione. «Tutte» scarica tutti i pendenti in chunk, con ripresa.">
                              Per volta
                              <select
                                value={batchSize}
                                onChange={(event) =>
                                  setBatchSize(Number(event.target.value))
                                }
                              >
                                <option value={0}>Tutte</option>
                                <option value={2}>2</option>
                                <option value={5}>5</option>
                                <option value={25}>25</option>
                                <option value={50}>50</option>
                                <option value={100}>100</option>
                              </select>
                            </label>
                            <label className="batch-option" title="Salta i layer già presenti in locale e scarica solo i mancanti (ripresa). Deseleziona per riscaricare tutto.">
                              <input
                                type="checkbox"
                                checked={onlyNew}
                                onChange={(event) => setOnlyNew(event.target.checked)}
                              />
                              Solo dati nuovi
                            </label>
                          </>
                        )}
                        {stage.id === "compose" ? (
                          <button
                            className="run-button"
                            onClick={runCompose}
                            disabled={!selectedTargets.length || busy}
                            title={
                              selectedTargets.length
                                ? ""
                                : "Seleziona almeno un layer da comporre"
                            }
                          >
                            Componi selezionati
                          </button>
                        ) : (
                          <button
                            className="run-button"
                            onClick={() => runStage(stage.id)}
                            disabled={!stage.available || busy}
                          >
                            Avvia
                          </button>
                        )}
                      </>
                    )}
                    {!stage.available && (
                      <button className="run-button" disabled>
                        Avvia
                      </button>
                    )}
                    {stage.viewer_available && (
                      <button
                        className="view-layer-button"
                        onClick={showFinalLayers}
                        disabled={busy}
                      >
                        Vedi layer
                      </button>
                    )}
                  </div>

                  {isStageJob && data.job && (
                    <div
                      className={`job-progress job-${data.job.status}`}
                      aria-live="polite"
                    >
                      <div className="progress-head">
                        <strong>{data.job.label}</strong>
                        <span>
                          {data.job.status === "running"
                            ? `${data.job.current} / ${data.job.total} · ${
                                data.job.progress
                              }% stimato · ${formatDuration(data.job.elapsed_seconds)}`
                            : data.job.status === "completed"
                              ? "Concluso"
                              : data.job.status === "cancelled"
                                ? "Interrotto"
                                : "Terminato con errori"}
                        </span>
                      </div>
                      {data.job.status === "running" && (
                        <div className="progress-bar">
                          <span style={{ width: `${data.job.progress}%` }} />
                        </div>
                      )}
                      <div className="job-bottom">
                        <span>
                          {data.job.result?.message ||
                            (data.job.status === "running"
                              ? `${data.job.progress}%`
                              : "Il processo non ha restituito un riepilogo.")}
                        </span>
                        {data.job.status === "running" && (
                          <button onClick={stopJob} disabled={busy}>
                            Interrompi
                          </button>
                        )}
                        {(data.job.status === "cancelled" ||
                          data.job.status === "failed") && (
                          <button
                            className="resume-button"
                            onClick={() => resumeJob(data.job as Job)}
                            disabled={busy || running}
                          >
                            Riprendi dal punto interrotto
                          </button>
                        )}
                      </div>
                      {showJobDetails &&
                        (data.job.status === "running" ||
                          data.job.status === "failed") && (
                        <div className="simple-log">
                          {data.job.logs.slice(-5).map((line, index) => (
                            <p key={`${line}-${index}`}>{line}</p>
                          ))}
                        </div>
                      )}
                      {!!data.job.calls_total && (
                        <div className="call-status">
                          <div className="call-summary">
                            <strong>{data.job.calls_total} chiamate</strong>
                            <span>
                              {data.job.call_counts?.running || 0} in corso ·{" "}
                              {data.job.call_counts?.completed || 0} concluse ·{" "}
                              {data.job.call_counts?.skipped || 0} già locali ·{" "}
                              {data.job.call_counts?.failed || 0} fallite
                            </span>
                            {showJobDetails && (
                              <label>
                                Stato
                                <select
                                  value={callFilter}
                                  onChange={(event) =>
                                    setCallFilter(
                                      event.target.value as typeof callFilter,
                                    )
                                  }
                                >
                                  <option value="all">Tutte</option>
                                  <option value="running">In corso</option>
                                  <option value="completed">Concluse</option>
                                  <option value="skipped">Già locali</option>
                                  <option value="failed">Fallite</option>
                                </select>
                              </label>
                            )}
                          </div>
                          {showJobDetails && <div className="call-list">
                            {displayedCalls.map((call) => (
                              <div key={call.id}>
                                <span className={`call-dot ${call.status}`} />
                                <span>{call.label}</span>
                                <strong>
                                  {call.status === "completed"
                                    ? "Conclusa"
                                    : call.status === "running"
                                      ? "In corso"
                                      : call.status === "skipped"
                                        ? "Già scaricata"
                                        : "Fallita"}
                                </strong>
                              </div>
                            ))}
                          </div>}
                          {showJobDetails &&
                            displayedCalls.length < filteredCalls.length && (
                            <button
                              className="more-calls"
                              onClick={() => setVisibleCalls((value) => value + 20)}
                            >
                              Mostra altre chiamate
                            </button>
                          )}
                          <button
                            className="job-detail-toggle"
                            onClick={() => setShowJobDetails((value) => !value)}
                          >
                            {showJobDetails
                              ? "Nascondi dettagli"
                              : "Mostra chiamate e log"}
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </section>
              );
            })}
          </div>

          {finalLayers && finalLayers.scope.key === scope.key && (
            <section className="final-viewer">
              <div className="final-viewer-head">
                <div>
                  <p>Output di Composizione</p>
                  <h2>Layer finali · {scope.name}</h2>
                </div>
                <button onClick={() => setFinalLayers(null)}>Chiudi</button>
              </div>
              <FinalLayerMap data={finalLayers} />
              <div className="final-layer-legend">
                {finalLayers.layers.map((layer) => (
                  <span key={layer.key}>
                    {layer.name} · {layer.features.toLocaleString("it-IT")} elementi
                  </span>
                ))}
                {finalLayers.truncated && <span>Anteprima limitata a 5.000 elementi</span>}
              </div>
            </section>
          )}

          {!!data.history.length && (
            <section className="territory-runs">
              <div className="history-head">
                <div>
                  <p>{levelLabels[scope.level]} · {scope.name}</p>
                  <h2>Esecuzioni recenti</h2>
                </div>
                <div className="history-filters" aria-label="Filtra esecuzioni">
                  <button
                    className={historyFilter === "all" ? "active" : ""}
                    onClick={() => setHistoryFilter("all")}
                  >
                    Tutte
                  </button>
                  <button
                    className={historyFilter === "completed" ? "active" : ""}
                    onClick={() => setHistoryFilter("completed")}
                  >
                    Concluse
                  </button>
                  <button
                    className={historyFilter === "attention" ? "active" : ""}
                    onClick={() => setHistoryFilter("attention")}
                  >
                    Da riprendere
                  </button>
                </div>
              </div>
              <div className="run-history-list">
                {displayedHistory.map((job) => (
                  <div key={job.id}>
                    <span className={`call-dot ${job.status}`} />
                    <span className="history-job">
                      <strong>{job.label}</strong>
                      <small>{formatDate(job.finished_at || null)}</small>
                    </span>
                    <span className={`history-status ${job.status}`}>
                      {job.status === "completed"
                        ? "Conclusa"
                        : job.status === "cancelled"
                          ? "Interrotta"
                          : job.status === "failed"
                            ? "Fallita"
                            : "In corso"}
                    </span>
                    <span className="history-message">
                      {job.result?.message || job.status}
                    </span>
                    {(job.status === "cancelled" || job.status === "failed") && (
                      <button
                        onClick={() => resumeJob(job)}
                        disabled={busy || running}
                      >
                        Riprendi
                      </button>
                    )}
                  </div>
                ))}
              </div>
              {filteredHistory.length > 6 && (
                <button
                  className="history-more"
                  onClick={() => setShowAllHistory((value) => !value)}
                >
                  {showAllHistory
                    ? "Mostra meno"
                    : `Mostra altre ${filteredHistory.length - 6}`}
                </button>
              )}
            </section>
          )}
        </section>
      ) : tab === "territory" ? (
        <section className="content">
          <div className="page-title territory-title">
            <div>
              <p>Copertura nazionale</p>
              <h1>Territorio</h1>
            </div>
            <div className="pipeline-scale-note">
              <strong>5 stadi · 20% ciascuno</strong>
              <span>100% = dati completi, layer creati e caricati</span>
            </div>
          </div>

          <section className="national-overview" aria-label="Sintesi nazionale">
            <div>
              <span>Avanzamento medio</span>
              <strong>{nationalAverage}%</strong>
              <small>media delle 20 regioni</small>
            </div>
            <div>
              <span>Regioni avviate</span>
              <strong>{activeRegions}/20</strong>
              <small>almeno uno stadio completo</small>
            </div>
            <div>
              <span>Copertura perfetta</span>
              <strong>{completeRegions}</strong>
              <small>regioni al 100%</small>
            </div>
            <div className="national-progress">
              <span>Obiettivo nazionale</span>
              <div>
                <i style={{ width: `${nationalAverage}%` }} />
              </div>
              <small>{100 - nationalAverage}% ancora da completare</small>
            </div>
          </section>

          <div className="map-layout">
            <section className="map-card">
              <div className="map-toolbar">
                <div>
                  <button
                    className={mapLevel === "region" ? "current" : ""}
                    onClick={() => {
                      setMapLevel("region");
                      setSelectedTerritory(
                        regions.find(
                          (item) => item.properties.key === regionKey,
                        ) || null,
                      );
                    }}
                  >
                    Italia
                  </button>
                  {mapLevel === "province" && (
                    <>
                      <span>/</span>
                      <strong>
                        {
                          regions.find(
                            (item) => item.properties.key === regionKey,
                          )?.properties.name
                        }
                      </strong>
                    </>
                  )}
                </div>
                <small>
                  Clicca una regione per vedere le province
                </small>
              </div>
              <ItalyMap
                features={mapFeatures}
                selectedKey={selectedTerritory?.properties.key}
                onSelect={(feature) => {
                  if (mapLevel === "region") {
                    chooseRegion(feature.properties.key, true);
                  } else {
                    chooseProvince(feature.properties.key);
                  }
                }}
              />
              <div className="legend">
                <span>
                  <i className="pct-0" /> 0%
                </span>
                <span>
                  <i className="pct-20" /> 20%
                </span>
                <span>
                  <i className="pct-40" /> 40%
                </span>
                <span>
                  <i className="pct-60" /> 60%
                </span>
                <span>
                  <i className="pct-80" /> 80%
                </span>
                <span>
                  <i className="pct-100" /> 100%
                </span>
              </div>
            </section>

            <aside className="territory-detail">
              {selectedTerritory ? (
                <>
                  <p>{levelLabels[selectedTerritory.properties.level]}</p>
                  <h2>{selectedTerritory.properties.name}</h2>
                  <div className="pipeline-completion">
                    <strong>{selectedMetrics?.pipeline_completion_pct || 0}%</strong>
                    <div>
                      <span>
                        {selectedMetrics?.pipeline_completed_steps || 0}/5 stadi completati
                      </span>
                      <small>
                        {nextSelectedStep
                          ? `Prossimo: ${nextSelectedStep.name}`
                          : "Pipeline regionale completa"}
                      </small>
                    </div>
                  </div>
                  <div className="pipeline-step-list">
                    {selectedMetrics?.pipeline_steps.map((step) => (
                      <div
                        key={step.id}
                        className={step.complete ? "complete" : "pending"}
                      >
                        <i aria-hidden="true">{step.complete ? "✓" : step.number}</i>
                        <span>
                          <strong>{step.name}</strong>
                          <small>{step.detail}</small>
                        </span>
                      </div>
                    ))}
                  </div>
                  <div className="territory-kpis">
                    <div>
                      <strong>{selectedMetrics?.active_source_count || 0}</strong>
                      <span>fonti attive</span>
                    </div>
                    <div>
                      <strong>{selectedMetrics?.final_layers || 0}</strong>
                      <span>layer finali</span>
                    </div>
                    <div>
                      <strong>
                        {selectedMetrics?.regulatory_coverage || 0}%
                      </strong>
                      <span>copertura PRG</span>
                    </div>
                  </div>

                  {selectedTerritory.properties.level === "region" && (
                    <button
                      className="open-processes"
                      onClick={() => setTab("processes")}
                    >
                      Apri i processi di questa regione
                    </button>
                  )}

                  {selectedTerritory.properties.level === "province" && (
                    <div className="municipality-search">
                      <label htmlFor="municipality-search">
                        Seleziona un comune
                      </label>
                      <input
                        id="municipality-search"
                        type="search"
                        placeholder="Cerca comune…"
                        value={municipalityQuery}
                        onChange={(event) =>
                          setMunicipalityQuery(event.target.value)
                        }
                      />
                      <div>
                        {municipalities.slice(0, 8).map((feature) => (
                          <button
                            key={feature.properties.key}
                            onClick={() =>
                              chooseMunicipality(feature.properties.key)
                            }
                          >
                            {feature.properties.name}
                            <span>
                              {feature.properties.metrics.process_available
                                ? "processi disponibili"
                                : "nessun catalogo"}
                            </span>
                          </button>
                        ))}
                      </div>
                    </div>
                  )}

                  <div className="source-list">
                    <h3>Fonti dati</h3>
                    {selectedMetrics?.sources.length ? (
                      selectedMetrics.sources.map((source) => (
                        <a
                          href={source.url}
                          target="_blank"
                          rel="noreferrer"
                          key={source.key}
                        >
                          <span>
                            <strong>{source.name}</strong>
                            <small>
                              {source.level} · {source.status}
                            </small>
                          </span>
                          ↗
                        </a>
                      ))
                    ) : (
                      <p className="empty-message">
                        Nessuna fonte registrata per questo territorio.
                      </p>
                    )}
                  </div>

                </>
              ) : (
                <p>Seleziona un territorio sulla mappa.</p>
              )}
            </aside>
          </div>

          {mapLevel === "region" && (
            <section className="region-ranking">
              <div className="region-ranking-head">
                <div>
                  <p>Confronto nazionale</p>
                  <h2>Avanzamento per regione</h2>
                </div>
                <button onClick={() => setShowAllRegions((value) => !value)}>
                  {showAllRegions ? "Mostra meno" : "Mostra tutte"}
                </button>
              </div>
              <div className="region-ranking-grid">
                {sortedRegions
                  .slice(0, showAllRegions ? sortedRegions.length : 6)
                  .map((feature, index) => {
                    const percentage =
                      feature.properties.metrics.pipeline_completion_pct;
                    return (
                      <button
                        key={feature.properties.key}
                        onClick={() => chooseRegion(feature.properties.key, true)}
                      >
                        <span className="rank-number">
                          {String(index + 1).padStart(2, "0")}
                        </span>
                        <strong>{feature.properties.name}</strong>
                        <span className="rank-bar">
                          <i style={{ width: `${percentage}%` }} />
                        </span>
                        <b>{percentage}%</b>
                      </button>
                    );
                  })}
              </div>
            </section>
          )}

          {registry &&
            registry.provinces !== registry.geometry_provinces && (
              <p className="registry-note">
                Il registro contiene {registry.provinces} province; la cartografia
                locale ne rappresenta {registry.geometry_provinces}. Le nuove
                ripartizioni senza geometria restano nel registro e verranno
                visualizzate dopo l’aggiornamento cartografico.
              </p>
            )}
        </section>
      ) : tab === "sources" ? (
        <section className="content sources-content">
          <div className="page-title sources-title">
            <div>
              <p>Registro territoriale</p>
              <h1>Fonti</h1>
            </div>
            <div className="sources-context">
              <span>Fonti applicabili a</span>
              <strong>
                {levelLabels[scope.level]} · {scope.name}
              </strong>
            </div>
          </div>

          <section className="source-overview" aria-label="Sintesi delle fonti">
            <div>
              <span>Fonti registrate</span>
              <strong>{applicableSources.length}</strong>
              <small>tutti i livelli territoriali</small>
            </div>
            <div>
              <span>Fonti attive</span>
              <strong>{activeSourceTotal}</strong>
              <small>collegamenti utilizzabili</small>
            </div>
            <div>
              <span>Fonti dirette</span>
              <strong>{directSourceTotal}</strong>
              <small>del territorio selezionato</small>
            </div>
            <div>
              <span>Tipi di piano</span>
              <strong>{instrumentTotal}</strong>
              <small>strumenti distinti censiti</small>
            </div>
          </section>

          <div className="sources-health">
            <button
              className="run-button"
              onClick={runHealthCheck}
              disabled={healthLoading}
            >
              {healthLoading ? "Verifica in corso…" : "Verifica link"}
            </button>
            {health && (
              <div className="health-result">
                <div className="health-summary">
                  <span className="health-ok">{health.ok}/{health.total} ok</span>
                  {health.degradato > 0 && (
                    <span className="health-warn">{health.degradato} degradati</span>
                  )}
                  {health.errore > 0 && (
                    <span className="health-bad">{health.errore} in errore</span>
                  )}
                </div>
                {health.sources
                  .filter((s) => s.status !== "ok")
                  .map((s) => (
                    <div key={s.key} className={`health-row ${s.status}`}>
                      <strong>{s.ente || s.key}</strong>
                      <span>
                        {s.checks
                          .filter((c) => !c.ok)
                          .map((c) => `${c.label}: ${c.http || c.error}`)
                          .join(" · ")}
                      </span>
                    </div>
                  ))}
                {health.errore === 0 && health.degradato === 0 && (
                  <p className="health-allok">Tutti i link funzionano ✓</p>
                )}
              </div>
            )}
          </div>

          <section className="sources-browser">
            <div className="sources-toolbar">
              <label className="source-search">
                Cerca una fonte
                <input
                  type="search"
                  value={sourceQuery}
                  onChange={(event) => setSourceQuery(event.target.value)}
                  placeholder="Nome, ente o tipo di piano…"
                />
              </label>
              <label>
                Tipo di piano
                <select
                  value={sourcePlanFilter}
                  onChange={(event) => setSourcePlanFilter(event.target.value)}
                >
                  <option value="all">Tutti i piani</option>
                  {sourcePlanOptions.map((instrument) => (
                    <option key={instrument} value={instrument}>
                      {instrument}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Livello della fonte
                <select
                  value={sourceLevelFilter}
                  onChange={(event) => setSourceLevelFilter(event.target.value)}
                >
                  <option value="all">Tutti i livelli</option>
                  <option value="nazionale">Nazionale</option>
                  <option value="regione">Regionale</option>
                  <option value="provincia">Provinciale</option>
                  <option value="comune">Comunale</option>
                </select>
              </label>
              <label className="source-active-filter">
                <input
                  type="checkbox"
                  checked={onlyActiveSources}
                  onChange={(event) =>
                    setOnlyActiveSources(event.target.checked)
                  }
                />
                Solo fonti attive
              </label>
              <label className="source-active-filter">
                <input
                  type="checkbox"
                  checked={onlySourceDownloadable}
                  onChange={(event) =>
                    setOnlySourceDownloadable(event.target.checked)
                  }
                />
                Solo scaricabili
              </label>
              <label className="source-active-filter">
                <input
                  type="checkbox"
                  checked={onlyNew}
                  onChange={(event) => setOnlyNew(event.target.checked)}
                />
                Solo dati nuovi
              </label>
            </div>

            <div className="source-results-head">
              <div>
                <h2>Elenco delle fonti</h2>
                <span>
                  {filteredSources.length}{" "}
                  {filteredSources.length === 1 ? "risultato" : "risultati"}
                </span>
              </div>
              {sourceLoading && <small>Aggiornamento registro…</small>}
              {(() => {
                const downloadable = filteredSources.filter(
                  (source) => source.download_available,
                );
                return downloadable.length ? (
                  <button
                    className="run-button"
                    disabled={busy}
                    onClick={() =>
                      runSourcesBatch(downloadable.map((source) => source.key))
                    }
                  >
                    {busy
                      ? "Avvio…"
                      : `Scarica scaricabili (${downloadable.length})`}
                  </button>
                ) : null;
              })()}
              {(sourceQuery ||
                sourcePlanFilter !== "all" ||
                sourceLevelFilter !== "all" ||
                onlyActiveSources ||
                onlySourceDownloadable) && (
                <button
                  onClick={() => {
                    setSourceQuery("");
                    setSourcePlanFilter("all");
                    setSourceLevelFilter("all");
                    setOnlyActiveSources(false);
                    setOnlySourceDownloadable(false);
                  }}
                >
                  Azzera filtri
                </button>
              )}
            </div>

            {filteredSources.length ? (
              <div className="source-grid">
                {filteredSources.map((source) => {
                  const instruments = sourceInstruments(source);
                  return (
                    <article className="source-card" key={source.key}>
                      <div className="source-card-head">
                        <div>
                          <span className={`source-status ${source.status}`}>
                            {sourceStatusLabels[source.status] || source.status}
                          </span>
                          <span className="source-level">
                            {sourceLevelLabels[source.level] || source.level}
                          </span>
                        </div>
                        <span className="source-relationship">
                          {source.relationship === "diretta"
                            ? "Diretta"
                            : source.relationship === "nazionale"
                              ? "Nazionale"
                              : source.relationship === "locale"
                                ? "Locale"
                              : "Sovraordinata"}
                        </span>
                      </div>
                      <div className="source-card-body">
                        <span className="source-key">{source.key}</span>
                        <h3>{source.name}</h3>
                        <div className="source-plan-tags">
                          {instruments.map((instrument) => (
                            <span key={instrument}>{instrument}</span>
                          ))}
                        </div>
                        {source.notes && <p>{source.notes}</p>}
                        {source.download_available && (
                          <details className="source-download-guide">
                            <summary>
                              <span>Come si scarica</span>
                              <strong>
                                {source.downloaded_datasets || 0}/
                                {source.expected_datasets || "?"}
                              </strong>
                            </summary>
                            <div className="source-download-progress">
                              <span
                                style={{
                                  width: `${
                                    source.expected_datasets
                                      ? Math.min(
                                          100,
                                          ((source.downloaded_datasets || 0) /
                                            source.expected_datasets) *
                                            100,
                                        )
                                      : 0
                                  }%`,
                                }}
                              />
                            </div>
                            <dl>
                              <div>
                                <dt>Formato</dt>
                                <dd>{source.data_format}</dd>
                              </div>
                              <div>
                                <dt>Batch</dt>
                                <dd>
                                  {source.batch_size
                                    ? `${source.batch_size} dataset per run`
                                    : "Tutti i pendenti"}
                                </dd>
                              </div>
                              <div>
                                <dt>Destinazione</dt>
                                <dd>{source.raw_path}</dd>
                              </div>
                              <div>
                                <dt>Ripresa</dt>
                                <dd>
                                  {source.resumable
                                    ? "Automatica dai file conclusi"
                                    : "Non configurata"}
                                </dd>
                              </div>
                            </dl>
                            <ol>
                              <li>
                                In <strong>Processi</strong> esegui{" "}
                                <strong>Scoperta fonti</strong>.
                              </li>
                              <li>
                                Avvia <strong>Download</strong> lasciando attivo{" "}
                                <strong>Solo dati nuovi</strong>.
                              </li>
                              <li>
                                Ripeti Download: ogni run acquisisce il batch
                                successivo senza riscaricare i file conclusi.
                              </li>
                            </ol>
                            <button
                              className="source-process-button"
                              onClick={() => setTab("processes")}
                            >
                              Vai a Processi
                            </button>
                            <details className="source-cli-guide">
                              <summary>Comandi equivalenti</summary>
                              <code>{source.discover_command}</code>
                              <code>{source.download_command}</code>
                            </details>
                          </details>
                        )}
                      </div>
                      <div className="source-card-footer">
                        <span>
                          {source.kind === "national_dataset"
                            ? "Dataset nazionale"
                            : source.kind === "wordpress_feed"
                              ? "Feed informativo"
                              : "Portale cartografico"}
                        </span>
                        <div className="source-card-links">
                          {source.download_available && (
                            <button
                              disabled={busy}
                              onClick={() => runSourceDownload(source.key)}
                              style={{
                                padding: "6px 12px",
                                borderRadius: 8,
                                border: "1px solid var(--line)",
                                background: "var(--green-soft)",
                                color: "var(--green)",
                                fontWeight: 700,
                                fontSize: 12,
                                cursor: busy ? "default" : "pointer",
                                opacity: busy ? 0.5 : 1,
                              }}
                            >
                              {(source.downloaded_datasets || 0) > 0
                                ? "Riscarica"
                                : "Scarica"}
                            </button>
                          )}
                          {source.links?.map((link) => (
                            <a
                              href={link.url}
                              target="_blank"
                              rel="noreferrer"
                              key={`${source.key}-${link.label}`}
                            >
                              {link.label} <span aria-hidden="true">↗</span>
                            </a>
                          ))}
                          {source.data_url && (
                            <a
                              href={source.data_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              Dati <span aria-hidden="true">↓</span>
                            </a>
                          )}
                          <a href={source.url} target="_blank" rel="noreferrer">
                            Apri fonte <span aria-hidden="true">↗</span>
                          </a>
                        </div>
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : (
              <div className="source-empty">
                <strong>Nessuna fonte trovata</strong>
                <p>
                  Non risultano fonti registrate per questo territorio oppure i
                  filtri attivi non producono risultati.
                </p>
                {(sourceQuery ||
                  sourcePlanFilter !== "all" ||
                  sourceLevelFilter !== "all" ||
                  onlyActiveSources) && (
                  <button
                    onClick={() => {
                      setSourceQuery("");
                      setSourcePlanFilter("all");
                      setSourceLevelFilter("all");
                      setOnlyActiveSources(false);
                    }}
                  >
                    Mostra tutte le fonti
                  </button>
                )}
              </div>
            )}
          </section>
        </section>
      ) : tab === "coverage" ? (
        <section className="content coverage-content">
          <div className="page-title">
            <div>
              <p>Matrice nazionale</p>
              <h1>Copertura</h1>
            </div>
            {coverageMatrix && (
              <div className="summary-line">
                <span>
                  <strong>{coverageMatrix.targets.length}</strong> target
                </span>
                <span>
                  <strong>{coverageMatrix.total_features.toLocaleString("it-IT")}</strong> feature totali
                </span>
              </div>
            )}
          </div>
          {coverageLoading && <p>Caricamento matrice…</p>}
          {coverageMatrix && (
            <div className="coverage-matrix-wrap">
              <table className="coverage-matrix">
                <thead>
                  <tr>
                    <th className="cm-corner">Target</th>
                    {coverageMatrix.regions.map((rk) => (
                      <th key={rk} className="cm-region" title={coverageMatrix.region_names[rk]}>
                        {coverageMatrix.region_names[rk].slice(0, 3).toUpperCase()}
                      </th>
                    ))}
                    <th className="cm-total">Reg</th>
                    <th className="cm-total">Totale</th>
                  </tr>
                </thead>
                <tbody>
                  {coverageMatrix.targets.map((target) => {
                    const row = coverageMatrix.matrix[target];
                    const cov = coverageMatrix.coverage_by_target[target] || 0;
                    const total = coverageMatrix.totals_by_target[target] || 0;
                    return (
                      <tr key={target}>
                        <td className="cm-target" title={target}>
                          {target.replace(/_/g, " ")}
                        </td>
                        {coverageMatrix.regions.map((rk) => {
                          const v = row[rk];
                          const cls =
                            v === null || v === undefined
                              ? "cm-cell cm-empty"
                              : v === 0
                                ? "cm-cell cm-zero"
                                : v < 100
                                  ? "cm-cell cm-low"
                                  : v < 10000
                                    ? "cm-cell cm-mid"
                                    : "cm-cell cm-high";
                          return (
                            <td
                              key={rk}
                              className={cls}
                              title={`${coverageMatrix.region_names[rk]}: ${v === null ? "–" : v.toLocaleString("it-IT")} ft`}
                            >
                              {v === null ? "" : v === 0 ? "0" : v < 1000 ? String(v) : `${Math.round(v / 1000)}k`}
                            </td>
                          );
                        })}
                        <td className="cm-total">{cov}/20</td>
                        <td className="cm-total">{total.toLocaleString("it-IT")}</td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <td className="cm-target">TOTALE</td>
                    {coverageMatrix.regions.map((rk) => {
                      const v = coverageMatrix.totals_by_region[rk] || 0;
                      return (
                        <td key={rk} className="cm-cell cm-foot" title={coverageMatrix.region_names[rk]}>
                          {v < 1000 ? String(v) : `${Math.round(v / 1000)}k`}
                        </td>
                      );
                    })}
                    <td className="cm-total" />
                    <td className="cm-total">
                      {coverageMatrix.total_features.toLocaleString("it-IT")}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </section>
      ) : null}
    </main>
  );
}
