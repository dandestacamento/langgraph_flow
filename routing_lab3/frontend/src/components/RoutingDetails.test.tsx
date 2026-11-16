import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RoutingSummary } from "../api/client";
import { RoutingDetails } from "./RoutingDetails";

const BASE_SUMMARY: RoutingSummary = {
  topics: [],
  subtopics: {},
  chapters: {},
  passages: {},
  tool_results: {},
  is_multi_hop: false,
  hop_results: [],
  recovery_attempts: {},
};

describe("RoutingDetails", () => {
  it("renders nothing when there are no selected topics", () => {
    const { container } = render(<RoutingDetails summary={BASE_SUMMARY} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders the topic/subtopic/chapter breadcrumb and cited passages", () => {
    render(
      <RoutingDetails
        summary={{
          ...BASE_SUMMARY,
          topics: ["appliances"],
          subtopics: { appliances: "washing_machines" },
          chapters: { appliances: "chapter_03_faults" },
          passages: {
            appliances: [
              { chapter_id: "chapter_03_faults", document_id: "d1", subtopic: "washing_machines", score: 0.79, text: "E21: drainage problem." },
            ],
          },
        }}
      />,
    );

    expect(screen.getByText("appliances \u203a washing_machines \u203a chapter_03_faults")).toBeInTheDocument();
    expect(screen.getByText(/E21: drainage problem/)).toBeInTheDocument();
  });

  it("renders a tool-result card when a tool ran", () => {
    render(
      <RoutingDetails
        summary={{
          ...BASE_SUMMARY,
          topics: ["appliances"],
          tool_results: {
            appliances: {
              tool_name: "sql_query",
              tool_input: "SELECT price_aud FROM specifications WHERE model = 'WM-900'",
              output: "[{'price_aud': 1499}]",
              error: null,
            },
          },
        }}
      />,
    );

    expect(screen.getByText("sql_query")).toBeInTheDocument();
    expect(screen.getByText(/Output: .*price_aud/)).toBeInTheDocument();
  });

  it("renders the multi-hop trace when is_multi_hop is true", () => {
    render(
      <RoutingDetails
        summary={{
          ...BASE_SUMMARY,
          topics: ["appliances"],
          is_multi_hop: true,
          hop_results: [
            { hop_number: 1, question: "Which model has the largest capacity?", final_answer: "WM-900", extracted_value: "WM-900" },
            { hop_number: 2, question: "What is the price of the WM-900?", final_answer: "$1499 AUD", extracted_value: null },
          ],
        }}
      />,
    );

    expect(screen.getByText(/Hop 1:/)).toBeInTheDocument();
    expect(screen.getByText(/Hop 2:/)).toBeInTheDocument();
  });

  it("renders a recovery badge only when a retry was actually attempted", () => {
    render(
      <RoutingDetails
        summary={{
          ...BASE_SUMMARY,
          topics: ["appliances"],
          recovery_attempts: {
            appliances: { attempted: true, reason: "insufficient_info", succeeded: true },
          },
        }}
      />,
    );

    expect(screen.getByText(/retried \(insufficient_info\) - recovered/)).toBeInTheDocument();
  });
});
