import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CommandExplorer from "./CommandExplorer";

describe("CommandExplorer", () => {
  it("lists generated commands, expands examples and filters by search", async () => {
    const user = userEvent.setup();
    render(<CommandExplorer />);

    await user.click(screen.getByRole("button", { name: /screen understanding/i }));
    const search = screen.getByLabelText(/search commands/i);
    await user.type(search, "describe");

    const list = screen.getAllByRole("list").find((node) =>
      within(node).queryByText("describe_screen") !== null,
    );
    expect(list).toBeDefined();
    expect(within(list!).getByText("describe_screen")).toBeInTheDocument();

    await user.click(within(list!).getByRole("button", { name: "describe_screen" }));
    expect(screen.getAllByText(/what's on my screen/i).length).toBeGreaterThan(0);
  });

  it("shows generated app skills and local voice shortcuts", () => {
    render(<CommandExplorer />);
    expect(screen.getByRole("heading", { name: /built-in app skills/i })).toBeInTheDocument();
    expect(screen.getByText("Blender")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /voice shortcuts that run locally/i })).toBeInTheDocument();
  });
});
