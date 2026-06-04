"use client";

// ─── AgentChatWindow ──────────────────────────────────────────────────────────
// Agent D natural-language query interface — live backend integration.
//
// Pipeline flow:
//   User submits
//     → stage: "cove"      Optimistic CoVe stepper plays (3 × COVE_PHASE_MS)
//                          dispatchConversation mutation fires in parallel
//     → stage: "polling"   CoVe animation done; useQuery polls every 2 s
//     → stage: "idle"      status "completed" or "failed" → message committed
//
// The CoVe animation is intentionally optimistic: it reflects the real
// Chain-of-Verification that runs inside the LangGraph backend but plays on
// a fixed schedule so the UI feels alive from the first keystroke.
//
// The placeholder agent message is seeded on dispatch and its content is
// filled in once the status query resolves, avoiding layout shift.

import { useState, useRef, useEffect, useCallback, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Components } from "react-markdown";
import { Send, Loader2, Bot, User, Sparkles, GitBranch, AlertTriangle, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils/cn";
import { CoveTimeline } from "./CoveTimeline";
import {
  dispatchConversation,
  checkConversationStatus,
  type ConversationStatusResponse,
} from "@/lib/api/intelligence";

// ── Types ─────────────────────────────────────────────────────────────────────
type MessageRole = "user" | "agent";

/** "cove"    — optimistic CoVe stepper is playing
 *  "polling" — dispatch done; status query is active
 *  "error"   — unrecoverable dispatch failure shown inline
 */
export type PipelineStage = "idle" | "cove" | "polling" | "error";

export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  verifiedByCove?: boolean;
  isError?: boolean;
}

// ── Constants ─────────────────────────────────────────────────────────────────
const COVE_PHASE_MS = 1_400;
const POLL_INTERVAL_MS = 2_000;

const SUGGESTED_QUERIES = [
  "Show me Q3 financial summary",
  "What is our cash runway?",
  "Flag any compliance issues",
  "Compare revenue vs expenses YoY",
];

// ── Helpers ───────────────────────────────────────────────────────────────────
function uid() {
  return Math.random().toString(36).slice(2, 11);
}

/**
 * Derive the best available answer text from a completed status response.
 * The current backend stores the answer in MongoDB and only surfaces
 * artifact_id in the status payload. If the backend is later extended to
 * embed `answer` here it will be used automatically.
 */
function resolveAnswer(status: ConversationStatusResponse): string {
  if (status.answer) return status.answer;
  if (status.artifact_id) {
    return (
      `Agent D completed the analysis.\n\n` +
      `> **Artifact reference:** \`${status.artifact_id}\`\n\n` +
      `The full report has been persisted to the Intelligence Hub. ` +
      `Navigate to **Intelligence → Core Reports** to view the rendered output.`
    );
  }
  return "Agent D completed the analysis. No artifact was returned.";
}

function resolveError(status: ConversationStatusResponse): string {
  return `⚠️ **Agent D encountered an error**\n\n${status.detail ?? "An unknown error occurred in the LangGraph pipeline. Please retry."}`;
}

