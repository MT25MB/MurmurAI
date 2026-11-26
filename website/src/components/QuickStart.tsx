import { REPO_URL } from "../config";

const steps = [
  {
    n: "01",
    title: "Install Ollama",
    body: "This is the engine that runs the models. Murmur AI checks for it on first launch and offers to install it if it can't find it.",
    code: "# macOS / Windows\nbrew install ollama      # or: winget install Ollama.Ollama\n\n# Linux\ncurl -fsSL https://ollama.com/install.sh | sh",
  },
  {
    n: "02",
    title: "First-run model download",
    body: "Setup pulls the two models it needs and stores Whisper and Kokoro weights under ~/.murmur-ai/models/. You'll see a progress bar for each.",
    code: "ollama pull qwen2.5:7b        # fast voice + tool chat\nollama pull qwen2.5vl:7b     # screen vision",
  },
  {
    n: "03",
    title: "Grant OS permissions",
    body: "Your OS decides whether an app can read the screen and move the mouse. Murmur AI checks what's already allowed and points you to the right settings screen.",
    code: "macOS   → Accessibility + Screen Recording\nLinux   → X11 (XTest) or Wayland portal capture\nWindows → no extra permission required",
  },
  {
    n: "04",
    title: "Talk to your computer",
    body: "The small HUD at the bottom of your screen listens, answers, and gets to work. Try “install Blender” or “what's on my screen?”",
    code: "you  →  “open DaVinci and import the clips”\nai   →  LISTENING → THINKING → EXECUTING → done",
  },
];

export default function QuickStart() {
  return (
    <section id="quickstart" className="border-y border-border bg-surface/40">
      <div className="mx-auto max-w-7xl px-5 py-24 sm:px-8">
        <div className="flex flex-col gap-3">
          <h2 className="max-w-2xl text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
            Up and running in four steps.
          </h2>
          <p className="max-w-xl text-sm leading-relaxed text-muted">
            No API keys. No accounts. No cloud. If you can install Ollama, you can run Murmur AI.
          </p>
        </div>

        <div className="mt-12 grid gap-4 md:grid-cols-2">
          {steps.map((s) => (
            <article key={s.n} className="panel min-w-0 p-5 sm:p-6">
              <div className="flex items-baseline gap-3">
                <span className="mono-label text-blue tabular-nums">{s.n}</span>
                <h3 className="text-base font-semibold text-ink">{s.title}</h3>
              </div>
              <p className="mt-3 text-sm leading-relaxed text-muted">{s.body}</p>
              <pre className="mt-4 overflow-x-auto rounded-lg border border-border bg-obsidian p-4 font-mono text-[11px] leading-relaxed text-ink/80 sm:text-xs">
                {s.code}
              </pre>
            </article>
          ))}
        </div>

        <div id="docs" className="mt-8 flex flex-col items-start justify-between gap-5 rounded-lg border border-border bg-surface p-6 sm:flex-row sm:items-center sm:p-8">
          <div>
            <p className="text-lg font-semibold text-ink">Want the full architecture and agent rules?</p>
            <p className="mt-1 text-sm text-muted">AGENTS.md covers every module, safety gate, and design choice in the repo.</p>
          </div>
          <a
            href={`${REPO_URL}#readme`}
            target="_blank"
            rel="noreferrer"
            className="btn-secondary shrink-0"
          >
            Read the docs →
          </a>
        </div>
      </div>
    </section>
  );
}
