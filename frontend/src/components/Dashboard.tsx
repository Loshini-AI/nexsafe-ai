"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Activity, AlertTriangle, ArrowDownToLine, BarChart3, Camera, Check, CircleHelp, CloudSun, Cpu, Eye, EyeOff, ExternalLink, LayoutDashboard, LockKeyhole, LogOut, Map, Menu, Plus, Radar, RefreshCw, Shield, ShieldAlert, Video, X } from "lucide-react";

const MapView = dynamic(() => import("./MapView"), { ssr: false });
const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type CameraRecord = { id: string; name: string; latitude: number | null; longitude: number | null; weather_station_id: string | null; enabled: boolean; created_at: string; connection_status: string };
type EventRecord = { id: string; camera_id: string | null; event_type: string; occurred_at: string; risk_score: number | null; model_confidence: number | null; status: string; assigned_to: string | null; details: string | null };
type Overview = { connected_cameras: number; registered_cameras: number; active_incidents: number; processed_frames: number; inference_latency_ms: number | null; current_inference_fps: number | null; inference_status: string; camera_status_note: string };
type RiskPrediction = { class: string; confidence: number; risk_score: number; model_version: string | null; prediction_type: string; environmental_context?: WeatherContext; weather_used_by_model?: boolean };
type LiveFrame = { image?: string; fps?: number; latency?: number; detections?: number; status?: string; risk?: RiskPrediction; opticalFlow?: number | null };
type Analytics = { status: string; message?: string; event_count: number; events_by_day: { date: string; count: number }[]; by_type: { type: string; count: number }[] };
type ModelMetrics = { accuracy?: number; macro_precision?: number; macro_recall?: number; macro_f1?: number; precision?: number; recall?: number; mAP50?: number; "mAP50-95"?: number };
type DetectorTrainingMetrics = { epochs_recorded: number; last_epoch: number; last_epoch_training_losses: Record<string, number> };
type DatasetStatus = { status: string; message: string; last_audited: string | null; dataset: { name: string; source: string; license: string; revision: string; supported_tasks: string[]; not_supported: string[] } | null; splits: { name: string; status: string; available_images: number | null; annotated_images: number | null; missing_images: number | null; annotations: number | null; image_bytes: number | null; dimension_mismatches: number | null }[] };
type DetectionResult = { class_id: number; label: string; confidence: number; xyxy: number[] };
type ImageInference = { detections: DetectionResult[]; latency_ms: number; image_dimensions: { width: number; height: number } };
type Model = { status: string; message: string | null; architecture: string | null; weights_configured: boolean; detector: { status: string; error: string | null; architecture: string | null; classes: string[]; model_version: string | null; dataset: string | null; training_metrics: DetectorTrainingMetrics | null; validation_metrics: ModelMetrics | null; test_metrics: ModelMetrics | null; metrics_note: string | null; training_info: { config?: { epochs?: number }; trained_at?: string } | null }; accident_classifier: { status: string; architecture: string | null; message: string | null; version: string | null; classes: string[]; evaluation_metrics: ModelMetrics | null; test_metrics: ModelMetrics | null; training_info: { dataset_name?: string; data_domain?: string; train_segments?: number; validation_segments?: number; test_segments?: number; epochs?: number; device?: string } | null }; structured_road_risk: { status: string; architecture: string | null; message: string | null; version: string | null; features: string[]; classes: string[]; evaluation_metrics: { validation?: ModelMetrics; test?: ModelMetrics } | null; training_info: { dataset_name?: string; label_definition?: string } | null } };
type GovernmentSource = { key: string; name: string; source_url: string; status: string; freshness: string; data_kind: string; source_timestamp: string | null; last_successful_sync: string | null; last_attempt: string | null; error: string | null; data: Record<string, unknown> | null };
type GovernmentData = { sources: Record<string, GovernmentSource> };
type GovernmentRecord = Record<string, unknown>;
type WeatherContext = { weather?: { status: string; station?: string; station_id?: string; observed_at?: string | null; observation?: Record<string, unknown> }; weather_used_by_model?: boolean };
type View = "overview" | "monitoring" | "alerts" | "map" | "analytics" | "model" | "government";

const nav: { id: View; label: string; icon: typeof LayoutDashboard }[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "monitoring", label: "Live monitoring", icon: Video },
  { id: "alerts", label: "Alert center", icon: ShieldAlert },
  { id: "map", label: "Risk map", icon: Map },
  { id: "analytics", label: "Analytics", icon: BarChart3 },
  { id: "model", label: "Model center", icon: Cpu },
  { id: "government", label: "Government data", icon: CloudSun },
];

