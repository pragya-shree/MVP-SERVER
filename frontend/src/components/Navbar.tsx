import React from 'react';
import { Terminal } from 'lucide-react';

interface NavbarProps {
  activeView: 'landing' | 'generator' | 'playground';
  setActiveView: (view: 'landing' | 'generator' | 'playground') => void;
}

export const Navbar: React.FC<NavbarProps> = ({ activeView, setActiveView }) => {
  return (
    <header className="border-b border-line bg-surface sticky top-0 z-30">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between">
        {/* Brand */}
        <button
          onClick={() => setActiveView('landing')}
          className="flex items-center space-x-2.5 text-left text-ink hover:text-accent transition-colors"
        >
          <div className="w-6 h-6 rounded bg-accent text-white flex items-center justify-center">
            <Terminal className="w-3.5 h-3.5 stroke-[2.5]" />
          </div>
          <span className="font-semibold text-sm tracking-tight">Anything-to-MCP</span>
        </button>

        {/* Navigation Links */}
        <nav className="flex items-center space-x-1 sm:space-x-2 text-xs">
          <button
            onClick={() => setActiveView('landing')}
            className={`px-3 py-1.5 rounded transition-colors ${
              activeView === 'landing'
                ? 'bg-accent-light text-accent font-medium'
                : 'text-ink-muted hover:text-ink hover:bg-canvas'
            }`}
          >
            Overview
          </button>
          <button
            onClick={() => setActiveView('generator')}
            className={`px-3 py-1.5 rounded transition-colors ${
              activeView === 'generator'
                ? 'bg-accent-light text-accent font-medium'
                : 'text-ink-muted hover:text-ink hover:bg-canvas'
            }`}
          >
            Generator
          </button>
          <button
            onClick={() => setActiveView('playground')}
            className={`px-3 py-1.5 rounded transition-colors ${
              activeView === 'playground'
                ? 'bg-accent-light text-accent font-medium'
                : 'text-ink-muted hover:text-ink hover:bg-canvas'
            }`}
          >
            Agent Playground
          </button>
        </nav>
      </div>
    </header>
  );
};
