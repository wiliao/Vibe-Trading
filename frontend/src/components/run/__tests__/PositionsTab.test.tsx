import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { Mock } from "vitest";
import type { RunData } from "@/lib/api";
import { PositionsTab } from "../PositionsTab";

vi.mock("@/lib/echarts", () => ({
  echarts: { init: vi.fn() },
  CHART_GROUP: "quant-charts",
  connectCharts: vi.fn(),
}));

import { echarts } from "@/lib/echarts";

interface FakeChart {
  setOption: Mock;
  resize: Mock;
  dispose: Mock;
  group: string;
}

const charts: FakeChart[] = [];

function makeRun(rows: Array<Record<string, string>>): RunData {
  return { status: "success", run_id: "run-test", artifacts_positions_csv: rows };
}

function seriesTypes(): string[] {
  return charts.flatMap((chart) =>
    chart.setOption.mock.calls.map((call) => {
      const option = call[0] as { series?: Array<{ type?: string }> };
      return option.series?.[0]?.type ?? "";
    }),
  );
}

function barCategoryAxes(): string[][] {
  return charts.flatMap((chart) =>
    chart.setOption.mock.calls
      .map((call) => {
        const option = call[0] as { yAxis?: { type?: string; data?: string[] } };
        return option.yAxis && option.yAxis.type === "category" ? option.yAxis.data ?? [] : null;
      })
      .filter((names): names is string[] => names !== null),
  );
}

interface AxisBounds {
  min?: number;
  max?: number;
}

function valueXAxes(): AxisBounds[] {
  return charts.flatMap((chart) =>
    chart.setOption.mock.calls
      .map((call) => {
        const option = call[0] as { xAxis?: { type?: string; min?: number; max?: number } };
        return option.xAxis && option.xAxis.type === "value"
          ? { min: option.xAxis.min, max: option.xAxis.max }
          : null;
      })
      .filter((axis): axis is AxisBounds => axis !== null),
  );
}

function valueYAxes(): AxisBounds[] {
  return charts.flatMap((chart) =>
    chart.setOption.mock.calls
      .map((call) => {
        const option = call[0] as { yAxis?: { type?: string; min?: number; max?: number } };
        return option.yAxis && option.yAxis.type === "value"
          ? { min: option.yAxis.min, max: option.yAxis.max }
          : null;
      })
      .filter((axis): axis is AxisBounds => axis !== null),
  );
}

function pieSliceNames(): string[] {
  return charts.flatMap((chart) =>
    chart.setOption.mock.calls.flatMap((call) => {
      const option = call[0] as {
        series?: Array<{ type?: string; data?: Array<{ name: string }> }>;
      };
      return (option.series ?? [])
        .filter((s) => s.type === "pie")
        .flatMap((s) => (s.data ?? []).map((d) => d.name));
    }),
  );
}

function evolutionSeriesNames(): string[] {
  return charts.flatMap((chart) =>
    chart.setOption.mock.calls.flatMap((call) => {
      const option = call[0] as {
        series?: Array<{ type?: string; name?: string; stack?: string }>;
      };
      return (option.series ?? [])
        .filter((s) => s.type === "line" && s.stack === "weights")
        .map((s) => s.name ?? "");
    }),
  );
}

function sectorMapResponse(body: Record<string, unknown>): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