export default function Dashboard() {
  const [token, setToken] = useState("");
  const [guestMode, setGuestMode] = useState(false);
  const [authMode, setAuthMode] = useState<"signin" | "signup">("signin");
  const [registrationStatus, setRegistrationStatus] = useState<{ available: boolean; first_account: boolean } | null>(null);
  const [registrationServiceStatus, setRegistrationServiceStatus] = useState<"checking" | "available" | "unavailable">("checking");
  const [registrationServiceMessage, setRegistrationServiceMessage] = useState("");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [authLoading, setAuthLoading] = useState(false);
  const [authSuccess, setAuthSuccess] = useState(false);
  const [view, setView] = useState<View>("overview");
  const [mobileNav, setMobileNav] = useState(false);
  const [cameras, setCameras] = useState<CameraRecord[]>([]);
  const [events, setEvents] = useState<EventRecord[]>([]);
  const [overview, setOverview] = useState<Overview | null>(null);
  const [analytics, setAnalytics] = useState<Analytics | null>(null);
  const [model, setModel] = useState<Model | null>(null);
  const [datasetStatus, setDatasetStatus] = useState<DatasetStatus | null>(null);
  const [governmentData, setGovernmentData] = useState<GovernmentData | null>(null);
  const [governmentBackendUnavailable, setGovernmentBackendUnavailable] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [dataAvailable, setDataAvailable] = useState(false);
  const [realtimeStatus, setRealtimeStatus] = useState<"connecting" | "connected" | "disconnected">("disconnected");
  const [cameraForm, setCameraForm] = useState(false);
  const [cameraName, setCameraName] = useState("");
  const [cameraSource, setCameraSource] = useState("");
  const [cameraLatitude, setCameraLatitude] = useState("");
  const [cameraLongitude, setCameraLongitude] = useState("");
  const [cameraWeatherStationId, setCameraWeatherStationId] = useState("");
  const [uploadMessage, setUploadMessage] = useState("");
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [imageInference, setImageInference] = useState<ImageInference | null>(null);
  const [imageInferenceMessage, setImageInferenceMessage] = useState("");
  const [imageInferenceLoading, setImageInferenceLoading] = useState(false);
  const [liveFrames, setLiveFrames] = useState<Record<string, LiveFrame>>({});
  const [systemMetrics, setSystemMetrics] = useState<{ cpu_percent: number; memory_percent: number; gpu: { available: boolean } } | null>(null);

  const passwordChecks = [
    password.length >= 12,
    /[a-z]/.test(password),
    /[A-Z]/.test(password),
    /\d/.test(password),
    /[^a-zA-Z0-9]/.test(password),
  ];
  const passwordStrength = passwordChecks.slice(1).filter(Boolean).length;
  const passwordIsStrong = passwordChecks[0] && passwordStrength >= 3;
  const passwordsMatch = password === confirmPassword;

  const checkRegistration = useCallback(async () => {
    setRegistrationServiceStatus("checking");
    setRegistrationServiceMessage("");
    try {
      const response = await fetch(`${API}/api/auth/registration`, { cache: "no-store" });
      const result = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof result?.detail === "string" ? result.detail : `Account service returned ${response.status}`);
      if (typeof result.available !== "boolean" || typeof result.first_account !== "boolean") {
        throw new Error("Account service returned an invalid registration status");
      }
      setRegistrationStatus(result);
      setRegistrationServiceStatus("available");
    } catch (reason) {
      setRegistrationStatus(null);
      setRegistrationServiceStatus("unavailable");
      setRegistrationServiceMessage(reason instanceof TypeError
        ? "Cannot connect to the account service. Start the backend and check the database connection."
        : reason instanceof Error ? reason.message : "The account service is unavailable.");
    }
  }, []);

  useEffect(() => {
    const stored = window.localStorage.getItem("nexsafe_access_token");
    if (stored) setToken(stored);
  }, []);

  useEffect(() => {
    if (!imagePreview) return;
    return () => URL.revokeObjectURL(imagePreview);
  }, [imagePreview]);

  useEffect(() => {
    if (!token && !guestMode) void checkRegistration();
  }, [checkRegistration, guestMode, token]);

  const request = useCallback(async (path: string, init?: RequestInit) => {
    const response = await fetch(`${API}${path}`, {
      ...init,
      headers: { ...(init?.headers || {}), Authorization: `Bearer ${token}`, ...(init?.body && !(init.body instanceof FormData) ? { "Content-Type": "application/json" } : {}) },
    });
    if (response.status === 401) {
      window.localStorage.removeItem("nexsafe_access_token");
      setToken("");
      throw new Error("Your session has expired or was revoked. Sign in again.");
    }
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      throw new Error(body?.detail || `Service returned ${response.status}`);
    }
    return response.status === 204 ? null : response.json();
  }, [token]);

  const refresh = useCallback(async () => {
    if (!token) return;
    setLoading(true);
    try {
      const [cam, ev, over, analytic, modelStatus, dataset, system, government] = await Promise.all([
        request("/api/cameras"), request("/api/events"), request("/api/overview"),
        request("/api/analytics"), request("/api/model"), request("/api/datasets/status"), request("/api/system"),
        request("/api/government"),
      ]);
      setCameras(cam); setEvents(ev); setOverview(over); setAnalytics(analytic); setModel(modelStatus); setDatasetStatus(dataset); setSystemMetrics(system); setGovernmentData(government); setGovernmentBackendUnavailable(false); setDataAvailable(true); setError("");
    } catch (reason) {
      setDataAvailable(false);
      setCameras([]); setEvents([]); setOverview(null); setAnalytics(null); setModel(null); setDatasetStatus(null); setSystemMetrics(null); setGovernmentBackendUnavailable(true);
      setError(reason instanceof Error ? reason.message : "Unable to load service data");
    } finally { setLoading(false); }
  }, [request, token]);

  useEffect(() => { void refresh(); }, [refresh]);

  useEffect(() => {
    if (!token) return;
    const timer = window.setInterval(() => {
      void request("/api/government").then((government) => {
        setGovernmentData(government);
        setGovernmentBackendUnavailable(false);
      }).catch(() => setGovernmentBackendUnavailable(true));
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [request, token]);

  useEffect(() => {
    if (!token) return;
    setRealtimeStatus("connecting");
    const socket = new WebSocket(`${API.replace(/^http/, "ws")}/api/ws?token=${encodeURIComponent(token)}`);
    socket.onopen = () => setRealtimeStatus("connected");
    socket.onclose = () => setRealtimeStatus("disconnected");
    socket.onmessage = (message) => {
      try {
        const event = JSON.parse(message.data);
        if (event.type === "camera.frame") {
          setLiveFrames((current) => ({ ...current, [event.camera_id]: {
            image: event.jpeg_base64 ? `data:image/jpeg;base64,${event.jpeg_base64}` : undefined,
            fps: event.inference_fps, latency: event.latency_ms, detections: event.detections?.length,
            status: "connected",
            risk: event.risk_prediction ?? current[event.camera_id]?.risk,
            opticalFlow: event.optical_flow_mean_magnitude,
          } }));
        } else if (event.type === "risk.prediction") {
          setLiveFrames((current) => ({ ...current, [event.camera_id]: {
            ...current[event.camera_id],
            risk: event,
          } }));
        } else if (event.type === "camera.status") {
          setLiveFrames((current) => ({ ...current, [event.camera_id]: { ...current[event.camera_id], status: event.status } }));
          void refresh();
        } else {
          void refresh();
        }
      } catch { setError("Received an unreadable real-time service message"); }
    };
    socket.onerror = () => socket.close();
    return () => socket.close();
  }, [token, refresh]);

  const authenticate = async (event: FormEvent) => {
    event.preventDefault(); setError(""); setAuthSuccess(false);
    if (authMode === "signup" && !passwordsMatch) {
      setError("Passwords do not match.");
      return;
    }
    if (authMode === "signup" && registrationServiceStatus !== "available") {
      setError("The account service is not ready. Start the backend and database, then check availability again.");
      return;
    }
    if (authMode === "signup" && registrationStatus && !registrationStatus.available) {
      setError("Account registration is disabled. Ask the workspace administrator to enable ALLOW_REGISTRATION.");
      return;
    }
    setAuthLoading(true);
    try {
      const response = authMode === "signup"
        ? await fetch(`${API}/api/auth/register`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ full_name: fullName, email, password }),
          })
        : await fetch(`${API}/api/auth/token`, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded" },
            body: new URLSearchParams({ username: email, password }),
          });
      const result = await response.json().catch(() => null);
      if (!result || typeof result !== "object") {
        throw new Error(`Account service returned an unreadable response (${response.status})`);
      }
      if (!response.ok) {
        const detail = result.detail;
        const message = typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail.map((item: { msg?: string }) => item.msg).filter(Boolean).join("; ")
            : "";
        throw new Error(message || (authMode === "signup" ? "Account creation failed" : "Sign in failed"));
      }
      if (typeof result.access_token !== "string" || !result.access_token) {
        throw new Error("Account service returned an invalid sign-in response");
      }
      if (authMode === "signup") setAuthSuccess(true);
      window.localStorage.setItem("nexsafe_access_token", result.access_token);
      setToken(result.access_token);
    } catch (reason) {
      setError(reason instanceof TypeError
        ? "Cannot connect to the NexSafe API. Start the backend and database, then retry."
        : reason instanceof Error ? reason.message : "Sign in failed");
    } finally {
      setAuthLoading(false);
    }
  };
  const logout = async () => {
    try {
      const response = await fetch(`${API}/api/auth/logout`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok) {
        throw new Error(`The server could not revoke this session (${response.status}).`);
      }
    } catch (reason) {
      setError(reason instanceof Error
        ? `${reason.message} The local session was cleared; the token expires automatically.`
        : "The server could not confirm logout. The local session was cleared; the token expires automatically.");
    } finally {
      window.localStorage.removeItem("nexsafe_access_token");
      setToken("");
      setGuestMode(false);
      setAuthSuccess(false);
      setDataAvailable(false);
      setRealtimeStatus("disconnected");
      setCameras([]);
      setEvents([]);
      setOverview(null);
      setAnalytics(null);
      setModel(null);
      setDatasetStatus(null);
      setSystemMetrics(null);
      setGovernmentData(null);
      setGovernmentBackendUnavailable(false);
    }
  };

  const createCamera = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await request("/api/cameras", { method: "POST", body: JSON.stringify({ name: cameraName, source: cameraSource, latitude: cameraLatitude ? Number(cameraLatitude) : null, longitude: cameraLongitude ? Number(cameraLongitude) : null, weather_station_id: cameraWeatherStationId.trim() || null }) });
      setCameraForm(false); setCameraName(""); setCameraSource(""); setCameraLatitude(""); setCameraLongitude(""); setCameraWeatherStationId(""); await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Camera registration failed"); }
  };

  const updateEvent = async (id: string, status: string) => {
    try { await request(`/api/events/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }); await refresh(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Event update failed"); }
  };

  const uploadVideo = async (file?: File) => {
    if (!file) return;
    setUploadMessage("Uploading and analyzing video…");
    const data = new FormData(); data.set("file", file);
    try {
      const result = await request("/api/videos/analyze", { method: "POST", body: data });
      const strongest = result.risk_predictions.reduce((best: RiskPrediction & { frame: number } | null, item: RiskPrediction & { frame: number }) => (
        !best || item.risk_score > best.risk_score ? item : best
      ), null);
      setUploadMessage(`${result.frames_processed} actual frames analyzed · ${result.detections.length} object detections · ${result.risk_predictions.length} temporal risk predictions.${strongest ? ` Highest model output: ${strongest.class} · score ${strongest.risk_score.toFixed(3)} · frame ${strongest.frame}.` : ""} Predictions are not confirmed accidents.`);
      await refresh();
    } catch (reason) { setUploadMessage(reason instanceof Error ? reason.message : "Video analysis failed"); }
  };

  const uploadImage = async (file?: File) => {
    if (!file) return;
    setImagePreview(URL.createObjectURL(file));
    setImageInference(null);
    setImageInferenceMessage("Preparing uploaded image for model inference…");
    setImageInferenceLoading(true);
    const formData = new FormData();
    formData.append("file", file);
    try {
      const result = await request("/api/inference/vehicle-detection", {
        method: "POST",
        body: formData,
      });
      setImageInference(result);
      setImageInferenceMessage(
        `Actual model inference completed · ${result.detections.length} detections · ${result.latency_ms.toFixed(1)} ms`,
      );
    } catch (reason) {
      setImageInferenceMessage(reason instanceof Error ? reason.message : "Image inference failed");
    } finally {
      setImageInferenceLoading(false);
    }
  };

  const title = nav.find((item) => item.id === view)?.label ?? "Overview";
  const locatedCameras = useMemo(() => cameras.filter((camera) => camera.latitude !== null && camera.longitude !== null), [cameras]);
  const refreshGovernmentData = async () => {
    try { await request("/api/government/refresh", { method: "POST" }); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not request a government data refresh"); }
  };

  if (!token && !guestMode) return <main className="grid min-h-screen place-items-center px-5">
    <div className="grid-bg pointer-events-none fixed inset-0" />
    <form onSubmit={authenticate} className="panel relative w-full max-w-md rounded-2xl p-7 shadow-2xl shadow-black/30">
      <div className="mb-8 flex items-center gap-3"><div className="grid h-10 w-10 place-items-center rounded-xl border border-cyan/30 bg-cyan/10 text-cyan"><Radar size={20} /></div><div><div className="font-display text-lg font-semibold">NexSafe<span className="text-cyan"> AI</span></div><div className="technical text-[9px] uppercase tracking-[.16em] text-slate-500">Secure operator access</div></div></div>
      <div className="mb-6 grid grid-cols-2 rounded-lg border border-slate-800 bg-midnight p-1">
        <button type="button" onClick={() => { setAuthMode("signin"); setError(""); }} className={`rounded-md py-2 text-xs transition ${authMode === "signin" ? "bg-slate-800 text-white" : "text-slate-500 hover:text-slate-200"}`}>Sign in</button>
        <button type="button" onClick={() => { setAuthMode("signup"); setError(""); }} className={`rounded-md py-2 text-xs transition ${authMode === "signup" ? "bg-slate-800 text-white" : "text-slate-500 hover:text-slate-200"}`}>Create account</button>
      </div>
      <h1 className="font-display text-2xl font-semibold">{authMode === "signup" ? "Create your account" : "Welcome back"}</h1><p className="mt-2 text-sm text-slate-400">{authMode === "signup" ? registrationStatus?.first_account ? "The first account becomes the workspace administrator. No sample data is created." : "Create an account in this secured workspace. Registration may be restricted by its administrator." : "Sign in to access your configured monitoring environment."}</p>
      {authMode === "signup" && <div role="status" className="mt-4 rounded-lg border border-slate-800 bg-white/[.02] p-3 text-xs text-slate-400">
        {registrationServiceStatus === "checking" ? "Checking account service…" :
          registrationServiceStatus === "unavailable" ? registrationServiceMessage :
            registrationStatus?.available ? "Account registration is available." : "Account registration is disabled. Ask the workspace administrator to enable ALLOW_REGISTRATION."}
        <button type="button" onClick={() => void checkRegistration()} disabled={registrationServiceStatus === "checking"} className="ml-2 text-cyan underline disabled:opacity-50">Check again</button>
      </div>}
      {authMode === "signup" && <label className="mt-7 block text-xs text-slate-400">Full name<input required maxLength={160} autoComplete="name" value={fullName} onChange={(e) => setFullName(e.target.value)} className="mt-2 w-full rounded-lg border border-slate-700 bg-midnight px-3 py-3 text-sm outline-none focus:border-cyan/60" /></label>}
      <label className={`${authMode === "signup" ? "mt-4" : "mt-7"} block text-xs text-slate-400`}>Email address<input required type="email" maxLength={320} autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} className="mt-2 w-full rounded-lg border border-slate-700 bg-midnight px-3 py-3 text-sm outline-none focus:border-cyan/60" /></label>
      <label className="mt-4 block text-xs text-slate-400">Password<span className="mt-2 flex rounded-lg border border-slate-700 bg-midnight focus-within:border-cyan/60"><input required minLength={authMode === "signup" ? 12 : 1} maxLength={128} type={showPassword ? "text" : "password"} autoComplete={authMode === "signup" ? "new-password" : "current-password"} value={password} onChange={(e) => setPassword(e.target.value)} className="min-w-0 flex-1 rounded-lg bg-transparent px-3 py-3 text-sm outline-none" /><button type="button" aria-label={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword} onClick={() => setShowPassword(!showPassword)} className="px-3 text-slate-500 hover:text-cyan">{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button></span>{authMode === "signup" && <span className="mt-2 block" aria-live="polite"><span className="mb-1.5 flex gap-1">{passwordChecks.map((check, index) => <span key={index} className={`h-1 flex-1 rounded-full ${check ? (passwordIsStrong ? "bg-emerald-400" : "bg-amber-400") : "bg-slate-700"}`} />)}</span><span className={`text-[10px] ${passwordIsStrong ? "text-emerald-300" : "text-slate-500"}`}>{passwordIsStrong ? "Strong password" : "Use at least 12 characters and 3 of: lowercase, uppercase, number, symbol."}</span></span>}</label>
      {authMode === "signup" && <label className="mt-4 block text-xs text-slate-400">Confirm password<span className={`mt-2 flex rounded-lg border bg-midnight focus-within:border-cyan/60 ${confirmPassword && !passwordsMatch ? "border-emergency/60" : "border-slate-700"}`}><input required minLength={12} maxLength={128} type={showPassword ? "text" : "password"} autoComplete="new-password" value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} className="min-w-0 flex-1 rounded-lg bg-transparent px-3 py-3 text-sm outline-none" /><button type="button" aria-label={showPassword ? "Hide password" : "Show password"} aria-pressed={showPassword} onClick={() => setShowPassword(!showPassword)} className="px-3 text-slate-500 hover:text-cyan">{showPassword ? <EyeOff size={16} /> : <Eye size={16} />}</button></span>{confirmPassword && <span className={`mt-1 block text-[10px] ${passwordsMatch ? "text-emerald-300" : "text-rose-300"}`} aria-live="polite">{passwordsMatch ? "Passwords match." : "Passwords do not match."}</span>}</label>}
      {error && <p role="alert" className="mt-4 rounded-lg border border-emergency/20 bg-emergency/[.08] p-3 text-xs text-rose-200">{error}</p>}
      <button type="submit" disabled={authLoading || (authMode === "signup" && (registrationServiceStatus !== "available" || !registrationStatus?.available))} aria-busy={authLoading} className="mt-6 w-full rounded-lg bg-cyan py-3 text-sm font-semibold text-midnight transition hover:bg-cyan/90 disabled:cursor-not-allowed disabled:opacity-50">{authLoading ? (authMode === "signup" ? "Creating account…" : "Signing in…") : authMode === "signup" ? "Create account" : "Sign in securely"}</button>
      {authMode === "signin" && <button type="button" onClick={() => setGuestMode(true)} className="mt-3 w-full rounded-lg border border-slate-700 py-3 text-sm font-medium text-slate-200 transition hover:border-cyan/40 hover:bg-cyan/[.04]">Explore read-only workspace</button>}
      <div className="mt-5 flex items-center gap-2 text-[11px] text-slate-500"><LockKeyhole size={13} /> Account sign-in connects to your configured services.</div>
      <Link href="/" className="mt-4 block text-center text-xs text-cyan hover:text-white">Return to public website</Link>
    </form>
  </main>;

  const SideNav = () => <aside className={`${mobileNav ? "fixed inset-0 z-30 flex" : "hidden"} lg:relative lg:z-auto lg:flex lg:w-[244px] lg:shrink-0 lg:flex-col lg:border-r lg:border-white/[.06] lg:bg-[#0a101c]`}>
    <div className="flex h-full w-[260px] flex-col border-r border-white/[.06] bg-[#0a101c] p-5 lg:w-full">
      <div className="mb-9 flex items-center justify-between"><a href="/" className="flex items-center gap-3"><span className="grid h-9 w-9 place-items-center rounded-xl border border-cyan/25 bg-cyan/10 text-cyan"><Radar size={18} /></span><span className="font-display font-semibold">nexsafe<span className="text-cyan">.ai</span></span></a><button onClick={() => setMobileNav(false)} className="text-slate-500 lg:hidden"><X size={18} /></button></div>
      <div className="technical mb-3 px-3 text-[9px] uppercase tracking-[.18em] text-slate-600">Workspace</div>
      <nav className="space-y-1">{nav.map(({ id, label, icon: Icon }) => <button key={id} onClick={() => { setView(id); setMobileNav(false); }} className={`flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-[13px] transition ${view === id ? "border border-cyan/10 bg-cyan/[.08] text-cyan" : "text-slate-400 hover:bg-white/[.04] hover:text-slate-200"}`}><Icon size={16} />{label}{id === "alerts" && events.some((event) => event.status === "open") && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-emergency" />}</button>)}</nav>
      <div className="mt-auto">
        <div className="mb-4 rounded-xl border border-slate-800 bg-white/[.02] p-3"><div className="flex items-center gap-2 text-xs text-slate-300"><span className={`h-1.5 w-1.5 rounded-full ${model?.status === "loaded" ? "bg-emerald-400" : "bg-amber-400"}`} />{model?.status === "loaded" ? "Model loaded" : "Model not loaded"}</div><p className="technical mt-2 text-[9px] leading-4 text-slate-600">{model?.status === "loaded" ? "INFERENCE READY" : "INFERENCE DISABLED"}</p></div>
        <button onClick={logout} className="flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left text-xs text-slate-500 hover:bg-white/[.04] hover:text-white"><LogOut size={15} /> {guestMode ? "Exit preview" : "Sign out"}</button>
      </div>
    </div>
    {mobileNav && <button aria-label="Close navigation" onClick={() => setMobileNav(false)} className="flex-1 bg-black/60 lg:hidden" />}
  </aside>;

  return <div className="flex min-h-screen bg-midnight">
    <SideNav />
    <main className="min-w-0 flex-1">
      <header className="sticky top-0 z-20 flex h-[68px] items-center justify-between border-b border-white/[.06] bg-midnight/85 px-5 backdrop-blur-xl sm:px-8">
        <div className="flex items-center gap-3"><button onClick={() => setMobileNav(true)} className="text-slate-400 lg:hidden"><Menu size={19} /></button><div><h1 className="font-display text-sm font-semibold">{title}</h1><p className="technical mt-0.5 hidden text-[9px] uppercase tracking-[.14em] text-slate-600 sm:block">NexSafe operations / {view}</p></div></div>
        <div className="flex items-center gap-3">{guestMode && <span className="rounded-md border border-amber-400/20 bg-amber-400/[.06] px-2 py-1 text-[9px] text-amber-200">READ-ONLY · NOT CONNECTED</span>}<span className="hidden items-center gap-2 text-[10px] text-slate-500 sm:flex"><span className={`h-1.5 w-1.5 rounded-full ${realtimeStatus === "connected" ? "bg-emerald-400" : "bg-amber-400"}`} />{guestMode ? "NO LIVE DATA CONNECTION" : `LIVE UPDATES ${realtimeStatus.toUpperCase()}`}</span>{!guestMode && <button aria-label="Refresh data" onClick={() => void refresh()} className="rounded-lg border border-slate-800 p-2 text-slate-400 transition hover:border-cyan/40 hover:text-cyan"><RefreshCw size={14} className={loading ? "animate-spin" : ""} /></button>}</div>
      </header>
      <div className="mx-auto max-w-[1500px] p-5 sm:p-8">
        {authSuccess && <div role="status" className="mb-5 rounded-lg border border-emerald-400/20 bg-emerald-400/[.06] px-4 py-3 text-xs text-emerald-200">Account created successfully. You are now signed in.</div>}
        {guestMode && <div className="mb-5 rounded-lg border border-amber-400/20 bg-amber-400/[.05] px-4 py-3 text-xs leading-5 text-amber-100/80">Read-only workspace preview. No account is signed in, no service data is connected, and no sample records are displayed. To manage cameras or view real data, sign in to a configured backend.</div>}
        {error && <div role="alert" className="mb-5 flex items-start justify-between gap-3 rounded-lg border border-emergency/20 bg-emergency/[.07] px-4 py-3 text-sm text-rose-200"><span>{error}</span><button onClick={() => setError("")}><X size={15} /></button></div>}
        {view === "overview" && <OverviewView overview={overview} events={events} model={model} systemMetrics={systemMetrics} governmentData={governmentData} governmentBackendUnavailable={governmentBackendUnavailable} loading={loading} dataAvailable={dataAvailable} onNavigate={setView} />}
        {view === "monitoring" && <MonitoringView cameras={cameras} liveFrames={liveFrames} readOnly={guestMode} dataAvailable={dataAvailable} onAdd={() => setCameraForm(true)} onUpload={uploadVideo} onImageUpload={uploadImage} imagePreview={imagePreview} imageInference={imageInference} imageInferenceMessage={imageInferenceMessage} imageInferenceLoading={imageInferenceLoading} onStart={async (id) => { try { await request(`/api/cameras/${id}/start`, { method: "POST" }); } catch (e) { setError(e instanceof Error ? e.message : "Could not start camera"); } }} onStop={async (id) => { try { await request(`/api/cameras/${id}/stop`, { method: "POST" }); } catch (e) { setError(e instanceof Error ? e.message : "Could not stop camera"); } }} uploadMessage={uploadMessage} />}
        {view === "alerts" && <AlertsView events={events} dataAvailable={dataAvailable} onUpdate={updateEvent} />}
        {view === "map" && <MapSection cameras={cameras} located={locatedCameras} dataAvailable={dataAvailable} />}
        {view === "analytics" && <AnalyticsView analytics={analytics} governmentData={governmentData} dataAvailable={dataAvailable} />}
        {view === "model" && <ModelView model={model} datasetStatus={datasetStatus} dataAvailable={dataAvailable} />}
        {view === "government" && <GovernmentDataView governmentData={governmentData} dataAvailable={dataAvailable} backendUnavailable={governmentBackendUnavailable} onRefresh={refreshGovernmentData} />}
      </div>
    </main>
    {cameraForm && !guestMode && <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4 backdrop-blur-sm"><form onSubmit={createCamera} className="panel w-full max-w-lg rounded-2xl p-6">
      <div className="flex items-start justify-between"><div><h2 className="font-display text-lg font-semibold">Register a camera</h2><p className="mt-1 text-xs text-slate-500">Authorized camera source only. Credentials are never returned by the API.</p></div><button type="button" onClick={() => setCameraForm(false)} className="text-slate-500"><X size={18} /></button></div>
      <label className="mt-6 block text-xs text-slate-400">Camera name<input required value={cameraName} onChange={(e) => setCameraName(e.target.value)} placeholder="Intersection camera 01" className="mt-2 w-full rounded-lg border border-slate-700 bg-midnight px-3 py-2.5 text-sm" /></label>
      <label className="mt-4 block text-xs text-slate-400">Device index or stream URL<input required value={cameraSource} onChange={(e) => setCameraSource(e.target.value)} placeholder="0 or rtsp://…" className="technical mt-2 w-full rounded-lg border border-slate-700 bg-midnight px-3 py-2.5 text-xs" /></label>
      <div className="mt-4 grid grid-cols-2 gap-3"><label className="text-xs text-slate-400">Latitude<input type="number" step="any" min="-90" max="90" value={cameraLatitude} onChange={(e) => setCameraLatitude(e.target.value)} className="mt-2 w-full rounded-lg border border-slate-700 bg-midnight px-3 py-2.5 text-sm" /></label><label className="text-xs text-slate-400">Longitude<input type="number" step="any" min="-180" max="180" value={cameraLongitude} onChange={(e) => setCameraLongitude(e.target.value)} className="mt-2 w-full rounded-lg border border-slate-700 bg-midnight px-3 py-2.5 text-sm" /></label></div>
      <label className="mt-4 block text-xs text-slate-400">IMD weather station ID (optional)<input value={cameraWeatherStationId} onChange={(e) => setCameraWeatherStationId(e.target.value)} placeholder="Official station identifier" className="technical mt-2 w-full rounded-lg border border-slate-700 bg-midnight px-3 py-2.5 text-xs" /></label>
      <p className="mt-4 text-[10px] leading-4 text-amber-200/70">A saved camera is registered, not necessarily reachable. Add its authorized host to CAMERA_ALLOWED_HOSTS; YOLO weights are required for stream processing.</p>
      <button className="mt-5 w-full rounded-lg bg-cyan py-2.5 text-sm font-semibold text-midnight">Save camera configuration</button>
    </form></div>}
  </div>;
}

function SectionHeading({ eyebrow, title, detail }: { eyebrow: string; title: string; detail: string }) {
  return <div className="mb-7"><p className="technical text-[9px] uppercase tracking-[.2em] text-cyan/80">{eyebrow}</p><div className="mt-2 flex flex-wrap items-end justify-between gap-3"><div><h2 className="font-display text-2xl font-semibold tracking-tight">{title}</h2><p className="mt-1.5 text-xs text-slate-500">{detail}</p></div></div></div>;
}
function Metric({ label, value, note, icon: Icon, tone = "cyan" }: { label: string; value: string; note: string; icon: typeof Activity; tone?: string }) {
  return (
    <article className="panel rounded-xl p-4 sm:p-5">
      <div className="flex items-start justify-between">
        <span className="text-xs text-slate-400">{label}</span>
        <span className={`rounded-lg p-2 ${tone === "red" ? "bg-emergency/10 text-emergency" : "bg-cyan/[.08] text-cyan"}`}>
          <Icon size={15} />
        </span>
      </div>
      <div className="technical mt-5 text-2xl font-medium tracking-tight">{value}</div>
      <div className="mt-2 text-[10px] text-slate-600">{note}</div>
    </article>
  );
}
function OverviewView({ overview, events, model, systemMetrics, governmentData, governmentBackendUnavailable, loading, dataAvailable, onNavigate }: { overview: Overview | null; events: EventRecord[]; model: Model | null; systemMetrics: { cpu_percent: number; memory_percent: number; gpu: { available: boolean } } | null; governmentData: GovernmentData | null; governmentBackendUnavailable: boolean; loading: boolean; dataAvailable: boolean; onNavigate: (view: View) => void }) {
  return <><SectionHeading eyebrow="Command center" title="Road safety overview" detail="Metrics reflect registered records and actual inference. No connected sources are assumed." />
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      <Metric label="Connected cameras" value={dataAvailable && overview ? String(overview.connected_cameras) : "—"} note={dataAvailable ? overview?.camera_status_note || "Awaiting live data" : "Service data unavailable"} icon={Camera} />
      <Metric label="Active incidents" value={dataAvailable && overview ? String(overview.active_incidents) : "—"} note={!dataAvailable ? "Service data unavailable" : overview?.active_incidents ? "Open or acknowledged stored events" : "No active incidents recorded"} icon={AlertTriangle} tone="red" />
      <Metric label="Frames processed" value={dataAvailable && overview ? overview.processed_frames.toLocaleString() : "—"} note={dataAvailable ? "From completed inference records" : "Service data unavailable"} icon={Eye} />
      <Metric label="Current inference FPS" value={dataAvailable && overview?.current_inference_fps != null ? overview.current_inference_fps.toFixed(1) : "—"} note={dataAvailable ? "Measured across active streams" : "Service data unavailable"} icon={Activity} />
      <Metric label="Mean inference latency" value={dataAvailable && overview?.inference_latency_ms != null ? `${overview.inference_latency_ms.toFixed(1)} ms` : "—"} note={dataAvailable ? "Recorded inference windows" : "Service data unavailable"} icon={Activity} />
    </div>
    <div className="mt-4 flex flex-wrap gap-3 text-[10px] text-slate-500"><span className="rounded-md border border-slate-800 px-3 py-2">CPU utilization <span className="technical ml-1 text-slate-300">{systemMetrics ? `${systemMetrics.cpu_percent.toFixed(1)}%` : "Unavailable"}</span></span><span className="rounded-md border border-slate-800 px-3 py-2">Memory utilization <span className="technical ml-1 text-slate-300">{systemMetrics ? `${systemMetrics.memory_percent.toFixed(1)}%` : "Unavailable"}</span></span><span className="rounded-md border border-slate-800 px-3 py-2">GPU <span className="ml-1 text-slate-300">{systemMetrics ? (systemMetrics.gpu.available ? "Available" : "Unavailable") : "Unavailable"}</span></span></div>
    <div className="mt-5 grid gap-4 xl:grid-cols-[1.35fr_.65fr]">
      <section className="panel rounded-xl p-5"><div className="flex items-center justify-between"><div><h3 className="font-display text-sm font-medium">Event activity</h3><p className="mt-1 text-[10px] text-slate-500">Persisted events · most recent first</p></div><button onClick={() => onNavigate("alerts")} className="text-[11px] text-cyan hover:text-white">View event log →</button></div>
        {events.length ? <div className="mt-5 space-y-3">{events.slice(0, 5).map((event) => <div key={event.id} className="flex items-center gap-3 border-t border-white/[.05] pt-3"><span className={`h-2 w-2 rounded-full ${event.status === "resolved" ? "bg-emerald-400" : "bg-amber-400"}`} /><div className="min-w-0 flex-1"><div className="truncate text-xs text-slate-200">{event.event_type === "predicted_risk" ? "Predicted risk · not a confirmed accident" : event.event_type}</div><div className="technical mt-1 text-[9px] text-slate-600">{event.camera_id || "NO CAMERA"} · {new Date(event.occurred_at).toLocaleString()}</div></div><span className="text-[10px] text-slate-500">{event.status}</span></div>)}</div>
          : <EmptyState icon={Activity} title={!dataAvailable ? "Awaiting live data" : loading ? "Loading stored events" : "No incidents recorded"} description={!dataAvailable ? "No authenticated backend data is connected in this session." : "Recorded events will appear here when produced by a configured inference pipeline."} />}
      </section>
      <section className="panel rounded-xl p-5"><div className="flex items-center justify-between"><div><h3 className="font-display text-sm font-medium">Inference status</h3><p className="mt-1 text-[10px] text-slate-500">Configured model availability</p></div><Cpu size={16} className="text-cyan" /></div>
        <div className="mt-5 rounded-lg border border-white/[.06] bg-black/10 p-4"><div className="flex items-center gap-2 text-xs"><span className={`h-1.5 w-1.5 rounded-full ${model?.status === "loaded" ? "bg-emerald-400" : "bg-amber-400"}`} />{model?.status === "loaded" ? "Model loaded" : "Model not loaded"}</div><p className="mt-3 text-xs leading-5 text-slate-500">{model?.message || "Model status unavailable."}</p></div>
        <button onClick={() => onNavigate("model")} className="mt-4 text-[11px] text-cyan hover:text-white">Open model center →</button>
      </section>
    </div>
    <div className="mt-5 grid gap-4 md:grid-cols-3">
      <QuickCard icon={Video} title="Live monitoring" detail="Register an authorized camera or upload video for configured model analysis." onClick={() => onNavigate("monitoring")} />
      <QuickCard icon={Map} title="Geospatial view" detail="Explore only cameras with registered coordinates on OpenStreetMap." onClick={() => onNavigate("map")} />
      <QuickCard icon={CloudSun} title="Government data" detail={governmentData ? "View source connectivity, actual IMD readings, and historical MoRTH records." : "Check government source configuration and synchronization."} onClick={() => onNavigate("government")} />
    </div>
    <GovernmentOverviewSection governmentData={governmentData} dataAvailable={dataAvailable} backendUnavailable={governmentBackendUnavailable} onOpen={() => onNavigate("government")} />
  </>;
}
function GovernmentOverviewSection({ governmentData, dataAvailable, backendUnavailable, onOpen }: { governmentData: GovernmentData | null; dataAvailable: boolean; backendUnavailable: boolean; onOpen: () => void }) {
  const sources = governmentData?.sources ?? {};
  const observationSource = sources.imd_observations;
  const observations = asRecords(observationSource?.data?.observations);
  const firstObservation = observations[0];
  const warningsSource = sources.imd_warnings;
  const warnings = asRecords(warningsSource?.data?.warnings);
  return <section className="panel mt-5 rounded-xl p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-display text-sm font-medium">Government data connections</h3><p className="mt-1 text-[10px] text-slate-500">Provider status, verified observation, and last successful synchronization.</p></div><button onClick={onOpen} className="text-[10px] text-cyan hover:text-white">Open source center →</button></div>
    {!dataAvailable && <p className="mt-4 text-xs text-amber-200">Government data service unavailable. Any displayed values are from its last response; current freshness cannot be confirmed.</p>}
    {!dataAvailable && !governmentData ? <p className="mt-2 text-xs text-slate-500">No cached government data is available in this browser session.</p> :
      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_1fr]"><div className="space-y-2">{Object.values(sources).map((source) => <div key={source.key} className="flex items-center justify-between gap-3 border-b border-white/[.04] pb-2 text-[10px]"><span className="text-slate-400">{source.name}</span><span className={backendUnavailable ? "text-amber-200" : source.status === "connected" ? "text-emerald-300" : source.status === "stale" ? "text-amber-200" : "text-slate-500"}>{backendUnavailable ? "service unavailable · freshness unconfirmed" : `${source.status.replace(/_/g, " ")} · ${source.freshness.replace(/_/g, " ")}`}</span></div>)}</div>
        <div className="rounded-lg border border-slate-800 p-3"><h4 className="text-[10px] font-medium text-slate-300">Latest cached IMD observation</h4>{firstObservation ? <><p className="technical mt-2 text-[9px] text-slate-500">{displayValue(firstObservation.station)} · {displayValue(firstObservation.station_id)} · {sourceDate(typeof firstObservation.observed_at === "string" ? firstObservation.observed_at : null)}</p><p className="mt-2 text-[10px] text-slate-300">Temperature {displayValue(firstObservation.temperature_c)}°C · humidity {displayValue(firstObservation.humidity_percent)}% · wind {displayValue(firstObservation.wind_speed_kmph)} km/h · rainfall {displayValue(firstObservation.rainfall_24h_mm)} mm</p><p className="mt-1 text-[9px] text-slate-500">Source values only · {observationSource?.freshness?.replace(/_/g, " ")}</p></> : <p className="mt-2 text-[10px] text-slate-500">{observationSource?.status === "not_configured" ? "IMD observations not configured." : "Awaiting live data."}</p>}{warnings.length > 0 && <p className="mt-2 text-[9px] text-amber-200">Cached IMD response contains {warnings.length} warning record(s) · {warningsSource?.freshness?.replace(/_/g, " ")}. Review details in Government Data.</p>}{warningsSource?.status === "stale" && <p className="mt-2 text-[9px] text-amber-200">Warning data is stale; last verified source timestamp is preserved.</p>}</div>
      </div>}
  </section>;
}
function QuickCard({ icon: Icon, title, detail, onClick }: { icon: typeof Video; title: string; detail: string; onClick: () => void }) {
  return <button onClick={onClick} className="panel flex items-start gap-4 rounded-xl p-5 text-left transition hover:border-cyan/25"><span className="rounded-lg bg-cyan/[.08] p-2.5 text-cyan"><Icon size={17} /></span><span><span className="block text-sm font-medium">{title}</span><span className="mt-1 block text-xs leading-5 text-slate-500">{detail}</span></span></button>;
}
function EmptyState({ icon: Icon, title, description, action }: { icon: typeof Activity; title: string; description: string; action?: ReactNode }) {
  return <div className="my-5 flex min-h-44 flex-col items-center justify-center rounded-xl border border-dashed border-slate-800 px-6 text-center"><span className="mb-3 rounded-xl border border-slate-800 bg-white/[.02] p-3 text-slate-500"><Icon size={19} /></span><h4 className="text-xs font-medium text-slate-300">{title}</h4><p className="mt-2 max-w-md text-[11px] leading-5 text-slate-500">{description}</p>{action}</div>;
}
function MonitoringView({ cameras, liveFrames, readOnly, dataAvailable, onAdd, onUpload, onImageUpload, imagePreview, imageInference, imageInferenceMessage, imageInferenceLoading, onStart, onStop, uploadMessage }: { cameras: CameraRecord[]; liveFrames: Record<string, LiveFrame>; readOnly: boolean; dataAvailable: boolean; onAdd: () => void; onUpload: (file?: File) => void; onImageUpload: (file?: File) => void; imagePreview: string | null; imageInference: ImageInference | null; imageInferenceMessage: string; imageInferenceLoading: boolean; onStart: (id: string) => void; onStop: (id: string) => void; uploadMessage: string }) {
  return <><SectionHeading eyebrow="Source monitoring" title="Live camera monitoring" detail="No stream is shown unless a real, authorized source and processing worker are available." />
    {!readOnly && dataAvailable && <div className="mb-5 flex flex-wrap gap-2"><button onClick={onAdd} className="inline-flex items-center gap-2 rounded-lg bg-cyan px-3.5 py-2.5 text-xs font-semibold text-midnight"><Plus size={14} /> Register camera</button><label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-700 px-3.5 py-2.5 text-xs text-slate-300 transition hover:border-cyan/40"><Eye size={14} /> Analyze image<input type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={(e) => { onImageUpload(e.target.files?.[0]); e.currentTarget.value = ""; }} /></label><label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-slate-700 px-3.5 py-2.5 text-xs text-slate-300 transition hover:border-cyan/40"><ArrowDownToLine size={14} /> Analyze video upload<input type="file" accept="video/mp4,video/quicktime,video/x-msvideo,video/webm" className="hidden" onChange={(e) => { onUpload(e.target.files?.[0]); e.currentTarget.value = ""; }} /></label></div>}
    {imageInferenceMessage && <section className="panel mb-5 rounded-xl p-4"><p role="status" className={`text-xs ${imageInference ? "text-cyan" : "text-amber-200"}`}>{imageInferenceLoading ? "Running actual detector inference…" : imageInferenceMessage}</p>
      {imagePreview && <div className="relative mt-3 inline-block max-w-full overflow-hidden rounded-lg border border-slate-800"><img src={imagePreview} alt="Uploaded image analyzed by the configured detector" className="block h-auto max-h-[560px] max-w-full object-contain" />{imageInference && <svg className="absolute inset-0 h-full w-full" viewBox={`0 0 ${imageInference.image_dimensions.width} ${imageInference.image_dimensions.height}`} preserveAspectRatio="none" aria-label="Actual vehicle detection bounding boxes">{imageInference.detections.map((detection, index) => { const [x1, y1, x2, y2] = detection.xyxy; return <g key={`${detection.class_id}-${index}`}><rect x={x1} y={y1} width={x2 - x1} height={y2 - y1} fill="none" stroke="#00E5FF" strokeWidth={Math.max(2, imageInference.image_dimensions.width / 500)} /><text x={x1} y={Math.max(14, y1 - 4)} fill="#00E5FF" fontSize={Math.max(14, imageInference.image_dimensions.width / 80)} paintOrder="stroke" stroke="#080D18" strokeWidth="3">{detection.label} {(detection.confidence * 100).toFixed(1)}%</text></g>; })}</svg>}</div>}
      {imageInference && imageInference.detections.length === 0 && <p className="mt-2 text-[10px] text-slate-500">The detector returned no objects for this image.</p>}
    </section>}
    {uploadMessage && <div className="mb-4 rounded-lg border border-slate-800 bg-slatepanel/70 p-3 text-xs text-slate-300">{uploadMessage}</div>}
    {cameras.length ? <div className="grid gap-4 md:grid-cols-2">{cameras.map((camera) => <article key={camera.id} className="panel overflow-hidden rounded-xl">
      <div className="relative grid aspect-video place-items-center bg-[#080e18]">{liveFrames[camera.id]?.image ? <img src={liveFrames[camera.id].image} alt={`Live annotated frame from ${camera.name}`} className="h-full w-full object-contain" /> : <div className="grid h-14 w-14 place-items-center rounded-2xl border border-slate-800 bg-white/[.02] text-slate-600"><Video size={23} /></div>}<div className="absolute left-4 top-4 flex items-center gap-2 rounded-md border border-slate-700 bg-midnight/80 px-2 py-1 text-[9px] text-slate-400"><span className={`h-1.5 w-1.5 rounded-full ${(liveFrames[camera.id]?.status ?? camera.connection_status) === "connected" ? "bg-emerald-400" : "bg-slate-500"}`} /> {(liveFrames[camera.id]?.status ?? camera.connection_status) === "not_started" ? "NOT STARTED" : (liveFrames[camera.id]?.status ?? camera.connection_status).toUpperCase()}</div>{liveFrames[camera.id]?.image ? <div className="absolute bottom-3 right-3 rounded bg-midnight/85 px-2 py-1 technical text-[9px] text-cyan">{liveFrames[camera.id].fps?.toFixed(1)} FPS · {liveFrames[camera.id].latency?.toFixed(1)} ms · {liveFrames[camera.id].detections} detections · flow {liveFrames[camera.id].opticalFlow?.toFixed(2) ?? "—"}</div> : <div className="absolute bottom-4 left-4 right-4 text-center text-[10px] text-slate-600">{!dataAvailable ? "Camera service unavailable" : "Awaiting a verified real stream connection"}</div>}{liveFrames[camera.id]?.risk && <div className="absolute left-3 right-3 top-12 rounded-md border border-amber-300/30 bg-midnight/90 p-2 text-[10px] text-amber-100">PREDICTED RISK · {liveFrames[camera.id].risk?.class} · {(liveFrames[camera.id].risk?.risk_score ?? 0).toFixed(3)} · {((liveFrames[camera.id].risk?.confidence ?? 0) * 100).toFixed(1)}% model confidence <span className="block text-[9px] text-amber-100/60">Model output only; not a confirmed accident. Weather used by model: {liveFrames[camera.id].risk?.weather_used_by_model ? "yes" : "no"}. {liveFrames[camera.id].risk?.environmental_context?.weather?.status === "available" ? `Linked IMD station ${liveFrames[camera.id].risk?.environmental_context?.weather?.station_id} observed ${liveFrames[camera.id].risk?.environmental_context?.weather?.observed_at || "time unavailable"} UTC (context only).` : ""}</span></div>}</div>
      <div className="flex items-center justify-between p-4"><div><h3 className="text-xs font-medium">{camera.name}</h3><p className="technical mt-1 text-[9px] text-slate-600">{camera.id.slice(0, 8)} · REGISTERED {new Date(camera.created_at).toLocaleDateString()}</p><p className="mt-1 text-[9px] text-slate-500">IMD context {camera.weather_station_id ? `· station ${camera.weather_station_id}` : "not linked"}</p></div>{!readOnly && (liveFrames[camera.id]?.status === "connected" || liveFrames[camera.id]?.status === "connecting" ? <button onClick={() => onStop(camera.id)} className="rounded-md border border-emergency/30 px-3 py-1.5 text-[10px] text-rose-200 hover:bg-emergency/10">Stop processing</button> : <button onClick={() => onStart(camera.id)} className="rounded-md border border-slate-700 px-3 py-1.5 text-[10px] text-slate-400 hover:border-cyan/40 hover:text-cyan">Start processing</button>)}</div>
    </article>)}</div> : <section className="panel rounded-xl p-3"><EmptyState icon={Camera} title={!dataAvailable || readOnly ? "Awaiting live camera data" : "No cameras registered"} description={!dataAvailable || readOnly ? "No authenticated camera records are connected in this session." : "Register an authorized camera source to begin. No synthetic feed is shown."} action={!readOnly && dataAvailable ? <button onClick={onAdd} className="mt-4 inline-flex items-center gap-2 rounded-md border border-cyan/30 px-3 py-2 text-[10px] text-cyan"><Plus size={13} /> Register a camera</button> : undefined} /></section>}
    <p className="mt-5 flex items-start gap-2 text-[10px] leading-5 text-slate-600"><CircleHelp size={13} className="mt-0.5 shrink-0" />Live stream processing and video analysis require actual model weights. Without them, inference is disabled and no detections are produced.</p>
  </>;
}
function AlertsView({ events, dataAvailable, onUpdate }: { events: EventRecord[]; dataAvailable: boolean; onUpdate: (id: string, status: string) => void }) {
  return <><SectionHeading eyebrow="Incident workflow" title="Alert center" detail="Only events stored by the backend are listed. No notifications are synthesized." />
    {events.length ? <div className="space-y-3">{events.map((event) => <article key={event.id} className="panel flex flex-col gap-4 rounded-xl p-4 sm:flex-row sm:items-center"><span className={`grid h-10 w-10 shrink-0 place-items-center rounded-lg ${event.status === "resolved" ? "bg-emerald-500/10 text-emerald-400" : "bg-emergency/10 text-emergency"}`}><AlertTriangle size={17} /></span><div className="min-w-0 flex-1"><div className="flex flex-wrap items-center gap-2"><h3 className="text-sm font-medium">{event.event_type === "predicted_risk" ? "Predicted risk" : event.event_type}</h3>{event.event_type === "predicted_risk" && <span className="rounded-full border border-amber-300/20 px-2 py-0.5 text-[9px] text-amber-200">NOT A CONFIRMED ACCIDENT</span>}<span className="rounded-full border border-slate-700 px-2 py-0.5 text-[9px] uppercase text-slate-400">{event.status}</span></div><p className="technical mt-1.5 text-[9px] text-slate-500">{new Date(event.occurred_at).toLocaleString()} · camera {event.camera_id || "unknown"}</p><p className="mt-2 break-all text-[11px] text-slate-500">{event.details || "No further event details recorded."}{event.risk_score !== null && ` · model risk score ${event.risk_score}`}{event.model_confidence !== null && ` · model confidence ${event.model_confidence}`}</p></div><div className="flex gap-2">{event.status === "open" && <button onClick={() => onUpdate(event.id, "acknowledged")} className="rounded-md border border-slate-700 px-3 py-2 text-[10px] text-slate-300">Acknowledge</button>}{event.status !== "resolved" && <button onClick={() => onUpdate(event.id, "resolved")} className="inline-flex items-center gap-1.5 rounded-md bg-cyan/10 px-3 py-2 text-[10px] text-cyan"><Check size={12} /> Resolve</button>}</div></article>)}</div> : <section className="panel rounded-xl p-3"><EmptyState icon={ShieldAlert} title={dataAvailable ? "No incidents recorded" : "Awaiting live data"} description={dataAvailable ? "Alerts appear only when real events have been persisted by a configured data pipeline." : "No authenticated event records are connected in this session."} /></section>}
  </>;
}
function MapSection({ cameras, located, dataAvailable }: { cameras: CameraRecord[]; located: CameraRecord[]; dataAvailable: boolean }) {
  return <><SectionHeading eyebrow="Geospatial operations" title="Registered camera map" detail="OpenStreetMap tiles · markers use saved camera coordinates only. No risk zones are inferred." />
    {located.length ? <div className="panel p-3"><MapView cameras={cameras} /></div> : <section className="panel rounded-xl p-3"><EmptyState icon={Map} title={dataAvailable ? "No camera locations available" : "Awaiting live location data"} description={dataAvailable ? "Register camera coordinates to see them on OpenStreetMap. NexSafe does not invent a default location." : "No authenticated camera data is connected in this session."} /></section>}
    {dataAvailable && <p className="mt-3 text-[10px] text-slate-500">{located.length} cameras with coordinates · {cameras.length - located.length} without location. {located.length ? "" : "No camera locations available."}</p>}
  </>;
}
function AnalyticsView({ analytics, governmentData, dataAvailable }: { analytics: Analytics | null; governmentData: GovernmentData | null; dataAvailable: boolean }) {
  const max = Math.max(1, ...(analytics?.events_by_day.map((row) => row.count) ?? []));
  return <><SectionHeading eyebrow="Evidence-based analysis" title="Incident analytics" detail="Charts are computed from persisted events. No generated samples, extrapolations, or unsupported risk claims." />
    {analytics?.status !== "available" ? <section className="panel rounded-xl p-3"><EmptyState icon={BarChart3} title={dataAvailable ? "INSUFFICIENT DATA FOR ANALYSIS" : "Awaiting live data"} description={dataAvailable ? analytics?.message || "Analytics are unavailable until event records can be loaded." : "No authenticated analytics data is connected in this session."} /></section>
      : <><div className="mb-4 grid gap-3 sm:grid-cols-2"><Metric label="Stored events" value={String(analytics.event_count)} note="Record count across database" icon={AlertTriangle} /><Metric label="Event categories" value={String(analytics.by_type.length)} note="Distinct stored event types" icon={BarChart3} /></div>
        <div className="grid gap-4 xl:grid-cols-2"><section className="panel rounded-xl p-5"><h3 className="text-sm font-medium">Events by date</h3><p className="mt-1 text-[10px] text-slate-500">Daily event totals · database timestamps</p>{analytics.events_by_day.length ? <div className="mt-6 flex h-48 items-end gap-2 overflow-x-auto border-b border-slate-800 pb-2">{analytics.events_by_day.map((row) => <div key={row.date} className="flex h-full min-w-8 flex-1 flex-col items-center justify-end gap-2"><span className="technical text-[9px] text-slate-500">{row.count}</span><div className="w-full max-w-10 rounded-t bg-gradient-to-t from-blue-600/70 to-cyan" style={{ height: `${Math.max(4, (row.count / max) * 78)}%` }} /><span className="technical whitespace-nowrap text-[8px] text-slate-600">{row.date.slice(5)}</span></div>)}</div> : <EmptyState icon={BarChart3} title="Insufficient data" description="No daily event data available." />}</section>
          <section className="panel rounded-xl p-5"><h3 className="text-sm font-medium">Events by type</h3><p className="mt-1 text-[10px] text-slate-500">Actual category counts</p><div className="mt-5 space-y-4">{analytics.by_type.map((row) => <div key={row.type}><div className="mb-1.5 flex justify-between text-[11px]"><span>{row.type}</span><span className="technical text-slate-500">{row.count}</span></div><div className="h-1.5 overflow-hidden rounded-full bg-slate-800"><div className="h-full rounded-full bg-cyan" style={{ width: `${(row.count / analytics.event_count) * 100}%` }} /></div></div>)}</div></section></div></>}
    <MoRTHHistoricalSection source={governmentData?.sources.morth_accidents ?? null} dataAvailable={dataAvailable || Boolean(governmentData)} />
  </>;
}
function asRecords(value: unknown): GovernmentRecord[] {
  return Array.isArray(value) ? value.filter((row): row is GovernmentRecord => Boolean(row) && typeof row === "object" && !Array.isArray(row)) : [];
}
function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  try { return JSON.stringify(value); } catch { return "—"; }
}
function sourceDate(value: string | null | undefined): string {
  if (!value) return "Not provided by source";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : `${parsed.toLocaleString(undefined, { timeZone: "UTC" })} UTC`;
}
function GovernmentSourceStatus({ source, backendUnavailable }: { source: GovernmentSource; backendUnavailable: boolean }) {
  const statusClass = backendUnavailable ? "text-amber-200" : source.status === "connected" ? "text-emerald-300" : source.status === "stale" ? "text-amber-200" : "text-slate-400";
  return <section className="panel rounded-xl p-4">
    <div className="flex items-start justify-between gap-3"><div><h3 className="text-xs font-medium text-slate-200">{source.name}</h3><p className={`technical mt-1 text-[9px] uppercase ${statusClass}`}>{backendUnavailable ? "service unavailable · freshness unconfirmed" : `${source.status.replace(/_/g, " ")} · ${source.freshness.replace(/_/g, " ")}`}</p></div><ExternalLink size={14} className="shrink-0 text-slate-600" /></div>
    <div className="mt-4 space-y-2 text-[10px] text-slate-500"><p>Source timestamp: <span className="text-slate-300">{sourceDate(source.source_timestamp)}</span></p><p>Last successful sync: <span className="text-slate-300">{sourceDate(source.last_successful_sync)}</span></p></div>
    {source.error && <p className={`mt-3 text-[10px] leading-4 ${source.status === "not_configured" ? "text-slate-500" : "text-amber-200/80"}`}>{source.status === "stale" || source.status === "unavailable" ? "Government data source temporarily unavailable. " : ""}{source.error}</p>}
    <a href={source.source_url} target="_blank" rel="noreferrer" className="mt-3 inline-block text-[9px] text-cyan hover:text-white">Official source ↗</a>
  </section>;
}
function MoRTHHistoricalSection({ source, dataAvailable }: { source: GovernmentSource | null; dataAvailable: boolean }) {
  const rows = asRecords(source?.data?.records);
  const columns = rows.length ? Object.keys(rows[0]).slice(0, 7) : [];
  const metadata = source?.data?.metadata;
  const title = metadata && typeof metadata === "object" ? (metadata as GovernmentRecord).title : null;
  const reportingYears = source?.data?.reporting_years;
  const yearList = Array.isArray(reportingYears) ? reportingYears.map(displayValue).join(", ") : "";
  return <section className="panel mt-5 rounded-xl p-5">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-display text-sm font-medium">Official MoRTH historical statistics</h3><p className="mt-1 text-[10px] text-slate-500">Published dataset from Open Government Data India · historical reporting, not live incidents.</p></div><span className="rounded border border-slate-700 px-2 py-1 text-[9px] text-slate-400">{source?.freshness === "historical" ? "HISTORICAL DATA" : source?.status?.toUpperCase() ?? "NOT CONNECTED"}</span></div>
    {source?.status === "stale" && <p className="mt-4 text-xs text-amber-200">Government data source temporarily unavailable. Showing the last verified dataset; its original source timestamp is preserved.</p>}
    {!dataAvailable ? <EmptyState icon={BarChart3} title="Government data source temporarily unavailable" description="The authenticated backend is not available; no local substitute is displayed." /> :
      source?.status === "not_configured" || !source ? <EmptyState icon={BarChart3} title="MoRTH dataset not configured" description="Set MORTH_OGD_RESOURCE_ID to a road-accident dataset from the official OGD catalog and provide an OGD API key. No statistics are generated locally." /> :
      rows.length ? <>
        <div className="mt-4 flex flex-wrap gap-4 text-[10px] text-slate-400"><span>Reporting years: <b className="font-normal text-slate-200">{yearList || "Not identified in source records"}</b></span><span>Rows fetched: <b className="font-normal text-slate-200">{displayValue(source.data?.records_fetched)}</b></span>{title !== null && title !== undefined ? <span>Dataset: <b className="font-normal text-slate-200">{displayValue(title)}</b></span> : null}</div>
        <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[640px] border-collapse text-left text-[10px]"><thead><tr>{columns.map((column) => <th key={column} className="border-b border-slate-700 px-3 py-2 font-medium text-slate-400">{column}</th>)}</tr></thead><tbody>{rows.slice(0, 10).map((row, index) => <tr key={index} className="border-b border-white/[.04]">{columns.map((column) => <td key={column} className="px-3 py-2 text-slate-300">{displayValue(row[column])}</td>)}</tr>)}</tbody></table></div>
        {Boolean(source.data?.truncated) && <p className="mt-3 text-[9px] text-amber-200/70">Dataset pagination reached the configured fetch limit; shown records are a partial source response.</p>}
      </> : <EmptyState icon={BarChart3} title={source.status === "connected" ? "No records returned by source" : "Government data source temporarily unavailable"} description={source.status === "connected" ? "The verified OGD resource returned no accident records." : "No local substitute is displayed. The source status and last verified timestamp are shown above."} />}
  </section>;
}
function OGDResourceSection({ source }: { source: GovernmentSource }) {
  const rows = asRecords(source.data?.records);
  const columns = rows.length ? Object.keys(rows[0]).slice(0, 7) : [];
  const metadata = source.data?.metadata;
  const title = metadata && typeof metadata === "object" ? (metadata as GovernmentRecord).title : null;
  return <section className="panel mt-5 rounded-xl p-5"><div><h3 className="font-display text-sm font-medium">{title ? displayValue(title) : source.name}</h3><p className="mt-1 text-[10px] text-slate-500">Open Government Data India · dataset values and dates are provider-supplied; confirm dataset scope and license in the catalog.</p></div>
    {rows.length ? <><div className={`mt-3 text-[10px] ${source.status === "stale" ? "text-amber-200" : "text-slate-500"}`}>{source.status === "stale" ? "Government data source temporarily unavailable · showing last verified records. " : ""}Source timestamp: {sourceDate(source.source_timestamp)} · last sync: {sourceDate(source.last_successful_sync)} · {displayValue(source.data?.records_fetched)} records fetched</div><div className="mt-3 overflow-x-auto"><table className="w-full min-w-[640px] border-collapse text-left text-[10px]"><thead><tr>{columns.map((column) => <th key={column} className="border-b border-slate-700 px-3 py-2 font-medium text-slate-400">{column}</th>)}</tr></thead><tbody>{rows.slice(0, 8).map((row, index) => <tr key={index} className="border-b border-white/[.04]">{columns.map((column) => <td key={column} className="px-3 py-2 text-slate-300">{displayValue(row[column])}</td>)}</tr>)}</tbody></table></div></> : <EmptyState icon={CloudSun} title={source.status === "not_configured" ? "OGD resource not configured" : source.status === "connected" ? "No records returned by source" : "Government data source temporarily unavailable"} description={source.error || "No resource records are available."} />}
  </section>;
}
function GovernmentDataView({ governmentData, dataAvailable, backendUnavailable, onRefresh }: { governmentData: GovernmentData | null; dataAvailable: boolean; backendUnavailable: boolean; onRefresh: () => Promise<void> }) {
  const [refreshRequested, setRefreshRequested] = useState(false);
  const sources = governmentData?.sources ?? {};
  const observationsSource = sources.imd_observations;
  const observations = asRecords(observationsSource?.data?.observations);
  const warningsSource = sources.imd_warnings;
  const warnings = asRecords(warningsSource?.data?.warnings);
  const forecastSource = sources.imd_forecasts;
  const forecasts = asRecords(forecastSource?.data?.forecasts);
  const extraOgdSources = Object.values(sources).filter((source) => source.key.startsWith("ogd_resource_"));
  const requestRefresh = async () => {
    await onRefresh();
    setRefreshRequested(true);
    window.setTimeout(() => setRefreshRequested(false), 5000);
  };
  return <>
    <SectionHeading eyebrow="Verified public sources" title="Government data" detail="Live IMD observations are distinct from forecasts. MoRTH records are historical publications; source dates and sync state are retained." />
    <div className="mb-4 flex flex-wrap items-center justify-between gap-3"><p className="max-w-3xl text-[10px] leading-5 text-slate-500">IMD APIs require an issued key and station identifiers. OGD requires an API key and a verified resource ID. No restricted iRAD pages are scraped or bypassed.</p><button onClick={() => void requestRefresh()} className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-3 py-2 text-[10px] text-slate-300 hover:border-cyan/40 hover:text-cyan"><RefreshCw size={13} />Request source sync</button></div>
    {refreshRequested && <p role="status" className="mb-3 text-[10px] text-cyan">Government data refresh requested. Source status will update after the configured service completes its next sync.</p>}
    {!dataAvailable && <div className="mb-4 rounded-lg border border-amber-400/20 bg-amber-400/[.05] p-3 text-xs text-amber-100/80">Government data status unavailable because the authenticated backend is not connected.</div>}
    {backendUnavailable && governmentData && <div className="mb-4 rounded-lg border border-amber-400/20 bg-amber-400/[.05] p-3 text-xs text-amber-100/80">Government data service unavailable. The values retained below came from the last successful backend response; source freshness cannot currently be checked.</div>}
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{Object.values(sources).map((source) => <GovernmentSourceStatus key={source.key} source={source} backendUnavailable={backendUnavailable} />)}</div>
    <section className="panel mt-5 rounded-xl p-5"><div><h3 className="font-display text-sm font-medium">IMD current observations</h3><p className="mt-1 text-[10px] text-slate-500">Station measurements, with the original UTC observation time. Forecast values are not shown as observations.</p></div>
      {observations.length ? <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{observations.map((observation, index) => <article key={`${displayValue(observation.station_id)}-${index}`} className="rounded-lg border border-slate-800 bg-white/[.015] p-4"><div className="flex justify-between gap-3"><div><h4 className="text-xs text-slate-200">{displayValue(observation.station)}</h4><p className="technical mt-1 text-[9px] text-slate-500">STATION {displayValue(observation.station_id)}</p></div><span className={`text-[9px] ${observationsSource?.freshness === "fresh" ? "text-emerald-300" : "text-amber-200"}`}>{observationsSource?.freshness?.toUpperCase()}</span></div><p className="technical mt-3 text-[9px] text-slate-500">OBSERVED {sourceDate(typeof observation.observed_at === "string" ? observation.observed_at : null)}</p><div className="mt-3 grid grid-cols-2 gap-2 text-[10px] text-slate-500">{[["Temperature", observation.temperature_c, "°C"], ["Humidity", observation.humidity_percent, "%"], ["Wind", observation.wind_speed_kmph, "km/h"], ["Wind direction", observation.wind_direction, ""], ["24 h rainfall", observation.rainfall_24h_mm, "mm"], ["Pressure", observation.mslp_hpa, "hPa"]].map(([label, value, unit]) => <div key={String(label)}>{String(label)} <span className="technical text-slate-200">{displayValue(value)}{value !== null && value !== undefined ? String(unit) : ""}</span></div>)}</div></article>)}</div> : <EmptyState icon={CloudSun} title={observationsSource?.status === "stale" ? "Government data source temporarily unavailable" : observationsSource?.status === "not_configured" ? "IMD observations not configured" : "Awaiting live data"} description={observationsSource?.status === "not_configured" ? "Configure IMD_API_KEY and IMD_STATION_IDS. A valid IMD-issued credential is required; no readings are filled in when access is missing." : observationsSource?.error || "No verified current station observation is available."} />}
    </section>
    <section className="panel mt-5 rounded-xl p-5"><h3 className="font-display text-sm font-medium">IMD warnings and forecasts</h3><p className="mt-1 text-[10px] text-slate-500">Forecast products and warning bulletins remain separate from station observations.</p>
      {warnings.length ? <div className="mt-4 space-y-2">{warnings.slice(0, 8).map((warning, index) => <pre key={index} className="overflow-x-auto rounded-lg border border-slate-800 p-3 text-[9px] leading-4 text-slate-300">{JSON.stringify(warning, null, 2)}</pre>)}</div> : <EmptyState icon={AlertTriangle} title={warningsSource?.status === "not_configured" ? "IMD warnings endpoint not configured" : "No verified warning records"} description={warningsSource?.error || "IMD warning endpoints are account-specific. Configure only an endpoint documented for the authorized account; no warnings are synthesized."} />}
      {forecasts.length > 0 && <div className="mt-4"><h4 className="text-xs text-slate-300">Forecasts · not current observations</h4>{forecasts.map((item, index) => <pre key={index} className="mt-2 overflow-x-auto rounded-lg border border-slate-800 p-3 text-[9px] leading-4 text-slate-400">{JSON.stringify(item, null, 2)}</pre>)}</div>}
    </section>
    <MoRTHHistoricalSection source={sources.morth_accidents ?? null} dataAvailable={dataAvailable || Boolean(governmentData)} />
    {extraOgdSources.map((source) => <OGDResourceSection key={source.key} source={source} />)}
    <section className="panel mt-5 rounded-xl p-5"><h3 className="font-display text-sm font-medium">iRAD authorized access</h3><p className="mt-1 text-[10px] text-slate-500">The public portal is role-based. Data retrieval is enabled only with an authorized institutional endpoint and credential; this integration does not scrape restricted content.</p><p className="mt-3 text-xs text-slate-300">{sources.irad_authorized_access?.status === "connected" ? `Authorized endpoint responded; ${displayValue(sources.irad_authorized_access.data?.record_count)} records reported. Record contents are not copied into this shared workspace.` : sources.irad_authorized_access?.error || "No public iRAD API is documented or configured."}</p></section>
  </>;
}
function ModelView({ model, datasetStatus, dataAvailable }: { model: Model | null; datasetStatus: DatasetStatus | null; dataAvailable: boolean }) {
  const detectorTraining = model?.detector?.training_metrics;
  const finalTrainingLosses = detectorTraining?.last_epoch_training_losses;
  return <><SectionHeading eyebrow="Model governance" title="Model center" detail="Only information exposed by the loaded runtime is displayed; evaluation metrics are never inferred from detections." />
    <section className="panel mb-4 rounded-xl p-5"><div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="text-sm font-medium">Dataset availability and suitability</h3><p className="mt-1 text-[10px] text-slate-500">{datasetStatus?.dataset?.name || "Dataset source unavailable"} · local acquisition audit</p></div><span className={`rounded-md border px-2 py-1 text-[9px] ${datasetStatus?.status === "complete" ? "border-emerald-400/20 text-emerald-300" : "border-amber-400/20 text-amber-200"}`}>{dataAvailable ? datasetStatus?.status?.toUpperCase() || "UNAVAILABLE" : "NOT CONNECTED"}</span></div>
      <p className="mt-3 text-xs leading-5 text-slate-300">{datasetStatus?.message || "No dataset audit is available from the backend."}</p>
      {datasetStatus?.dataset && <><p className="mt-2 break-all text-[10px] leading-5 text-slate-500">Source: {datasetStatus.dataset.source} · License: {datasetStatus.dataset.license} · Revision: {datasetStatus.dataset.revision || "Not recorded"}</p><div className="mt-3 grid gap-2 sm:grid-cols-2">{datasetStatus.splits.map((split) => <div key={split.name} className="rounded-lg border border-slate-800 p-3"><div className="flex justify-between gap-2 text-[10px]"><span className="text-slate-300">{split.name} split</span><span className="text-amber-200">{split.status}</span></div><div className="mt-2 grid grid-cols-2 gap-2 text-[9px] text-slate-500"><span>Images available <b className="text-slate-200">{split.available_images?.toLocaleString() ?? "Not reported"}</b></span><span>Annotated images <b className="text-slate-200">{split.annotated_images?.toLocaleString() ?? "Not reported"}</b></span><span>Images missing <b className="text-slate-200">{split.missing_images?.toLocaleString() ?? "Not reported"}</b></span><span>Annotations <b className="text-slate-200">{split.annotations?.toLocaleString() ?? "Not reported"}</b></span><span>Data on disk <b className="text-slate-200">{split.image_bytes === null ? "Not reported" : `${(split.image_bytes / 1024 ** 3).toFixed(2)} GiB`}</b></span><span>Image dimension issues <b className="text-slate-200">{split.dimension_mismatches?.toLocaleString() ?? "Not reported"}</b></span></div></div>)}</div><p className="mt-3 text-[9px] text-slate-600">Tasks supported by source labels: {datasetStatus.dataset.supported_tasks.join(", ") || "Not reported"} · Last audit: {datasetStatus.last_audited || "Not recorded"}</p></>}
    </section>
    <div className="grid gap-4 lg:grid-cols-[.8fr_1.2fr]"><section className="panel rounded-xl p-5"><div className="flex items-center gap-3"><div className="grid h-11 w-11 place-items-center rounded-xl border border-cyan/20 bg-cyan/[.07] text-cyan"><Cpu size={19} /></div><div><div className="text-sm font-medium">{model?.architecture || "No architecture loaded"}</div><div className="technical mt-1 text-[9px] text-slate-600">RUNTIME STATUS · {dataAvailable ? model?.status?.toUpperCase() || "UNKNOWN" : "NOT CONNECTED"}</div></div></div><div className="mt-6 rounded-lg border border-amber-400/15 bg-amber-400/[.04] p-4"><p className="text-xs font-medium text-amber-200">{dataAvailable ? model?.message || "Model status unavailable." : "Awaiting model service data."}</p><p className="mt-2 text-[10px] leading-5 text-slate-500">No checkpoint, version, or training metadata is assumed. Configure actual YOLO weights for object detections and a separately validated temporal checkpoint for risk predictions.</p></div></section>
      <section className="panel rounded-xl p-5"><h3 className="text-sm font-medium">Temporal model evaluation</h3><div className="mt-4 divide-y divide-white/[.06]">{[
        ["Accident classifier", model?.accident_classifier?.architecture || "Not loaded"],
        ["Classifier state", model?.accident_classifier?.status || "Unavailable"],
        ["Model version", model?.accident_classifier?.version || "Not loaded"],
        ["Dataset", model?.accident_classifier?.training_info?.dataset_name || "Not provided"],
        ["Video data domain", model?.accident_classifier?.training_info?.data_domain?.toUpperCase() || "Not provided"],
        ["Train / validation segments", model?.accident_classifier?.training_info ? `${model.accident_classifier.training_info.train_segments} / ${model.accident_classifier.training_info.validation_segments}` : "Not provided"],
        ["Validation macro precision", model?.accident_classifier?.evaluation_metrics?.macro_precision !== undefined ? `${(model.accident_classifier.evaluation_metrics.macro_precision * 100).toFixed(1)}%` : "Not available"],
        ["Validation macro recall", model?.accident_classifier?.evaluation_metrics?.macro_recall !== undefined ? `${(model.accident_classifier.evaluation_metrics.macro_recall * 100).toFixed(1)}%` : "Not available"],
        ["Validation macro F1", model?.accident_classifier?.evaluation_metrics?.macro_f1 !== undefined ? `${(model.accident_classifier.evaluation_metrics.macro_f1 * 100).toFixed(1)}%` : "Not available"],
        ["Validation accuracy", model?.accident_classifier?.evaluation_metrics?.accuracy !== undefined ? `${(model.accident_classifier.evaluation_metrics.accuracy * 100).toFixed(1)}%` : "Not available"],
        ["Held-out test accuracy", model?.accident_classifier?.test_metrics?.accuracy !== undefined ? `${(model.accident_classifier.test_metrics.accuracy * 100).toFixed(1)}%` : "Not available"],
        ["Held-out test macro precision", model?.accident_classifier?.test_metrics?.macro_precision !== undefined ? `${(model.accident_classifier.test_metrics.macro_precision * 100).toFixed(1)}%` : "Not available"],
        ["Held-out test macro recall", model?.accident_classifier?.test_metrics?.macro_recall !== undefined ? `${(model.accident_classifier.test_metrics.macro_recall * 100).toFixed(1)}%` : "Not available"],
        ["Held-out test macro F1", model?.accident_classifier?.test_metrics?.macro_f1 !== undefined ? `${(model.accident_classifier.test_metrics.macro_f1 * 100).toFixed(1)}%` : "Not available"],
        ["Vehicle detector", model?.detector?.status || "Unavailable"],
        ["Detector load error", model?.detector?.error || "None"],
        ["Detector dataset", model?.detector?.dataset || "Not provided"],
        ["Detector version", model?.detector?.model_version || "Not provided"],
        ["Training epochs recorded", detectorTraining?.epochs_recorded !== undefined ? `${detectorTraining.epochs_recorded} · final epoch ${detectorTraining.last_epoch}` : "Not available"],
        ["Final training losses", finalTrainingLosses ? Object.entries(finalTrainingLosses).map(([name, value]) => `${name} ${value.toFixed(4)}`).join(" · ") : "Not available"],
        ["Detector validation mAP50", model?.detector?.validation_metrics?.mAP50 !== undefined ? `${(model.detector.validation_metrics.mAP50 * 100).toFixed(1)}%` : "Not available"],
        ["Detector validation mAP50-95", model?.detector?.validation_metrics?.["mAP50-95"] !== undefined ? `${(model.detector.validation_metrics["mAP50-95"] * 100).toFixed(1)}%` : "Not available"],
        ["Detector validation precision", model?.detector?.validation_metrics?.precision !== undefined ? `${(model.detector.validation_metrics.precision * 100).toFixed(1)}%` : "Not available"],
        ["Detector validation recall", model?.detector?.validation_metrics?.recall !== undefined ? `${(model.detector.validation_metrics.recall * 100).toFixed(1)}%` : "Not available"],
        ["Temporal held-out test F1", model?.accident_classifier?.test_metrics?.macro_f1 !== undefined ? `${(model.accident_classifier.test_metrics.macro_f1 * 100).toFixed(1)}%` : "Not available"],
        ["YOLO object detector", model?.weights_configured ? "Loaded" : "Not loaded"],
      ].map(([label, value]) => <div key={label} className="flex items-center justify-between gap-4 py-3 text-xs"><span className="text-slate-500">{label}</span><span className="text-right text-slate-300">{value}</span></div>)}</div>
        {model?.accident_classifier?.message && <p className="mt-4 text-[10px] leading-4 text-slate-500">{model.accident_classifier.message}</p>}
      </section>
    </div>
    <div className="mt-4 grid gap-4 lg:grid-cols-2">
      <section className="panel rounded-xl p-5"><h3 className="text-sm font-medium">Detector classes and evaluation</h3>
        <p className="mt-2 text-[10px] leading-5 text-slate-500">{model?.detector?.metrics_note || "No verified detector checkpoint metadata is available."}</p>
        <p className="mt-3 break-words text-[10px] leading-5 text-slate-300">{model?.detector?.classes?.length ? model.detector.classes.join(" · ") : "No detector classes loaded"}</p>
        {model?.detector?.test_metrics && <p className="mt-2 text-[10px] text-slate-500">Test metrics: {JSON.stringify(model.detector.test_metrics)}</p>}
      </section>
      <section className="panel rounded-xl p-5"><h3 className="text-sm font-medium">Structured road-risk model</h3>
        <div className="mt-3 divide-y divide-white/[.06]">{[
          ["Status", model?.structured_road_risk?.status || "Unavailable"],
          ["Architecture", model?.structured_road_risk?.architecture || "Not loaded"],
          ["Version", model?.structured_road_risk?.version || "Not loaded"],
          ["Dataset", model?.structured_road_risk?.training_info?.dataset_name || "Not provided"],
          ["Observed target", model?.structured_road_risk?.training_info?.label_definition || "Not provided"],
          ["Features", model?.structured_road_risk?.features?.join(", ") || "Not loaded"],
          ["Held-out test metrics", model?.structured_road_risk?.evaluation_metrics?.test ? JSON.stringify(model.structured_road_risk.evaluation_metrics.test) : "Not available"],
        ].map(([label, value]) => <div key={label} className="flex items-start justify-between gap-4 py-2 text-[10px]"><span className="text-slate-500">{label}</span><span className="max-w-[65%] break-words text-right text-slate-300">{value}</span></div>)}</div>
        {model?.structured_road_risk?.message && <p className="mt-3 text-[10px] leading-4 text-slate-500">{model.structured_road_risk.message}</p>}
      </section>
    </div>
    <p className="mt-4 flex items-start gap-2 text-[10px] leading-5 text-slate-600"><Shield size={13} className="mt-0.5 shrink-0" />YOLO detections identify objects only. Temporal predictions require a validated trained checkpoint and are risk estimates—not confirmed accidents or safety decisions.</p>
  </>;
}
