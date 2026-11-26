const requirements = [
  { name: "OS", minimum: "Windows 10, macOS 12, Linux (X11/Wayland)", recommended: "Latest" },
  { name: "CPU", minimum: "4 cores with AVX2", recommended: "8 cores" },
  { name: "RAM", minimum: "8 GB", recommended: "16 GB+" },
  { name: "Storage", minimum: "~8 GB free for models and weights", recommended: "20 GB SSD" },
  { name: "GPU", minimum: "Not needed — CPU inference works", recommended: "NVIDIA or Apple Silicon for lower latency" },
  { name: "Microphone", minimum: "Any input device", recommended: "Noise-cancelling" },
];

const tiers = [
  {
    name: "Light",
    when: "8–12 GB RAM, no GPU",
    models: "qwen2.5:3b + qwen2.5vl:3b",
    whisper: "tiny.en · int8",
  },
  {
    name: "High",
    when: "16 GB+ RAM or 6 GB+ VRAM",
    models: "qwen2.5:7b + qwen2.5vl:7b",
    whisper: "small.en · float16",
  },
];

export default function HardwareRequirements() {
  return (
    <section id="hardware" className="scroll-mt-24 border-y border-border bg-surface/40 px-5 py-20 sm:px-8">
      <div className="mx-auto max-w-7xl">
        <h2 className="text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          What your machine needs
        </h2>
        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-muted">
          Everything runs locally. Murmur AI picks a model tier on first launch from your RAM,
          VRAM and compute backend; you can override it in Settings at any time.
        </p>

        <div className="mt-10 overflow-x-auto rounded-xl border border-border bg-obsidian">
          <table className="w-full min-w-[640px] border-collapse text-left text-sm">
            <caption className="sr-only">Minimum and recommended hardware requirements</caption>
            <thead>
              <tr className="border-b border-border text-xs text-muted">
                <th scope="col" className="px-5 py-4 font-medium">Requirement</th>
                <th scope="col" className="px-5 py-4 font-medium">Minimum</th>
                <th scope="col" className="px-5 py-4 font-medium">Recommended</th>
              </tr>
            </thead>
            <tbody>
              {requirements.map((row) => (
                <tr key={row.name} className="border-b border-border/70 last:border-0">
                  <th scope="row" className="px-5 py-4 font-medium text-ink">{row.name}</th>
                  <td className="px-5 py-4 text-muted">{row.minimum}</td>
                  <td className="px-5 py-4 text-ink/85">{row.recommended}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-2">
          {tiers.map((tier) => (
            <div key={tier.name} className="rounded-xl border border-border bg-obsidian p-5">
              <div className="flex items-baseline justify-between gap-3">
                <h3 className="text-lg font-semibold text-ink">{tier.name} tier</h3>
                <span className="mono-label text-muted">{tier.when}</span>
              </div>
              <p className="mt-4 text-sm text-ink/85">{tier.models}</p>
              <p className="mono-label mt-2 text-muted">speech: {tier.whisper}</p>
            </div>
          ))}
        </div>

        <p className="mt-6 text-xs leading-relaxed text-muted">
          Model downloads are one-time and local: about 4.4 GB for qwen2.5:7b and 5.6 GB for
          qwen2.5vl:7b on the high tier. The light-tier 3B models are smaller. No account,
          API key, or cloud service is required.
        </p>
      </div>
    </section>
  );
}