// ── Markdown renderer ─────────────────────────────────────────────────────────
const mdComponents: Components = {
  h1: ({ children }) => (
    <h1 className="text-lg font-bold text-lf-on-surface mt-4 mb-2 first:mt-0">{children}</h1>
  ),
  h2: ({ children }) => (
    <h2 className="text-base font-bold text-lf-on-surface mt-3 mb-2 first:mt-0">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="text-sm font-semibold text-lf-on-surface mt-2 mb-1">{children}</h3>
  ),
  p: ({ children }) => (
    <p className="text-sm text-lf-on-surface leading-relaxed mb-2 last:mb-0">{children}</p>
  ),
  ul: ({ children }) => (
    <ul className="list-disc list-outside pl-4 text-sm text-lf-on-surface mb-2 space-y-0.5">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="list-decimal list-outside pl-4 text-sm text-lf-on-surface mb-2 space-y-0.5">{children}</ol>
  ),
  li: ({ children }) => (
    <li className="text-sm text-lf-on-surface leading-relaxed">{children}</li>
  ),
  strong: ({ children }) => <strong className="font-bold text-lf-on-surface">{children}</strong>,
  em: ({ children }) => <em className="italic text-lf-on-surface-variant">{children}</em>,
  code: ({ children }) => (
    <code className="bg-lf-surface-container-high text-lf-primary text-xs px-1.5 py-0.5 rounded font-mono">{children}</code>
  ),
  pre: ({ children }) => (
    <pre className="bg-lf-surface-container-high rounded-lg p-3 overflow-x-auto text-xs mb-2 font-mono">{children}</pre>
  ),
  blockquote: ({ children }) => (
    <blockquote className="border-l-4 border-lf-error/40 bg-lf-error-container/10 pl-3 pr-2 py-2 rounded-r-lg text-sm text-lf-on-surface mb-2">{children}</blockquote>
  ),
  table: ({ children }) => (
    <div className="overflow-x-auto mb-3 rounded-xl border border-lf-outline-variant/20">
      <table className="w-full text-sm border-collapse">{children}</table>
    </div>
  ),
  thead: ({ children }) => (
    <thead className="bg-lf-surface-container-low border-b border-lf-outline-variant/20">{children}</thead>
  ),
  tbody: ({ children }) => <tbody>{children}</tbody>,
  tr: ({ children }) => (
    <tr className="border-b border-lf-outline-variant/10 last:border-0 hover:bg-lf-surface-container-low/50 transition-colors">{children}</tr>
  ),
  th: ({ children }) => (
    <th className="px-4 py-2.5 text-left text-[10px] font-bold tracking-widest uppercase text-lf-on-surface-variant">{children}</th>
  ),
  td: ({ children }) => (
    <td className="px-4 py-2.5 text-sm text-lf-on-surface">{children}</td>
  ),
};

