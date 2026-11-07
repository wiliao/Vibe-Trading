import { fireEvent, render, screen } from "@testing-library/react";
import { Correlation } from "../Correlation";
import { api } from "@/lib/api";
import i18n from "@/i18n";
import type { CorrelationRegimeResponse, CorrelationResponse } from "@/lib/api";

const apiMock = vi.hoisted(() => ({
  getCorrelation: vi.fn(),
  getCorrelationRegime: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ api: apiMock }));
vi.mock("@/components/charts/CorrelationMatrix", () => ({
  CorrelationMatrix: ({ labels }: { labels: string[] }) => (
    <div data-testid="correlation-result">{labels.join(",")}</div>
  ),
}));
vi.mock("@/components/charts/RegimeTimeline", () => ({
  RegimeTimeline: () => <div data-testid="regime-timeline" />,
}));

function correlation(labels: string[]): CorrelationResponse {
  return { labels, matrix: labels.map((_, row) => labels.map((__, column) => row === column ? 1 : 0.5)) };
}

function regime(): CorrelationRegimeResponse {
  return {
    labels: ["AAPL.US", "MSFT.US"],
    dates: ["2026-01-01"],
    density: [0.5],
    smoothed: [0.5],
    fused: [1],
    episodes: [],
    params: {
      days: 90,
      corr_window: 30,
      edge_threshold: 0.5,
      smooth_window: 5,
      enter_threshold: 0.7,
      exit_threshold: 0.3,
    },
  };
}

beforeEach(() => {
  apiMock.getCorrelation.mockReset();
  apiMock.getCorrelationRegime.mockReset();
});

it("computes and displays the default US/Canada comparison", async () => {
  apiMock.getCorrelation.mockResolvedValue(correlation(["AAPL.US", "MSFT.US"]));
  render(<Correlation />);

  fireEvent.click(screen.getByRole("button", { name: i18n.t("correlation.compute") }));

  expect(await screen.findByTestId("correlation-result")).toHaveTextContent("AAPL.US,MSFT.US");
  expect(apiMock.getCorrelation).toHaveBeenCalledWith(
    "AAPL.US,MSFT.US,SPY.US,RY.TO",
    90,
    "pearson",
  );
});

it("uses the selected symbols, lookback window, and correlation method", async () => {
  apiMock.getCorrelation.mockResolvedValue(correlation(["AAPL.US", "RY.TO"]));
  render(<Correlation />);

  fireEvent.change(screen.getByRole("textbox"), { target: { value: "AAPL.US,RY.TO" } });
  fireEvent.click(screen.getByRole("button", { name: "180d" }));
  fireEvent.click(screen.getByRole("button", { name: i18n.t("correlation.method_spearman") }));
  fireEvent.click(screen.getByRole("button", { name: i18n.t("correlation.compute") }));

  expect(await screen.findByTestId("correlation-result")).toHaveTextContent("AAPL.US,RY.TO");
  expect(apiMock.getCorrelation).toHaveBeenCalledWith("AAPL.US,RY.TO", 180, "spearman");
});

it("computes the regime timeline only when requested", async () => {
  apiMock.getCorrelation.mockResolvedValue(correlation(["AAPL.US", "MSFT.US"]));
  apiMock.getCorrelationRegime.mockResolvedValue(regime());
  render(<Correlation />);

  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: i18n.t("correlation.compute") }));

  expect(await screen.findByTestId("regime-timeline")).toBeInTheDocument();
  expect(apiMock.getCorrelationRegime).toHaveBeenCalledWith(
    "AAPL.US,MSFT.US,SPY.US,RY.TO",
    90,
  );
});

it("displays the API error when correlation calculation fails", async () => {
  apiMock.getCorrelation.mockRejectedValue(new Error("Not enough overlapping observations"));
  render(<Correlation />);

  fireEvent.click(screen.getByRole("button", { name: i18n.t("correlation.compute") }));

  expect(await screen.findByText("Not enough overlapping observations")).toBeInTheDocument();
});
