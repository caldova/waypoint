import enActivity from "./locales/en/activity.json";
import enAgent from "./locales/en/agent.json";
import enAuth from "./locales/en/auth.json";
import enCommon from "./locales/en/common.json";
import enHome from "./locales/en/home.json";
import enInvoices from "./locales/en/invoices.json";
import enQuality from "./locales/en/quality.json";
import esActivity from "./locales/es/activity.json";
import esAgent from "./locales/es/agent.json";
import esAuth from "./locales/es/auth.json";
import esCommon from "./locales/es/common.json";
import esHome from "./locales/es/home.json";
import esInvoices from "./locales/es/invoices.json";
import esQuality from "./locales/es/quality.json";

/**
 * Resources are bundled statically: the string set is small, and having every
 * locale available synchronously keeps SSR output and hydration identical.
 */
export const resources = {
  en: {
    common: enCommon,
    home: enHome,
    auth: enAuth,
    activity: enActivity,
    quality: enQuality,
    agent: enAgent,
    invoices: enInvoices,
  },
  es: {
    common: esCommon,
    home: esHome,
    auth: esAuth,
    activity: esActivity,
    quality: esQuality,
    agent: esAgent,
    invoices: esInvoices,
  },
} as const;