// ── AgentChatWindow ───────────────────────────────────────────────────────────
export function AgentChatWindow() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [stage, setStage] = useState<PipelineStage>("idle");
  const [currentCovePhase, setCurrentCovePhase] = useState(-1);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);

  // Stable ref holding the ID of the in-flight placeholder agent message.
  // Using a ref (not state) avoids a re-render when we set it, and the
  // message update effect reads it without stale closure issues.
  const pendingMsgIdRef = useRef<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // ── Auto-scroll ────────────────────────────────────────────────────────────
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, stage]);

  // ── CoVe animation — plays while stage === "cove" ─────────────────────────
  // Steps through phases 0 → 1 → 2 at COVE_PHASE_MS intervals, then marks
  // all complete (phase 3) and transitions to "polling".
  useEffect(() => {
    if (stage !== "cove") return;

    let phase = 0;
    setCurrentCovePhase(0);

    const id = setInterval(() => {
      phase += 1;
      if (phase < 3) {
        setCurrentCovePhase(phase);
      } else {
        clearInterval(id);
        setCurrentCovePhase(3);
        // Only advance if we haven't already been moved to error/idle
        setStage((prev) => (prev === "cove" ? "polling" : prev));
      }
    }, COVE_PHASE_MS);

    return () => clearInterval(id);
  }, [stage]);

  // ── Dispatch mutation ──────────────────────────────────────────────────────
  const dispatchMutation = useMutation({
    mutationFn: (query: string) => dispatchConversation({ message: query }),

    onMutate: (query) => {
      // Seed the chat history immediately — user message + empty placeholder
      const agentMsgId = uid();
      pendingMsgIdRef.current = agentMsgId;

      setMessages((prev) => [
        ...prev,
        { id: uid(), role: "user", content: query },
        { id: agentMsgId, role: "agent", content: "", verifiedByCove: true },
      ]);
    },

    onSuccess: (data) => {
      if (data.session_id) {
        // Background task dispatched — activate the status poller.
        // Stage will already be moving through "cove" → "polling" via the
        // animation effect, but we set session ID here so the query enables
        // as soon as the animation finishes (or immediately if already done).
        setActiveSessionId(data.session_id);
        return;
      }

      // Path 1 cache hit: artifact was returned synchronously (no polling needed)
      if (!data.refreshing && data.artifact) {
        const answer =
          (data.artifact.answer as string | undefined) ??
          "Agent D returned a cached response from the Intelligence Hub.";

        commitAgentMessage(answer, false);
        return;
      }

      // Unexpected: no session_id and no artifact
      commitAgentMessage(
        "⚠️ Agent D returned an unexpected response. Please retry.",
        false,
        true
      );
    },

    onError: (err) => {
      const msg = err instanceof Error ? err.message : "Network error";
      commitAgentMessage(`⚠️ Failed to reach Agent D: ${msg}`, false, true);
    },
  });

  // ── Status polling query ───────────────────────────────────────────────────
  // Enabled only when we have a session_id AND the pipeline has reached the
  // "polling" stage (i.e., the CoVe animation has completed).
  const { data: statusData } = useQuery({
    queryKey: ["chat-status", activeSessionId],
    queryFn: () => checkConversationStatus(activeSessionId!),
    enabled: stage === "polling" && !!activeSessionId,
    refetchInterval: (query) => {
      const s = query.state.data?.status;
      return s === "completed" || s === "failed" ? false : POLL_INTERVAL_MS;
    },
    refetchIntervalInBackground: false,
    staleTime: 1_000,
    retry: false,
  });

  // ── Resolve status → commit message ───────────────────────────────────────
  useEffect(() => {
    if (!statusData || stage !== "polling") return;

    if (statusData.status === "completed") {
      commitAgentMessage(resolveAnswer(statusData), true);
    } else if (statusData.status === "failed") {
      commitAgentMessage(resolveError(statusData), false, true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusData?.status]);

  // ── Shared commit helper ───────────────────────────────────────────────────
  const commitAgentMessage = useCallback(
    (content: string, verifiedByCove: boolean, isError = false) => {
      const msgId = pendingMsgIdRef.current;
      if (msgId) {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === msgId ? { ...m, content, verifiedByCove, isError } : m
          )
        );
        pendingMsgIdRef.current = null;
      }
      setActiveSessionId(null);
      setStage("idle");
      setCurrentCovePhase(-1);
    },
    []
  );

  // ── Submit handlers ────────────────────────────────────────────────────────
  function handleSubmit(e?: FormEvent) {
    e?.preventDefault();
    const query = inputValue.trim();
    if (!query || stage !== "idle") return;
    setInputValue("");
    setStage("cove"); // start CoVe animation immediately for responsiveness
    dispatchMutation.mutate(query);
  }

  function handleSuggestedQuery(q: string) {
    if (stage !== "idle") return;
    setInputValue("");
    setStage("cove");
    dispatchMutation.mutate(q);
  }

  // ── Render ─────────────────────────────────────────────────────────────────
  const isEmpty = messages.length === 0 && stage === "idle";
  const isBusy = stage !== "idle";

  return (
    <div className="flex flex-col bg-lf-surface-container-lowest rounded-2xl border border-lf-outline-variant/20 shadow-[0_4px_24px_rgba(0,0,0,0.04)] overflow-hidden">
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-3 px-5 py-4 border-b border-lf-outline-variant/20 bg-lf-surface-container-low/60">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-lf-primary to-lf-secondary flex items-center justify-center shadow-sm shrink-0">
          <Sparkles size={16} className="text-lf-on-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-bold text-lf-on-surface">
            Agent D — Intelligence Query
          </p>
          <p className="text-[11px] font-bold tracking-widest uppercase text-lf-primary">
            Chain-of-Verification · NL → SQL
          </p>
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              "w-2 h-2 rounded-full",
              isBusy ? "bg-[#f59e0b] animate-pulse" : "bg-[#4ade80] animate-pulse"
            )}
          />
          <span className="text-xs font-semibold text-lf-on-surface-variant">
            {stage === "cove"
              ? "Verifying"
              : stage === "polling"
              ? "Analyzing"
              : "Online"}
          </span>
        </div>
      </div>

      {/* ── Message area ───────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-4 min-h-[420px] max-h-[520px]">
        {/* Empty state */}
        {isEmpty && (
          <div className="flex flex-col items-center justify-center flex-1 gap-6 py-8">
            <div className="w-16 h-16 rounded-2xl bg-lf-primary-fixed flex items-center justify-center">
              <GitBranch size={28} className="text-lf-primary" />
            </div>
            <div className="text-center">
              <p className="text-base font-semibold text-lf-on-surface">
                Ask Agent D anything
              </p>
              <p className="text-sm text-lf-on-surface-variant mt-1 max-w-sm">
                Agent D queries your financial database using natural language.
                Each response is validated through the CoVe pipeline.
              </p>
            </div>
            <div className="flex flex-wrap gap-2 justify-center max-w-lg">
              {SUGGESTED_QUERIES.map((q) => (
                <button
                  key={q}
                  onClick={() => handleSuggestedQuery(q)}
                  className="text-xs font-semibold text-lf-primary bg-lf-primary-fixed/30 hover:bg-lf-primary-fixed/60 border border-lf-primary/20 px-3 py-1.5 rounded-full transition-colors"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Message history */}
        {messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            isPending={
              msg.id === pendingMsgIdRef.current && stage === "polling"
            }
          />
        ))}

        {/* ── CoVe Timeline bubble ──────────────────────────────────────── */}
        {stage === "cove" && (
          <div className="flex gap-3 self-start max-w-[85%]">
            <div className="w-8 h-8 rounded-full bg-lf-primary-fixed border-2 border-lf-primary/20 flex items-center justify-center shrink-0 mt-0.5">
              <Bot size={15} className="text-lf-primary" />
            </div>
            <div className="bg-lf-primary-fixed/20 rounded-xl rounded-tl-sm border border-lf-primary-fixed-dim shadow-sm p-4 min-w-[260px]">
              <p className="text-[10px] font-bold tracking-widest uppercase text-lf-primary mb-3">
                CoVe Pipeline Running
              </p>
              <CoveTimeline currentPhase={currentCovePhase} />
            </div>
          </div>
        )}

        {/* ── Polling "thinking" bubble ─────────────────────────────────── */}
        {stage === "polling" && (
          <div className="flex gap-3 self-start max-w-[85%]">
            <div className="w-8 h-8 rounded-full bg-lf-primary-fixed border-2 border-lf-primary/20 flex items-center justify-center shrink-0 mt-0.5">
              <Bot size={15} className="text-lf-primary" />
            </div>
            <div className="bg-lf-primary-fixed/20 rounded-xl rounded-tl-sm border border-lf-primary-fixed-dim shadow-sm p-4 min-w-[260px]">
              <p className="text-[10px] font-bold tracking-widest uppercase text-lf-primary mb-2">
                CoVe Pipeline Complete
              </p>
              <CoveTimeline currentPhase={3} />
              <div className="mt-3 pt-3 border-t border-lf-primary/10 flex items-center gap-2">
                <RefreshCw size={12} className="text-lf-primary animate-spin shrink-0" />
                <span className="text-xs font-semibold text-lf-primary">
                  Agent D is analyzing your query…
                </span>
              </div>
              <p className="text-[10px] text-lf-on-surface-variant/60 mt-1">
                Polling every {POLL_INTERVAL_MS / 1000}s
              </p>
            </div>
          </div>
        )}

        {/* Scroll anchor */}
        <div ref={messagesEndRef} />
      </div>

      {/* ── Input bar ──────────────────────────────────────────────────── */}
      <form
        onSubmit={handleSubmit}
        className="flex items-end gap-3 px-4 py-4 border-t border-lf-outline-variant/20 bg-lf-surface-container-low/40"
      >
        <textarea
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSubmit();
            }
          }}
          disabled={isBusy}
          rows={1}
          placeholder={
            stage === "idle"
              ? "Ask a question about your finances…"
              : stage === "cove"
              ? "CoVe pipeline running…"
              : "Agent D is analyzing…"
          }
          aria-label="Query input"
          className={cn(
            "flex-1 resize-none rounded-xl border bg-lf-surface-container-low",
            "px-4 py-2.5 text-sm text-lf-on-surface",
            "placeholder:text-lf-on-surface-variant/50",
            "focus:outline-none focus:ring-2 focus:ring-lf-primary/25 focus:border-lf-primary",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            "transition-all border-lf-outline-variant/30",
            "min-h-[44px] max-h-[120px]"
          )}
        />
        <button
          type="submit"
          disabled={!inputValue.trim() || isBusy}
          aria-label="Send query"
          className={cn(
            "flex items-center justify-center w-11 h-11 rounded-xl transition-all shadow-sm shrink-0",
            "bg-lf-primary text-lf-on-primary hover:bg-lf-secondary",
            "disabled:opacity-40 disabled:cursor-not-allowed"
          )}
        >
          {isBusy ? (
            <Loader2 size={18} className="animate-spin" />
          ) : (
            <Send size={17} />
          )}
        </button>
      </form>
    </div>
  );
}

