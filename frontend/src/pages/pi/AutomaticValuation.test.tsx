import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import AutomaticValuation from "./AutomaticValuation";
import { api, download } from "../../api";
const permission = vi.hoisted(() => ({ allowed: true }));
vi.mock("../../context", () => ({ useApp: () => ({ can: () => permission.allowed }) }));
vi.mock("../../api", () => ({ api: { get: vi.fn(), post: vi.fn() }, download: vi.fn() }));
const show = () => render(<MemoryRouter><AutomaticValuation batchId={12} /></MemoryRouter>);
beforeEach(() => { permission.allowed = true; vi.mocked(api.get).mockResolvedValue([]); });
afterEach(cleanup);
describe("automatic pricing workflow", () => {
  it("queues one complete analysis through the backend", async () => {
    vi.mocked(api.post).mockResolvedValue({ id: 9, status: "queued", total: 3, done: 0, failed: 0,
      workflow: { phase: "Identifying products", events: [] } });
    show();
    fireEvent.click(screen.getByRole("button", { name: "Analyze & Calculate Market Prices" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/pi/batches/12/analyze"));
    expect(await screen.findByRole("button", { name: "Analysis in progress…" })).toHaveProperty("disabled", true);
  });
  it("renders real backend progress and offline mode honestly", async () => {
    vi.mocked(api.get).mockResolvedValue([{ id: 9, status: "running", total: 20, done: 7, failed: 1,
      workflow: { phase: "Researching market", research_mode: "offline_history", events: [{ phase: "Importing assets" }] } }]);
    show();
    expect(await screen.findByText("Researching market", { selector: "b" })).toBeTruthy();
    expect(screen.getByText(/Offline \/ historical mode/)).toBeTruthy();
    expect(screen.getByRole("progressbar").getAttribute("value")).toBe("8");
    expect(screen.getByText(/7 \/ 20 finished/)).toBeTruthy();
  });
  it("downloads the completed server workbook and keeps review status", async () => {
    vi.mocked(api.get).mockResolvedValue([{ id: 9, status: "completed", total: 1, done: 1, failed: 0,
      workflow: { phase: "Needs Review", result: "Needs Review", artifact: "generated.xlsx", events: [] } }]);
    show();
    fireEvent.click(await screen.findByRole("button", { name: "Download completed Excel" }));
    await waitFor(() => expect(download).toHaveBeenCalledWith("/api/pi/jobs/9/workbook", "Casterly_Valuation_12.xlsx"));
    expect(screen.getByText(/Generated quotations are drafts/)).toBeTruthy();
  });
  it("shows backend errors instead of successful progress", async () => {
    vi.mocked(api.post).mockRejectedValue(new Error("Job queue unavailable"));
    show(); fireEvent.click(screen.getByRole("button", { name: "Analyze & Calculate Market Prices" }));
    expect(await screen.findByText("Job queue unavailable")).toBeTruthy();
  });
  it("respects existing permissions", () => {
    permission.allowed = false; show();
    expect(screen.getByRole("button", { name: "Analyze & Calculate Market Prices" })).toHaveProperty("disabled", true);
  });
});

it("refreshes pricing review when a generated workbook becomes available", async () => {
  const completed = vi.fn();
  vi.mocked(api.get).mockResolvedValue([{ id: 10, status: "completed", total: 1, done: 1, failed: 0,
    workflow: { phase: "Needs Review", result: "Needs Review", priced_lines: 2891, artifact: "ready.xlsx", events: [] } }]);
  render(<MemoryRouter><AutomaticValuation batchId={12} onComplete={completed} /></MemoryRouter>);
  await waitFor(() => expect(completed).toHaveBeenCalledTimes(1));
  expect(screen.getByText(/2,891 rows priced/)).toBeTruthy();
});
it("labels a zero-price export as a review workbook", async () => {
  vi.mocked(api.get).mockResolvedValue([{ id: 11, status: "completed", total: 1, done: 1, failed: 0,
    workflow: { phase: "Research Unavailable", result: "Research Unavailable", priced_lines: 0, artifact: "review.xlsx", events: [] } }]);
  show();
  expect(await screen.findByRole("button", { name: "Download review workbook (no prices)" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Download completed Excel" })).toBeNull();
});
