import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import i18n from "@/i18n";
import { SourcePrioritySettings } from "@/components/settings/SourcePrioritySettings";
import { toast } from "sonner";

const apiMock = vi.hoisted(() => ({
  getDataSourceSettings: vi.fn(),
  updateDataSourceSettings: vi.fn(),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    api: apiMock,
  };
});

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    info: vi.fn(),
    error: vi.fn(),
  },
}));

// The three markets that still have a configurable fallback chain, in the
// order the card renders them (first entry becomes the active market).
const US_EQUITY_DEFAULT = [
  "yahoo", "stooq", "sina", "eastmoney", "yfinance",
  "tiingo", "fmp", "finnhub", "alphavantage", "local",
];
const CA_EQUITY_DEFAULT = ["yahoo", "yfinance", "local"];
const INDEX_DEFAULT = ["yahoo", "yfinance", "local"];

function sourceOrders(overrides: Record<string, string[]> = {}) {
  const base: Array<[string, string[]]> = [
    ["us_equity", US_EQUITY_DEFAULT],
    ["ca_equity", CA_EQUITY_DEFAULT],
    ["index", INDEX_DEFAULT],
  ];
  return base.map(([market, order]) => ({
    market,
    env_var: `MARKET_DATA_ORDER_${market.toUpperCase()}`,
    default_order: order,
    effective_order: overrides[market] ?? order,
    override: overrides[market] ?? null,
    override_invalid: false,
  }));
}

function dataSourceSettings(overrides: Record<string, string[]> = {}) {
  return {
    env_path: "agent/.env",
    source_orders: sourceOrders(overrides),
  };
}

describe("SourcePrioritySettings", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    window.localStorage.clear();
    apiMock.getDataSourceSettings.mockReset();
    apiMock.updateDataSourceSettings.mockReset();
    vi.mocked(toast.success).mockClear();
    vi.mocked(toast.error).mockClear();
    apiMock.getDataSourceSettings.mockResolvedValue(dataSourceSettings());
  });

  afterEach(() => {
    cleanup();
  });

  it("renders the default order for the first market with boundary-disabled reordering", async () => {
    render(<SourcePrioritySettings />);

    expect(await screen.findByText("Data Source Priority")).toBeInTheDocument();
    // us_equity is the first market: its default head renders as a row.
    expect(screen.getByText("yahoo")).toBeInTheDocument();
    expect(screen.getByText("alphavantage")).toBeInTheDocument();
    // First row cannot move up, last row cannot move down.
    expect(screen.getByRole("button", { name: "Move up: yahoo" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move down: local" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Move up: stooq" })).toBeEnabled();
    // Default badge — nothing customized yet.
    expect(screen.getByText("Default")).toBeInTheDocument();
    // Adjustment-caliber caveat is surfaced next to the setting (see PR review).
    expect(screen.getByText(/adjustment basis/)).toBeInTheDocument();
  });

  it("sends all markets on save: reordered draft as order, default-equal as null", async () => {
    render(<SourcePrioritySettings />);

    await screen.findByText("yahoo");
    // Move stooq up one slot (yahoo <-> stooq swap).
    fireEvent.click(screen.getByRole("button", { name: "Move up: stooq" }));
    // The active market now shows a Custom badge.
    expect(screen.getByText("Custom")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(apiMock.updateDataSourceSettings).toHaveBeenCalledTimes(1));
    expect(apiMock.updateDataSourceSettings).toHaveBeenCalledWith({
      source_orders: [
        {
          market: "us_equity",
          order: [
            "stooq", "yahoo", "sina", "eastmoney", "yfinance",
            "tiingo", "fmp", "finnhub", "alphavantage", "local",
          ],
        },
        { market: "ca_equity", order: null },
        { market: "index", order: null },
      ],
    });
  });

  it("reset restores the default order and saves null (clearing saved residue)", async () => {
    // An override is already in effect from a previous save.
    apiMock.getDataSourceSettings.mockResolvedValue(
      dataSourceSettings({
        us_equity: ["stooq", "yahoo", "sina", "eastmoney", "yfinance", "tiingo", "fmp", "finnhub", "alphavantage", "local"],
      }),
    );
    render(<SourcePrioritySettings />);

    await screen.findByText("stooq");
    expect(screen.getByText("Custom")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reset to default" }));
    expect(screen.getByText("Default")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(apiMock.updateDataSourceSettings).toHaveBeenCalledTimes(1));
    const payload = apiMock.updateDataSourceSettings.mock.calls[0][0];
    expect(payload.source_orders.find((e: { market: string }) => e.market === "us_equity").order).toBeNull();
  });

  it("switches markets via the selector and edits that market's order", async () => {
    render(<SourcePrioritySettings />);

    await screen.findByText("yahoo");
    fireEvent.change(screen.getByLabelText("Market"), { target: { value: "ca_equity" } });
    // The Canadian chain has no stooq row; yahoo heads its three sources.
    expect(screen.getByText("yfinance")).toBeInTheDocument();
    expect(screen.queryByText("stooq")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Move up: yfinance" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(apiMock.updateDataSourceSettings).toHaveBeenCalledTimes(1));
    const payload = apiMock.updateDataSourceSettings.mock.calls[0][0];
    expect(payload.source_orders.find((e: { market: string }) => e.market === "ca_equity").order).toEqual([
      "yfinance", "yahoo", "local",
    ]);
  });

  it("shows an error toast and message when the save is rejected", async () => {
    apiMock.updateDataSourceSettings.mockRejectedValue(
      new Error("Invalid source order for ca_equity: must be a permutation of the default chain"),
    );
    render(<SourcePrioritySettings />);

    await screen.findByText("yahoo");
    fireEvent.click(screen.getByRole("button", { name: "Move up: stooq" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(vi.mocked(toast.error).mock.calls[0][0]).toContain("permutation");
    expect(
      await screen.findByText(/must be a permutation of the default chain/),
    ).toBeInTheDocument();
  });

  it("warns when a persisted override is invalid", async () => {
    const settings = dataSourceSettings();
    settings.source_orders = settings.source_orders.map((entry) =>
      entry.market === "us_equity"
        ? { ...entry, effective_order: US_EQUITY_DEFAULT, override: ["stooq"], override_invalid: true }
        : entry,
    );
    apiMock.getDataSourceSettings.mockResolvedValue(settings);

    render(<SourcePrioritySettings />);

    expect(
      await screen.findByText(/MARKET_DATA_ORDER_US_EQUITY is invalid/),
    ).toBeInTheDocument();
  });
});
