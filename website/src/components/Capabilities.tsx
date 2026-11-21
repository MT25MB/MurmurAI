import { useRef, useState } from "react";

type Workflow = {
  id: string;
  index: string;
  title: string;
  blurb: string;
  lines: { tone: "muted" | "blue" | "red" | "ink"; text: string }[];
};

const workflows: Workflow[] = [
  {
    id: "gui",
    index: "01",
    title: "Complex GUI navigation",
    blurb:
      "Set-of-Marks grounding finds clickable elements, then executes precise actions inside Blender, DaVinci Resolve, or any app — no cloud vision API.",
    lines: [
      { tone: "muted", text: "# goal: smooth the selected mesh in Blender" },
      { tone: "blue", text: "screen.capture() → 17 marked elements" },
      { tone: "ink", text: "VLM → { action: CLICK, element_id: 6 }" },
      { tone: "ink", text: "resolve 6 → (0.712, 0.384) → pyautogui.click" },
      { tone: "muted", text: "# hotkeys preferred over menu hunting" },
      { tone: "red", text: "hotkey('shift','a') → modifier applied ✓" },
    ],
  },
  {
    id: "install",
    index: "02",
    title: "Autonomous app installation",
    blurb:
      "Native silent package managers first. The agent searches, shows you the exact command, waits for approval, then streams live download progress.",
    lines: [
      { tone: "muted", text: "# user: install blender" },
      { tone: "blue", text: "detect → winget | brew | flatpak | snap | apt" },
      { tone: "ink", text: "winget search --name Blender" },
      { tone: "ink", text: "→ BlenderFoundation.Blender" },
      { tone: "red", text: "CONFIRMATION_REQUIRED → user approved" },
      { tone: "ink", text: "winget install --id … --silent  45% → 100%" },
    ],
  },
  {
    id: "privacy",
    index: "03",
    title: "Local privacy architecture",
    blurb:
      "Every model, transcript, and screenshot stays on your machine. There is no cloud inference, no telemetry, and no API key to configure.",
    lines: [
      { tone: "muted", text: "# network egress audit" },
      { tone: "ink", text: "Ollama        127.0.0.1:11434  ✓ local" },
      { tone: "ink", text: "WebSocket     127.0.0.1:8765   ✓ local" },
      { tone: "ink", text: "faster-whisper  on-device CPU   ✓ local" },
      { tone: "ink", text: "Kokoro-82M      on-device TTS   ✓ local" },
      { tone: "red", text: "cloud APIs      0                ✓ none" },
    ],
  },
];

const toneClass: Record<Workflow["lines"][number]["tone"], string> = {
  muted: "text-muted",
  blue: "text-blue",
  red: "text-red",
  ink: "text-ink/85",
};

export default function Capabilities() {
  const [active, setActive] = useState(0);
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([]);
  const current = workflows[active];

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next =
      e.key === "ArrowRight"
        ? (active + 1) % workflows.length
        : (active - 1 + workflows.length) % workflows.length;
    setActive(next);
    tabRefs.current[next]?.focus();
  };

  return (
    <section id="capabilities" className="mx-auto max-w-7xl px-5 py-24 sm:px-8">
      <div className="flex flex-col gap-3">
        <span className="mono-label"><span className="text-red">02</span> / capabilities</span>
        <h2 className="max-w-2xl text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          It doesn&apos;t just answer. It <span className="text-blue">operates</span>.
        </h2>
      </div>

      <div className="mt-10 grid gap-6 lg:grid-cols-[380px_1fr]">
        {/* Tab list */}
        <div role="tablist" aria-label="Capabilities" aria-orientation="vertical" className="flex flex-col gap-2">
          {workflows.map((w, i) => (
            <button
              key={w.id}
              ref={(el) => { tabRefs.current[i] = el; }}
              role="tab"
              id={`tab-${w.id}`}
              aria-selected={active === i}
              aria-controls={`panel-${w.id}`}
              tabIndex={active === i ? 0 : -1}
              onClick={() => setActive(i)}
              onKeyDown={onKeyDown}
              className={`group min-w-0 rounded-xl border p-4 text-left transition-all ${
                active === i
                  ? "border-blue bg-blue-deep/20"
                  : "border-border bg-surface hover:border-muted/50"
              }`}
            >
              <div className="flex items-start gap-3">
                <span className={`mono-label ${active === i ? "!text-blue" : ""}`}>{w.index}</span>
                <div>
                  <p className="text-sm font-semibold text-ink">{w.title}</p>
                  <p className="mt-1 text-xs leading-relaxed text-muted">{w.blurb}</p>
                </div>
              </div>
            </button>
          ))}
        </div>

        {/* Panel */}
        <div
          role="tabpanel"
          id={`panel-${current.id}`}
          aria-labelledby={`tab-${current.id}`}
          className="panel min-w-0 overflow-hidden"
        >
          <div className="flex items-center justify-between border-b border-border px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full bg-red" />
              <span className="mono-label !text-ink">agent trace · {current.id}</span>
            </div>
            <span className="mono-label">stdout</span>
          </div>
          <div className="scanlines min-h-[300px] bg-obsidian/60 p-5 sm:p-7">
            <pre className="space-y-1.5 overflow-x-auto font-mono text-xs leading-relaxed sm:text-[13px]">
              {current.lines.map((l, i) => (
                <div key={i} className={toneClass[l.tone]}>
                  <span className="mr-3 select-none text-border">{String(i + 1).padStart(2, "0")}</span>
                  {l.text}
                </div>
              ))}
            </pre>
          </div>
        </div>
      </div>
    </section>
  );
}
