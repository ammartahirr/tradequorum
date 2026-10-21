import { useEffect, useRef } from 'react';
import {
  CandlestickSeries,
  ColorType,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type IPriceLine,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useTheme } from '../../context/ThemeContext';
import type { Candle, SandboxTrade } from '../../api/sandbox';

interface Props {
  candles: Candle[];
  trades: SandboxTrade[];
  selectedIndex: number | null;
  onSelectTrade?: (index: number) => void;
  height?: number;
}

const ts = (t: number) => t as UTCTimestamp;

function buildMarkers(trades: SandboxTrade[], win: string, loss: string, neutral: string) {
  const markers: SeriesMarker<Time>[] = [];
  trades.forEach((t, i) => {
    const long = t.side === 'long';
    markers.push({
      id: `entry-${i}`,
      time: ts(t.entry_ts),
      position: long ? 'belowBar' : 'aboveBar',
      shape: long ? 'arrowUp' : 'arrowDown',
      color: neutral,
      text: `#${i + 1} ${long ? 'BUY' : 'SELL'} ${t.entry_price.toFixed(2)}`,
    });
    markers.push({
      id: `exit-${i}`,
      time: ts(t.exit_ts),
      position: long ? 'aboveBar' : 'belowBar',
      shape: 'circle',
      color: t.pnl > 0 ? win : loss,
      text: `#${i + 1} ${t.exit_reason.toUpperCase()} ${t.pnl >= 0 ? '+' : ''}${t.pnl.toFixed(0)}`,
    });
  });
  return markers.sort((a, b) => (a.time as number) - (b.time as number));
}

export function BacktestChart({ candles, trades, selectedIndex, onSelectTrade, height = 520 }: Props) {
  const { colors } = useTheme();
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const tradeLineRef = useRef<ISeriesApi<'Line'> | null>(null);
  const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);

  // Create chart once per theme
  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      autoSize: true,
      height,
      layout: {
        background: { type: ColorType.Solid, color: colors.bgSecondary },
        textColor: colors.textSecondary,
        fontFamily: 'SF Mono, Fira Code, monospace',
      },
      grid: {
        vertLines: { color: colors.border },
        horzLines: { color: colors.border },
      },
      rightPriceScale: { borderColor: colors.border },
      timeScale: { borderColor: colors.border, timeVisible: true, secondsVisible: false },
      crosshair: { mode: 0 },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: colors.success,
      downColor: colors.error,
      wickUpColor: colors.success,
      wickDownColor: colors.error,
      borderVisible: false,
    });
    const tradeLine = chart.addSeries(LineSeries, {
      color: colors.info,
      lineWidth: 2,
      lineStyle: LineStyle.Dotted,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    chartRef.current = chart;
    seriesRef.current = series;
    tradeLineRef.current = tradeLine;
    markersRef.current = createSeriesMarkers(series, []);

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
      tradeLineRef.current = null;
      markersRef.current = null;
      priceLinesRef.current = [];
    };
  }, [colors, height]);

  // Data + markers
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    series.setData(
      candles.map((c) => ({ time: ts(c.time), open: c.open, high: c.high, low: c.low, close: c.close })),
    );
    markersRef.current?.setMarkers(buildMarkers(trades, colors.success, colors.error, colors.textPrimary));
    chartRef.current?.timeScale().fitContent();
  }, [candles, trades, colors]);

  // Click on chart -> select nearest trade
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !onSelectTrade || trades.length === 0) return;
    const handler = (param: { time?: Time }) => {
      if (param.time === undefined) return;
      const t = param.time as number;
      const idx = trades.findIndex((tr) => t >= tr.entry_ts && t <= tr.exit_ts);
      if (idx >= 0) onSelectTrade(idx);
    };
    chart.subscribeClick(handler);
    return () => chart.unsubscribeClick(handler);
  }, [trades, onSelectTrade, colors]);

  // Selected trade: SL / TP / entry lines, entry->exit path, zoom
  useEffect(() => {
    const series = seriesRef.current;
    const chart = chartRef.current;
    const tradeLine = tradeLineRef.current;
    if (!series || !chart || !tradeLine) return;
    priceLinesRef.current.forEach((l) => series.removePriceLine(l));
    priceLinesRef.current = [];
    tradeLine.setData([]);
    if (selectedIndex === null || !trades[selectedIndex]) return;

    const t = trades[selectedIndex];
    const line = (price: number, color: string, title: string, style = LineStyle.Dashed) =>
      series.createPriceLine({ price, color, lineWidth: 1, lineStyle: style, axisLabelVisible: true, title });
    priceLinesRef.current = [
      line(t.entry_price, colors.textPrimary, `Entry #${selectedIndex + 1}`, LineStyle.Solid),
      line(t.stop_loss, colors.error, 'SL'),
      line(t.take_profit, colors.success, 'TP'),
    ];
    if (t.exit_ts > t.entry_ts) {
      tradeLine.setData([
        { time: ts(t.entry_ts), value: t.entry_price },
        { time: ts(t.exit_ts), value: t.exit_price },
      ]);
    }

    const entryIdx = candles.findIndex((c) => c.time >= t.entry_ts);
    const exitIdx = candles.findIndex((c) => c.time >= t.exit_ts);
    if (entryIdx >= 0) {
      const span = Math.max(20, (exitIdx >= 0 ? exitIdx : entryIdx) - entryIdx);
      chart.timeScale().setVisibleLogicalRange({
        from: Math.max(0, entryIdx - span * 2),
        to: Math.min(candles.length - 1, (exitIdx >= 0 ? exitIdx : entryIdx) + span * 2),
      });
    }
  }, [selectedIndex, trades, candles, colors]);

  return (
    <div
      ref={containerRef}
      data-testid="backtest-chart"
      style={{ width: '100%', height, border: `1px solid ${colors.border}`, borderRadius: 12, overflow: 'hidden' }}
    />
  );
}
