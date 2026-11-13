"use client";

import { motion } from "framer-motion";
import Link from "next/link";
import { ArrowDown, ArrowRight, AudioWaveform, Eye, LockKeyhole, Radar, ShieldCheck } from "lucide-react";

const steps = [
  { n: "01", title: "Connect your cameras", text: "Register authorized IP cameras and video sources. Connection state is reported from the service—not assumed." },
  { n: "02", title: "Analyze real frames", text: "Run configured, loaded object-detection weights against uploaded video. No weights means inference stays disabled." },
  { n: "03", title: "Act on evidence", text: "Review recorded events, camera metadata, and measured system health in one operational workspace." },
];

export default function Home() {
  return (
    <main className="overflow-hidden">
      <nav className="relative z-10 mx-auto flex max-w-7xl items-center justify-between px-6 py-6 lg:px-10">
        <Link href="/" className="flex items-center gap-3">
          <div className="grid h-9 w-9 place-items-center rounded-xl border border-cyan/30 bg-cyan/10 text-cyan"><Radar size={19} /></div>
          <span className="font-display text-lg font-semibold tracking-tight">nexsafe<span className="text-cyan">.ai</span></span>
        </Link>
        <div className="hidden items-center gap-8 text-sm text-slate-400 md:flex">
          <a href="#technology" className="transition hover:text-white">Technology</a>
          <a href="#workflow" className="transition hover:text-white">How it works</a>
          <a href="#trust" className="transition hover:text-white">Trust & privacy</a>
        </div>
        <Link href="/dashboard" className="inline-flex items-center gap-2 rounded-lg border border-slate-700 bg-white/[.04] px-4 py-2.5 text-sm font-medium transition hover:border-cyan/50 hover:bg-cyan/10">
          Open workspace <ArrowRight size={15} className="text-cyan" />
        </Link>
      </nav>

      <section className="relative mx-auto grid min-h-[690px] max-w-7xl items-center gap-10 px-6 pb-24 pt-16 lg:grid-cols-[1.02fr_.98fr] lg:px-10 lg:pt-12">
        <div className="grid-bg pointer-events-none absolute inset-0 -z-10 opacity-80" />
        <div className="pointer-events-none absolute -left-40 top-20 -z-10 h-96 w-96 rounded-full bg-blue-600/10 blur-[120px]" />
        <motion.div initial={{ opacity: 0, y: 18 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .65 }}>
          <div className="mb-7 inline-flex items-center gap-2 rounded-full border border-cyan/20 bg-cyan/[.06] px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[.18em] text-cyan">
            <span className="h-1.5 w-1.5 rounded-full bg-cyan" /> Road safety intelligence
          </div>
          <h1 className="max-w-2xl font-display text-5xl font-semibold leading-[1.08] tracking-[-.045em] sm:text-6xl lg:text-[68px]">
            See danger <span className="bg-gradient-to-r from-cyan to-blue-400 bg-clip-text text-transparent">before</span> it happens.
          </h1>
          <p className="mt-7 max-w-xl text-base leading-7 text-slate-400 sm:text-lg">
            Powered by deep learning and real-time computer vision, NexSafe AI transforms road surveillance into an evidence-led safety operation.
          </p>
          <div className="mt-9 flex flex-wrap gap-3">
            <Link href="/dashboard" className="inline-flex items-center gap-2 rounded-lg bg-cyan px-5 py-3 text-sm font-semibold text-midnight shadow-glow transition hover:bg-cyan/90">
              Launch AI workspace <ArrowRight size={16} />
            </Link>
            <a href="#technology" className="inline-flex items-center gap-2 rounded-lg border border-slate-700 px-5 py-3 text-sm font-medium text-slate-200 transition hover:border-slate-500">
              Explore technology <ArrowDown size={15} />
            </a>
          </div>
          <p className="technical mt-7 text-[10px] uppercase tracking-[.13em] text-slate-600">No configured model weights · no inference · no fabricated alerts</p>
        </motion.div>

        <motion.div initial={{ opacity: 0, scale: .97 }} animate={{ opacity: 1, scale: 1 }} transition={{ duration: .8, delay: .12 }} className="relative">
          <div className="absolute -inset-8 rounded-[36px] bg-cyan/[.035] blur-2xl" />
          <div className="glass relative overflow-hidden rounded-2xl p-3 shadow-2xl shadow-black/40">
            <div className="relative min-h-[385px] overflow-hidden rounded-xl border border-white/[.06] bg-[#0b1421]">
              <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_55%_48%,rgba(31,71,100,.42),transparent_58%),linear-gradient(180deg,#0d1a2a_0%,#101b25_48%,#080d18_100%)]" />
              <div className="absolute inset-x-0 top-[39%] h-px bg-cyan/15" />
              <div className="absolute left-1/2 top-[39%] h-[62%] w-[56%] -translate-x-1/2 origin-top [transform:perspective(280px)_rotateX(22deg)]">
                <div className="absolute inset-0 bg-gradient-to-b from-slate-500/10 via-slate-400/[.05] to-slate-900/20" />
                <div className="absolute left-1/2 h-full w-px -translate-x-1/2 border-l border-dashed border-cyan/30" />
                {[20, 42, 64, 84].map((y) => <div key={y} className="absolute inset-x-0 h-px bg-white/[.07]" style={{ top: `${y}%` }} />)}
                <div className="absolute bottom-0 left-[18%] h-[40%] w-[18%] rounded-t-lg border border-white/10 bg-gradient-to-b from-slate-500/20 to-slate-800/60" />
                <div className="absolute bottom-0 right-[19%] h-[34%] w-[18%] rounded-t-lg border border-white/10 bg-gradient-to-b from-slate-500/20 to-slate-800/60" />
              </div>
              <div className="absolute left-[24%] top-[61%] h-16 w-10 rounded-md border border-cyan/60 shadow-[0_0_22px_rgba(0,229,255,.12)]">
                <span className="absolute -top-5 left-0 whitespace-nowrap rounded bg-cyan px-1.5 py-0.5 font-mono text-[8px] text-midnight">TRACK · NOT LIVE</span>
              </div>
              <div className="absolute right-[25%] top-[54%] h-12 w-9 rounded-md border border-blue-400/60">
                <span className="absolute -top-5 right-0 whitespace-nowrap rounded bg-blue-500/80 px-1.5 py-0.5 font-mono text-[8px]">VISUAL CONCEPT</span>
              </div>
              <div className="absolute left-5 top-5 flex items-center gap-2 rounded-md border border-white/10 bg-black/30 px-2.5 py-2 text-[10px] text-slate-300 backdrop-blur">
                <Eye size={13} className="text-cyan" /> ORIGINAL ROADWAY VISUALIZATION
              </div>
              <div className="absolute inset-x-5 bottom-5 flex items-end justify-between">
                <div className="technical text-[9px] leading-5 text-slate-500">NO CAMERA CONNECTED<br />VISUALIZATION ONLY</div>
                <div className="flex items-center gap-2 rounded-md border border-slate-700/70 bg-midnight/75 px-3 py-2 text-[10px] text-slate-400">
                  <span className="h-1.5 w-1.5 rounded-full bg-slate-500" /> AWAITING LIVE DATA
                </div>
              </div>
              <div className="absolute right-8 top-16 h-28 w-28 rounded-full border border-cyan/10"><div className="absolute inset-3 rounded-full border border-cyan/[.08]" /><div className="absolute left-1/2 top-1/2 h-1 w-1 rounded-full bg-cyan shadow-[0_0_16px_4px_rgba(0,229,255,.45)]" /></div>
            </div>
            <div className="flex items-center justify-between px-2 pb-1 pt-3 text-[10px] text-slate-500">
              <span>Illustrative interface · no surveillance footage</span><span className="technical">SOURCE: LOCAL RENDER</span>
            </div>
          </div>
        </motion.div>
      </section>

      <section id="workflow" className="mx-auto max-w-7xl px-6 py-24 lg:px-10">
        <div className="max-w-2xl">
          <p className="technical text-[10px] uppercase tracking-[.2em] text-cyan">Operational by design</p>
          <h2 className="mt-4 font-display text-3xl font-semibold tracking-tight sm:text-4xl">From raw video to a clearer picture.</h2>
          <p className="mt-4 text-sm leading-6 text-slate-400">A transparent pipeline that keeps real input, model output, and operational decisions distinct.</p>
        </div>
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {steps.map((step) => <article key={step.n} className="panel rounded-xl p-6 transition hover:-translate-y-1 hover:border-cyan/25">
            <span className="technical text-xs text-cyan/70">{step.n} / PIPELINE</span>
            <h3 className="mt-7 font-display text-lg font-medium">{step.title}</h3>
            <p className="mt-3 text-sm leading-6 text-slate-400">{step.text}</p>
          </article>)}
        </div>
      </section>

      <section id="technology" className="border-y border-white/[.06] bg-slatepanel/30">
        <div className="mx-auto grid max-w-7xl gap-12 px-6 py-24 lg:grid-cols-[.8fr_1.2fr] lg:px-10">
          <div><p className="technical text-[10px] uppercase tracking-[.2em] text-cyan">Technology with boundaries</p><h2 className="mt-4 font-display text-3xl font-semibold tracking-tight">Intelligence you can inspect.</h2><p className="mt-4 text-sm leading-6 text-slate-400">A model is only useful when its capability and limits are visible. NexSafe reports model availability, inference measurements, and the provenance of stored events.</p></div>
          <div className="grid gap-3 sm:grid-cols-2">
            {[
              [AudioWaveform, "Computer vision", "Configured YOLO weights can return object detections from uploaded video. Accident classification is not implied."],
              [Radar, "Live operations", "Camera count, frame throughput, and latency are read from registered sources and actual inference records."],
              [ShieldCheck, "Evidence first", "Events and analytics come from persisted records. Empty datasets stay empty; no sample values are introduced."],
              [LockKeyhole, "Security & privacy", "Bearer-token API access, camera source secrecy, and a self-hosted deployment boundary."],
            ].map(([Icon, title, copy]) => {
              const I = Icon as typeof AudioWaveform;
              return <article key={title as string} className="glass rounded-xl p-5"><I size={18} className="text-cyan" /><h3 className="mt-4 text-sm font-semibold">{title as string}</h3><p className="mt-2 text-xs leading-5 text-slate-400">{copy as string}</p></article>;
            })}
          </div>
        </div>
      </section>

      <section id="trust" className="mx-auto flex max-w-7xl flex-col items-start justify-between gap-6 px-6 py-20 sm:flex-row sm:items-center lg:px-10">
        <div><p className="technical text-[10px] uppercase tracking-[.2em] text-cyan">Build a safer view</p><h2 className="mt-3 font-display text-2xl font-semibold">Your infrastructure. Your evidence.</h2><p className="mt-2 text-sm text-slate-400">Connect an authorized source to begin. No connected camera or trained model is assumed.</p></div>
        <Link href="/dashboard" className="inline-flex shrink-0 items-center gap-2 rounded-lg border border-cyan/40 px-5 py-3 text-sm font-medium text-cyan transition hover:bg-cyan/10">Open NexSafe workspace <ArrowRight size={15} /></Link>
      </section>

      <footer className="border-t border-white/[.06] px-6 py-6 text-center text-xs text-slate-600">NexSafe AI · Predict. Protect. Prevent. <span className="mx-2 text-slate-800">/</span> Data availability depends on your configured infrastructure.</footer>
    </main>
  );
}
