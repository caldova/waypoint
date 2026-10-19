import { useMemo } from "react";
import { useLocale } from "./LocaleProvider";
import type { Locale } from "./config";

/**
 * Regional formatting conventions for each UI language. Spanish uses Latin
 * American conventions (es-419): period decimals, comma grouping, 12-hour time.
 */
export const INTL_LOCALES: Record<Locale, string> = {
  en: "en-US",
  es: "es-419",
};

type DateInput = string | number | Date | null | undefined;

function toDate(value: DateInput): Date | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function toNumber(value: number | string | null | undefined): number | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  const amount = typeof value === "number" ? value : Number(value);
  return Number.isFinite(amount) ? amount : null;
}

export interface Formatters {
  locale: Locale;
  /** BCP 47 tag passed to `Intl`. */
  intlLocale: string;
  number(value: number | string | null | undefined, options?: Intl.NumberFormatOptions): string;
  /** Format an amount in its own currency (never converted). Non-numeric input renders as 0. */
  currency(
    value: number | string | null | undefined,
    currency?: string,
    options?: Pick<Intl.NumberFormatOptions, "minimumFractionDigits" | "maximumFractionDigits">,
  ): string;
  /** Format a 0–1 ratio as a percentage. */
  percent(ratio: number, fractionDigits?: number): string;
  /** Localized date, or `null` when the input isn't a valid date. */
  date(value: DateInput, options?: Intl.DateTimeFormatOptions): string | null;
  time(value: DateInput, options?: Intl.DateTimeFormatOptions): string | null;
  dateTime(value: DateInput, options?: Intl.DateTimeFormatOptions): string | null;
  relativeTime(value: number, unit: Intl.RelativeTimeFormatUnit, options?: Intl.RelativeTimeFormatOptions): string;
  list(items: string[], options?: Intl.ListFormatOptions): string;
}

export function createFormatters(locale: Locale): Formatters {
  const intlLocale = INTL_LOCALES[locale];

  const formatCurrency = (
    value: number | string | null | undefined,
    currency = "USD",
    options: Pick<Intl.NumberFormatOptions, "minimumFractionDigits" | "maximumFractionDigits"> = {},
  ) => {
    const amount = toNumber(value) ?? 0;
    try {
      return new Intl.NumberFormat(intlLocale, {
        style: "currency",
        currency: currency || "USD",
        ...options,
      }).format(amount);
    } catch {
      // Unknown ISO code from upstream data: keep the number readable.
      return `${currency} ${new Intl.NumberFormat(intlLocale, options).format(amount)}`;
    }
  };

  return {
    locale,
    intlLocale,
    number: (value, options) => {
      const amount = toNumber(value);
      return amount === null ? String(value ?? "") : new Intl.NumberFormat(intlLocale, options).format(amount);
    },
    currency: formatCurrency,
    percent: (ratio, fractionDigits = 1) =>
      new Intl.NumberFormat(intlLocale, {
        style: "percent",
        minimumFractionDigits: fractionDigits,
        maximumFractionDigits: fractionDigits,
      }).format(ratio),
    date: (value, options = { year: "numeric", month: "short", day: "numeric" }) => {
      const date = toDate(value);
      return date ? new Intl.DateTimeFormat(intlLocale, options).format(date) : null;
    },
    time: (value, options = { hour: "numeric", minute: "2-digit" }) => {
      const date = toDate(value);
      return date ? new Intl.DateTimeFormat(intlLocale, options).format(date) : null;
    },
    dateTime: (
      value,
      options = { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" },
    ) => {
      const date = toDate(value);
      return date ? new Intl.DateTimeFormat(intlLocale, options).format(date) : null;
    },
    relativeTime: (value, unit, options = { numeric: "auto" }) =>
      new Intl.RelativeTimeFormat(intlLocale, options).format(value, unit),
    list: (items, options = { style: "long", type: "conjunction" }) =>
      new Intl.ListFormat(intlLocale, options).format(items),
  };
}

/** Locale-bound formatters for the active UI language. */
export function useFormat(): Formatters {
  const { locale } = useLocale();
  return useMemo(() => createFormatters(locale), [locale]);
}
