import React from 'react';

export const Footer: React.FC = () => {
  return (
    <footer className="border-t border-line bg-surface py-6 mt-auto">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-ink-muted">
        <span className="font-medium text-ink">Anything-to-MCP</span>
        <span>OpenAPI 3.0 & 3.1 to Model Context Protocol (MCP) server generator.</span>
      </div>
    </footer>
  );
};
