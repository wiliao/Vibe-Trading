import {
  CASH_SYMBOL,
  aggregateWeights,
  classifyAssetClass,
  downsampleDates,
  latestHoldingDate,
  parsePositionsPanel,
  withCashSlice,
  type PositionsPanel,
} from "../positions";

describe("parsePositionsPanel", () => {
  it("parses string weights per date and collects symbols in first-seen order", () => {
    const panel = parsePositionsPanel([
      { timestamp: "2023-07-31", "AAPL.US": "0.0", "RY.TO": "0.5" },
      { timestamp: "2023-08-01", "AAPL.US": "0.95", "SHOP.TO": "0.05" },
    ]);

    expect(panel.dates).toEqual(["2023-07-31", "2023-08-01"]);
    expect(panel.symbols).toEqual(["AAPL.US", "RY.TO", "SHOP.TO"]);
    expect(panel.weightByDate.get("2023-07-31")).toEqual({ "AAPL.US": 0, "RY.TO": 0.5 });
    expect(panel.weightByDate.get("2023-08-01")).toEqual({ "AAPL.US": 0.95, "SHOP.TO": 0.05 });
  });

  it("treats missing and NaN cells as 0", () => {
    const panel = parsePositionsPanel([
      { timestamp: "2024-01-02", "AAPL.US": "not-a-number" },
      { timestamp: "2024-01-03" },
    ]);

    expect(panel.weightByDate.get("2024-01-02")).toEqual({ "AAPL.US": 0 });
    expect(panel.weightByDate.get("2024-01-03")).toEqual({});
    expect(panel.symbols).toEqual(["AAPL.US"]);
  });

  it("skips date columns case-insensitively and tolerates a date alias", () => {
    const panel = parsePositionsPanel([
      { Timestamp: "2024-02-01", "AAPL.US": "0.4" } as unknown as Record<string, string>,
      { date: "2024-02-02", "AAPL.US": "0.6" },
    ]);

    expect(panel.dates).toEqual(["2024-02-01", "2024-02-02"]);
    expect(panel.symbols).toEqual(["AAPL.US"]);
  });

  it("returns an empty panel for empty input", () => {
    const panel = parsePositionsPanel([]);
    expect(panel.dates).toEqual([]);
    expect(panel.symbols).toEqual([]);
    expect(panel.weightByDate.size).toBe(0);
  });
});

describe("latestHoldingDate", () => {
  function panelFrom(rows: Array<Record<string, string>>): PositionsPanel {
    return parsePositionsPanel(rows);
  }

  it("returns the last date whose weight sum exceeds 0.001", () => {
    const panel = panelFrom([
      { timestamp: "2024-01-01", "AAPL.US": "0.5" },
      { timestamp: "2024-01-02", "AAPL.US": "0.9" },
      { timestamp: "2024-01-03", "AAPL.US": "0.0" },
    ]);
    expect(latestHoldingDate(panel)).toBe("2024-01-02");
  });

  it("returns null when all weights are zero", () => {
    const panel = panelFrom([
      { timestamp: "2024-01-01", "AAPL.US": "0.0" },
      { timestamp: "2024-01-02", "AAPL.US": "0" },
    ]);
    expect(latestHoldingDate(panel)).toBeNull();
  });

  it("returns null for an empty panel", () => {
    expect(latestHoldingDate(parsePositionsPanel([]))).toBeNull();
  });

  it("treats a dust sum below the threshold as flat", () => {
    const panel = panelFrom([{ timestamp: "2024-01-01", "AAPL.US": "0.0005" }]);
    expect(latestHoldingDate(panel)).toBeNull();
  });

  it("detects a market-neutral book whose signed sum is zero", () => {
    const panel = panelFrom([
      { timestamp: "2024-01-01", "AAPL.US": "0.5", "RY.TO": "-0.5" },
      { timestamp: "2024-01-02", "AAPL.US": "0.0", "RY.TO": "0.0" },
    ]);
    expect(latestHoldingDate(panel)).toBe("2024-01-01");
  });

  it("detects a short-only book", () => {
    const panel = panelFrom([
      { timestamp: "2024-01-01", "RY.TO": "-0.4" },
      { timestamp: "2024-01-02", "RY.TO": "0.0" },
    ]);
    expect(latestHoldingDate(panel)).toBe("2024-01-01");
  });
});

describe("classifyAssetClass parity with backend rules", () => {
  const cases: Array<[string, ReturnType<typeof classifyAssetClass>]> = [
    ["AAPL.US", "us_equity"],
    ["MSFT.US", "us_equity"],
    ["GOOGL.US", "us_equity"],
    ["AMZN.US", "us_equity"],
    ["META.US", "us_equity"],
    ["BRK-B.US", "us_equity"],
    ["TD.TO", "ca_equity"],
    ["SHOP.TO", "ca_equity"],
    ["BAM.TO", "ca_equity"],
    ["CNR.TO", "ca_equity"],
    ["PNG.V", "ca_equity"],
    ["SHOP.V", "ca_equity"],
    ["AAPL", "us_equity"],
    ["NVDA", "us_equity"],
    ["SPY", "us_equity"],
    // Unknown/odd shapes fall through to "other" rather than being claimed by
    // a market the app no longer supports: dotted non-exchange suffixes,
    // index symbols with a caret, numeric codes, and the empty string.
    ["BRK.B", "other"],
    ["^GSPC", "other"],
    ["^VIX", "other"],
    ["12345", "other"],
    ["", "other"],
  ];

  it.each(cases)("classifies %s as %s", (symbol, expected) => {
    expect(classifyAssetClass(symbol)).toBe(expected);
  });

  it("covers at least 18 parity cases", () => {
    expect(cases.length).toBeGreaterThanOrEqual(18);
  });
});

