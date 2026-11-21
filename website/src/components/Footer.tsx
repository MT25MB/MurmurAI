import { REPO_URL } from "../config";

export default function Footer() {
  return (
    <footer className="border-t border-border">
      <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-5 py-10 sm:flex-row sm:px-8">
        <div className="flex items-center gap-3">
          <img src="/MurmurAI/logo-blue.png" alt="" aria-hidden="true" className="h-8 w-8 object-contain" />
          <span className="text-sm font-semibold tracking-tight text-ink">MURMUR<span className="text-blue">/AI</span></span>
          <span className="mono-label hidden sm:inline">· 100% local · $0 forever</span>
        </div>
        <div className="flex items-center gap-5">
          <a href={REPO_URL} target="_blank" rel="noreferrer" className="mono-label !text-ink/70 hover:!text-blue">GitHub</a>
          <a href={`${REPO_URL}/blob/main/LICENSE`} target="_blank" rel="noreferrer" className="mono-label !text-ink/70 hover:!text-blue">MIT License</a>
          <a href="#top" className="mono-label !text-ink/70 hover:!text-blue">Back to top ↑</a>
        </div>
      </div>
    </footer>
  );
}
