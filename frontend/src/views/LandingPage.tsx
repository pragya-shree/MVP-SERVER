import React from 'react';
import { ArrowRight } from 'lucide-react';

interface LandingPageProps {
  onNavigate: (view: 'generator' | 'playground') => void;
}

export const LandingPage: React.FC<LandingPageProps> = ({ onNavigate }) => {
  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-20 sm:py-28 text-center">
      {/* Hero */}
      <h1 className="text-3xl sm:text-4xl font-semibold text-ink tracking-tight mb-4">
        Turn your API into MCP tools.
      </h1>

      <p className="text-base text-ink-muted mb-8 max-w-lg mx-auto leading-relaxed">
        Generate a runnable MCP server from an OpenAPI specification.
      </p>

      {/* Primary & Secondary Action Buttons (Only place they appear on landing) */}
      <div className="flex flex-col sm:flex-row items-center justify-center gap-3 mb-12">
        <button
          onClick={() => onNavigate('generator')}
          className="w-full sm:w-auto inline-flex items-center justify-center space-x-2 px-5 py-2.5 rounded bg-accent hover:bg-accent-hover text-white text-sm font-medium transition-colors shadow-card"
        >
          <span>Generate MCP Server</span>
          <ArrowRight className="w-4 h-4" />
        </button>

        <button
          onClick={() => onNavigate('playground')}
          className="w-full sm:w-auto inline-flex items-center justify-center px-5 py-2.5 rounded bg-surface hover:bg-canvas text-ink border border-line text-sm font-medium transition-colors"
        >
          Try Demo Agent
        </button>
      </div>

      {/* Three short facts as plain text with subtle separators */}
      <div className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-xs text-ink-muted font-normal">
        <span>OpenAPI 3.0 and 3.1</span>
        <span className="text-line-dark select-none">•</span>
        <span>Typed tool schemas</span>
        <span className="text-line-dark select-none">•</span>
        <span>Optional read-only generation</span>
      </div>
    </div>
  );
};
