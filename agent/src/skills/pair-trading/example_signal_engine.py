"""配对交易策略信号引擎。

基于两个相关标的的价格比值 Z-score 进行均值回归交易。
需要恰好两个标的，等权分配。纯 pandas 实现。
"""

from typing import Dict

import pandas as pd


class SignalEngine:
    """配对交易信号引擎。

    计算两个标的的价格比值，通过 Z-score 判断偏离程度，
    偏离过大时反向交易等待回归。

    Attributes:
        lookback: 均值和标准差回看窗口。
        entry_z: 开仓 Z-score 阈值。
        exit_z: 平仓 Z-score 阈值。

    Example:
        >>> engine = SignalEngine(lookback=60, entry_z=2.0)
        >>> signals = engine.generate({"AAPL.US": df1, "MSFT.US": df2})
    """

    def __init__(
        self,
        lookback: int = 60,
        entry_z: float = 2.0,
        exit_z: float = 0.5,
    ):
        """初始化配对交易引擎。

        Args:
            lookback: 均值和标准差回看窗口。
            entry_z: 开仓 Z-score 阈值。
            exit_z: 平仓 Z-score 阈值。
        """
        self.lookback = lookback
        self.entry_z = entry_z
        self.exit_z = exit_z

    def generate(self, data_map: Dict[str, pd.DataFrame]) -> Dict[str, pd.Series]:
        """根据价格比值 Z-score 生成配对交易信号。

        Args:
            data_map: 恰好两个标的代码到 OHLCV DataFrame 的映射。

        Returns:
            标的代码到信号 Series 的映射。
            第一个标的：0.5=做多, -0.5=做空, 0=空仓。
            第二个标的：方向与第一个相反。

        Raises:
            ValueError: 当标的数量不为 2 时。
        """
        codes = list(data_map.keys())
        if len(codes) != 2:
            raise ValueError(f"配对交易需要恰好 2 个标的，当前 {len(codes)} 个: {codes}")

        code_a, code_b = codes[0], codes[1]
        df_a, df_b = data_map[code_a], data_map[code_b]

        # 日期对齐（inner join）
        common_idx = df_a.index.intersection(df_b.index)
        close_a = df_a.loc[common_idx, "close"]
        close_b = df_b.loc[common_idx, "close"]

        # 价格比值
        ratio = close_a / close_b

        # Z-score
        mean = ratio.rolling(self.lookback).mean()
        std = ratio.rolling(self.lookback).std()
        z = (ratio - mean) / std

        # 信号生成
        sig_a = pd.Series(0.0, index=common_idx)
        sig_b = pd.Series(0.0, index=common_idx)

        # Z < -entry_z → 做多 A、做空 B（比值偏低，预期回归向上）
        long_pair = z < -self.entry_z
        sig_a[long_pair] = 0.5
        sig_b[long_pair] = -0.5

        # Z > +entry_z → 做空 A、做多 B（比值偏高，预期回归向下）
        short_pair = z > self.entry_z
        sig_a[short_pair] = -0.5
        sig_b[short_pair] = 0.5

        # |Z| < exit_z → 平仓
        flat = z.abs() < self.exit_z
        sig_a[flat] = 0.0
        sig_b[flat] = 0.0

        # 填充 NaN（lookback 窗口前无数据）
        sig_a = sig_a.fillna(0.0)
        sig_b = sig_b.fillna(0.0)

        # 对齐回原始索引
        return {
            code_a: sig_a.reindex(df_a.index).fillna(0.0),
            code_b: sig_b.reindex(df_b.index).fillna(0.0),
        }


if __name__ == "__main__":
    import requests

    def _fetch_yahoo(symbol: str, interval: str = "1d", range_: str = "2y") -> pd.DataFrame:
        """从 Yahoo Finance 获取 K 线数据。

        Args:
            symbol: 美股 / 加股代码，如 "KO"。
            interval: K 线周期，默认 "1d"。
            range_: 回看区间，默认 "2y"。

        Returns:
            OHLCV DataFrame。
        """
        resp = requests.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"range": range_, "interval": interval},
            headers={"User-Agent": "Mozilla/5.0"},
        )
        result = resp.json()["chart"]["result"][0]
        quote = result["indicators"]["quote"][0]
        df = pd.DataFrame(
            {
                "open": quote["open"],
                "high": quote["high"],
                "low": quote["low"],
                "close": quote["close"],
                "volume": quote["volume"],
            },
            index=pd.to_datetime(result["timestamp"], unit="s"),
        )
        df.index.name = "ts"
        return df.dropna(subset=["open", "high", "low", "close"])

    pair = ["KO", "PEP"]
    data_map = {}
    for sym in pair:
        print(f"Fetching {sym} ...")
        data_map[sym] = _fetch_yahoo(sym)

    engine = SignalEngine(lookback=60, entry_z=2.0, exit_z=0.5)
    signals = engine.generate(data_map)

    for sym in pair:
        sig = signals[sym]
        print(f"\n{sym} ({len(sig)} bars)")
        print(f"  Long  (0.5):  {(sig == 0.5).sum()}")
        print(f"  Short (-0.5): {(sig == -0.5).sum()}")
        print(f"  Flat  (0.0):  {(sig == 0.0).sum()}")
