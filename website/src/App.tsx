import Nav from "./components/Nav";
import HudPreview from "./components/HudPreview";
import DownloadButton from "./components/DownloadButton";
import Capabilities from "./components/Capabilities";
import QuickStart from "./components/QuickStart";
import Footer from "./components/Footer";
import { REPO_URL } from "./config";

const badges = [
  { label: "MIT License", href: `${REPO_URL}/blob/main/LICENSE` },
  { label: "Windows", href: "#download" },
  { label: "macOS", href: "#download" },
  { label: "Linux", href: "#download" },
  { label: "100% Local", href: "#capabilities" },
];

export default function App() {
  return (
    <div id="top" className="min-h-screen bg-obsidian text-ink">
      <Nav />

      <main>
        {/* ── HERO ─────────────────────────────────────────────── */}
        <section className="relative overflow-hidden">
          <div className="absolute inset-0 grid-field" aria-hidden="true" />
          <div className="absolute -left-40 top-10 h-[420px] w-[420px] rounded-full bg-blue-fill/10 blur-[120px]" aria-hidden="true" />
          <div className="absolute -right-40 top-52 h-[360px] w-[360px] rounded-full bg-red-fill/10 blur-[120px]" aria-hidden="true" />

          <div className="relative mx-auto grid max-w-7xl items-center gap-14 px-5 pb-16 pt-20 sm:px-8 lg:grid-cols-[1.05fr_0.95fr] lg:gap-10 lg:pb-20 lg:pt-28">
            <div>
              <img
                src="/MurmurAI/logo-blue.png"
                alt="Murmur AI logo"
                className="rise mb-6 h-16 w-16 object-contain sm:h-20 sm:w-20"
              />
              <div className="rise flex flex-wrap gap-2" aria-label="Project facts">
                {badges.map((b) => (
                  <a
                    key={b.label}
                    href={b.href}
                    className="mono-label rounded-md border border-border bg-surface/80 px-2.5 py-1 transition-colors hover:border-blue hover:!text-blue"
                  >
                    {b.label}
                  </a>
                ))}
              </div>

              <h1 className="rise delay-1 mt-7 text-4xl font-semibold leading-[1.05] tracking-[-0.03em] text-ink sm:text-5xl lg:text-[3.6rem]">
                Control your entire computer with your voice.
                <span className="mt-3 block text-blue">100% Local.</span>
                <span className="block text-red">$0 Forever.</span>
              </h1>

              <p className="rise delay-2 mt-6 max-w-xl text-base leading-relaxed text-muted">
                Murmur AI is an open-source assistant that takes your voice commands
                and acts on them: opening apps, clicking through Blender, reading a
                dialog out loud. Every model runs on your machine. Your files and
                voice never go anywhere. No subscription, no account, no cloud.
              </p>

              <div id="download" className="rise delay-3 mt-9 scroll-mt-24">
                <DownloadButton />
              </div>

              <div className="rise delay-3 mt-10 flex items-center gap-6">
                <div>
                  <p className="text-xl font-semibold text-ink">0</p>
                  <p className="mono-label">cloud calls</p>
                </div>
                <div className="h-8 w-px bg-border" />
                <div>
                  <p className="text-xl font-semibold text-ink">3</p>
                  <p className="mono-label">platforms</p>
                </div>
                <div className="h-8 w-px bg-border" />
                <div>
                  <p className="text-xl font-semibold text-ink">MIT</p>
                  <p className="mono-label">license</p>
                </div>
              </div>
            </div>

            <div className="rise delay-2 flex justify-center lg:justify-end">
              <HudPreview />
            </div>
          </div>
        </section>

        {/* ── CAPABILITIES ─────────────────────────────────────── */}
        <Capabilities />

        {/* ── QUICK START / DOCS ───────────────────────────────── */}
        <QuickStart />
      </main>

      <Footer />
    </div>
  );
}
