import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { installTauriBridges } from './lib/tauri';
import './styles/globals.css';

// Route external-link clicks through the Tauri opener plugin when
// running inside the desktop shell so they actually leave the webview
// (and don't open inside a useless Tauri-protocol popup). No-op in
// browser mode -- existing window.open / <a target="_blank"> sites
// don't need to import anything.
installTauriBridges();

const rootElement = document.getElementById('root');
if (!rootElement) throw new Error('Root element not found');

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </React.StrictMode>,
);
