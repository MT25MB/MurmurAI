import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import HardwareRequirements from "./HardwareRequirements";

describe("HardwareRequirements", () => {
  it("shows minimum, recommended and model-tier information", () => {
    render(<HardwareRequirements />);

    expect(screen.getByRole("heading", { name: /what your machine needs/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /minimum/i })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: /recommended/i })).toBeInTheDocument();
    expect(screen.getByText("16 GB+")).toBeInTheDocument();
    expect(screen.getAllByText(/qwen2\.5vl:7b/).length).toBeGreaterThan(0);
    expect(screen.getByText(/8–12 GB RAM, no GPU/)).toBeInTheDocument();
  });
});
