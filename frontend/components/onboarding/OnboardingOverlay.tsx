"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { X, ChevronRight, ChevronLeft } from "lucide-react";
import { useChatStore } from "@/stores/chatStore";
import { useAppStore } from "@/stores/appStore";

const ONBOARDING_KEY = "grass-onboarding-completed";

interface TourStep {
  title: string;
  description: string;
  target: string; // CSS selector for the element to highlight
  position: "left" | "right" | "top" | "bottom";
  exampleQuery?: string;
  requiredRightTab?: "map" | "data" | "charts" | "agent";
}

const TOUR_STEPS: TourStep[] = [
  {
    title: "Chat Panel",
    description:
      "Ask questions about your supply chain data in natural language. The AI will generate queries, analyze data, and provide insights.",
    target: '[data-tour="chat-panel"]',
    position: "right",
    exampleQuery: "What are the top 5 processors by county count?",
  },
  {
    title: "Database Panel",
    description:
      "Write and execute Cypher queries directly against Neo4j. Browse the schema and save frequently used queries.",
    target: '[data-tour="database-panel"]',
    position: "left",
    exampleQuery: "Show all farms on the map",
    requiredRightTab: "data",
  },
  {
    title: "Map Panel",
    description:
      "Visualize spatial data on an interactive map. Click markers to explore details and send queries back to the chat.",
    target: '[data-tour="map-panel"]',
    position: "left",
    exampleQuery: "Optimize transportation costs between farms and processors in PA",
    requiredRightTab: "map",
  },
];

