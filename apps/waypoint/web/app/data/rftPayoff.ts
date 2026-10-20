/**
 * Contract-policy expert MAI RFT payoff: full Foundry hosted-agent evals for the
 * baseline, optimized, and tuned MAI agent, plus the token counts behind the cost
 * estimate. Mirrors the RFT Cost Quality canvas
 * (.github/extensions/rft-cost-quality-canvas) and
 * modules/agents/contract-policy-expert/FOUNDRY_OPTIMIZER_REPLAY.md.
 */

export type PayoffStageId = "baseline" | "optimized" | "tuned";
export type CostOptionId = "optimized" | "tuned";

export interface PayoffStage {
  id: PayoffStageId;
  agentVersion: string;
  model: string;
  evalId: string;
  /** Passed rows in each of the sequential eval runs. */
  passes: number[];
}

export interface CostOption {
  id: CostOptionId;
  model: string;
  /** Token totals measured across `cost.observedRequests` eval requests. */
  inputTokens: number;
  outputTokens: number;
  inputPricePerMillion: number;
  outputPricePerMillion: number;
}

export const RFT_PAYOFF = {
  agent: "contract-policy-expert",
  dataset: { name: "contract-policy-expert-test-foundry-eval", version: "2.0" },
  rubric: { name: "contract-policy-expert-generated-rubric", version: "13" },
  rowsPerRun: 24,
  stages: [
    {
      id: "baseline",
      agentVersion: "6",
      model: "gpt-6-astra",
      evalId: "eval_2d5a13a976c14355aee3317f87e5e171",
      passes: [16, 15, 11, 14, 18],
    },
    {
      id: "optimized",
      agentVersion: "7",
      model: "gpt-6-astra",
      evalId: "eval_9421539dcd754815b8c5443bca0e971c",
      passes: [24, 24, 24, 24, 24],
    },
    {
      id: "tuned",
      agentVersion: "10",
      model: "contract-policy-expert-mai-rft-v2-pt09",
      evalId: "eval_4031396f93ac47418b78477ab712fd7e",
      passes: [24, 24, 24, 24, 24],
    },
  ] satisfies PayoffStage[],
  optimizer: {
    jobId: "opt_2fb58fc1723e461d9a1496907d029ac8",
    candidate: "candidate_14",
    candidateId: "cand_opt_2fb58fc1723e461d9a1496907d029ac8_0014",
    baselineScore: 0.455684,
    candidateScore: 0.8000013333333332,
  },
  rft: {
    jobId: "ftjob-44f31c01823d4e13a213dddf0d22fb55",
    deployment: "contract-policy-expert-mai-rft-v2-pt09",
    fineTunedModel: "mai-code-1.1-flash-2026-08-27.ft-44f31c01823d4e13a213dddf0d22fb55-cpe-v2-pt09",
  },
  cost: {
    observedRequests: 120,
    unitSize: 10_000,
    minRequests: 10_000,
    maxRequests: 5_000_000,
    step: 10_000,
    options: [
      {
        id: "optimized",
        model: "gpt-6-astra",
        inputTokens: 118_530,
        outputTokens: 164_282,
        inputPricePerMillion: 10,
        outputPricePerMillion: 50,
      },
      {
        id: "tuned",
        model: "contract-policy-expert-mai-rft-v2-pt09",
        inputTokens: 118_530,
        outputTokens: 178_656,
        inputPricePerMillion: 0.2,
        outputPricePerMillion: 1.2,
      },
    ] satisfies CostOption[],
  },
};

export function stageMean(stage: PayoffStage, rowsPerRun = RFT_PAYOFF.rowsPerRun): number {
  const total = stage.passes.length * rowsPerRun;
  return total ? stage.passes.reduce((sum, passed) => sum + passed, 0) / total : 0;
}

/** Cost reduction of tuned MAI vs Astra at the default published token prices. */
export function defaultCostReduction(): number {
  const cost = (option: CostOption) =>
    option.inputTokens * option.inputPricePerMillion + option.outputTokens * option.outputPricePerMillion;
  const [astra, tuned] = (["optimized", "tuned"] as const).map(
    (id) => RFT_PAYOFF.cost.options.find((option) => option.id === id) as CostOption,
  );
  return 1 - cost(tuned) / cost(astra);
}