// ── MessageBubble ──────────────────────────────────────────────────────────────
interface MessageBubbleProps {
  message: ChatMessage;
  /** True while this is the placeholder being populated by the status poller */
  isPending: boolean;
}

function MessageBubble({ message, isPending }: MessageBubbleProps) {
  const isAgent = message.role === "agent";

  return (
    <div
      className={cn(
        "flex gap-3",
        isAgent
          ? "self-start max-w-[92%]"
          : "self-end max-w-[70%] flex-row-reverse"
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          "w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-0.5",
          isAgent
            ? "bg-lf-primary-fixed border-2 border-lf-primary/20"
            : "bg-lf-surface-container-high border-2 border-lf-outline-variant/30"
        )}
      >
        {isAgent ? (
          <Bot size={15} className="text-lf-primary" />
        ) : (
          <User size={15} className="text-lf-on-surface-variant" />
        )}
      </div>

      {/* Bubble */}
      {isAgent ? (
        <AgentBubble message={message} isPending={isPending} />
      ) : (
        <div className="bg-lf-primary text-lf-on-primary rounded-xl rounded-tr-sm px-4 py-2.5 text-sm leading-relaxed shadow-sm">
          {message.content}
        </div>
      )}
    </div>
  );
}

// ── AgentBubble ────────────────────────────────────────────────────────────────
function AgentBubble({
  message,
  isPending,
}: {
  message: ChatMessage;
  isPending: boolean;
}) {
  return (
    <div className="flex flex-col gap-1.5 min-w-0">
      {/* CoVe badge — shown on completed, non-error messages */}
      {message.verifiedByCove && !isPending && !message.isError && (
        <VerifiedBadge />
      )}

      {/* Error badge */}
      {message.isError && !isPending && (
        <div className="flex items-center gap-1.5 self-start">
          <span className="inline-flex items-center gap-1 text-[10px] font-bold tracking-wider text-lf-error bg-lf-error-container/40 border border-lf-error/20 px-2 py-0.5 rounded-full">
            <AlertTriangle size={9} />
            Error
          </span>
        </div>
      )}

      {/* Content card */}
      <div
        className={cn(
          "bg-lf-surface-container-lowest rounded-xl rounded-tl-sm border shadow-sm p-4 min-w-0",
          message.isError
            ? "border-lf-error/20"
            : "border-lf-outline-variant/20"
        )}
      >
        {isPending ? (
          /* Skeleton while waiting for the status poller to resolve */
          <div className="flex flex-col gap-2">
            <div className="h-2.5 w-48 bg-lf-surface-container-highest rounded-full animate-pulse" />
            <div className="h-2.5 w-36 bg-lf-surface-container-highest rounded-full animate-pulse" />
            <div className="h-2.5 w-44 bg-lf-surface-container-highest rounded-full animate-pulse" />
          </div>
        ) : (
          <div className="min-w-0 overflow-hidden">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={mdComponents}
            >
              {message.content}
            </ReactMarkdown>
          </div>
        )}
      </div>
    </div>
  );
}

// ── VerifiedBadge ──────────────────────────────────────────────────────────────
function VerifiedBadge() {
  return (
    <div className="flex items-center gap-1.5 self-start">
      <span className="inline-flex items-center gap-1 text-[10px] font-bold tracking-wider text-[#166534] bg-[#dcfce7] border border-[#86efac] px-2 py-0.5 rounded-full">
        <svg
          width="10"
          height="10"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline points="20 6 9 17 4 12" />
        </svg>
        CoVe Verified
      </span>
    </div>
  );
}