describe("PositionsTab", () => {
  beforeEach(() => {
    charts.length = 0;
    vi.mocked(echarts.init).mockImplementation((() => {
      const chart: FakeChart = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn(), group: "" };
      charts.push(chart);
      return chart;
    }) as typeof echarts.init);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const multiSymbolRows = [
    { timestamp: "2023-07-31", "AAPL.US": "0.0", "RY.TO": "0.0" },
    { timestamp: "2023-08-01", "AAPL.US": "0.6", "RY.TO": "0.3" },
    { timestamp: "2023-08-02", "AAPL.US": "0.0", "RY.TO": "0.0" },
  ];

  it("shows the selected date label and holdings count", () => {
    render(<PositionsTab run={makeRun(multiSymbolRows)} />);

    expect(screen.getByText("As of 2023-08-01")).toBeInTheDocument();
    expect(screen.getByText("2 holdings")).toBeInTheDocument();
  });

  it("renders short legs as labelled slices and counts them in holdings", () => {
    const shortRows = [
      { timestamp: "2024-03-01", "AAPL.US": "0.4", "RY.TO": "-0.2" },
      { timestamp: "2024-03-04", "AAPL.US": "0.4", "RY.TO": "-0.2" },
    ];
    render(<PositionsTab run={makeRun(shortRows)} />);

    expect(screen.getByText("2 holdings")).toBeInTheDocument();

    const pieNames = charts.flatMap((chart) =>
      chart.setOption.mock.calls.flatMap((call) => {
        const option = call[0] as {
          series?: Array<{ type?: string; data?: Array<{ name: string }> }>;
        };
        return (option.series ?? [])
          .filter((s) => s.type === "pie")
          .flatMap((s) => (s.data ?? []).map((d) => d.name));
      }),
    );
    expect(pieNames).toContain("RY.TO Short");
    expect(pieNames).toContain("AAPL.US");
  });

  it("renders pie by default and switches to treemap via the toggle", () => {
    render(<PositionsTab run={makeRun(multiSymbolRows)} />);

    expect(seriesTypes()).toContain("pie");
    expect(seriesTypes()).not.toContain("treemap");

    fireEvent.click(screen.getByRole("button", { name: "Treemap" }));

    expect(seriesTypes()).toContain("treemap");
  });

  it("hides the resolve button when every symbol classifies as US/Canada equity", () => {
    const equityRows = [
      { timestamp: "2024-01-01", "AAPL.US": "0.6", "RY.TO": "0.4" },
      { timestamp: "2024-01-02", "AAPL.US": "0.5", "RY.TO": "0.5" },
    ];
    render(<PositionsTab run={makeRun(equityRows)} />);

    expect(screen.queryByText("Resolve industries")).not.toBeInTheDocument();
  });

  it("shows the resolve button for a symbol the frontend classifier cannot place", () => {
    // "^GSPC" has no recognised exchange suffix and no bare-ticker shape, so it
    // classifies as "other"; the backend sector map still classifies such
    // symbols offline, so the button must still be offered.
    const unknownRows = [
      { timestamp: "2024-01-01", "^GSPC": "0.6" },
      { timestamp: "2024-01-02", "^GSPC": "0.5" },
    ];
    render(<PositionsTab run={makeRun(unknownRows)} />);

    expect(screen.getByRole("button", { name: "Resolve industries" })).toBeInTheDocument();
  });

  it("shows the empty-state note and no charts for an all-zero payload", () => {
    const zeroRows = [
      { timestamp: "2024-01-01", "AAPL.US": "0.0" },
      { timestamp: "2024-01-02", "AAPL.US": "0" },
    ];
    render(<PositionsTab run={makeRun(zeroRows)} />);

    expect(screen.getByText("No position weights recorded for this run.")).toBeInTheDocument();
    expect(charts).toHaveLength(0);
  });

  it("resolves industries and re-renders the sector chart with resolved names", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sectorMapResponse({
        ok: true,
        run_id: "run-test",
        symbols: {
          "^GSPC": { asset_class: "index", industry: "Technology Hardware", industry_source: "eastmoney" },
        },
        unresolved: [],
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<PositionsTab run={makeRun([{ timestamp: "2024-01-01", "^GSPC": "0.7" }])} />);

    fireEvent.click(screen.getByRole("button", { name: "Resolve industries" }));

    // Wait on the re-render itself, not on the spinner going away: when the
    // stubbed fetch settles before waitFor's first poll, "Resolving..." is never
    // observed, the wait returns immediately and the sector chart has not been
    // re-rendered yet.
    await waitFor(() => {
      expect(barCategoryAxes().some((names) => names.includes("Technology Hardware"))).toBe(true);
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/runs/run-test/positions/sectors",
      expect.objectContaining({ headers: expect.anything() }),
    );
  });

  it("shows an inline retryable error when sector resolution fails", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("boom"));
    vi.stubGlobal("fetch", fetchMock);

    render(<PositionsTab run={makeRun([{ timestamp: "2024-01-01", "^GSPC": "0.7" }])} />);

    fireEvent.click(screen.getByRole("button", { name: "Resolve industries" }));

    await waitFor(() => {
      expect(screen.getByText(/Failed to resolve industries/)).toBeInTheDocument();
    });

    fetchMock.mockResolvedValue(sectorMapResponse({ ok: true, symbols: {}, unresolved: [] }));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
    });
    expect(fetchMock.mock.calls[1][0]).toBe("/runs/run-test/positions/sectors?refresh=1");
  });

  const marketNeutralRows = [
    { timestamp: "2024-05-01", "AAPL.US": "0.5", "RY.TO": "-0.5" },
    { timestamp: "2024-05-02", "AAPL.US": "0.5", "RY.TO": "-0.5" },
  ];

  it("renders a market-neutral book instead of the empty state", () => {
    render(<PositionsTab run={makeRun(marketNeutralRows)} />);

    expect(
      screen.queryByText("No position weights recorded for this run."),
    ).not.toBeInTheDocument();
    expect(screen.getByText("2 holdings")).toBeInTheDocument();
    expect(seriesTypes()).toContain("pie");
  });

  it("does not fabricate a cash slice for a market-neutral book", () => {
    render(<PositionsTab run={makeRun(marketNeutralRows)} />);

    const names = pieSliceNames();
    expect(names).toContain("AAPL.US");
    expect(names).toContain("RY.TO Short");
    expect(names).not.toContain("Cash");
  });

  it("keeps a gross-basis cash slice for a short-only book", () => {
    const shortOnlyRows = [
      { timestamp: "2024-06-01", "RY.TO": "-0.4" },
      { timestamp: "2024-06-03", "RY.TO": "-0.4" },
    ];
    render(<PositionsTab run={makeRun(shortOnlyRows)} />);

    const names = pieSliceNames();
    expect(names).toContain("RY.TO Short");
    expect(names).toContain("Cash");
  });

  it("uses a symmetric sector axis when the book is net short", () => {
    const netShortRows = [
      { timestamp: "2024-07-01", "AAPL.US": "0.3", "RY.TO": "-0.5" },
      { timestamp: "2024-07-02", "AAPL.US": "0.3", "RY.TO": "-0.5" },
    ];
    render(<PositionsTab run={makeRun(netShortRows)} />);

    const axes = valueXAxes();
    expect(axes.length).toBeGreaterThan(0);
    for (const axis of axes) {
      expect(axis.min).toBeLessThan(0);
      expect(axis.max).toBeGreaterThan(0);
      expect(axis.min).toBe(-(axis.max as number));
    }
  });

  it("keeps a zero-based sector axis for long-only books", () => {
    render(<PositionsTab run={makeRun(multiSymbolRows)} />);

    const axes = valueXAxes();
    expect(axes.length).toBeGreaterThan(0);
    for (const axis of axes) {
      expect(axis.min).toBe(0);
      expect(axis.max).toBeGreaterThan(0);
    }
  });

  it("ranks persistent shorts into the evolution top set and splits the remainder", () => {
    const weights: Record<string, string> = { "AAPL.US": "-0.4" };
    for (let i = 0; i < 10; i += 1) weights[`L${i}.US`] = "0.02";
    weights["RY.TO"] = "-0.01";
    const rows = [
      { timestamp: "2024-01-01", ...weights },
      { timestamp: "2024-01-02", ...weights },
    ];
    render(<PositionsTab run={makeRun(rows)} />);

    const names = evolutionSeriesNames();
    expect(names).toContain("AAPL.US");
    expect(names).toContain("Other (long)");
    expect(names).toContain("Other (short)");
    expect(names).not.toContain("Other");

    const axes = valueYAxes();
    expect(axes.length).toBeGreaterThan(0);
    for (const axis of axes) {
      expect(axis.min).toBeLessThan(0);
      expect(axis.max).toBeGreaterThan(0);
    }
  });
});
