import { useMemo, useState } from "react";
import {
  generatedReference,
  type VoiceTool,
} from "../data/generatedReference";

const { categories, skills, pronunciations, settingPhrases } = generatedReference;

/**
 * Interactive, accessible command and skill explorer fed by generated data.
 * Filter with the search field, pick a category, then expand a tool to see
 * example phrases. Everything is plain text so screen readers work normally.
 */
export default function CommandExplorer() {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState(categories[0]?.category ?? "");
  const [open, setOpen] = useState<string | null>(null);

  const visibleTools = useMemo(() => {
    const active = categories.find((group) => group.category === category);
    const source = active ? active.tools : [];
    const needle = query.trim().toLowerCase();
    if (!needle) return source;
    return source.filter((tool: VoiceTool) =>
      [tool.name, tool.description, ...tool.examples]
        .join(" ")
        .toLowerCase()
        .includes(needle),
    );
  }, [category, query]);

  const totalTools = categories.reduce((sum, group) => sum + group.tools.length, 0);

  return (
    <section id="commands" className="scroll-mt-24 border-y border-border bg-surface/40 px-5 py-20 sm:px-8">
      <div className="mx-auto max-w-7xl">
        <h2 className="text-3xl font-semibold tracking-tight text-ink sm:text-4xl">
          Every command, in plain English
        </h2>
        <p className="mt-4 max-w-2xl text-sm leading-relaxed text-muted">
          {totalTools} local tools, {skills.length} built-in app skills, and {pronunciations.length}
          {" "}safe pronunciation defaults. Search or browse below. This reference is generated
          from the exact release you are about to install.
        </p>

        <div className="mt-10 grid gap-6 lg:grid-cols-[300px_1fr]">
          <div className="space-y-4">
            <div>
              <label htmlFor="command-search" className="block text-xs font-medium text-ink">
                Search commands
              </label>
              <input
                id="command-search"
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Try 'clipboard' or 'diagnostics'"
                className="mt-1 w-full rounded-md border border-border bg-obsidian px-3 py-2 text-sm text-ink"
              />
            </div>
            <nav aria-label="Command categories" className="flex flex-col gap-1">
              {categories.map((group) => (
                <button
                  key={group.category}
                  type="button"
                  aria-pressed={group.category === category}
                  onClick={() => { setCategory(group.category); setOpen(null); }}
                  className={`rounded-md border px-3 py-2 text-left text-sm transition-colors ${
                    group.category === category
                      ? "border-blue bg-blue-deep/20 text-ink"
                      : "border-border bg-surface text-muted hover:border-blue"
                  }`}
                >
                  {group.category}
                  <span className="mono-label ml-2">{group.tools.length}</span>
                </button>
              ))}
            </nav>
          </div>

          <div>
            <p role="status" aria-live="polite" className="mb-3 text-xs text-muted">
              {visibleTools.length} command{visibleTools.length === 1 ? "" : "s"} in {category}
            </p>
            {visibleTools.length === 0 ? (
              <p className="rounded-lg border border-border bg-obsidian p-5 text-sm text-muted">
                No commands match that search. Try a different word.
              </p>
            ) : (
              <ul className="space-y-2">
                {visibleTools.map((tool) => {
                  const expanded = open === tool.name;
                  return (
                    <li key={tool.name} className="rounded-lg border border-border bg-obsidian">
                      <button
                        type="button"
                        aria-expanded={expanded}
                        onClick={() => setOpen(expanded ? null : tool.name)}
                        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
                      >
                        <span className="font-mono text-sm text-blue">{tool.name}</span>
                        <span aria-hidden="true" className="text-muted">{expanded ? "−" : "+"}</span>
                      </button>
                      {expanded ? (
                        <div className="border-t border-border px-4 py-3">
                          <p className="text-sm leading-relaxed text-ink/90">{tool.description}</p>
                          <p className="mt-2 text-xs font-semibold text-muted">Say it like this</p>
                          <ul className="mt-1 space-y-1">
                            {tool.examples.map((example) => (
                              <li key={example} className="text-sm text-ink">“{example}”</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>

        <div className="mt-12 grid gap-6 md:grid-cols-2">
          <div className="rounded-lg border border-border bg-obsidian p-5">
            <h3 className="text-lg font-semibold text-ink">Built-in app skills</h3>
            <p className="mt-1 text-xs text-muted">Hotkeys and terminology only, never executable code.</p>
            <ul className="mt-4 space-y-4">
              {skills.map((skill) => (
                <li key={skill.id}>
                  <p className="text-sm font-semibold text-ink">{skill.appName}</p>
                  <ul className="mt-1 space-y-1">
                    {Object.entries(skill.hotkeys).slice(0, 5).map(([action, keys]) => (
                      <li key={action} className="text-xs text-muted">
                        {action}: <span className="font-mono text-ink/90">{keys}</span>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-lg border border-border bg-obsidian p-5">
            <h3 className="text-lg font-semibold text-ink">Voice shortcuts that run locally</h3>
            <p className="mt-1 text-xs text-muted">
              Matched before the model, so these work even when Ollama is offline.
            </p>
            <ul className="mt-4 space-y-2">
              {settingPhrases.map((group) => (
                <li key={group.group}>
                  <p className="text-xs font-semibold text-blue">{group.group}</p>
                  <p className="text-sm text-ink/90">{group.phrases.join(" · ")}</p>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}
