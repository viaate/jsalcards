/**
 * The panels' guards around a chart (ChanceSection, AreaPanel), kept apart from app/chance.ts so
 * the panels take only these few lines.
 */

import type { ChartView } from './chance';

/**
 * Whether a panel shows its chart at `now` (its own clock, ticking between readings): any chart
 * it has, but a night chart only before its `until` (critic r2 S4), so a phone woken past the
 * night's window never shows it while the next reading is on its way.
 */
export function chartShown(chart: ChartView | null, now: number): chart is ChartView {
  if (chart === null) return false;
  // Outside the chart's boundary: a bug here is no chart, never a lost chance.
  try {
    return chart.until === null || now < chart.until.getTime();
  } catch (error) {
    chartFailed(error);
    return false;
  }
}

/**
 * A chart that throws while it draws is no chart (the boundary keeps the chance), but never a
 * silent one: the error goes to the console, where the e2e's problem watch and a field report
 * see it (critic r2 S5).
 */
export function chartFailed(error: unknown): void {
  console.error('Snowlight: the chart could not draw', error);
}
