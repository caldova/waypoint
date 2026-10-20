/**
 * Line diff used to show what the Agent Optimizer changed. Same algorithm as
 * the Optimizer Diff canvas (LCS line diff with focused hunks), so the counts
 * match what reviewers see there.
 */

export type DiffKind = "same" | "added" | "removed";

export interface DiffRow {
  kind: DiffKind;
  text: string;
  beforeLine: number | null;
  afterLine: number | null;
}

export function splitLines(value: string | null | undefined): string[] {
  return String(value ?? "").replace(/\r\n/g, "\n").split("\n");
}

export function lineDiff(beforeText: string, afterText: string): DiffRow[] {
  const before = splitLines(beforeText);
  const after = splitLines(afterText);
  const dp: number[][] = Array.from({ length: before.length + 1 }, () =>
    new Array<number>(after.length + 1).fill(0),
  );
  for (let i = before.length - 1; i >= 0; i -= 1) {
    for (let j = after.length - 1; j >= 0; j -= 1) {
      dp[i][j] =
        before[i] === after[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < before.length && j < after.length) {
    if (before[i] === after[j]) {
      rows.push({ kind: "same", text: before[i], beforeLine: i + 1, afterLine: j + 1 });
      i += 1;
      j += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push({ kind: "removed", text: before[i], beforeLine: i + 1, afterLine: null });
      i += 1;
    } else {
      rows.push({ kind: "added", text: after[j], beforeLine: null, afterLine: j + 1 });
      j += 1;
    }
  }
  for (; i < before.length; i += 1) {
    rows.push({ kind: "removed", text: before[i], beforeLine: i + 1, afterLine: null });
  }
  for (; j < after.length; j += 1) {
    rows.push({ kind: "added", text: after[j], beforeLine: null, afterLine: j + 1 });
  }
  return rows;
}

/** Changed rows with `context` unchanged lines around them, merged when they touch. */
export function changedHunks(rows: DiffRow[], context = 2): DiffRow[][] {
  const ranges: Array<{ start: number; end: number }> = [];
  rows.forEach((row, index) => {
    if (row.kind === "same") {
      return;
    }
    const start = Math.max(0, index - context);
    const end = Math.min(rows.length - 1, index + context);
    const previous = ranges.at(-1);
    if (previous && start <= previous.end + 1) {
      previous.end = Math.max(previous.end, end);
    } else {
      ranges.push({ start, end });
    }
  });
  return ranges.map((range) => rows.slice(range.start, range.end + 1));
}

export function diffStats(rows: DiffRow[]) {
  return {
    added: rows.filter((row) => row.kind === "added").length,
    removed: rows.filter((row) => row.kind === "removed").length,
  };
}

/** Case-insensitive occurrences of `term` in `text`. */
export function countTerm(text: string, term: string): number {
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return (String(text).match(new RegExp(escaped, "gi")) ?? []).length;
}
