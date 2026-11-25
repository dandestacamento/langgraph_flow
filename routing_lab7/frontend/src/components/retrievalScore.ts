import type { RetrievedPassage } from "../api/client";

export function retrievalScoreLabel(type: RetrievedPassage["score_type"]): string {
  switch (type) {
    case "vector_distance":
      return "Vector distance (lower is closer)";
    case "hybrid_rank":
      return "Hybrid rank indicator (higher is earlier)";
    case "reranker":
      return "Reranker score (higher is better)";
    default:
      return "Score (type unavailable)";
  }
}
