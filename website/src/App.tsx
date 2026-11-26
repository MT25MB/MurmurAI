import Nav from "./components/Nav";
import HudPreview from "./components/HudPreview";
import DownloadButton from "./components/DownloadButton";
import Capabilities from "./components/Capabilities";
import QuickStart from "./components/QuickStart";
import Footer from "./components/Footer";
import HardwareRequirements from "./components/HardwareRequirements";

export default function App() {
  return (
    <div id="top" className="min-h-screen bg-obsidian text-ink">
      <Nav />

      <main>
        {/* ── HERO ─────────────────────────────────────────────── */}
        <section className="relative border-b border-border">
          <div className="relative mx-auto grid max-w-7xl items-center gap-14 px-5 pb-16 pt-20 sm:px-8 lg:grid-cols-[1.05fr_0.95fr] lg:gap-10 lg:pb-20 lg:pt-28">
            <div className="min-w-0">
              <img
                src="/MurmurAI/logo-blue.png"
                alt="Murmur AI logo"
                className="rise mb-8 h-16 w-16 object-contain sm:h-20 sm:w-20"
              />

              <h1 className="rise delay-1 mt-2 max-w-2xl text-4xl font-semibold leading-[1.05] tracking-[-0.03em] text-ink sm:text-5xl lg:text-[3.6rem]">
                Control your computer with your voice. Nothing leaves your machine.
              </h1>

              <p className="rise delay-2 mt-6 max-w-xl text-base leading-relaxed text-muted">
                Murmur AI is an open-source assistant that takes your voice commands
                and acts on them: opening apps, clicking through Blender, reading a
                dialog out loud. Every model runs on your machine. Your files and
                voice never go anywhere. No subscription, no account, no cloud.
              </p>

              <p className="rise delay-2 mt-5 label-text">
                MIT licensed · Windows, macOS and Linux · Local models, no API key.
              </p>

              <div id="download" className="rise delay-3 mt-9 scroll-mt-24">
                <DownloadButton />
              </div>
            </div>

            <div className="rise delay-2 flex min-w-0 justify-center lg:justify-end">
              <HudPreview />
            </div>
          </div>
        </section>

        {/* ── HARDWARE ─────────────────────────────────────────── */}
        <HardwareRequirements />

        {/* ── CAPABILITIES ─────────────────────────────────────── */}
        <Capabilities />

        {/* ── QUICK START / DOCS ───────────────────────────────── */}
        <QuickStart />
      </main>

      <Footer />
    </div>
  );
}
