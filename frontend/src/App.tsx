import { useState } from 'react';
import { Navbar } from './components/Navbar';
import { Footer } from './components/Footer';
import { LandingPage } from './views/LandingPage';
import { GeneratorWorkspace } from './views/GeneratorWorkspace';
import { AgentPlayground } from './views/AgentPlayground';

export function App() {
  const [activeView, setActiveView] = useState<'landing' | 'generator' | 'playground'>('landing');

  return (
    <div className="min-h-screen flex flex-col bg-canvas text-ink font-sans selection:bg-accent selection:text-white">
      {/* Top Navigation */}
      <Navbar activeView={activeView} setActiveView={setActiveView} />

      {/* Main Content View */}
      <main className="flex-1 pb-16">
        {activeView === 'landing' && (
          <LandingPage onNavigate={(view) => setActiveView(view)} />
        )}
        {activeView === 'generator' && (
          <GeneratorWorkspace />
        )}
        {activeView === 'playground' && (
          <AgentPlayground />
        )}
      </main>

      {/* Footer */}
      <Footer />
    </div>
  );
}

export default App;
