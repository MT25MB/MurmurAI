import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import TranscriptStream from "./TranscriptStream";
import type { ServerMessage } from "../lib/websocket";

const turn = (text: string, role: "assistant" | "system" = "assistant"): ServerMessage =>
  ({ type: "transcript", text, role });

describe("TranscriptStream", () => {
  it("exposes a polite live log for assistive tech", () => {
    render(<TranscriptStream lastMessage={null} />);
    const log = screen.getByRole("log", { name: /murmur ai transcript/i });
    expect(log).toHaveAttribute("aria-live", "polite");
    expect(log).toHaveAttribute("aria-relevant", "additions");
  });

  it("renders plain-text turns without formatting", () => {
    const { rerender } = render(<TranscriptStream lastMessage={null} />);
    rerender(<TranscriptStream lastMessage={turn("**Bold** and `code`")} />);
    const log = screen.getByRole("log", { name: /murmur ai transcript/i });
    expect(log).toHaveTextContent("**Bold** and `code`");
    expect(log.querySelectorAll("strong, code, em")).toHaveLength(0);
  });

  it("accumulates several turns in order", () => {
    const { rerender } = render(<TranscriptStream lastMessage={turn("First reply.")} />);
    rerender(<TranscriptStream lastMessage={turn("Second reply.", "system")} />);
    const log = screen.getByRole("log", { name: /murmur ai transcript/i });
    expect(log).toHaveTextContent(/First reply.*Status: Second reply/s);
    expect(log.querySelectorAll("p")).toHaveLength(2);
  });

  it("bounds the number of retained turns", () => {
    const { rerender } = render(<TranscriptStream lastMessage={turn("one")} maxTurns={2} />);
    rerender(<TranscriptStream lastMessage={turn("two")} maxTurns={2} />);
    rerender(<TranscriptStream lastMessage={turn("three")} maxTurns={2} />);
    const log = screen.getByRole("log", { name: /murmur ai transcript/i });
    expect(log).toHaveTextContent("two");
    expect(log).toHaveTextContent("three");
    expect(log).not.toHaveTextContent("one");
    expect(log.querySelectorAll("p")).toHaveLength(2);
  });

  it("collapses whitespace from streamed text", () => {
    render(<TranscriptStream lastMessage={turn("  line one \n  line two  ")} />);
    expect(screen.getByRole("log", { name: /murmur ai transcript/i })).toHaveTextContent("line one line two");
  });
});