describe("aggregateWeights", () => {
  it("groups by the provided function and sorts descending", () => {
    const result = aggregateWeights(
      { "AAPL.US": 0.4, "RY.TO": 0.2, "SHOP.TO": 0.3 },
      (symbol) => (symbol.endsWith(".TO") ? "ca" : "us"),
    );
    expect(result.map((item) => item.group)).toEqual(["ca", "us"]);
    expect(result[0].weight).toBeCloseTo(0.5, 10);
    expect(result[1].weight).toBeCloseTo(0.4, 10);
  });

  it("keeps up to 12 groups untouched", () => {
    const weights: Record<string, number> = {};
    for (let i = 0; i < 12; i += 1) weights[`S${i}`] = 0.05;
    const result = aggregateWeights(weights, (symbol) => symbol);
    expect(result).toHaveLength(12);
  });

  it("merges the remainder into other when groups exceed 12", () => {
    const weights: Record<string, number> = {};
    for (let i = 0; i < 15; i += 1) weights[`S${i}`] = (15 - i) / 100;
    const result = aggregateWeights(weights, (symbol) => symbol);

    expect(result).toHaveLength(12);
    const other = result.find((item) => item.group === "other");
    expect(other).toBeDefined();
    expect(other!.weight).toBeCloseTo(0.01 + 0.02 + 0.03 + 0.04, 10);
    const total = result.reduce((sum, item) => sum + item.weight, 0);
    expect(total).toBeCloseTo(1.2, 10);
    for (let i = 1; i < result.length; i += 1) {
      expect(result[i - 1].weight).toBeGreaterThanOrEqual(result[i].weight);
    }
  });

  it("ignores zero and non-finite weights", () => {
    const result = aggregateWeights(
      { A: 0.5, B: 0, C: Number.NaN },
      (symbol) => symbol,
    );
    expect(result).toEqual([{ group: "A", weight: 0.5 }]);
  });
});

describe("withCashSlice", () => {
  it("adds a cash pseudo-symbol for the uninvested remainder", () => {
    const result = withCashSlice({ "AAPL.US": 0.6, "RY.TO": 0.2 });
    expect(result[CASH_SYMBOL]).toBeCloseTo(0.2, 10);
    expect(result["AAPL.US"]).toBe(0.6);
  });

  it("adds no cash when weights sum to exactly 1", () => {
    const result = withCashSlice({ A: 0.5, B: 0.5 });
    expect(CASH_SYMBOL in result).toBe(false);
  });

  it("adds no cash when the remainder is within the 0.005 tolerance", () => {
    const result = withCashSlice({ A: 0.996 });
    expect(CASH_SYMBOL in result).toBe(false);
  });

  it("adds cash when the remainder just exceeds the tolerance", () => {
    const result = withCashSlice({ A: 0.99 });
    expect(result[CASH_SYMBOL]).toBeCloseTo(0.01, 10);
  });

  it("does not mutate the input", () => {
    const input = { A: 0.5 };
    withCashSlice(input);
    expect(input).toEqual({ A: 0.5 });
  });

  it("adds no invented cash for a market-neutral book", () => {
    const result = withCashSlice({ "AAPL.US": 0.5, "RY.TO": -0.5 });
    expect(CASH_SYMBOL in result).toBe(false);
  });

  it("derives cash from gross exposure for a short-only book", () => {
    const result = withCashSlice({ "RY.TO": -0.4 });
    expect(result[CASH_SYMBOL]).toBeCloseTo(0.6, 10);
  });

  it("derives cash from gross exposure for a mixed long-short book", () => {
    const result = withCashSlice({ "AAPL.US": 0.4, "RY.TO": -0.2 });
    expect(result[CASH_SYMBOL]).toBeCloseTo(0.4, 10);
  });

  it("omits cash when the book is levered (gross above 1)", () => {
    const result = withCashSlice({ "AAPL.US": 0.8, "RY.TO": -0.5 });
    expect(CASH_SYMBOL in result).toBe(false);
  });
});

describe("downsampleDates", () => {
  it("returns all dates when under the cap", () => {
    const dates = ["2024-01-01", "2024-01-02", "2024-01-03"];
    expect(downsampleDates(dates, 500)).toEqual(dates);
  });

  it("keeps first and last and stays within the cap", () => {
    const dates = Array.from({ length: 1234 }, (_, i) => `d${i}`);
    const result = downsampleDates(dates, 500);

    expect(result[0]).toBe("d0");
    expect(result[result.length - 1]).toBe("d1233");
    expect(result.length).toBeLessThanOrEqual(500);
    expect(new Set(result).size).toBe(result.length);
    for (let i = 1; i < result.length; i += 1) {
      expect(dates.indexOf(result[i])).toBeGreaterThan(dates.indexOf(result[i - 1]));
    }
  });

  it("returns a copy, not the original array", () => {
    const dates = ["a", "b"];
    const result = downsampleDates(dates);
    expect(result).toEqual(dates);
    expect(result).not.toBe(dates);
  });
});
