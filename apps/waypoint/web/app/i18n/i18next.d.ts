import "i18next";
import type { resources } from "./resources";

declare module "i18next" {
  interface CustomTypeOptions {
    defaultNS: "common";
    // English is the source of truth; `npm run i18n:check` keeps other locales in sync.
    resources: (typeof resources)["en"];
  }
}
