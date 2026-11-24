/**
 * The advice by ticket type (flights spec D19) with the airline's waiver (D20, waivers spec W8).
 * The ticket type never changes the chance; it changes what switching costs. With a waiver found
 * on the airline's own page, the advice leads with "You can change for free"; with none found,
 * D19's advice stands, plus "We will tell you if one appears"; unclear or not checked, D19's
 * advice plus that line and the airline's link. Never a waiver that was not read (W1).
 */
import {
  tripsCopy,
  waiverAdvice,
  waiverNotCheckedAdvice,
  waiverUnclearAdvice,
  type TicketKey,
} from '../../copy-trips';
import type { WaiverState } from './data';

export interface Advice {
  /** The lines, in order. */
  readonly lines: readonly string[];
  /** Whether a free change was read on the airline's page. */
  readonly free: boolean;
  /** Whether the must-get-there line belongs (D18): a ticket that may not change for free. */
  readonly mustGo: boolean;
}

/** D19's own words for a ticket type. */
export function ticketLines(ticket: TicketKey): string[] {
  if (ticket === 'regular' || ticket === 'premium') return [tripsCopy.advice.regular];
  if (ticket === 'basic') return [tripsCopy.advice.basic];
  return [tripsCopy.advice.unsure];
}

/**
 * The advice for a trip: its ticket type and its airline's waiver state at the trip's airports
 * on its day (the most telling of the two ends: a waiver at either end covers the trip).
 * `basicIncluded`: the waiver says plainly that basic economy is in it (W3, LR-W7.5).
 */
export function adviceFor(
  ticket: TicketKey,
  states: readonly WaiverState[],
  basicIncluded = false,
): Advice {
  const found = states.find((state) => state.state === 'waiver');
  if (found !== undefined) {
    // A waiver that does not say basic economy is in it never tells a basic ticket it is free.
    if (ticket === 'basic' && !basicIncluded)
      return {
        lines: [waiverUnclearAdvice(found.airline), tripsCopy.advice.basic],
        free: false,
        mustGo: true,
      };
    return {
      lines: [waiverAdvice(found.airline, basicIncluded && ticket === 'basic')],
      free: true,
      mustGo: false,
    };
  }
  const lines = ticketLines(ticket);
  const unclear = states.find((state) => state.state === 'unclear');
  const unread = states.find((state) => state.state === 'not_checked');
  if (unclear !== undefined) lines.push(waiverUnclearAdvice(unclear.airline));
  else if (unread !== undefined) lines.push(waiverNotCheckedAdvice(unread.airline));
  else if (states.some((state) => state.state === 'none_found'))
    lines.push(tripsCopy.advice.watching);
  return { lines, free: false, mustGo: ticket !== 'regular' && ticket !== 'premium' };
}
