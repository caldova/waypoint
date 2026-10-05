/**
 * Third-party evidence sources the assurance pipeline can call alongside the
 * Microsoft IQ planes. A lane is matched by its `agent`/`plane` identifiers.
 *
 * To add a source (SAP is next, once its logo is approved): add an entry
 * here and drop its logo into `public/integrations/`.
 */
export interface Integration {
  key: string;
  /** Short name shown on chips, map tiles and evidence groups. */
  label: string;
  /** The connector/agent name shown as a tile title. */
  agent: string;
  /** Product the connector reads from. */
  product: string;
  /** What the source contributes, for evidence-group subtitles. */
  scope: string;
  img: string;
  hex: string;
  match: (identifier: string) => boolean;
}

export const INTEGRATIONS: Integration[] = [
  {
    key: "oracle-erp",
    label: "Oracle ERP",
    agent: "Oracle ERP connector",
    product: "Oracle Database@Azure",
    scope: "Payables, purchasing and supplier records on Oracle Database@Azure",
    img: "/integrations/oracle-database.png",
    hex: "#c74634",
    match: (identifier) => identifier.includes("oracle"),
  },
];

export function integrationForLane(lane: {
  agent?: string | null;
  plane?: string | null;
}): Integration | null {
  const identifier = `${lane.agent ?? ""} ${lane.plane ?? ""}`.toLowerCase();
  return INTEGRATIONS.find((integration) => integration.match(identifier)) ?? null;
}
