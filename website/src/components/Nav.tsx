import { REPO_URL } from "../config";

const links = [
  ["hardware", "Hardware"],
  ["capabilities", "Capabilities"],
  ["quickstart", "Quick start"],
  ["docs", "Docs"],
] as const;

export default function Nav() {
  return (
    <header className="sticky top-0 z-50 border-b border-border bg-obsidian/85 backdrop-blur-xl">
      <nav
        className="mx-auto flex h-16 max-w-7xl items-center justify-between px-5 sm:px-8"
        aria-label="Main navigation"
      >
        <a href="#top" className="group flex items-center gap-3" aria-label="Murmur AI home">
          <img
            src="/MurmurAI/logo-blue.png"
            alt=""
            aria-hidden="true"
            className="h-9 w-9 object-contain"
          />
          <span className="text-sm font-semibold tracking-tight text-ink">MURMUR<span className="text-blue">/AI</span></span>
        </a>

        <div className="hidden items-center gap-8 md:flex">
          {links.map(([id, label]) => (
            <a
              key={id}
              href={`#${id}`}
              className="mono-label !text-ink/70 transition-colors hover:!text-blue"
            >
              {label}
            </a>
          ))}
        </div>

        <a
          href={REPO_URL}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-xs font-medium text-ink transition-colors hover:border-blue"
        >
          <svg viewBox="0 0 16 16" className="h-4 w-4 fill-current" aria-hidden="true">
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82a7.4 7.4 0 0 1 2-.27c.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A7.99 7.99 0 0 0 16 8c0-4.42-3.58-8-8-8Z" />
          </svg>
          <span className="hidden sm:inline">Star on GitHub</span>
          <span className="sm:hidden">GitHub</span>
        </a>
      </nav>
    </header>
  );
}