export function OnboardingOverlay() {
  const [isVisible, setIsVisible] = useState(false);
  const [currentStep, setCurrentStep] = useState(0);
  const [highlightRect, setHighlightRect] = useState<DOMRect | null>(null);
  const setInputDraft = useChatStore((s) => s.setInputDraft);
  const setActiveRightTab = useAppStore((s) => s.setActiveRightTab);

  useEffect(() => {
    // Check if onboarding has been completed
    if (typeof window === "undefined") return;

    const completed = localStorage.getItem(ONBOARDING_KEY);
    if (!completed) {
      // Small delay to ensure DOM is ready
      const timer = setTimeout(() => setIsVisible(true), 500);
      return () => clearTimeout(timer);
    }
  }, []);

  useEffect(() => {
    if (!isVisible) return;

    // Some tour targets live inside tab panels; ensure required tab is active.
    const requiredTab = TOUR_STEPS[currentStep].requiredRightTab;
    if (requiredTab) {
      setActiveRightTab(requiredTab);
    }

    const updateHighlight = () => {
      const target = document.querySelector(TOUR_STEPS[currentStep].target);
      if (target) {
        const rect = target.getBoundingClientRect();
        // Ignore hidden/zero-sized targets (e.g. inactive tabs).
        if (rect.width > 0 && rect.height > 0) {
          setHighlightRect(rect);
          return;
        }
      }
      setHighlightRect(null);
    };

    // Delay helps after tab switches and initial layout.
    const timer = window.setTimeout(updateHighlight, 120);
    window.addEventListener("resize", updateHighlight);
    window.addEventListener("scroll", updateHighlight, true);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("resize", updateHighlight);
      window.removeEventListener("scroll", updateHighlight, true);
    };
  }, [isVisible, currentStep, setActiveRightTab]);

  const handleDismiss = () => {
    setIsVisible(false);
    localStorage.setItem(ONBOARDING_KEY, "true");
  };

  const handleNext = () => {
    if (currentStep < TOUR_STEPS.length - 1) {
      setCurrentStep(currentStep + 1);
    } else {
      handleDismiss();
    }
  };

  const handlePrev = () => {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1);
    }
  };

  const handleTryExample = () => {
    const step = TOUR_STEPS[currentStep];
    if (step.exampleQuery) {
      setInputDraft(step.exampleQuery);
      handleDismiss();
    }
  };

  if (!isVisible) return null;

  const step = TOUR_STEPS[currentStep];

  // Calculate tooltip position
  const getTooltipStyle = (): React.CSSProperties => {
    const tooltipWidth = 320;
    const padding = 20;
    const viewportW = typeof window !== "undefined" ? window.innerWidth : 1200;
    const viewportH = typeof window !== "undefined" ? window.innerHeight : 800;

    // Fallback: center tooltip when no valid target is found.
    if (!highlightRect) {
      return {
        left: Math.max(padding, (viewportW - tooltipWidth) / 2),
        top: Math.max(padding, viewportH * 0.2),
      };
    }

    let left = (viewportW - tooltipWidth) / 2;
    let top = viewportH * 0.2;
    let transform: React.CSSProperties["transform"] = undefined;

    switch (step.position) {
      case "right":
        left = highlightRect.right + padding;
        top = highlightRect.top + highlightRect.height / 2;
        transform = "translateY(-50%)";
        break;
      case "left":
        left = highlightRect.left - tooltipWidth - padding;
        top = highlightRect.top + highlightRect.height / 2;
        transform = "translateY(-50%)";
        break;
      case "top":
        left = highlightRect.left + highlightRect.width / 2 - tooltipWidth / 2;
        top = highlightRect.top - padding - 220;
        break;
      case "bottom":
        left = highlightRect.left + highlightRect.width / 2 - tooltipWidth / 2;
        top = highlightRect.bottom + padding;
        break;
    }

    // Keep tooltip within viewport bounds to avoid "stuck with invisible tooltip".
    left = Math.min(Math.max(left, padding), viewportW - tooltipWidth - padding);
    top = Math.min(Math.max(top, padding), viewportH - 260);

    return { left, top, transform };
  };

  return (
    <>
      {/* Overlay backdrop */}
      <div
        className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm"
        onClick={handleDismiss}
      />

      {/* Highlight cutout */}
      {highlightRect && (
        <div
          className="fixed z-[101] rounded-lg ring-4 ring-primary/50 ring-offset-4 ring-offset-black/60 transition-all duration-300"
          style={{
            left: highlightRect.left - 8,
            top: highlightRect.top - 8,
            width: highlightRect.width + 16,
            height: highlightRect.height + 16,
            pointerEvents: "none",
          }}
        />
      )}

      {/* Tooltip */}
      <div
        className="fixed z-[102] w-80 rounded-lg border bg-background p-6 shadow-2xl transition-all duration-300"
        style={getTooltipStyle()}
      >
        <button
          onClick={handleDismiss}
          className="absolute right-2 top-2 rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
        >
          <X className="h-4 w-4" />
          <span className="sr-only">Close</span>
        </button>

        <div className="space-y-4">
          <div>
            <h3 className="text-lg font-semibold">{step.title}</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              {step.description}
            </p>
          </div>

          {step.exampleQuery && (
            <Button
              onClick={handleTryExample}
              variant="outline"
              size="sm"
              className="w-full"
            >
              Try example: &ldquo;{step.exampleQuery.slice(0, 30)}&hellip;&rdquo;
            </Button>
          )}

          <div className="flex items-center justify-between pt-2">
            <div className="flex gap-1">
              {TOUR_STEPS.map((_, idx) => (
                <div
                  key={idx}
                  className={`h-1.5 w-1.5 rounded-full transition-colors ${
                    idx === currentStep ? "bg-primary" : "bg-muted"
                  }`}
                />
              ))}
            </div>

            <div className="flex gap-2">
              {currentStep > 0 && (
                <Button
                  onClick={handlePrev}
                  variant="ghost"
                  size="sm"
                  className="h-8 px-2"
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
              )}
              <Button onClick={handleNext} size="sm" className="h-8">
                {currentStep < TOUR_STEPS.length - 1 ? (
                  <>
                    Next
                    <ChevronRight className="ml-1 h-4 w-4" />
                  </>
                ) : (
                  "Get Started"
                )}
              </Button>
            </div>
          </div>

          <button
            onClick={handleDismiss}
            className="w-full text-center text-xs text-muted-foreground hover:text-foreground"
          >
            Skip tour
          </button>
        </div>
      </div>
    </>
  );
}
